"""Bitrate do vídeo comprimido medido em trechos, e não adivinhado.

Quanto um vídeo encolhe depende do conteúdo, e nenhum metadado mostra isso.
Medido em gravações reais com o mesmo bitrate de origem: uma tela quase parada
do OBS saiu com 4% do tamanho, a fonte sintética com movimento, com 70%. A
estimativa por pixels errava de −66% a +1500%. Codificar trechos com o mesmo
comando da conversão mede o que o encoder faz com *este* conteúdo.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.errors import ConversionError
from videomanager.domain.i18n import Text
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import VideoTarget
from videomanager.infrastructure.ffmpeg.converter import build_video_args
from videomanager.infrastructure.system.memory import available_bytes
from videomanager.infrastructure.system.process import ProcessControl

# Medido contra a codificação completa de 6 vídeos reais (90–120 s) em três
# níveis: com 3 trechos de 2 s o erro chegava a +195%, com 3 de 4 s a +76% e com
# 3 de 8 s ficou em −38% no pior caso (tela quase parada do OBS) e até 13% no
# resto. O que decide é o keyframe que abre cada trecho: 8 s é o intervalo de
# keyframes do x264 (250 quadros a 30 fps), e trechos desse tamanho têm a mesma
# proporção de keyframes que o arquivo inteiro.
SAMPLES = 3
SAMPLE_SECONDS = 8.0

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


def fits_in_memory(media: LocalMedia) -> bool:
    """Se há memória para medir sem arriscar a máquina; não saber é não medir."""
    video = media.video
    pixels = (video.width or 0) * (video.height or 0) if video else 0
    available = available_bytes()
    return available is not None and pixels * _BYTES_PER_PIXEL <= available * _MEMORY_SHARE


def sample_windows(duration: float) -> list[tuple[float, float]]:
    """Trechos espalhados pelo arquivo; curto demais para isso, o arquivo inteiro."""
    if duration <= 0:
        return []
    if duration <= SAMPLES * SAMPLE_SECONDS:
        return [(0.0, duration)]
    return [(duration * (index + 1) / (SAMPLES + 1) - SAMPLE_SECONDS / 2, SAMPLE_SECONDS)
            for index in range(SAMPLES)]


def sample_video_kbps(media: LocalMedia, target: VideoTarget, tools: FFmpegTools,
                      control: ProcessControl) -> float:
    # Só a imagem: o áudio a estimativa já acerta pela conta (medido: erro de 4%).
    silent = replace(media, streams=tuple(stream for stream in media.streams if stream.kind == "video"))
    total_bytes = total_seconds = 0.0
    with tempfile.TemporaryDirectory(prefix="videomanager-amostra-") as folder:
        for index, (start, length) in enumerate(sample_windows(media.duration or 0.0)):
            if not fits_in_memory(media):
                # A conta por pixels fica no lugar: pior estimativa, máquina de pé.
                raise ConversionError(Text("CONVERT_SAMPLE_FAILED"))
            output = Path(folder) / f"{index}.{target.extension}"
            args = build_video_args(silent, target, output, tools)
            at = args.index("-i")
            args[at:at] = ["-ss", f"{start:.3f}", "-t", f"{length:.3f}"]
            result = control.run(args, timeout=180)
            if result.returncode != 0 or not output.is_file():
                raise ConversionError(Text("CONVERT_SAMPLE_FAILED"))
            total_bytes += output.stat().st_size
            total_seconds += length
    if total_seconds <= 0:
        raise ConversionError(Text("CONVERT_SAMPLE_FAILED"))
    return total_bytes * 8 / 1000 / total_seconds
