"""Descritores de capacidades e ferramentas disponíveis, sem sondagem."""
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class FFmpegTools:
    """Par ffmpeg/ffprobe validado e pronto para uso."""

    ffmpeg: Path
    ffprobe: Path
    source: str  # "empacotado" | "gerenciado" | "sistema" — para exibir na UI

    @property
    def ffmpeg_str(self) -> str:
        return str(self.ffmpeg)

    @property
    def ffprobe_str(self) -> str:
        return str(self.ffprobe)
