"""Adaptador Qt da fila: pools e sinais; transições pertencem a JobService."""
import shutil
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

from videomanager.application.events import DownloadResult
from videomanager.application.jobs.models import Job
from videomanager.application.jobs.models import JobStatus
from videomanager.application.jobs.requests import ConversionRequest
from videomanager.application.jobs.requests import DownloadRequest
from videomanager.application.jobs.service import JobService
from videomanager.application.errors import error_message
from videomanager.infrastructure.storage.outputs import FileOutputStore
from videomanager.infrastructure.qt.workers.convert_worker import ConvertWorker
from videomanager.infrastructure.qt.workers.download_worker import DownloadWorker
from videomanager.infrastructure.qt.workers.download_worker import task_dir
from videomanager.infrastructure.qt.workers.signals import report_unexpected

_LOCAL_JOBS = 1


def _size_of(path):
    try:
        return path.stat().st_size if path else None
    except OSError:
        return None


class _Attempt(QObject):
    """Receptor com afinidade à thread principal e identidade fixa da tentativa."""
    def __init__(self, queue, job, worker):
        super().__init__(queue)
        self.queue, self.worker = queue, worker
        self.attempt = job.attempt_id

    @Slot(int, object)
    def progress(self, job_id, progress):
        job = self.queue.service.progress(job_id, self.attempt, progress)
        if job:
            self.queue.job_changed.emit(job)

    @Slot(int, object)
    def finished(self, job_id, result):
        path = result.path if isinstance(result, DownloadResult) else result
        job = self.queue.service.finish(job_id, self.attempt, result, size=_size_of(path))
        self.queue._terminal(job, job_id, self)

    @Slot(int, object)
    def failed(self, job_id, message):
        job = self.queue.service.fail(job_id, self.attempt, message, getattr(self.worker, 'log', ()))
        self.queue._terminal(job, job_id, self)

    @Slot(int)
    def cancelled(self, job_id):
        job = self.queue.service.cancelled(job_id, self.attempt)
        self.queue._terminal(job, job_id, self)


class JobQueue(QObject):
    job_added = Signal(object)
    job_changed = Signal(object)
    counts_changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.service = JobService()
        self._workers = {}
        self._receivers = {}
        self._pool = QThreadPool(self)
        self._local = QThreadPool(self)
        self._local.setMaxThreadCount(_LOCAL_JOBS)
        self.apply_settings(settings)

    @property
    def jobs(self):
        return self.service.jobs

    def job(self, job_id):
        return self.service.job(job_id)

    def count_by_status(self, *statuses):
        return self.service.count_by_status(*statuses)

    @property
    def has_unfinished(self):
        return self.service.has_unfinished

    def apply_settings(self, settings):
        self._pool.setMaxThreadCount(max(1, settings.max_concurrent_jobs))

    def submit(self, job: Job) -> Job:
        self.service.add(job)
        self.job_added.emit(job)
        self._start(job)
        return job

    def _start(self, job):
        attempt = self.service.begin(job)
        try:
            worker = ConvertWorker(job) if job.kind.runs_ffmpeg_locally else DownloadWorker(job)
        except Exception as exc:
            report_unexpected(exc)
            if isinstance(job.request, ConversionRequest):
                path = job.request.destination
                FileOutputStore().abort(path, lease=job.request.lease)
            self.service.fail(job.job_id, attempt, str(exc))
            self.job_changed.emit(job)
            self.counts_changed.emit()
            return
        receiver = _Attempt(self, job, worker)
        worker.signals.progress.connect(receiver.progress)
        worker.signals.finished.connect(receiver.finished)
        worker.signals.failed.connect(receiver.failed)
        worker.signals.cancelled.connect(receiver.cancelled)
        self._workers[job.job_id] = worker
        self._receivers[job.job_id] = receiver
        self.job_changed.emit(job)
        pool = self._local if job.kind.runs_ffmpeg_locally else self._pool
        pool.start(worker)
        self.counts_changed.emit()

    def _terminal(self, job, job_id, receiver):
        if self._receivers.get(job_id) is receiver:
            self._workers.pop(job_id, None)
            self._receivers.pop(job_id, None)
        # O receptor vive até esvaziar seus sinais já enfileirados; a tentativa
        # fixa também protege uma repetição iniciada por reação ao evento final.
        receiver.deleteLater()
        if job:
            self.job_changed.emit(job)
            self.counts_changed.emit()

    def cancel(self, job_id):
        job = self.job(job_id)
        if job and not job.status.is_final and job_id in self._workers:
            worker = self._workers[job_id]
            pool = self._local if job.kind.runs_ffmpeg_locally else self._pool
            if pool.tryTake(worker):
                # Ainda esperando vaga: sai da fila agora. Só marcar o worker
                # deixava a tarefa "Pendente" — e a reserva de 0 byte na pasta
                # do usuário — até a vaga liberar, o que atrás de uma
                # exportação interpolada leva minutos.
                if isinstance(job.request, ConversionRequest):
                    FileOutputStore().abort(job.request.destination, lease=job.request.lease)
                receiver = self._receivers[job_id]
                self._terminal(self.service.cancelled(job_id, receiver.attempt), job_id, receiver)
                return
            worker.cancel()

    def cancel_all(self):
        for job_id in list(self._workers):
            self.cancel(job_id)

    def shutdown(self, timeout_ms=4000):
        self.cancel_all()
        self._pool.waitForDone(timeout_ms // 2)
        self._local.waitForDone(timeout_ms // 2)

    def retry(self, job_id):
        job = self.job(job_id)
        if not job or job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
            return
        if isinstance(job.request, ConversionRequest):
            request = job.request
            try:
                lease = FileOutputStore().reserve(Path(job.url), request.target, request.destination.parent,
                                          custom_stem=request.destination.stem)
            except Exception as exc:
                report_unexpected(exc)
                self.service.retry_failed(job_id, error_message(exc))
                self.job_changed.emit(job)
                return
            self.service.replace_request(job_id, replace(request, destination=lease.path, lease=lease))
        self._start(job)

    def remove_finished(self):
        # Sem a tarefa na fila não há "Repetir": o .part que uma falha guardou
        # para continuar o download não tem mais quem o use.
        for job in self.service.jobs:
            if job.status.is_final and isinstance(job.request, DownloadRequest):
                shutil.rmtree(task_dir(job), ignore_errors=True)
        self.service.remove_finished()
        self.counts_changed.emit()

__all__ = [
    'DownloadResult',
    'Job',
    'JobStatus',
    'ConversionRequest',
    'JobService',
]
