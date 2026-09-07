"""Leitura de projetos e inspeção de mídias fora da thread da interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from ..core.binaries import FFmpegTools
from ..core.converter import LocalMedia, probe_file
from ..core.errors import JobCancelled, VideoManagerError
from ..core.process import ProcessControl
from ..core.project import MediaKind, MediaRef, Project, media_ref
from ..core.project_io import load_project
from .signals import emit_safely


@dataclass
class MediaResult:
    project: Project | None = None
    references: list[MediaRef] = field(default_factory=list)
    probed: dict[Path, LocalMedia] = field(default_factory=dict)
    missing: list[Path] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


class MediaSignals(QObject):
    progress = Signal(int, int, int)  # token, concluídos, total
    finished = Signal(int, object)
    failed = Signal(int, str)
    cancelled = Signal(int)
    done = Signal()


class MediaWorker(QRunnable):
    """Uma operação cancelável; o token impede resultados de projetos anteriores."""

    def __init__(self, token: int, tools: FFmpegTools | None, paths: list[Path],
                 *, project_path: Path | None = None,
                 known: dict[Path, MediaRef] | None = None) -> None:
        super().__init__()
        self.signals = MediaSignals()
        self.token = token
        self.tools = tools
        self.paths = list(dict.fromkeys(paths))
        self.project_path = project_path
        self.known = known or {}
        self.control = ProcessControl()

    def cancel(self) -> None:
        self.control.cancel()

    @Slot()
    def run(self) -> None:
        try:
            self.control.check()
            result = MediaResult()
            paths = self.paths
            if self.project_path is not None:
                result.project, result.missing = load_project(self.project_path)
                refs = {c.media.path: c.media for c in result.project.clips
                        if c.overlay_type not in ("text", "filter", "transition")}
                result.references = list(refs.values())
                paths = list(refs)
            for index, path in enumerate(paths):
                self.control.check()
                try:
                    if self.project_path is None and path in self.known:
                        result.references.append(self.known[path])
                    elif self.tools is not None:
                        local = probe_file(path, self.tools, control=self.control)
                        reference = media_ref(local)
                        if self.project_path is None:
                            if reference.kind is not MediaKind.IMAGE and not reference.duration:
                                raise VideoManagerError("A mídia não informa duração.")
                            result.references.append(reference)
                        result.probed[path] = local
                except JobCancelled:
                    raise
                except VideoManagerError as exc:
                    if self.project_path is None:
                        result.rejected.append(f"{path.name}: {exc}")
                emit_safely(self.signals.progress, self.token, index + 1, len(paths))
            self.control.check()
            emit_safely(self.signals.finished, self.token, result)
        except JobCancelled:
            emit_safely(self.signals.cancelled, self.token)
        except Exception as exc:
            emit_safely(self.signals.failed, self.token, str(exc))
        finally:
            emit_safely(self.signals.done)
