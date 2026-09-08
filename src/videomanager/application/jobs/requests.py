"""Dados de uma tarefa; opções de ferramentas externas não atravessam a fila."""
from dataclasses import dataclass, field
from pathlib import Path
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import VideoTarget
from videomanager.domain.composition import Composition
from videomanager.domain.timing import TrimTarget
from videomanager.domain.formats import MediaInfo
from videomanager.domain.selection import Request
from videomanager.application.preferences import Preferences
from videomanager.application.ports.output import OutputLease

ConversionTarget = AudioTarget | VideoTarget | TrimTarget | Composition


@dataclass(frozen=True)
class ConversionRequest:
    media: LocalMedia | None
    target: ConversionTarget
    destination: Path
    text_assets: tuple[tuple[int, Path], ...] = ()
    lease: OutputLease | None = None


@dataclass(frozen=True)
class DownloadRequest:
    selection: Request
    media: MediaInfo
    destination: Path
    temporary: Path
    preferences: Preferences = field(repr=False)


JobRequest = ConversionRequest | DownloadRequest
