"""Único proprietário dos estados; adaptadores entregam eventos por tentativa."""
from pathlib import Path
from videomanager.application.jobs.models import Job
from videomanager.application.jobs.models import JobStatus
from videomanager.application.events import DownloadResult
from videomanager.application.events import Progress
from videomanager.application.events import ProgressStage
from videomanager.domain.i18n import Text


class JobService:
    def __init__(self):
        self._jobs: dict[int, Job] = {}

    @property
    def jobs(self) -> list[Job]:
        return list(self._jobs.values())

    def job(self, job_id: int) -> Job | None:
        return self._jobs.get(job_id)

    def add(self, job: Job) -> None:
        if job.job_id in self._jobs:
            raise ValueError('A tarefa já está registrada.')
        self._jobs[job.job_id] = job

    def begin(self, job: Job) -> int:
        job.attempt_id += 1
        job.status = JobStatus.PENDING
        job.progress = None
        job.error = None
        job.result_path = None
        job.result_size = None
        job.log = ()
        return job.attempt_id

    def active(self, job_id: int, attempt: int) -> Job | None:
        job = self.job(job_id)
        return job if job and job.attempt_id == attempt and not job.status.is_final else None

    def progress(self, job_id: int, attempt: int, progress: Progress) -> Job | None:
        job = self.active(job_id, attempt)
        if job:
            job.progress = progress
            job.status = JobStatus.RUNNING if progress.stage is ProgressStage.DOWNLOAD else JobStatus.PROCESSING
        return job

    def finish(self, job_id: int, attempt: int, result: DownloadResult | Path | None,
               *, size: int | None = None) -> Job | None:
        job = self.active(job_id, attempt)
        if job:
            job.status = JobStatus.DONE
            job.progress = None
            if isinstance(result, DownloadResult):
                job.result_path, job.log = result.path, result.log
                if result.title and job.title in ('', job.url):
                    job.title = result.title
            else:
                job.result_path = result
            job.result_size = size
        return job

    def fail(self, job_id: int, attempt: int, message: str | Text, log=()) -> Job | None:
        job = self.active(job_id, attempt)
        if job:
            job.status, job.error, job.log = JobStatus.FAILED, message, tuple(log)
            job.progress = None
        return job

    def cancelled(self, job_id: int, attempt: int) -> Job | None:
        job = self.active(job_id, attempt)
        if job:
            job.status = JobStatus.CANCELLED
            job.progress = None
        return job

    def remove_finished(self) -> None:
        self._jobs = {key: job for key, job in self._jobs.items() if not job.status.is_final}

    def count_by_status(self, *statuses) -> int:
        return sum(job.status in statuses for job in self._jobs.values())

    @property
    def has_unfinished(self) -> bool:
        return any(not job.status.is_final for job in self._jobs.values())

    def replace_request(self, job_id, request):
        job = self.job(job_id)
        if job is None or job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
            raise ValueError("A tarefa não pode ser repetida neste estado.")
        job.request = request

    def retry_failed(self, job_id, message):
        job = self.job(job_id)
        if job is not None:
            job.error = message
            job.status = JobStatus.FAILED
