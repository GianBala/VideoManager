"""Leitura de projetos e inspeção de mídias fora da thread da interface."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from videomanager.application.capabilities import FFmpegTools
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.application.errors import JobCancelled
from videomanager.infrastructure.system.process import ProcessControl
from videomanager.domain.project import MediaRef
from videomanager.application.editor.media import MediaResult
from videomanager.application.editor.media import ReadMedia
from videomanager.infrastructure.storage.projects import JsonProjectRepository
from videomanager.infrastructure.qt.workers.signals import emit_safely


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
                 known: dict[Path, MediaRef] | None = None, require_duration: bool = True) -> None:
        super().__init__()
        self.signals = MediaSignals()
        self.token = token
        self.tools = tools
        self.paths = list(dict.fromkeys(paths))
        self.project_path = project_path
        self.known = known or {}
        self.require_duration = require_duration
        self.control = ProcessControl()

    def cancel(self) -> None:
        self.control.cancel()

    @Slot()
    def run(self) -> None:
        try:
            class Probe:
                def inspect(_, path, cancellation):
                    return probe_file(path, self.tools, control=self.control)

            reader = ReadMedia(JsonProjectRepository(), Probe() if self.tools else None)
            result = reader.execute(
                self.paths, self.control, project_path=self.project_path, known=self.known,
                require_duration=self.require_duration,
                on_progress=lambda done, total: emit_safely(self.signals.progress, self.token, done, total),
            )
            emit_safely(self.signals.finished, self.token, result)
        except JobCancelled:
            emit_safely(self.signals.cancelled, self.token)
        except Exception as exc:
            emit_safely(self.signals.failed, self.token, str(exc))
        finally:
            emit_safely(self.signals.done)


__all__ = [
    'MediaWorker',
    'MediaResult',
    'FFmpegTools',
    'JobCancelled',
    'MediaRef',
    'ReadMedia',
]
