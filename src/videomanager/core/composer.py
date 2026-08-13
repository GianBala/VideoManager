"""Monta o grafo do ffmpeg que transforma um projeto em imagem e som.

**Um grafo só, três usos.** O mesmo montador serve para exportar o arquivo
final, para desenhar o quadro parado da prévia e para alimentar a reprodução. A
consequência é a que importa: **o que está na tela é a composição de verdade** —
com as trilhas sobrepostas na ordem certa, com os volumes e os mudos aplicados —,
e não uma aproximação que só vira o resultado na hora de exportar.

O que muda entre os três usos é só onde a leitura começa (``at``), quanto dura
(``span``) e para onde vai a saída. Por isso :func:`build_graph` é uma função
pura: recebe o projeto e devolve entradas, filtros e rótulos; quem chama decide
se aquilo vira arquivo, um quadro cru ou um fluxo de PCM.

Três decisões de montagem:

**A tela é um fundo preto do tamanho do projeto, e cada bloco é sobreposto a
ele.** Não se "emenda" vídeo: emendar só funciona quando tudo tem o mesmo
tamanho, o mesmo framerate e nenhuma trilha por cima da outra. Sobrepor a um
fundo resolve vão, formato misturado e trilha de cima com a mesma regra.

**Cada bloco é ajustado à tela antes de entrar.** ``scale`` preservando a
proporção e ``pad`` centralizando: um vídeo vertical no meio de horizontais
aparece inteiro, com tarja, em vez de esticado.

**A mixagem não normaliza.** O ``amix`` do ffmpeg divide o volume pelo número de
entradas por padrão — dois blocos simultâneos sairiam pela metade, sem ninguém
ter pedido. Com ``normalize=0`` cada bloco sai no volume que o usuário ajustou,
e a soma é responsabilidade dele.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import hwaccel
from .binaries import FFmpegTools
from .errors import ConversionError
from .project import Clip, MediaKind, Project, TrackKind
from .trimmer import (
    CutMode,
    Segment,
    TrimTarget,
    encode_audio_args,
    format_span,
    tail_args,
)

# Formato interno do áudio. Fixá-lo antes da mixagem evita o erro mais comum de
# ``amix``: entradas com taxas ou layouts diferentes, que ele recusa.
SAMPLE_RATE = 48_000
CHANNELS = 2
_AUDIO_BASE = f"aformat=sample_fmts=fltp:sample_rates={SAMPLE_RATE}"

# Mono vira estéreo copiando o canal, e não pela conversão de layout do ffmpeg:
# a conversão normaliza a potência e tira **3 dB** exatos do material, o que
# quebraria a promessa de que 0 dB no bloco significa "não mexe". Medido: uma
# trilha mono de -21,5 dB sai a -24,5 dB por ``aformat=channel_layouts=stereo``
# e a -21,5 dB por ``pan``.
_MONO_TO_STEREO = "pan=stereo|c0=c0|c1=c0"
# De 5.1 para estéreo a atenuação é desejada — é o que evita a soma dos canais
# estourar —, então ali a conversão normal é a correta.
_TO_STEREO = "aformat=channel_layouts=stereo"

# Duração mínima do fundo. Um projeto vazio ainda precisa de um quadro para
# mostrar, senão o ffmpeg sai sem escrever nada e a prévia fica sem explicação.
_MIN_CANVAS = 0.04


@dataclass(frozen=True)
class Composition:
    """Pedido de exportação de um projeto — um alvo de conversão como os outros.

    Quem executa é o :class:`~videomanager.core.converter.Converter`, com o mesmo
    progresso, cancelamento e limpeza de saída parcial das outras abas.
    """

    project: Project
    container: str = "mp4"
    # Preferência de codificação por placa, resolvida na hora de gravar (com
    # queda para software quando ela não abrir). Ver ``core/hwaccel.py``.
    hardware: str = hwaccel.SOFTWARE

    @property
    def extension(self) -> str:
        return self.container

    @property
    def output_duration(self) -> float:
        return self.project.duration


@dataclass(frozen=True)
class _Piece:
    """Um bloco já traduzido para a janela de tempo pedida."""

    clip: Clip
    index: int  # posição na lista de entradas do ffmpeg
    seek: float  # onde começar a ler dentro do arquivo
    offset: float  # onde entra na saída, em segundos
    duration: float


def _pieces(project: Project, at: float, span: float | None) -> list[_Piece]:
    """Blocos que aparecem na janela pedida, na ordem de composição.

    A ordem é a de baixo para cima: a trilha de vídeo mais baixa é o fundo e as
    de cima passam por cima dela, como em qualquer editor. As de áudio entram
    depois, e para elas a ordem não significa nada — som se soma.
    """
    end = None if span is None else at + span
    ordered = [*reversed(project.video_tracks), *project.audio_tracks]

    pieces: list[_Piece] = []
    for track in ordered:
        if track.muted and track.kind is TrackKind.AUDIO:
            # Trilha de áudio muda não entra no grafo: é mais barato não
            # decodificar do que decodificar e multiplicar por zero.
            continue
        for clip in track.sorted_clips():
            if clip.end <= at or (end is not None and clip.start >= end):
                continue
            begin = max(clip.start, at)
            finish = clip.end if end is None else min(clip.end, end)
            if finish - begin <= 0:
                continue
            pieces.append(
                _Piece(
                    clip=clip,
                    index=len(pieces),
                    seek=clip.source_time(begin),
                    offset=begin - at,
                    duration=finish - begin,
                )
            )
    return pieces


def _input_args(piece: _Piece, fps: float) -> list[str]:
    clip = piece.clip
    if clip.media.kind is MediaKind.IMAGE:
        # Uma imagem não tem duração: ela é repetida pelo tempo do bloco. O
        # ``-t`` na entrada é o que encerra essa repetição.
        return [
            "-loop", "1",
            "-framerate", f"{fps:.6f}",
            "-t", f"{piece.duration:.6f}",
            "-i", str(clip.media.path),
        ]
    return ["-ss", f"{piece.seek:.6f}", "-i", str(clip.media.path)]


def _video_chain(piece: _Piece, project: Project, fps: float) -> str:
    """Ajusta um bloco ao formato da tela e o coloca no instante certo."""
    steps = [f"trim=duration={piece.duration:.6f}"]
    if piece.offset > 0:
        steps.append(f"setpts=PTS-STARTPTS+{piece.offset:.6f}/TB")
    else:
        steps.append("setpts=PTS-STARTPTS")
    steps.append(f"fps={fps:.6f}")
    steps.append(_fit_scale(project.width, project.height))
    steps.append(
        f"pad={project.width}:{project.height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    steps.append("setsar=1")
    return f"[{piece.index}:v]" + ",".join(steps) + f"[v{piece.index}]"


def _fit_scale(width: int, height: int) -> str:
    """Encaixa o bloco na tela **pela forma com que ele é exibido**.

    ``force_original_aspect_ratio=decrease`` mede a proporção em pixels
    armazenados e ignora a proporção do pixel; com o ``setsar=1`` logo depois, um
    arquivo de pixel não quadrado — rip de DVD, filmadora antiga — saía achatado
    na horizontal. Medido: uma fonte 720×480 com pixel 32:27 (exibida em 16:9)
    saía 720×480 quadrado, ou seja 3:2. Nada falhava; a imagem só ficava
    espremida.

    ``dar`` é a proporção de exibição da entrada, que o ffmpeg já calcula com o
    pixel embutido. Onde o arquivo não informa o pixel, ele assume quadrado e a
    conta devolve o mesmo de antes (conferido com uma entrada de ``sar``
    desconhecido). O arredondamento para par é exigência dos codificadores.
    """
    largest = f"min({width},{height}*dar)"
    tallest = f"min({height},{width}/dar)"
    return f"scale=w='trunc({largest}/2)*2':h='trunc({tallest}/2)*2'"


def _audio_chain(piece: _Piece) -> str:
    steps = [f"atrim=duration={piece.duration:.6f}", "asetpts=PTS-STARTPTS"]
    if abs(piece.clip.gain_db) >= 0.05:
        steps.append(f"volume={piece.clip.gain_db:.2f}dB")
    steps.append(_AUDIO_BASE)
    steps.append(
        _MONO_TO_STEREO if piece.clip.media.channels == 1 else _TO_STEREO
    )
    if piece.offset > 0:
        # ``all=1`` aplica o atraso a todos os canais; sem ele, só o primeiro
        # canal é atrasado e o bloco sai com a imagem à frente do som num lado.
        steps.append(f"adelay={int(piece.offset * 1000)}:all=1")
    return f"[{piece.index}:a]" + ",".join(steps) + f"[a{piece.index}]"


@dataclass(frozen=True)
class Graph:
    """Entradas e filtros prontos, com os rótulos de saída."""

    inputs: list[str]
    filters: list[str]
    video_label: str | None
    audio_label: str | None


def build_graph(
    project: Project,
    *,
    at: float = 0.0,
    span: float | None = None,
    fps: float | None = None,
    want_video: bool = True,
    want_audio: bool = True,
) -> Graph:
    """Traduz o projeto num grafo de filtros do ffmpeg."""
    fps = fps or project.fps
    pieces = _pieces(project, at, span)
    duration = span if span is not None else max(_MIN_CANVAS, project.duration - at)

    inputs: list[str] = []
    filters: list[str] = []
    video_parts: list[_Piece] = []
    audio_parts: list[_Piece] = []

    for piece in pieces:
        inputs += _input_args(piece, fps)
        # ``has_image``, e não ``media.has_video``: o bloco de "separar áudio"
        # vem de um arquivo com imagem, e pela mídia ele entrava aqui — a
        # composição desenhava o vídeo dele por cima de tudo, no instante em que
        # o som estivesse, e ainda pagava a decodificação.
        if want_video and piece.clip.has_image:
            video_parts.append(piece)
        if want_audio and piece.clip.has_sound:
            audio_parts.append(piece)

    video_label = None
    if want_video and project.has_video:
        filters.append(
            f"color=c=black:s={project.width}x{project.height}"
            f":r={fps:.6f}:d={max(_MIN_CANVAS, duration):.6f}[base]"
        )
        current = "[base]"
        for order, piece in enumerate(video_parts):
            filters.append(_video_chain(piece, project, fps))
            start, end = piece.offset, piece.offset + piece.duration
            label = f"[o{order}]"
            filters.append(
                f"{current}[v{piece.index}]"
                # ``repeatlast=0`` impede o último quadro do bloco de ficar
                # congelado na tela depois que ele acaba; ``eof_action=pass``
                # deixa o fundo seguir sozinho a partir daí.
                f"overlay=eof_action=pass:repeatlast=0"
                f":enable='between(t,{start:.6f},{end:.6f})'{label}"
            )
            current = label
        video_label = current

    audio_label = None
    if want_audio and audio_parts:
        for piece in audio_parts:
            filters.append(_audio_chain(piece))
        labels = "".join(f"[a{piece.index}]" for piece in audio_parts)
        if len(audio_parts) == 1:
            audio_label = labels
        else:
            filters.append(
                f"{labels}amix=inputs={len(audio_parts)}:normalize=0"
                # Sem isto o ffmpeg baixa o volume por alguns instantes cada vez
                # que uma das entradas termina, e a mixagem "respira".
                ":dropout_transition=0[mix]"
            )
            audio_label = "[mix]"

    return Graph(inputs, filters, video_label, audio_label)


# ---------------------------------------------------------------------------
# Os três usos
# ---------------------------------------------------------------------------


def export_args(
    project: Project,
    destination: Path,
    tools: FFmpegTools,
    *,
    container: str = "mp4",
    hardware: str = hwaccel.SOFTWARE,
) -> list[str]:
    """Comando que grava o projeto inteiro em um arquivo."""
    if project.is_empty:
        raise ConversionError("Não há nada na linha do tempo para exportar.")

    graph = build_graph(project)
    family = hwaccel.family_for(container)
    encoder = hwaccel.resolve(family, hardware, tools)
    args = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-y"]
    # O dispositivo é declarado antes das entradas: o VAAPI precisa dele para
    # abrir o contexto em que os quadros serão enviados à placa.
    args += [*encoder.device, *graph.inputs]

    filters = list(graph.filters)
    video_label = graph.video_label
    if video_label and encoder.filter_suffix:
        filters.append(f"{video_label}{encoder.filter_suffix}[vhw]")
        video_label = "[vhw]"
    if filters:
        args += ["-filter_complex", ";".join(filters)]
    if video_label:
        args += ["-map", video_label, "-c:v", encoder.name, *encoder.quality]
    if graph.audio_label:
        args += ["-map", graph.audio_label, *encode_audio_args(container)]
    elif video_label:
        args += ["-an"]
    if not video_label and not graph.audio_label:
        raise ConversionError(
            "Todos os blocos estão mudos ou vazios: não há o que exportar."
        )
    return args + tail_args(container, destination)


def frame_command(
    project: Project,
    at: float,
    size: tuple[int, int],
    tools: FFmpegTools,
) -> list[str]:
    """Comando que devolve **um** quadro da composição, em rgb24 cru.

    A janela é a de **um quadro**, e não a do projeto até o fim: para desenhar
    um instante só interessa o que aparece nele. Sem esse limite, cada quadro da
    navegação abria todos os arquivos seguintes da edição — medido num projeto
    de vinte blocos: vinte arquivos abertos e 0,77 s por quadro, com o custo
    crescendo a cada bloco acrescentado.
    """
    width, height = size
    graph = build_graph(
        project, at=at, span=1.0 / max(1.0, project.fps), want_audio=False
    )
    args = [
        tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error", *graph.inputs
    ]
    filters = list(graph.filters)
    if graph.video_label:
        filters.append(f"{graph.video_label}scale={width}:{height}[out]")
        args += ["-filter_complex", ";".join(filters), "-map", "[out]"]
    else:
        # Projeto sem imagem no instante pedido: um quadro preto diz isso melhor
        # que a tela vazia da prévia, que parece falha de carregamento.
        args += ["-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d=0.1"]
    return args + [
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"
    ]


def playback_command(
    project: Project,
    at: float,
    size: tuple[int, int],
    tools: FFmpegTools,
    *,
    fps: int,
) -> list[str]:
    """Comando que produz o fluxo de quadros da reprodução, a partir de ``at``."""
    width, height = size
    graph = build_graph(project, at=at, span=None, fps=float(fps), want_audio=False)
    args = [
        tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error", *graph.inputs
    ]
    filters = list(graph.filters)
    if graph.video_label:
        filters.append(f"{graph.video_label}scale={width}:{height}[out]")
        args += ["-filter_complex", ";".join(filters), "-map", "[out]"]
    else:
        remaining = max(_MIN_CANVAS, project.duration - at)
        args += [
            "-f", "lavfi",
            "-i", f"color=c=black:s={width}x{height}:r={fps}:d={remaining:.3f}",
        ]
    return args + ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]


def audio_command(
    project: Project, at: float, tools: FFmpegTools
) -> list[str] | None:
    """Comando que produz a mixagem em PCM, a partir de ``at``.

    ``None`` quando não há som a tocar — o que a interface usa para não abrir
    processo nenhum, em vez de tocar silêncio.
    """
    graph = build_graph(project, at=at, span=None, want_video=False)
    if not graph.audio_label:
        return None
    return [
        tools.ffmpeg_str,
        "-nostdin",
        "-hide_banner",
        "-v", "error",
        *graph.inputs,
        "-filter_complex", ";".join(graph.filters),
        "-map", graph.audio_label,
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "pipe:1",
    ]


# ---------------------------------------------------------------------------
# Caminho rápido
# ---------------------------------------------------------------------------


def simple_trim(project: Project) -> tuple[Segment, ...] | None:
    """Se o projeto é só um recorte de um arquivo, devolve os trechos dele.

    Existe para preservar o corte sem recodificar (ver ``core/trimmer.py``)
    depois que o editor virou multipista: enquanto ninguém acrescentou uma
    segunda mídia, mexeu no volume ou mudou um bloco de lugar, cortar continua
    sendo instantâneo e sem perda. Basta uma dessas coisas para a resposta ser
    ``None`` e a exportação passar a compor.
    """
    clips = project.clips
    if not clips:
        return None
    first = clips[0].media
    if any(clip.media.path != first.path for clip in clips):
        return None
    if any(clip.muted or abs(clip.gain_db) >= 0.05 for clip in clips):
        return None
    # Um bloco de "separar áudio" é só o som do arquivo, e copiar os dados
    # levaria a imagem junto: o que se pediu na tela deixaria de ser o que sai.
    if any(clip.audio_only or clip.detached for clip in clips):
        return None
    if first.kind is MediaKind.IMAGE:
        return None
    # Copiar os dados entrega a imagem como ela está no arquivo: uma tela pedida
    # em outro tamanho ou outra taxa seria simplesmente ignorada, e o arquivo
    # sairia diferente do que a tela do editor anuncia.
    if first.width and first.height and (
        (project.width, project.height) != (first.width, first.height)
    ):
        return None
    if first.fps and abs(project.fps - first.fps) > 0.01:
        return None
    if len(project.video_tracks) > 1 and sum(
        1 for track in project.video_tracks if track.clips
    ) > 1:
        return None
    if any(track.muted for track in project.tracks if track.clips):
        return None

    ordered = sorted(clips, key=lambda clip: clip.start)
    # O recorte simples é a mídia na ordem original: se os blocos foram
    # embaralhados no tempo, quem monta é o compositor.
    if any(
        later.in_point < earlier.in_point
        for earlier, later in zip(ordered, ordered[1:])
    ):
        return None
    return tuple(Segment(clip.in_point, clip.out_point) for clip in ordered)


def as_trim_target(
    project: Project, container: str, mode: CutMode, anchor: float | None
) -> TrimTarget | None:
    segments = simple_trim(project)
    if segments is None:
        return None
    return TrimTarget(
        segments=segments, container=container, mode=mode, anchor=anchor
    )


def describe_export(
    project: Project, container: str, hardware: str = hwaccel.SOFTWARE
) -> str:
    """Resumo do que a exportação vai produzir."""
    videos = sum(len(track.clips) for track in project.video_tracks)
    audios = sum(len(track.clips) for track in project.audio_tracks)
    parts = [f".{container}"]
    if videos:
        parts.append(f"{videos} bloco(s) de imagem")
    if audios:
        parts.append(f"{audios} de áudio")
    if project.has_video:
        parts.append(f"{project.width}×{project.height} · {project.fps:g} fps")
    if hardware != hwaccel.SOFTWARE:
        parts.append("placa de vídeo, se disponível")
    parts.append(f"{format_span(project.duration)} de duração")
    return " · ".join(parts)
