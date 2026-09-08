"""Fronteiras de inspeção e reserva de arquivos para processamento."""
from pathlib import Path
from typing import Protocol
from videomanager.domain.media import LocalMedia
from videomanager.application.jobs.requests import ConversionTarget
from .output import OutputLease


class MediaCatalog(Protocol):
    def exists(self, path: Path) -> bool: ...
    def inspect(self, path: Path) -> LocalMedia: ...
    def writable(self, directory: Path) -> bool: ...


class OutputStore(Protocol):
    def reserve(self, source: Path, target: ConversionTarget, directory: Path | None,
                suffix: str = '', custom_stem: str | None = None) -> OutputLease: ...
    def abort(self, destination: Path, *, lease: OutputLease | None = None) -> None: ...

    def commit(self, temporary: Path, destination: Path, *, lease: OutputLease | None = None) -> None: ...
