"""Execução de um download numa thread de trabalho."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QRunnable, Slot

from videomanager.infrastructure.yt_dlp.downloader import Downloader
from videomanager.infrastructure.system.binaries import find_tools
from videomanager.infrastructure.yt_dlp.selector import build_opts
from videomanager.application.errors import BinaryNotFoundError
from videomanager.application.errors import JobCancelled
from videomanager.application.errors import VideoManagerError
from videomanager.application.errors import error_message
from videomanager.domain.i18n import Text
from videomanager.application.jobs.models import Job
from videomanager.infrastructure.qt.workers.signals import DownloadSignals
from videomanager.infrastructure.qt.workers.signals import emit_safely


def task_dir(job: Job) -> Path:
    """Pasta dos temporários desta tarefa, dentro da pasta da sessão.

    Uma por tarefa porque o yt-dlp retoma o ``.part`` que encontra com o nome
    esperado: numa pasta comum, o resto de uma tarefa cancelada era continuado
    por outra de mesmo título e id e outro formato, e o arquivo saía corrompido
    e "Concluído". O ``job_id`` não muda entre tentativas, então "Repetir"
    reencontra o ``.part`` da própria tarefa e continua de onde parou.
    """
    return job.request.temporary / f"tarefa-{job.job_id}"


class DownloadWorker(QRunnable):
    """Baixa o que a :class:`Job` descreve, reportando progresso por sinal."""

    def __init__(self, job: Job) -> None:
        super().__init__()
        self._job = job
        self.signals = DownloadSignals()
        request = job.request
        tools = find_tools()
        if tools is None:
            raise BinaryNotFoundError(Text("FFMPEG_UNAVAILABLE"))
        self._temp = task_dir(job)
        opts, _ = build_opts(request.selection, request.media, request.preferences, tools, request.destination, self._temp)
        self._downloader = Downloader(opts, on_progress=self._emit_progress)
        self._cancel_requested = False

    @property
    def log(self) -> tuple[str, ...]:
        """Mensagens do yt-dlp, para a janela de detalhes de uma falha."""
        return self._downloader.log

    # -- controle ---------------------------------------------------------

    def cancel(self) -> None:
        """Marca o cancelamento.

        Funciona tanto antes de começar (a tarefa pode estar esperando vaga na
        pool) quanto durante o download.
        """
        self._cancel_requested = True
        self._downloader.cancel()

    # -- interno ----------------------------------------------------------

    def _emit_progress(self, progress) -> None:
        emit_safely(self.signals.progress, self._job.job_id, progress)

    @Slot()
    def run(self) -> None:
        job_id = self._job.job_id

        # A pool pode ter mantido esta tarefa na espera; se o usuário cancelou
        # nesse meio-tempo, não começamos nada.
        if self._cancel_requested:
            emit_safely(self.signals.cancelled, job_id)
            return

        try:
            result = self._downloader.run(self._job.url)
        except JobCancelled:
            # Cancelar é desistir: o .part não serve a ninguém. Numa falha ele
            # fica, para "Repetir" continuar de onde parou.
            shutil.rmtree(self._temp, ignore_errors=True)
            emit_safely(self.signals.cancelled, job_id)
        except VideoManagerError as exc:
            emit_safely(self.signals.failed, job_id, error_message(exc))
        except Exception as exc:  # noqa: BLE001
            emit_safely(
                self.signals.failed,
                job_id,
                Text("ERROR_UNEXPECTED", kind=type(exc).__name__, detail=str(exc)),
            )
        else:
            shutil.rmtree(self._temp, ignore_errors=True)
            emit_safely(self.signals.finished, job_id, result)

__all__ = [
    'BinaryNotFoundError',
    'JobCancelled',
    'VideoManagerError',
    'Job',
]
