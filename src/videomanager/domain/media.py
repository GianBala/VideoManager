"""Descritores de mídia e pedidos de conversão sem dependência de ffprobe."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_AUDIO_EXTENSIONS = {
    "mp3": "mp3",
    "aac": "m4a",
    "m4a": "m4a",
    "opus": "opus",
    "vorbis": "ogg",
    "ogg": "ogg",
    "flac": "flac",
    "alac": "m4a",
    "wav": "wav",
}


_LOSSLESS = {"flac", "alac", "wav"}


@dataclass(frozen=True)
class LocalStream:
    index: int
    kind: str  # "video" | "audio" | "subtitle" | outro
    codec: str
    height: int | None = None
    width: int | None = None
    fps: float | None = None
    # Proporção do pixel (``sample_aspect_ratio``). Quase toda mídia atual tem
    # pixel quadrado e traz 1, mas rip de DVD e filmadora antiga guardam a
    # imagem espremida — 720×480 para exibir em 16:9 — e só este número diz
    # isso. Sem ele, a imagem sai achatada e nada falha. ``None`` quando o
    # arquivo não informa, que o ffmpeg trata como 1.
    sar: float | None = None
    bitrate: float | None = None  # kbps
    sample_rate: int | None = None
    channels: int | None = None
    language: str | None = None


@dataclass(frozen=True)
class LocalMedia:
    """Um arquivo local já inspecionado pelo ffprobe."""

    path: Path
    duration: float | None
    format_name: str
    size: int | None
    streams: tuple[LocalStream, ...]

    @property
    def video(self) -> LocalStream | None:
        return next((s for s in self.streams if s.kind == "video"), None)

    @property
    def audio(self) -> LocalStream | None:
        return next((s for s in self.streams if s.kind == "audio"), None)

    @property
    def has_video(self) -> bool:
        return self.video is not None

    @property
    def has_audio(self) -> bool:
        return self.audio is not None


@dataclass(frozen=True)
class AudioTarget:
    """Pedido de conversão para áudio."""

    codec: str = "mp3"
    bitrate: str = "192"

    @property
    def extension(self) -> str:
        return _AUDIO_EXTENSIONS.get(self.codec, self.codec)

    @property
    def is_lossless(self) -> bool:
        return self.codec in _LOSSLESS


@dataclass(frozen=True)
class VideoTarget:
    """Pedido de conversão para vídeo.

    ``video_codec="copy"`` troca só o container: rápido e sem perda. É o padrão
    por isso mesmo.
    """

    container: str = "mp4"
    video_codec: str = "copy"
    audio_codec: str = "copy"
    audio_bitrate: str = "192"
    height: int | None = None
    fps: float | None = None
    crf: int = 20
    hardware: str = "software"

    @property
    def extension(self) -> str:
        return self.container
