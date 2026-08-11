"""Execução de uma conversão local numa thread de trabalho.

A tarefa carrega o pedido em ``opts`` — que aqui não são opções do yt-dlp, mas as
peças da conversão montadas pela interface: ``media``, ``target``, ``destination``
e ``tools``.
"""

from __future__ import annotations

from PySide6.QtCore import QRunnable, Slot

from ..core.converter import Converter
from ..core.errors import JobCancelled, VideoManagerError
from ..core.job import Job
from .signals import ConvertSignals, emit_safely


class ConvertWorker(QRunnable):
    """Converte um arquivo local, reportando progresso por sinal."""

    def __init__(self, job: Job) -> None:
        super().__init__()
        self._job = job
        self.signals = ConvertSignals()
        self._cancel_requested = False
        self._converter = Converter(
            media=job.opts["media"],
            target=job.opts["target"],
            destination=job.opts["destination"],
            tools=job.opts["tools"],
            on_progress=self._emit_progress,
        )

    def cancel(self) -> None:
        self._cancel_requested = True
        self._converter.cancel()

    def _emit_progress(self, progress) -> None:
        emit_safely(self.signals.progress, self._job.job_id, progress)

    @Slot()
    def run(self) -> None:
        job_id = self._job.job_id
        if self._cancel_requested:
            emit_safely(self.signals.cancelled, job_id)
            return

        try:
            path = self._converter.run()
        except JobCancelled:
            emit_safely(self.signals.cancelled, job_id)
        except VideoManagerError as exc:
            emit_safely(self.signals.failed, job_id, str(exc))
        except Exception as exc:  # noqa: BLE001
            emit_safely(
                self.signals.failed,
                job_id,
                f"Erro inesperado ({type(exc).__name__}): {exc}",
            )
        else:
            emit_safely(self.signals.finished, job_id, path)
