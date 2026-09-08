"""Fronteiras de leitura, escrita e inspeção exigidas pelo editor."""
from pathlib import Path
from typing import Protocol

from videomanager.domain.media import LocalMedia
from videomanager.domain.project import Project


class Cancellation(Protocol):
    def check(self) -> None: ...


class ProjectRepository(Protocol):
    def load(self, path: Path) -> tuple[Project, list[Path]]: ...
    def save(self, project: Project, path: Path) -> None: ...


class MediaProbe(Protocol):
    def inspect(self, path: Path, cancellation: Cancellation) -> LocalMedia: ...
