"""Recodificar um vídeo já baixado para um bitrate médio escolhido.

O download nunca recodifica por conta própria (ver ``yt_dlp/selector.py``). Pedir um bitrate de vídeo é o consentimento: o
yt-dlp entrega o arquivo como o site o serve, e este módulo o codifica de novo, mantendo o que não é imagem (áudio, legendas,
capa, metadados) como está.

Três decisões:

- **O codec da fonte, se o container o aceita.** Um vídeo H.264 sai H.264, um VP9 sai VP9: trocar de codec junto com o
  bitrate mudaria o que o usuário pediu e o que o aparelho dele toca. Onde o container não aceita o codec (VP9 em MP4), a
  saída é H.264 em MP4 e MKV, e VP9 em WebM.
- **Nada de aumentar.** Uma fonte que já está no bitrate pedido, ou abaixo dele, fica como está: recodificar a um bitrate
  maior só gasta tempo e tamanho sem recuperar qualidade (a mesma regra do áudio, ver ``POLICY_AUDIO_BITRATE``).
- **Bitrate médio, não CRF, em duas passadas.** Quem pede um bitrate quer controlar o tamanho; o arquivo sai perto de
  ``kbps × duração``. Medido em vídeos reais, a passada única do x264 estourava o alvo em +12% (1080p60) e, num conteúdo
  fácil, gastava de 8% a 44% dele: o tamanho não era previsível. A primeira passada analisa o vídeo inteiro, e a segunda
  distribui o bitrate sabendo o que vem depois. O SVT-AV1 não tem passada dupla no ffmpeg e fica com a única.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from videomanager.application.capabilities import FFmpegTools
from videomanager.infrastructure.ffmpeg import hardware as hwaccel
from videomanager.infrastructure.system.binaries import subprocess_kwargs

# Folga abaixo da qual a fonte conta como "já no bitrate pedido": o bitrate que o ffprobe lê da fonte oscila uns pontos, e
# recodificar para ganhar 2% é desperdício.
_SOURCE_TOLERANCE = 1.02

_ENCODERS = {"h264": "libx264", "hevc": "libx265", "vp9": "libvpx-vp9", "av1": "libsvtav1"}
_FAMILY_OF = {"h264": "h264", "hevc": "hevc", "h265": "hevc", "vp9": "vp9", "av1": "av1"}
# Que codecs cada container aceita guardar; o que não está aqui não é recodificado (cai no padrão do container).
_CONTAINER_FAMILIES = {"mp4": ("h264", "hevc", "av1"), "mkv": ("h264", "hevc", "vp9", "av1"), "webm": ("vp9", "av1"),
                       "mov": ("h264", "hevc")}
_CONTAINER_DEFAULT = {"mp4": "h264", "mkv": "h264", "mov": "h264", "webm": "vp9"}


@dataclass(frozen=True)
class SourceVideo:
    """O que a recodificação precisa saber do arquivo baixado."""

    family: str | None
    container: str
    kbps: float | None
    duration: float | None


def probe_video(path: Path, tools: FFmpegTools, *, timeout: float = 60.0) -> SourceVideo:
    """Codec, container, bitrate de vídeo e duração do arquivo, pelo ffprobe."""
    command = [tools.ffprobe_str, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    result = subprocess.run(command, timeout=timeout, **subprocess_kwargs())
    data = json.loads(result.stdout or b"{}")
    streams = data.get("streams") or []
    # O primeiro vídeo de verdade: a capa embutida (attached_pic) também é um stream de vídeo.
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    fmt = data.get("format") or {}
    duration = _number(fmt.get("duration")) or (_number(video.get("duration")) if video else None)
    bps = _number(video.get("bit_rate")) if video else None
    if bps is None and video and duration:
        # Sem bitrate por trilha (MKV, WebM): o do arquivo menos o do áudio.
        total = _number(fmt.get("size"))
        audio = sum(_number(s.get("bit_rate")) or 0.0 for s in streams if s.get("codec_type") == "audio")
        bps = max(0.0, total * 8 / duration - audio) or None if total else None
    kbps = bps / 1000 if bps else None
    codec = str(video.get("codec_name") or "") if video else ""
    return SourceVideo(
        family=_FAMILY_OF.get(codec.lower()),
        container=path.suffix.lower().lstrip("."),
        kbps=kbps,
        duration=duration,
    )


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def needs_recode(source: SourceVideo, kbps: int) -> bool:
    """Falso quando a fonte já está no bitrate pedido ou abaixo: ali recodificar só aumentaria o arquivo."""
    return source.kbps is None or source.kbps > kbps * _SOURCE_TOLERANCE


def target_family(source: SourceVideo) -> str:
    """A família de codec em que o vídeo sai: a da fonte, se o container a aceita."""
    container = source.container
    accepted = _CONTAINER_FAMILIES.get(container, ("h264",))
    if source.family in accepted:
        return source.family
    return _CONTAINER_DEFAULT.get(container, "h264")


# Os encoders que têm passada dupla pelo ffmpeg (``-pass 1``/``-pass 2``).
_TWO_PASS = ("libx264", "libx265", "libvpx-vp9")


def passes_for(family: str) -> int:
    return 2 if _ENCODERS[family] in _TWO_PASS else 1


def build_args(source: Path, destination: Path, family: str, kbps: int, container: str, tools: FFmpegTools,
               *, passlog: Path | None = None) -> list[list[str]]:
    """Os comandos do ffmpeg, em ordem: uma passada, ou duas (a primeira só analisa e descarta a saída).

    Só o primeiro vídeo é recodificado; o resto do arquivo é copiado como está. ``passlog`` é o prefixo dos arquivos que a
    primeira passada deixa para a segunda (obrigatório nas duas passadas).
    """
    encoder = _ENCODERS[family]
    video = ["-c:v:0", encoder, *hwaccel.target_bitrate_quality(encoder, kbps)]
    head = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-y", "-i", str(source)]
    final = [
        *head, "-map", "0", "-c", "copy", *video, *hwaccel.hevc_tag(encoder, container),
        "-map_metadata", "0",
        *(["-movflags", "+faststart"] if container in ("mp4", "mov") else []),
    ]
    if passes_for(family) == 1 or passlog is None:
        return [[*final, "-progress", "pipe:1", "-nostats", str(destination)]]
    first = [*head, "-map", "0:v:0", "-an", "-sn", "-c:v", encoder, *hwaccel.target_bitrate_quality(encoder, kbps),
             "-pass", "1", "-passlogfile", str(passlog), "-f", "null", os.devnull, "-progress", "pipe:1", "-nostats"]
    second = [*final, "-pass", "2", "-passlogfile", str(passlog), "-progress", "pipe:1", "-nostats", str(destination)]
    return [first, second]


def passlog_files(passlog: Path) -> list[Path]:
    """Os arquivos que a passada dupla deixa ao lado do prefixo (``.log``, ``.log.mbtree``, ``.log.cutree``…)."""
    return sorted(passlog.parent.glob(f"{passlog.name}*"))


def seconds_done(line: str) -> float | None:
    """O tempo já codificado numa linha de ``-progress`` (``out_time_us=…``), ou ``None``."""
    key, _, value = line.strip().partition("=")
    if key not in ("out_time_us", "out_time_ms"):  # as duas saem em microssegundos
        return None
    try:
        return max(0.0, int(value) / 1_000_000)
    except ValueError:
        return None


__all__ = ["SourceVideo", "build_args", "needs_recode", "passes_for", "passlog_files", "probe_video", "seconds_done",
           "target_family"]
