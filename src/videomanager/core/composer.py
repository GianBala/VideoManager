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
from .binaries import FFmpegTools, decode_thread_args
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

# Sobra clonada no fim de um bloco interpolado (ver :func:`_rate_chain`). Meio
# segundo cobre com folga os poucos quadros que o filtro não consegue produzir,
# e nada disso aparece: a sobreposição é desligada no fim do bloco.
_INTERPOLATE_TAIL = 0.5

# Memória do ``minterpolate``, por pixel do quadro que ele **recebe**. Medido
# nesta máquina, pico de RSS de uma exportação: 1589 MB a 1920×1080 (803 B/px) e
# 5655 MB a 3840×2160 (715 B/px). Não cresce com a duração — 20 s a 1080p pediu
# os mesmos 1,6 GB que 5 s —, e é por isso que o custo pode ser anunciado antes
# de a exportação começar (ver :func:`interpolation_bytes`). O valor é o maior
# dos dois: errar para cima só antecipa um aviso, errar para baixo derruba a
# máquina.
_INTERPOLATE_BYTES_PER_PIXEL = 803


@dataclass(frozen=True)
class Composition:
    """Pedido de exportação de um projeto — um alvo de conversão como os outros.

    Quem executa é o :class:`~videomanager.core.converter.Converter`, com o mesmo
    progresso, cancelamento e limpeza de saída parcial das outras abas.
    """

    project: Project
    container: str = "mp4"
    family: str | None = None
    # Preferência de codificação por placa, resolvida na hora de gravar (com
    # queda para software quando ela não abrir). Ver ``core/hwaccel.py``.
    hardware: str = hwaccel.SOFTWARE
    # Inventar os quadros que faltam ao subir a taxa, em vez de repetir os que
    # existem. Só na exportação: ver :func:`_rate_chain`.
    interpolate: bool = False
    audio_only: bool = False
    audio_codec: str | None = None

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
    track_muted: bool = False


def _pieces(
    project: Project,
    at: float,
    span: float | None,
    *,
    want_video: bool = True,
    want_audio: bool = True,
) -> list[_Piece]:
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
        if track.muted and not want_video:
            # Se a trilha está muda e não precisamos de vídeo (ex.: reprodução só
            # de áudio), os blocos dela não têm o que contribuir para a saída.
            continue
        for clip in track.sorted_clips():
            if clip.end <= at or (end is not None and clip.start >= end):
                continue
            begin = max(clip.start, at)
            finish = clip.end if end is None else min(clip.end, end)
            if finish - begin <= 0:
                continue
            has_v = want_video and clip.has_image
            has_a = want_audio and clip.has_sound and not track.muted
            if not has_v and not has_a:
                continue
            pieces.append(
                _Piece(
                    clip=clip,
                    index=len(pieces),
                    seek=clip.source_time(begin),
                    offset=begin - at,
                    duration=finish - begin,
                    track_muted=track.muted,
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


def _interpolates(piece: _Piece, fps: float, interpolate: bool) -> bool:
    """Se **este** bloco vai ter quadros inventados.

    A caixa marcada não basta: só há o que interpolar num bloco de vídeo abaixo
    da taxa da tela. Um bloco já na taxa (ou acima) pagaria a estimativa de
    movimento para nada, e uma imagem parada não tem movimento a estimar.
    """
    origem = piece.clip.media.fps
    return bool(interpolate and origem and origem < fps - 0.01)


def _rate_chain(piece: _Piece, fps: float, interpolate: bool) -> str:
    """Como este bloco chega à taxa da tela.

    O normal é ``fps``, que **duplica ou descarta quadros inteiros**: subir de 24
    para 60 assim entrega um arquivo de 60 fps com 24 imagens por segundo (e uma
    cadência 2-3-2-3, que treme mais que os 24 originais). É o comportamento
    certo por padrão — é instantâneo e não inventa nada.

    ``minterpolate`` estima o movimento e **sintetiza** os quadros que faltam;
    é a única forma de ganhar fluidez de verdade. Medido nesta máquina, 5 s a
    24→60 fps: 0,15 s duplicando contra 5,73 s interpolando (38×), com 296 dos
    300 quadros distintos contra 120. Em troca, ela inventa pixels — movimento
    rápido, oclusão e corte de cena saem deformados —, e por isso é escolha
    explícita e nunca o padrão.

    Só entra onde há o que interpolar: ver :func:`_interpolates`.
    """
    if _interpolates(piece, fps, interpolate):
        # ``tpad`` repõe o fim: para inventar um quadro, o filtro precisa do
        # **seguinte**, e por isso ele entrega alguns quadros a menos do que
        # recebeu. Medido: 236 de 240. O bloco acabava antes da hora e o que
        # aparecia no lugar era o fundo preto da composição — duração certa,
        # contagem de quadros certa, nenhum erro, e o último décimo de segundo
        # preto. O excedente clonado não vaza: a sobreposição já é desligada no
        # fim do bloco.
        return (
            f"minterpolate=fps={fps:.6f}:mi_mode=mci:mc_mode=aobmc:vsbmc=1,"
            f"tpad=stop_mode=clone:stop_duration={_INTERPOLATE_TAIL}"
        )
    return f"fps={fps:.6f}"


def _video_chain(
    piece: _Piece, project: Project, fps: float, interpolate: bool = False
) -> str:
    """Ajusta um bloco ao formato da tela e o coloca no instante certo."""
    steps = [f"trim=duration={piece.duration:.6f}"]
    if piece.offset > 0:
        steps.append(f"setpts=PTS-STARTPTS+{piece.offset:.6f}/TB")
    else:
        steps.append("setpts=PTS-STARTPTS")
    if _rate_first(piece, project, fps, interpolate):
        steps.append(_rate_chain(piece, fps, interpolate))
        steps.append(_fit_scale(project.width, project.height))
    else:
        steps.append(_fit_scale(project.width, project.height))
        steps.append(_rate_chain(piece, fps, interpolate))
    steps.append(
        f"pad={project.width}:{project.height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    steps.append("setsar=1")
    return f"[{piece.index}:v]" + ",".join(steps) + f"[v{piece.index}]"


def _rate_first(
    piece: _Piece, project: Project, fps: float, interpolate: bool
) -> bool:
    """Se a taxa é ajustada **antes** do encaixe na tela.

    A regra é uma só: **o trabalho pesado acontece no menor dos dois tamanhos.**

    Duplicar quadro é sempre depois de encaixar. Assim o ``scale`` recebe os
    quadros da origem (24) em vez dos da tela (60) — a duplicação em si é de
    graça, porque o ffmpeg só repassa o mesmo quadro.

    Interpolar é o contrário quando a tela é **maior** que o material: estimar
    movimento em pixels que o ``scale`` acabou de inventar custa o tamanho da
    tela e não acrescenta informação nenhuma — o movimento está nos pixels
    originais. Subir depois sai mais barato e mais fiel.

    A ordem não é detalhe de desempenho: a memória do ``minterpolate`` é função
    do tamanho do quadro (medido: 1,6 GB a 1080p, 5,6 GB a 4K, com 20 s gastando
    o mesmo que 5 s). Interpolar um material 1080p numa tela 4K reservava os
    5,6 GB **sem nada em troca**, e foi assim que uma exportação sozinha comeu a
    memória da máquina.
    """
    if not _interpolates(piece, fps, interpolate):
        return False
    media = piece.clip.media
    if not media.width or not media.height:
        # Sem saber o tamanho da origem, encaixar primeiro é o lado seguro: a
        # tela é um teto conhecido, e o do material não.
        return False
    return media.width * media.height < project.width * project.height


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
    interpolate: bool = False,
) -> Graph:
    """Traduz o projeto num grafo de filtros do ffmpeg.

    ``interpolate`` é pedido **só pela exportação**: ele multiplica o tempo de
    codificação por dezenas, e o mesmo grafo alimenta o quadro parado e a
    reprodução da prévia, que precisam sair na hora. É a única coisa que a
    prévia não mostra do resultado, e a aba diz isso ao lado do controle.
    """
    fps = fps or project.fps
    pieces = _pieces(project, at, span, want_video=want_video, want_audio=want_audio)
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
        if want_audio and piece.clip.has_sound and not piece.track_muted:
            audio_parts.append(piece)

    video_label = None
    if want_video and project.has_video:
        filters.append(
            f"color=c=black:s={project.width}x{project.height}"
            f":r={fps:.6f}:d={max(_MIN_CANVAS, duration):.6f}[base]"
        )
        current = "[base]"
        for order, piece in enumerate(video_parts):
            filters.append(_video_chain(piece, project, fps, interpolate))
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
    family: str | None = None,
    hardware: str = hwaccel.SOFTWARE,
    interpolate: bool = False,
    audio_only: bool = False,
    audio_codec: str | None = None,
) -> list[str]:
    """Comando que grava o projeto inteiro em um arquivo."""
    if project.is_empty:
        raise ConversionError("Não há nada na linha do tempo para exportar.")

    if audio_only:
        graph = build_graph(project, want_video=False, want_audio=True)
        if not graph.audio_label:
            raise ConversionError(
                "Não há blocos de áudio audíveis na linha do tempo para exportar."
            )
        args = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-y", *graph.inputs]
        filters = list(graph.filters)
        if filters:
            filter_text = ";".join(filters)
            if len(filter_text) > 4000:
                try:
                    script_path = destination.with_suffix(".filter_script")
                    script_path.write_text(filter_text, encoding="utf-8")
                    args += ["-filter_complex_script", str(script_path)]
                except OSError:
                    args += ["-filter_complex", filter_text]
            else:
                args += ["-filter_complex", filter_text]

        target_codec = (audio_codec or container).lower()
        args += ["-map", graph.audio_label, "-vn"]
        if target_codec in ("mp3", "libmp3lame"):
            args += ["-c:a", "libmp3lame", "-b:a", "192k", "-id3v2_version", "3"]
        elif target_codec in ("m4a", "aac"):
            args += ["-c:a", "aac", "-b:a", "192k"]
        elif target_codec in ("flac",):
            args += ["-c:a", "flac"]
        elif target_codec in ("wav", "pcm"):
            args += ["-c:a", "pcm_s16le"]
        elif target_codec in ("opus", "libopus"):
            args += ["-c:a", "libopus", "-b:a", "128k"]
        elif target_codec in ("ogg", "vorbis", "libvorbis"):
            args += ["-c:a", "libvorbis", "-q:a", "5"]
        else:
            args += encode_audio_args(container)
        return args + ["-map_metadata", "0", "-progress", "pipe:1", "-nostats", str(destination)]

    graph = build_graph(project, interpolate=interpolate)
    codec_family = family or hwaccel.family_for(container)
    encoder = hwaccel.resolve(codec_family, hardware, tools)
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
        filter_text = ";".join(filters)
        if len(filter_text) > 4000:
            try:
                script_path = destination.with_suffix(".filter_script")
                script_path.write_text(filter_text, encoding="utf-8")
                args += ["-filter_complex_script", str(script_path)]
            except OSError:
                args += ["-filter_complex", filter_text]
        else:
            args += ["-filter_complex", filter_text]
    if video_label:
        args += ["-map", video_label, "-c:v", encoder.name, *encoder.quality]
        if (
            encoder.name in ("libx265", "hevc_nvenc", "hevc_qsv", "hevc_amf", "hevc_vaapi")
            and container in ("mp4", "mov")
        ):
            args += ["-tag:v", "hvc1"]
    if graph.audio_label:
        args += ["-map", graph.audio_label, *encode_audio_args(container)]
    elif video_label:
        args += ["-an"]
    if not video_label and not graph.audio_label:
        raise ConversionError(
            "Todos os blocos estão mudos ou vazios: não há o que exportar."
        )
    return args + tail_args(container, destination)


def _limited_inputs(inputs: list[str]) -> list[str]:
    """Repete o teto de threads de decodificação antes de **cada** entrada.

    ``-threads`` é opção de entrada e vale para a que vem logo depois: pôr uma
    vez só na frente limitaria o primeiro arquivo e deixaria os outros no padrão.

    Vale para o quadro parado da prévia, e não para a exportação nem para a
    reprodução. Na exportação o que se quer é o arquivo pronto antes, e todo
    núcleo é bem-vindo. Na reprodução o relógio já limita o trabalho — ela
    decodifica na velocidade em que consome —, e apertar as threads ali só
    arriscaria não acompanhar o material mais pesado.
    """
    limitados: list[str] = []
    for arg in inputs:
        if arg == "-i":
            limitados += decode_thread_args()
        limitados.append(arg)
    return limitados


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
        tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error",
        *_limited_inputs(graph.inputs),
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
    project: Project,
    at: float,
    tools: FFmpegTools,
    *,
    sample_rate: int = SAMPLE_RATE,
    channels: int = CHANNELS,
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
        "-ar", str(sample_rate),
        "-ac", str(channels),
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


def _interpolated_clips(project: Project) -> list[Clip]:
    """Os blocos que teriam quadros inventados nesta edição.

    Uma regra só, usada para oferecer a opção e para dizer o que ela vai custar:
    duas contas para a mesma decisão acabam discordando, e aqui a que discordasse
    anunciaria uma memória que não é a pedida.
    """
    return [
        clip
        for track in project.video_tracks
        for clip in track.clips
        if clip.has_image and clip.media.fps and clip.media.fps < project.fps - 0.01
    ]


def can_interpolate(project: Project) -> bool:
    """Se há bloco abaixo da taxa da tela — o único caso com o que interpolar."""
    return bool(_interpolated_clips(project))


def interpolation_bytes(project: Project) -> int:
    """Memória que uma exportação interpolada deste projeto vai pedir.

    Existe para a aba **dizer o número antes de enfileirar**, como já diz o ponto
    real do corte rápido. O ``minterpolate`` não tem controle de memória — nem
    ``mb_size``, nem desligar o ``vsbmc`` mudam o pico (medido: 1573 contra 1589
    MB) —, então o que resta é escolher uma tela que caiba e saber disso antes.

    O total soma os blocos porque o grafo instancia **um filtro por bloco**, e
    todos vivem enquanto a exportação existe. Cada um conta pelo quadro que
    recebe, que é o menor entre material e tela — a mesma regra de
    :func:`_rate_first`.
    """
    total = 0
    for clip in _interpolated_clips(project):
        pixels = project.width * project.height
        if clip.media.width and clip.media.height:
            pixels = min(pixels, clip.media.width * clip.media.height)
        total += pixels * _INTERPOLATE_BYTES_PER_PIXEL
    return total


# Quanto de um trecho paralelo é decodificado **além** do fim dele, só para o
# ``minterpolate`` ter o quadro seguinte na hora de inventar os últimos. Sem essa
# sobra, cada emenda perde os quadros que o ``tpad`` clonou: medido, 476 imagens
# distintas com sobra contra 464 sem ela, num vídeo cortado em quatro — doze
# quadros, exatamente quatro por emenda.
_SEGMENT_TAIL = 0.5

# Piso de duração de um trecho. Abaixo disto o que se paga para abrir um
# processo, decodificar a sobra e concatenar come o que se ganha dividindo.
_MIN_SEGMENT = 2.0

# Teto de trechos simultâneos. Mais que isto não acelera — o gargalo passa a ser
# a leitura do mesmo arquivo por todos eles — e multiplica a memória sem retorno.
_MAX_SEGMENTS = 8

# Fração da memória disponível que a exportação pode reservar. O resto fica para
# o sistema e para o que mais estiver aberto: o número que ``available_bytes``
# devolve é um palpite honesto do instante, não uma promessa para os próximos
# minutos, e errar aqui é derrubar a máquina — não ficar lento.
_MEMORY_SHARE = 0.5


def interpolation_segments(
    project: Project,
    *,
    available: int | None,
    cores: int,
) -> int:
    """Em quantos trechos paralelos a interpolação deste projeto pode ser feita.

    O ``minterpolate`` é **de uma thread só** — medido, 110% de CPU numa máquina
    de vinte núcleos — e é o filtro mais caro que esta aplicação usa. Dividir a
    linha do tempo e interpolar os pedaços ao mesmo tempo é a única forma de usar
    o resto da máquina: medido, 43,7 s para 16,6 s em quatro trechos (2,6×), com
    a saída indistinguível da serial (SSIM 0,997, as mesmas 476 imagens
    distintas).

    Devolver ``1`` significa "faça do jeito de sempre, num comando só", e é a
    resposta para tudo que não se encaixa: projeto sem o que interpolar, curto
    demais para dividir, máquina sem núcleos sobrando — e, principalmente,
    **memória desconhecida**. Cada trecho carrega um ``minterpolate`` inteiro, e
    foi exatamente essa memória que já derrubou a máquina uma vez: onde não dá
    para perguntar quanta há, o caminho seguro é não multiplicar nada.
    """
    custo = interpolation_bytes(project)
    if custo <= 0 or project.duration < _MIN_SEGMENT * 2:
        return 1
    if available is None:
        return 1

    por_memoria = int(available * _MEMORY_SHARE) // custo
    por_duracao = int(project.duration // _MIN_SEGMENT)
    return max(1, min(_MAX_SEGMENTS, cores, por_memoria, por_duracao))


def segment_bounds(duration: float, segments: int) -> tuple[tuple[float, float], ...]:
    """Início e duração de cada trecho, cobrindo a edição inteira sem sobrepor.

    O último absorve o resto da divisão, em vez de todos carregarem um pedaço da
    sobra: assim a soma das durações é exatamente a do projeto, e não uma soma de
    arredondamentos que erra o fim por alguns milissegundos.
    """
    if segments <= 1:
        return ((0.0, duration),)
    passo = duration / segments
    return tuple(
        (i * passo, passo if i < segments - 1 else duration - i * passo)
        for i in range(segments)
    )


def segment_video_args(
    project: Project,
    at: float,
    span: float,
    destination: Path,
    tools: FFmpegTools,
    *,
    container: str = "mp4",
    family: str | None = None,
    hardware: str = hwaccel.SOFTWARE,
) -> list[str]:
    """Um trecho da composição, **só vídeo**, para ser concatenado depois.

    O grafo é montado com uma sobra no fim (:data:`_SEGMENT_TAIL`) e a saída é
    cortada em ``span``: é a sobra que dá ao ``minterpolate`` o quadro seguinte
    de que ele precisa para inventar os últimos do trecho. Sem ela a emenda perde
    quadros interpolados, e o que aparece no lugar são clones.

    Áudio não entra aqui de propósito. Emendar trilhas codificadas em pontos
    arbitrários produz salto ou estalo na junção, porque o quadro de áudio não
    termina onde o corte cai; o som sai num passe só, que é barato.
    """
    graph = build_graph(
        project, at=at, span=span + _SEGMENT_TAIL, want_audio=False, interpolate=True
    )
    if not graph.video_label:
        raise ConversionError("O trecho não tem imagem para exportar.")
    codec_family = family or hwaccel.family_for(container)
    encoder = hwaccel.resolve(codec_family, hardware, tools)
    args = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-y", "-progress", "pipe:1"]
    args += [*encoder.device, *graph.inputs]
    filters = list(graph.filters)
    video_label = graph.video_label
    if encoder.filter_suffix:
        filters.append(f"{video_label}{encoder.filter_suffix}[vhw]")
        video_label = "[vhw]"
    filter_text = ";".join(filters)
    if len(filter_text) > 4000:
        try:
            script_path = destination.with_suffix(f".{destination.stem}_filter.txt")
            script_path.write_text(filter_text, encoding="utf-8")
            args += ["-filter_complex_script", str(script_path)]
        except OSError:
            args += ["-filter_complex", filter_text]
    else:
        args += ["-filter_complex", filter_text]
    args += ["-map", video_label, "-c:v", encoder.name, *encoder.quality]
    if encoder.name in ("libx265", "hevc_nvenc", "hevc_qsv", "hevc_amf", "hevc_vaapi") and container == "mp4":
        args += ["-tag:v", "hvc1"]
    # ``-t`` na saída, e não ``-frames:v``: a conta que interessa é a do tempo,
    # e é ela que faz a soma dos trechos bater com a duração do projeto.
    return args + ["-an", "-t", f"{span:.6f}", str(destination)]


def concat_args(
    parts: Path, destination: Path, tools: FFmpegTools
) -> list[str]:
    """Emenda os trechos **sem recodificar**, pelo demuxer ``concat``.

    Todos saíram do mesmo encoder com os mesmos parâmetros e cada um começa em
    keyframe, que são as condições para copiar os dados em vez de decodificar
    tudo de novo — o que jogaria fora o tempo que a divisão economizou.
    """
    return [
        tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(parts),
        "-c", "copy", str(destination),
    ]


def audio_only_args(
    project: Project, destination: Path, tools: FFmpegTools, *, container: str = "mp4"
) -> list[str] | None:
    """A mixagem inteira num passe só, ou ``None`` se a edição não tem som."""
    graph = build_graph(project, want_video=False)
    if not graph.audio_label:
        return None
    args = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error", "-y"]
    args += [*graph.inputs, "-filter_complex", ";".join(graph.filters)]
    args += ["-map", graph.audio_label, *encode_audio_args(container)]
    return args + [str(destination)]


def mux_args(
    video: Path, audio: Path | None, destination: Path, tools: FFmpegTools
) -> list[str]:
    """Junta imagem e som já prontos, copiando os dois."""
    args = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(video)]
    if audio is not None:
        args += ["-i", str(audio)]
    args += ["-c", "copy"]
    if audio is not None:
        # ``-shortest``: a mixagem pode passar do fim da imagem por alguns
        # milissegundos de arredondamento, e um arquivo mais longo que o vídeo
        # termina em tela preta.
        args += ["-shortest"]
    return args + [str(destination)]


def describe_export(
    project: Project,
    container: str,
    hardware: str = hwaccel.SOFTWARE,
    interpolate: bool = False,
    family: str | None = None,
    audio_only: bool = False,
    audio_codec: str | None = None,
) -> str:
    """Resumo do que a exportação vai produzir."""
    audios = sum(len(track.clips) for track in project.audio_tracks)
    if audio_only:
        codec_name = (audio_codec or container).upper()
        parts = [f".{container} (Áudio · {codec_name})"]
        if audios:
            parts.append(f"{audios} bloco(s) de áudio")
        parts.append(f"{format_span(project.duration)} de duração")
        return " · ".join(parts)

    videos = sum(len(track.clips) for track in project.video_tracks)
    codec_family = family or hwaccel.family_for(container)
    parts = [f".{container} ({hwaccel.family_label(codec_family)})"]
    if videos:
        parts.append(f"{videos} bloco(s) de imagem")
    if audios:
        parts.append(f"{audios} de áudio")
    if project.has_video:
        parts.append(f"{project.width}×{project.height} · {project.fps:g} fps")
    if interpolate and can_interpolate(project):
        parts.append("movimento interpolado (lento)")
    if hardware != hwaccel.SOFTWARE:
        parts.append("placa de vídeo, se disponível")
    parts.append(f"{format_span(project.duration)} de duração")
    return " · ".join(parts)
