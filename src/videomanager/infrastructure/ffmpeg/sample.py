"""Bitrate do que vai ser codificado, medido em trechos e não adivinhado.

Quanto um vídeo encolhe depende do conteúdo, e nenhum metadado mostra isso.
Medido em gravações reais com o mesmo bitrate de origem: uma tela quase parada
do OBS saiu com 4% do tamanho, a fonte sintética com movimento, com 70%. A
estimativa por pixels errava de −66% a +1500%. Codificar trechos com o mesmo
comando da conversão mede o que o encoder faz com *este* conteúdo.

Onde os trechos ficam e como a conta passa deles ao arquivo inteiro é de
``domain/size_model.py`` (estratos, trecho representativo pela curva da fonte,
estimador de razão). Aqui está o que toca em processo: ler a curva da fonte,
codificar os trechos e somar os bytes que o encoder gravou.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.errors import ConversionError
from videomanager.domain import size_model
from videomanager.domain.i18n import Text
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import VideoTarget
from videomanager.infrastructure.ffmpeg.converter import build_audio_args
from videomanager.infrastructure.ffmpeg.converter import build_video_args
from videomanager.infrastructure.system.memory import available_bytes
from videomanager.infrastructure.system.process import ProcessControl

# Pico de memória de uma amostra por pixel do quadro de origem, medido nesta
# máquina (20 núcleos, threads automáticas): 4,3 GB num 4K em H.264, 4,1 GB em
# AV1, 2,6 GB em HEVC, e 1,25 GB num 1080p — até 600 bytes por pixel. Pesam a
# decodificação e o lookahead, não o que sai; limitar threads não resolve (o
# x264 cai para 2,3 GB e mede 4,7% a menos, o SVT-AV1 chegou a 6,4 GB). É o que a
# própria conversão vai pedir; o risco é somar a ela, com a fila convertendo
# ao lado.
# ponytail: medido com 20 núcleos; máquina com muito mais núcleos pede mais.
_BYTES_PER_PIXEL = 600
# Fração do disponível, como na interpolação (``composer._MEMORY_SHARE``), só que
# maior porque aqui não se multiplica nada: com 7 GB disponíveis um 4K é
# medido; com uma conversão 4K rodando ao lado (sobram ~2,7 GB), não.
_MEMORY_SHARE = 0.7

# Prazos: a curva da fonte só demultiplexa (1 GB em 2 s), mas pode estar num disco de rede; um trecho é uns segundos de
# vídeo, e o AV1 em software é lento.
_CURVE_TIMEOUT = 120
_WINDOW_TIMEOUT = 180

# Áudio: o encoder custa centenas de vezes o tempo real, então se mede mais denso do que o vídeo. Oito trechos de 5 s
# (40 s, meio segundo de CPU) erraram no máximo 3,6% em vídeos reais, contra os 35% do bitrate nominal do AAC e os 27% do
# Opus, que variam com o conteúdo.
AUDIO_STRATA = 8
AUDIO_WINDOW_SECONDS = 5.0


def fits_in_memory(media: LocalMedia) -> bool:
    """Se há memória para medir sem arriscar a máquina; não saber é não medir."""
    video = media.video
    pixels = (video.width or 0) * (video.height or 0) if video else 0
    available = available_bytes()
    return available is not None and pixels * _BYTES_PER_PIXEL <= available * _MEMORY_SHARE


def _require_memory(media: LocalMedia) -> None:
    if not fits_in_memory(media):
        # A conta por pixels fica no lugar: pior estimativa, máquina de pé.
        raise ConversionError(Text("CONVERT_SAMPLE_FAILED"))


def source_curve(media: LocalMedia, tools: FFmpegTools, control: ProcessControl) -> size_model.SourceCurve | None:
    """Quanto a fonte pesa a cada segundo; ``None`` quando o arquivo não deixa ler (a conta cai na extrapolação direta)."""
    stream = media.video
    duration = media.duration or 0.0
    if stream is None or duration <= 0:
        return None
    command = [
        tools.ffprobe_str, "-v", "error", "-select_streams", str(stream.index),
        # O início do arquivo vem junto: TS, MTS e gravações de câmera não começam em zero, e o ``-ss`` conta a partir dele.
        "-show_entries", "packet=pts_time,dts_time,size:format=start_time", "-of", "csv=p=0", str(media.path),
    ]
    try:
        result = control.run(command, timeout=_CURVE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None  # sem a curva a amostra segue: pior estimativa, mas segue
    if result.returncode != 0:
        return None
    start = 0.0
    packets: list[tuple[float, int]] = []
    for line in result.stdout.decode(errors="replace").splitlines():
        parts = line.split(",")
        try:
            if len(parts) == 1:
                start = float(parts[0])  # o ffprobe lista o formato depois dos pacotes
                continue
            instant = parts[0] if parts[0] not in ("", "N/A") else parts[1]
            packets.append((float(instant), int(parts[2])))
        except (ValueError, IndexError):
            continue
    packets = [(instant - start, size) for instant, size in packets]
    return size_model.SourceCurve.from_packets(packets, duration) if packets else None


def payload_bytes(path: Path, selector: str, tools: FFmpegTools, control: ProcessControl) -> int:
    """Soma dos pacotes de uma trilha: o que o encoder gravou, sem o container (cuja sobra, por trecho, distorce)."""
    command = [tools.ffprobe_str, "-v", "error", "-select_streams", selector, "-show_entries", "packet=size",
               "-of", "csv=p=0", str(path)]
    result = control.run(command, timeout=_WINDOW_TIMEOUT)
    if result.returncode != 0:
        raise ConversionError(Text("CONVERT_SAMPLE_FAILED"))
    return sum(int(value) for value in result.stdout.split() if value.isdigit())


def _encode_window(silent: LocalMedia, target: VideoTarget, tools: FFmpegTools, control: ProcessControl,
                   output: Path, start: float, length: float, timeout: float) -> float:
    """Codifica ``length`` s a partir de ``start`` como a conversão faria; devolve os segundos de relógio que levou."""
    args = build_video_args(silent, target, output, tools)
    at = args.index("-i")
    args[at:at] = ["-ss", f"{start:.3f}", "-t", f"{length:.3f}"]
    began = time.monotonic()
    result = control.run(args, timeout=timeout)
    if result.returncode != 0 or not output.is_file():
        raise ConversionError(Text("CONVERT_SAMPLE_FAILED"))
    return time.monotonic() - began


def sample_video_kbps(media: LocalMedia, target: VideoTarget, tools: FFmpegTools,
                      control: ProcessControl) -> float:
    """O bitrate do vídeo de ``target`` para o arquivo inteiro, a partir de trechos codificados de verdade."""
    duration = media.duration or 0.0
    # Antes de qualquer processo, inclusive o que lê a curva: sem memória, nada roda.
    _require_memory(media)
    # Só a imagem: o áudio tem a própria medida.
    silent = replace(media, streams=tuple(stream for stream in media.streams if stream.kind == "video"))
    curve = source_curve(media, tools, control)
    windows: list[size_model.Window] = []
    with tempfile.TemporaryDirectory(prefix="videomanager-amostra-") as folder:
        speed = float("inf")
        if duration > size_model.MIN_CONTENT:
            # O piloto, no meio do arquivo: quanto o encoder anda neste conteúdo decide quanto dele se mede.
            pilot = size_model.PILOT_SECONDS
            elapsed = _encode_window(silent, target, tools, control, Path(folder) / f"piloto.{target.extension}",
                                     max(0.0, duration / 2 - pilot / 2), pilot, _WINDOW_TIMEOUT)
            speed = pilot / max(elapsed, 0.05)
        strata, length = size_model.plan_design(duration, speed)
        # Medir o arquivo inteiro leva o que o piloto prometeu, com folga para o conteúdo não ser uniforme.
        timeout = max(_WINDOW_TIMEOUT, 10 * length / speed) if speed != float("inf") else _WINDOW_TIMEOUT
        for index, (start, window_length) in enumerate(size_model.plan_windows(duration, curve, strata, length)):
            # De novo a cada trecho: a fila pode ter começado uma conversão pesada desde o anterior.
            _require_memory(media)
            output = Path(folder) / f"{index}.{target.extension}"
            _encode_window(silent, target, tools, control, output, start, window_length, timeout)
            windows.append(size_model.Window(start, window_length, payload_bytes(output, "v:0", tools, control)))
    total = size_model.project_bytes(duration, windows, curve)
    if total is None:
        raise ConversionError(Text("CONVERT_SAMPLE_FAILED"))
    return total * 8 / 1000 / duration


def sample_audio_kbps(media: LocalMedia, target: AudioTarget, tools: FFmpegTools, control: ProcessControl) -> float:
    """O bitrate do áudio de ``target`` para a trilha inteira, medido em trechos."""
    duration = media.duration or 0.0
    windows: list[size_model.Window] = []
    with tempfile.TemporaryDirectory(prefix="videomanager-amostra-") as folder:
        for index, (start, length) in enumerate(
                size_model.plan_windows(duration, None, AUDIO_STRATA, AUDIO_WINDOW_SECONDS)):
            output = Path(folder) / f"{index}.{target.extension}"
            args = build_audio_args(media, replace(target, reencode=True), output, tools)
            at = args.index("-i")
            args[at:at] = ["-ss", f"{start:.3f}", "-t", f"{length:.3f}"]
            result = control.run(args, timeout=_WINDOW_TIMEOUT)
            if result.returncode != 0 or not output.is_file():
                raise ConversionError(Text("CONVERT_SAMPLE_FAILED"))
            windows.append(size_model.Window(start, length, payload_bytes(output, "a:0", tools, control)))
    total = size_model.project_bytes(duration, windows, None)
    if total is None:
        raise ConversionError(Text("CONVERT_SAMPLE_FAILED"))
    return total * 8 / 1000 / duration


def sample_kbps(media: LocalMedia, target: VideoTarget | AudioTarget, tools: FFmpegTools,
                control: ProcessControl) -> float:
    """O bitrate medido do que ``target`` grava: o vídeo, ou o áudio de uma conversão só de som."""
    if isinstance(target, AudioTarget):
        return sample_audio_kbps(media, target, tools, control)
    return sample_video_kbps(media, target, tools, control)
