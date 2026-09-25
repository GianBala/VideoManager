"""Execução Qt de ConversionRequest com progresso, cancelamento e reserva."""

from __future__ import annotations

from PySide6.QtCore import QRunnable, Slot

from videomanager.infrastructure.ffmpeg.converter import Converter
from videomanager.infrastructure.system.binaries import find_tools
from videomanager.application.errors import BinaryNotFoundError
from videomanager.application.errors import JobCancelled
from videomanager.application.errors import VideoManagerError
from videomanager.application.errors import error_message
from videomanager.domain.i18n import Text
from videomanager.application.jobs.models import Job
from videomanager.infrastructure.qt.workers.signals import ConvertSignals
from videomanager.infrastructure.qt.workers.signals import emit_safely


class ConvertWorker(QRunnable):
    """Converte um arquivo local, reportando progresso por sinal."""

    def __init__(self, job: Job) -> None:
        super().__init__()
        self._job = job
        self.signals = ConvertSignals()
        self._cancel_requested = False
        tools = find_tools()
        if tools is None:
            raise BinaryNotFoundError(Text("FFMPEG_UNAVAILABLE"))
        self._converter = Converter(
            media=job.request.media,
            target=job.request.target,
            destination=job.request.destination,
            tools=tools,
            on_progress=self._emit_progress,
            text_assets=dict(job.request.text_assets),
            lease=job.request.lease,
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
            # Cancelada ainda na espera da fila: o nome de saída já estava
            # reservado (ver ``converter.output_path``) e precisa ser devolvido,
            # senão sobra na pasta do usuário um arquivo de zero byte com o nome
            # do resultado que ele não vai ter.
            self._converter.discard_reservation()
            emit_safely(self.signals.cancelled, job_id)
            return

        try:
            path = self._converter.run()
        except JobCancelled:
            self._converter.discard_reservation()
            emit_safely(self.signals.cancelled, job_id)
        except VideoManagerError as exc:
            # Também aqui: uma falha antes de o ffmpeg abrir (alvo impossível,
            # pasta sem permissão) não passa pela limpeza de saída parcial.
            self._converter.discard_reservation()
            emit_safely(self.signals.failed, job_id, error_message(exc))
        except Exception as exc:  # noqa: BLE001
            self._converter.discard_reservation()
            emit_safely(
                self.signals.failed,
                job_id,
                Text("ERROR_UNEXPECTED", kind=type(exc).__name__, detail=str(exc)),
            )
        else:
            emit_safely(self.signals.finished, job_id, path)

__all__ = [
    'BinaryNotFoundError',
    'JobCancelled',
    'VideoManagerError',
    'Job',
]
