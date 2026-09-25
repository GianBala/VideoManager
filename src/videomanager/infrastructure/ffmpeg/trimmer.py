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

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from videomanager.infrastructure.ffmpeg import hardware as hwaccel
from videomanager.application.capabilities import FFmpegTools
from videomanager.infrastructure.system.binaries import subprocess_kwargs
from videomanager.application.errors import ConversionError
from videomanager.domain.i18n import Text

if TYPE_CHECKING:  # pragma: no cover - só para o verificador de tipos
    from videomanager.domain.media import LocalMedia

# Recorte mais curto que isto não gera arquivo utilizável — e costuma ser
# resultado de um clique acidental na linha do tempo, não de uma intenção.
from videomanager.domain.constants import MIN_SEGMENT

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

from videomanager.domain.timing import CutMode
from videomanager.domain.timing import seek_time
from videomanager.domain.timing import TrimTarget
from videomanager.domain.timing import has_real_video


# Qualidade do corte exato. Alta de propósito: quem recorta quer o mesmo vídeo
# mais curto, não uma versão pior dele. (Na aba de conversão o objetivo é outro,
# e o CRF de lá é outro.)
_EXACT_AUDIO_BITRATE = "192k"


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
        raise ConversionError(Text("TRIM_KEYFRAMES_FAILED", error=str(exc))) from exc
    if register is not None:
        register(proc)
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.communicate()
        raise ConversionError(Text("TRIM_KEYFRAMES_TIMEOUT")) from exc
    except OSError as exc:
        # O processo pode ter ficado de pé: matá-lo antes de subir o erro.
        proc.kill()
        proc.communicate()
        raise ConversionError(Text("TRIM_KEYFRAMES_FAILED", error=str(exc))) from exc

    if proc.returncode != 0:
        raise ConversionError(Text("TRIM_KEYFRAMES_UNREADABLE"))

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


# ---------------------------------------------------------------------------
# Montagem dos argumentos (funções puras, testáveis sem ffmpeg)
# ---------------------------------------------------------------------------


def _source_fps(media: LocalMedia) -> float | None:
    stream = media.video
    return stream.fps if stream is not None else None


def _audio_encoder(container: str) -> str:
    return _EXACT_AUDIO_ENCODERS.get(container, _DEFAULT_AUDIO_ENCODER)


def _audio_encode_args(encoder: str) -> list[str]:
    args = ["-c:a", encoder]
    if encoder not in _LOSSLESS_ENCODERS:
        args += ["-b:a", _EXACT_AUDIO_BITRATE]
    return args


def encode_audio_args(container: str) -> list[str]:
    return _audio_encode_args(_audio_encoder(container))


def _validate(media: LocalMedia, target: TrimTarget) -> None:
    if not target.segments:
        raise ConversionError(Text("TRIM_NO_SEGMENTS"))
    for segment in target.segments:
        if not segment.is_usable:
            # O rótulo leva tempos com separador decimal: refeito na exibição.
            raise ConversionError(Text("TRIM_SEGMENT_TOO_SHORT", segment=Text.of(lambda s=segment: s.label)))
    if not has_real_video(media) and not media.has_audio:
        raise ConversionError(Text("TRIM_NO_TRACKS", name=media.path.name))
    if target.joins and target.mode is CutMode.FAST:
        # Recusado aqui, e não silenciosamente recodificado: a promessa de
        # "sem recodificar" não pode ser quebrada sem o usuário saber.
        raise ConversionError(Text("TRIM_JOIN_NEEDS_REENCODE"))


def tail_args(
    container: str, destination: Path, *, map_metadata: bool = True
) -> list[str]:
    args: list[str] = []
    if container == "mp4":
        # Índice no começo: permite começar a assistir antes de o arquivo todo
        # ser lido, e é o que players web esperam.
        args += ["-movflags", "+faststart"]
    if map_metadata:
        args += ["-map_metadata", "0"]
    else:
        args += ["-map_metadata", "-1", "-map_chapters", "-1"]
    args += ["-progress", "pipe:1", "-nostats", str(destination)]
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

    return args + tail_args(target.container, destination, map_metadata=target.copy_metadata)


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

    return args + tail_args(target.container, destination, map_metadata=target.copy_metadata)


def build_trim_args(
    media: LocalMedia, target: TrimTarget, destination: Path, tools: FFmpegTools
) -> list[str]:
    """Argumentos do ffmpeg para o recorte pedido."""
    _validate(media, target)
    if target.joins:
        return build_join_args(media, target, destination, tools)
    return build_single_args(media, target, destination, tools)
