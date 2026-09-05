"""Recorte de trechos de um arquivo local: a lógica da aba de edição.

Quatro decisões sustentam este módulo.

**Cortar sem recodificar só é possível em um keyframe.** Vídeo comprimido guarda
quadros completos de tempos em tempos e, entre eles, apenas diferenças — que
sozinhas não formam imagem. Por isso um corte em ``-c copy`` começa no keyframe
anterior ao ponto marcado, e não no ponto marcado. As duas saídas honestas são
recodificar (corte no quadro exato, custa tempo) ou aceitar o keyframe (corte
instantâneo, começa um pouco antes). O módulo oferece as duas e **anuncia qual
será o ponto real antes de a tarefa entrar na fila** — daí :func:`keyframe_times`
mapear os keyframes com o ffprobe em vez de deixar o usuário descobrir depois.

**Buscar um quadro é pedir um instante ligeiramente anterior a ele.** O ``-ss``
do ffmpeg entrega o primeiro quadro cujo pts é *maior ou igual* ao pedido. Pedir
exatamente ``índice / fps`` erra por um quadro sempre que o arredondamento do
float cair para cima — em 29,97 fps isso acontece o tempo todo. :func:`seek_time`
recua um quarto de quadro, que é curto demais para alcançar o quadro anterior e
longo o bastante para absorver o erro do float.

**Juntar trechos exige recodificar.** Vários pedaços viram um arquivo só pelo
filtro ``concat``, que trabalha sobre quadros decodificados. Não há como
concatenar em ``-c copy`` num comando só, então a combinação "juntar" + "sem
recodificar" é recusada aqui, na montagem dos argumentos, e explicada na tela
antes de o usuário escolhê-la.

**Um trecho só não passa pelo filtro.** Com um único recorte usamos ``-ss``
antes do ``-i``, que salta direto para o ponto pedido; o ``concat`` teria de
decodificar o arquivo desde o começo. Num vídeo de uma hora, a diferença entre
os dois caminhos é de minutos.
"""

from __future__ import annotations

import bisect
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from . import hwaccel
from .binaries import FFmpegTools, subprocess_kwargs
from .errors import ConversionError

if TYPE_CHECKING:  # pragma: no cover - só para o verificador de tipos
    from .converter import LocalMedia

# Recorte mais curto que isto não gera arquivo utilizável — e costuma ser
# resultado de um clique acidental na linha do tempo, não de uma intenção.
MIN_SEGMENT = 0.05

# Codecs do corte exato, por container de saída. O recorte preserva o container
# da origem, então pôr H.264 dentro de um .webm — ou AAC dentro de um .mp3 —
# geraria um arquivo que quase nenhum player abre, quando o ffmpeg não recusa
# antes de começar.
_EXACT_VIDEO_ENCODERS = {"webm": "libvpx-vp9"}
_DEFAULT_VIDEO_ENCODER = "libx264"

_EXACT_AUDIO_ENCODERS = {
    "mp3": "libmp3lame",
    "opus": "libopus",
    "webm": "libopus",
    "ogg": "libvorbis",
    "oga": "libvorbis",
    "flac": "flac",
    "wav": "pcm_s16le",
}
_DEFAULT_AUDIO_ENCODER = "aac"

# Codecs sem perda: pedir bitrate para eles não significa nada, e o ffmpeg
# ignora ou reclama.
_LOSSLESS_ENCODERS = {"flac", "pcm_s16le", "alac"}

# Nome de exibição de cada encoder, para o texto de "o que vai acontecer".
_ENCODER_NAMES = {
    "libx264": "H.264",
    "libvpx-vp9": "VP9",
    "libmp3lame": "MP3",
    "libopus": "Opus",
    "libvorbis": "Vorbis",
    "pcm_s16le": "WAV",
    "aac": "AAC",
    "flac": "FLAC",
}

# Capa de MP3 e miniatura embutida aparecem como trilha de vídeo. Recodificá-las
# como vídeo produz um arquivo de uma imagem só, com horas de duração.
IMAGE_CODECS = {"mjpeg", "png", "bmp", "gif", "webp"}

# Qualidade do corte exato. Alta de propósito: quem recorta quer o mesmo vídeo
# mais curto, não uma versão pior dele. (Na aba de conversão o objetivo é outro,
# e o CRF de lá é outro.)
_X264_CRF = 18
_VP9_CRF = 30
_EXACT_AUDIO_BITRATE = "192k"


class CutMode(Enum):
    """Como o corte trata os quadros que não são keyframe."""

    FAST = "rapido"  # -c copy: instantâneo, começa no keyframe anterior
    EXACT = "exato"  # recodifica: começa no quadro marcado


# ---------------------------------------------------------------------------
# Timecode
# ---------------------------------------------------------------------------

# Aceita "12", "12,5", "1:23.45", "01:02:03,250". A vírgula decimal é a forma
# em pt-BR (é a que o próprio formato de legenda .srt usa no Brasil), mas o
# ponto também é aceito: teclado numérico e conteúdo colado usam ponto.
_SECONDS = re.compile(r"^\d{1,2}(?:[.,]\d{1,6})?$")
_WHOLE = re.compile(r"^\d{1,3}$")


def parse_timecode(text: str) -> float | None:
    """Converte ``h:mm:ss,mmm`` em segundos. ``None`` se não for um timecode.

    Devolver ``None`` em vez de levantar é deliberado: quem chama é um campo de
    texto sendo digitado, onde um valor incompleto é o estado normal e não um
    erro a relatar.
    """
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3 or not _SECONDS.match(parts[-1]):
        return None
    if any(not _WHOLE.match(part) for part in parts[:-1]):
        return None

    total = float(parts[-1].replace(",", "."))
    # Com minuto ou hora à frente, os campos seguintes são de timecode e não
    # aceitam transbordo: "1:99" tanto pode ser um erro de digitação quanto
    # 2:39, e num campo de precisão adivinhar é pior que devolver o valor
    # anterior, que continua à vista.
    if len(parts) >= 2:
        if total >= 60:
            return None
        total += int(parts[-2]) * 60
    if len(parts) == 3:
        if int(parts[-2]) >= 60:
            return None
        total += int(parts[0]) * 3600
    return total


def format_timecode(seconds: float | None, *, milliseconds: bool = True) -> str:
    """Segundos como ``h:mm:ss,mmm`` — a forma que o campo de tempo aceita de volta.

    Arredondado ao milissegundo, e não truncado: um instante marcado em 5,3 s
    chega aqui como 5,2999999 (é o que o float guarda), e truncar mostraria
    "5,299" a quem acabou de digitar "5,3". O erro do arredondamento é de meio
    milissegundo — fração de quadro em qualquer framerate — e o que o corte usa
    é o valor em segundos, não este texto.
    """
    if seconds is None or seconds < 0:
        seconds = 0.0
    total = int(seconds * 1000 + 0.5)
    hours, rest = divmod(total, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    base = f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{base},{millis:03d}" if milliseconds else base


def format_span(seconds: float) -> str:
    """Duração de um trecho, para rótulos onde o timecode completo seria ruído.

    Abaixo de um minuto, segundos com duas casas ("4,25 s") — que é como se fala
    da duração de um corte. Acima, o timecode sem a hora enquanto ela for zero.
    """
    if seconds < 60:
        return f"{seconds:.2f}".replace(".", ",") + " s"
    label = format_timecode(seconds)
    return label[2:] if label.startswith("0:") else label


# ---------------------------------------------------------------------------
# Quadros
# ---------------------------------------------------------------------------


def frame_index(seconds: float, fps: float | None) -> int:
    """Número do quadro que está na tela no instante dado."""
    if not fps or fps <= 0:
        return 0
    # A tolerância absorve o erro do float: sem ela, um instante calculado como
    # 7,499999999 em vez de 7,5 devolve o quadro anterior.
    return max(0, int(seconds * fps + 1e-6))


def frame_time(index: int, fps: float | None) -> float:
    if not fps or fps <= 0:
        return 0.0
    return max(0, index) / fps


def frame_step(fps: float | None) -> float:
    """Duração de um quadro — o passo fino da navegação.

    Sem vídeo (um arquivo de áudio na aba de edição) não há quadro; 10 ms é um
    passo que ainda é preciso para o ouvido e não deixa a navegação travada.
    """
    return 1.0 / fps if fps and fps > 0 else 0.010


def seek_time(seconds: float, fps: float | None) -> float:
    """Instante a pedir ao ffmpeg para obter o quadro que contém ``seconds``.

    Ver a explicação no topo do módulo: o ``-ss`` entrega o primeiro quadro com
    pts ``>=`` ao pedido, então pedimos o começo do quadro recuado de um quarto
    de quadro.
    """
    if not fps or fps <= 0:
        return max(0.0, seconds)
    start = frame_time(frame_index(seconds, fps), fps)
    return max(0.0, start - 0.25 / fps)


# ---------------------------------------------------------------------------
# Trechos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Segment:
    """Um trecho do arquivo, em segundos a partir do início."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def is_usable(self) -> bool:
        return self.duration >= MIN_SEGMENT

    def contains(self, seconds: float) -> bool:
        return self.start <= seconds <= self.end

    def split_at(self, seconds: float) -> tuple[Segment, ...]:
        """Divide no instante dado. Devolve o trecho intacto se o corte não couber.

        É a operação da tesoura: dividir onde não há espaço para os dois lados
        criaria um trecho de duração zero, que o ffmpeg recusa.
        """
        if (
            seconds - self.start < MIN_SEGMENT
            or self.end - seconds < MIN_SEGMENT
        ):
            return (self,)
        return (Segment(self.start, seconds), Segment(seconds, self.end))

    @property
    def label(self) -> str:
        return (
            f"{format_timecode(self.start)} → {format_timecode(self.end)}"
            f"  ({format_span(self.duration)})"
        )


@dataclass(frozen=True)
class TrimTarget:
    """Pedido de recorte, pronto para virar argumentos do ffmpeg.

    ``anchor`` é o keyframe em que a cópia direta vai realmente começar, quando
    ele já é conhecido. Fica no pedido — e não é descoberto na hora de montar os
    argumentos — para que a tela mostre o ponto real de corte antes de
    enfileirar, com o mesmo número que o ffmpeg vai usar.
    """

    segments: tuple[Segment, ...]
    container: str = "mp4"
    mode: CutMode = CutMode.EXACT
    anchor: float | None = None
    # Preferência de codificação por placa. Fica no pedido, e não numa variável
    # global, porque é o pedido que atravessa a fila até o worker.
    hardware: str = hwaccel.SOFTWARE

    @property
    def extension(self) -> str:
        return self.container

    @property
    def joins(self) -> bool:
        return len(self.segments) > 1

    @property
    def effective_segments(self) -> tuple[Segment, ...]:
        """Os trechos que a saída vai conter de fato.

        Diferem dos marcados apenas na cópia direta, onde o início escorrega
        para o keyframe anterior.
        """
        if self.mode is CutMode.FAST and self.anchor is not None and self.segments:
            first = self.segments[0]
            return (Segment(min(self.anchor, first.start), first.end),) + self.segments[1:]
        return self.segments

    @property
    def output_duration(self) -> float:
        return sum(segment.duration for segment in self.effective_segments)

    @property
    def drift(self) -> float:
        """Quanto o corte real começa antes do ponto marcado, em segundos."""
        if self.mode is not CutMode.FAST or self.anchor is None or not self.segments:
            return 0.0
        return max(0.0, self.segments[0].start - self.anchor)


# ---------------------------------------------------------------------------
# Keyframes
# ---------------------------------------------------------------------------


def keyframe_times(
    path: Path,
    tools: FFmpegTools,
    *,
    limit: int = 50_000,
    timeout: int = 180,
    register: Callable[[subprocess.Popen], None] | None = None,
) -> tuple[float, ...]:
    """Instantes em que o corte sem recodificar pode começar.

    Usa ``-show_packets``, que apenas demultiplexa o arquivo: é ordens de
    grandeza mais rápido que ``-skip_frame nokey``, que decodifica cada keyframe
    para depois jogá-lo fora. Num vídeo de vinte segundos a diferença é
    imperceptível; num de duas horas é a diferença entre a interface responder e
    a interface esperar.

    ``register`` entrega o processo a quem chamou, para poder interrompê-lo.
    Este é o mais demorado dos trabalhos de fundo da aba — num arquivo de duas
    horas ele percorre o índice inteiro —, e o destrutor do ``QThreadPool``
    espera as threads dele: sem poder matá-lo, fechar a janela logo depois de
    importar um arquivo longo segurava a saída do aplicativo até o prazo acabar.
    """
    command = [
        tools.ffprobe_str,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_packets",
        "-show_entries", "packet=pts_time,flags",
        "-of", "csv=p=0",
        str(path),
    ]
    try:
        proc = subprocess.Popen(command, **subprocess_kwargs())
    except OSError as exc:
        raise ConversionError(f"Falha ao mapear os keyframes: {exc}") from exc
    if register is not None:
        register(proc)
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.communicate()
        raise ConversionError(
            "O ffprobe passou do tempo ao mapear os keyframes deste arquivo."
        ) from exc
    except OSError as exc:
        # O processo pode ter ficado de pé: matá-lo antes de subir o erro.
        proc.kill()
        proc.communicate()
        raise ConversionError(f"Falha ao mapear os keyframes: {exc}") from exc

    if proc.returncode != 0:
        raise ConversionError(
            "O ffprobe não conseguiu mapear os keyframes deste arquivo."
        )

    times: list[float] = []
    for line in (stdout or b"").decode("utf-8", "replace").splitlines():
        moment = _keyframe_line(line)
        if moment is None:
            continue
        times.append(moment)
        if len(times) >= limit:
            break
    times.sort()
    return tuple(times)


def _keyframe_line(line: str) -> float | None:
    """Lê ``pts_time,flags`` de uma linha do ffprobe. ``None`` se não for keyframe."""
    fields = line.strip().split(",")
    # "K" é a marca de keyframe; as demais posições da bandeira dizem outras
    # coisas ("D" de descartável, "C" de corrompido) e não interessam aqui.
    if len(fields) < 2 or "K" not in fields[1]:
        return None
    try:
        return float(fields[0])
    except ValueError:
        # pts_time=N/A acontece em fluxos sem timestamp de apresentação.
        return None


def keyframe_at_or_before(times: tuple[float, ...], seconds: float) -> float | None:
    """Onde a cópia direta começaria se o corte fosse pedido em ``seconds``."""
    if not times:
        return None
    position = bisect.bisect_right(times, seconds + 1e-6)
    return times[position - 1] if position else times[0]


def keyframe_after(times: tuple[float, ...], seconds: float) -> float | None:
    """Próximo keyframe, para quem prefere mover a marca a recodificar."""
    if not times:
        return None
    position = bisect.bisect_right(times, seconds + 1e-6)
    return times[position] if position < len(times) else None


def nearest_keyframe(times: tuple[float, ...], seconds: float) -> float | None:
    before = keyframe_at_or_before(times, seconds)
    after = keyframe_after(times, seconds)
    if before is None:
        return after
    if after is None:
        return before
    return before if seconds - before <= after - seconds else after


# ---------------------------------------------------------------------------
# Montagem dos argumentos (funções puras, testáveis sem ffmpeg)
# ---------------------------------------------------------------------------


def has_real_video(media: LocalMedia) -> bool:
    """Se há trilha de vídeo de verdade, e não a capa embutida de um áudio."""
    stream = media.video
    return stream is not None and stream.codec.lower() not in IMAGE_CODECS


def _source_fps(media: LocalMedia) -> float | None:
    stream = media.video
    return stream.fps if stream is not None else None


def _video_encoder(container: str) -> str:
    return _EXACT_VIDEO_ENCODERS.get(container, _DEFAULT_VIDEO_ENCODER)


def _audio_encoder(container: str) -> str:
    return _EXACT_AUDIO_ENCODERS.get(container, _DEFAULT_AUDIO_ENCODER)


def _audio_encode_args(encoder: str) -> list[str]:
    args = ["-c:a", encoder]
    if encoder not in _LOSSLESS_ENCODERS:
        args += ["-b:a", _EXACT_AUDIO_BITRATE]
    return args


def _video_encode_args(encoder: str) -> list[str]:
    if encoder == "libvpx-vp9":
        # Sem ``-b:v 0`` o VP9 trata o CRF como teto de bitrate e o corte sai
        # visivelmente pior que a origem.
        return ["-c:v", "libvpx-vp9", "-crf", str(_VP9_CRF), "-b:v", "0"]
    if encoder == "libx264":
        # yuv420p é o único formato de pixel que reproduz em qualquer lugar.
        return [
            "-c:v", "libx264",
            "-crf", str(_X264_CRF),
            "-preset", "medium",
            "-pix_fmt", "yuv420p",
        ]
    return ["-c:v", encoder]


def encode_video_args(
    container: str,
    *,
    hardware: str = hwaccel.SOFTWARE,
    tools: FFmpegTools | None = None,
) -> list[str]:
    """Argumentos de codificação de vídeo para este container.

    Público porque o compositor da linha do tempo (``core/composer.py``) grava
    com as mesmas escolhas do recorte. A escolha do encoder passa pelo
    ``hwaccel``, que sonda a placa antes de usá-la e cai para software quando
    ela não abre — sem isso, uma preferência guardada numa máquina viraria
    exportação falhada noutra.
    """
    return hwaccel.encode_args(hwaccel.family_for(container), hardware, tools)


def encode_audio_args(container: str) -> list[str]:
    return _audio_encode_args(_audio_encoder(container))


def _validate(media: LocalMedia, target: TrimTarget) -> None:
    if not target.segments:
        raise ConversionError("Não há nenhum trecho para exportar.")
    for segment in target.segments:
        if not segment.is_usable:
            raise ConversionError(
                f"O trecho {segment.label} é curto demais para virar um arquivo."
            )
    if not has_real_video(media) and not media.has_audio:
        raise ConversionError(
            f"“{media.path.name}” não tem trilha de vídeo nem de áudio para recortar."
        )
    if target.joins and target.mode is CutMode.FAST:
        # Recusado aqui, e não silenciosamente recodificado: a promessa de
        # "sem recodificar" não pode ser quebrada sem o usuário saber.
        raise ConversionError(
            "Juntar vários trechos num arquivo só exige recodificar. Escolha o "
            "corte exato, ou exporte cada trecho em um arquivo."
        )


def tail_args(container: str, destination: Path) -> list[str]:
    args: list[str] = []
    if container == "mp4":
        # Índice no começo: permite começar a assistir antes de o arquivo todo
        # ser lido, e é o que players web esperam.
        args += ["-movflags", "+faststart"]
    args += [
        "-map_metadata", "0",
        "-metadata", "title=",
        "-progress", "pipe:1",
        "-nostats",
        str(destination),
    ]
    return args


def build_single_args(
    media: LocalMedia, target: TrimTarget, destination: Path, tools: FFmpegTools
) -> list[str]:
    """Um trecho só: ``-ss`` antes do ``-i``, que salta direto para o ponto."""
    segment = target.segments[0]
    has_video = has_real_video(media)

    if target.mode is CutMode.FAST:
        # Sem recodificar não há como parar num quadro qualquer: o ponto de
        # partida é o keyframe. Quando ele já é conhecido, pedimos exatamente
        # ele — pedir um instante anterior faria o ffmpeg recuar mais um.
        start = target.anchor if target.anchor is not None else segment.start
    else:
        start = seek_time(segment.start, _source_fps(media))

    args = [
        tools.ffmpeg_str,
        "-nostdin",
        "-hide_banner",
        "-y",
        "-ss", f"{start:.6f}",
        "-i", str(media.path),
        # A duração conta a partir de onde a busca parou, e não do ponto
        # marcado: é o que faz o trecho terminar onde o usuário pediu mesmo
        # quando o início escorregou para trás.
        "-t", f"{max(MIN_SEGMENT, segment.end - start):.6f}",
    ]
    if has_video:
        args += ["-map", "0:v:0"]
    if media.has_audio:
        args += ["-map", "0:a:0"]

    if target.mode is CutMode.FAST:
        # ``make_zero`` evita timestamps negativos no começo do arquivo, que em
        # vários players aparecem como um congelamento antes de a imagem andar.
        args += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    else:
        if has_video:
            family = hwaccel.family_for(target.container)
            encoder = hwaccel.resolve(family, target.hardware, tools)
            args[1:1] = list(encoder.device)
            if encoder.filter_suffix:
                args += ["-vf", f"format=nv12,{encoder.filter_suffix}"]
            args += ["-c:v", encoder.name, *encoder.quality]
        if media.has_audio:
            # O áudio é recodificado junto: copiá-lo manteria os quadros de som
            # inteiros da origem, que começam antes do corte e empurram a
            # imagem para fora de sincronia logo no primeiro segundo.
            args += _audio_encode_args(_audio_encoder(target.container))

    return args + tail_args(target.container, destination)


def build_join_args(
    media: LocalMedia, target: TrimTarget, destination: Path, tools: FFmpegTools
) -> list[str]:
    """Vários trechos num arquivo só, pelo filtro ``concat``.

    ``setpts=PTS-STARTPTS`` em cada pedaço é o que faz o seguinte começar onde o
    anterior terminou: sem isso os trechos mantêm o tempo original e o arquivo
    sai com horas de vazio entre eles.
    """
    has_video = has_real_video(media)
    has_audio = media.has_audio

    steps: list[str] = []
    labels: list[str] = []
    for index, segment in enumerate(target.segments):
        if has_video:
            steps.append(
                f"[0:v]trim=start={segment.start:.6f}:end={segment.end:.6f},"
                f"setpts=PTS-STARTPTS[v{index}]"
            )
            labels.append(f"[v{index}]")
        if has_audio:
            steps.append(
                f"[0:a]atrim=start={segment.start:.6f}:end={segment.end:.6f},"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )
            labels.append(f"[a{index}]")

    count = len(target.segments)
    outputs = ""
    if has_video:
        outputs += "[v]"
    if has_audio:
        outputs += "[a]"
    steps.append(
        "".join(labels)
        + f"concat=n={count}:v={int(has_video)}:a={int(has_audio)}{outputs}"
    )

    args = [
        tools.ffmpeg_str,
        "-nostdin",
        "-hide_banner",
        "-y",
        "-i", str(media.path),
        "-filter_complex", ";".join(steps),
    ]
    if has_video:
        family = hwaccel.family_for(target.container)
        encoder = hwaccel.resolve(family, target.hardware, tools)
        args[1:1] = list(encoder.device)
        if encoder.filter_suffix:
            steps[-1] = steps[-1].replace("[v]", "[vsw]")
            steps.append(f"[vsw]{encoder.filter_suffix}[v]")
            args[args.index("-filter_complex") + 1] = ";".join(steps)
        args += ["-map", "[v]", "-c:v", encoder.name, *encoder.quality]
    if has_audio:
        args += ["-map", "[a]"] + _audio_encode_args(_audio_encoder(target.container))

    return args + tail_args(target.container, destination)


def build_trim_args(
    media: LocalMedia, target: TrimTarget, destination: Path, tools: FFmpegTools
) -> list[str]:
    """Argumentos do ffmpeg para o recorte pedido."""
    _validate(media, target)
    if target.joins:
        return build_join_args(media, target, destination, tools)
    return build_single_args(media, target, destination, tools)


def describe_trim(media: LocalMedia, target: TrimTarget) -> str:
    """Resumo do que o recorte vai fazer, para exibir antes de começar."""
    video = has_real_video(media)
    parts = [f".{target.container}"]
    if not video:
        parts.append("somente áudio")
    if target.joins:
        parts.append(f"{len(target.segments)} trechos unidos")
    if target.mode is CutMode.FAST:
        parts.append("cópia direta (sem recodificar)")
    else:
        # O codec anunciado é o da trilha que existe: dizer "recodifica em
        # H.264" ao recortar um MP3 descreveria um arquivo que não existe.
        if video:
            family = hwaccel.family_for(target.container)
            nome = hwaccel.family_label(family)
            if target.hardware != hwaccel.SOFTWARE:
                nome += " (placa, se disponível)"
        else:
            encoder = _audio_encoder(target.container)
            nome = _ENCODER_NAMES.get(encoder, encoder)
        parts.append(f"corte exato · recodifica em {nome}")
    parts.append(f"{format_span(target.output_duration)} de duração")
    return " · ".join(parts)
