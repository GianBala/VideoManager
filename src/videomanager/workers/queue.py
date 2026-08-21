"""Fila de tarefas: agenda, acompanha e cancela downloads e conversões.

Usa ``QThreadPool``, que já resolve o enfileiramento: tarefas acima do limite de
simultaneidade ficam esperando vaga sozinhas, sem precisarmos de um agendador
próprio.

**São duas filas, porque são dois recursos diferentes.** Baixar espera a rede, e
o limite existe porque baixar dez vídeos ao mesmo tempo numa conexão doméstica
deixa todos lentos e aumenta a chance de a plataforma limitar a banda. Converter
espera a **máquina**, e aí o limite é outro: um ffmpeg já usa todos os núcleos
sozinho, então dois em paralelo não entregam nada antes — só dividem os mesmos
núcleos e **somam a memória**. Ver :data:`_LOCAL_JOBS`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal

from ..core.downloader import PHASE_DOWNLOADING, DownloadResult, Progress
from ..core.job import Job, JobStatus
from ..core.settings import Settings
from .convert_worker import ConvertWorker
from .download_worker import DownloadWorker

# Quantas tarefas de ffmpeg local correm ao mesmo tempo — uma. Não é conta de
# núcleos: um ffmpeg sozinho já ocupa os que existem, e o que a segunda tarefa
# acrescenta é **memória**. Uma exportação com interpolação pede 5,6 GB numa tela
# 4K (medido; ver ``core/composer.py``), e três delas em paralelo — que era o
# padrão desta fila — não cabem em máquina nenhuma que se venda hoje. O custo de
# serializar é nenhum: o mesmo trabalho, na mesma ordem, terminando antes por
# não disputar cache nem memória.
_LOCAL_JOBS = 1


def _size_of(path: Path | None) -> int | None:
    """Tamanho do arquivo produzido, medido uma vez só.

    Aqui, e não na hora de desenhar a linha: a coluna que mostra esse número é
    repintada a cada atualização de progresso das outras tarefas, e perguntar ao
    disco ali punha duas chamadas de sistema em cada quadro — perceptível quando
    o destino é uma pasta de rede.
    """
    if path is None:
        return None
    try:
        return path.stat().st_size
    except OSError:
        return None


class JobQueue(QObject):
    """Dona de todas as tarefas e única a mudar o estado delas.

    A interface só lê ``Job`` e reage aos sinais. Concentrar as transições de
    estado aqui evita o problema clássico de uma tarefa cancelada voltar a
    "baixando" porque um sinal atrasado chegou depois.
    """

    job_added = Signal(object)  # Job
    job_changed = Signal(object)  # Job
    counts_changed = Signal()

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._jobs: dict[int, Job] = {}
        self._order: list[int] = []
        self._workers: dict[int, DownloadWorker | ConvertWorker] = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(1, settings.max_concurrent_jobs))
        self._local = QThreadPool(self)
        self._local.setMaxThreadCount(_LOCAL_JOBS)

    # -- leitura ----------------------------------------------------------

    @property
    def jobs(self) -> list[Job]:
        return [self._jobs[i] for i in self._order]

    def job(self, job_id: int) -> Job | None:
        return self._jobs.get(job_id)

    def count_by_status(self, *statuses: JobStatus) -> int:
        return sum(1 for job in self._jobs.values() if job.status in statuses)

    @property
    def has_unfinished(self) -> bool:
        return any(not job.status.is_final for job in self._jobs.values())

    def apply_settings(self, settings: Settings) -> None:
        """A preferência do usuário vale para a rede, e só.

        A fila local não é ajustável de propósito: o número que faz sentido ali
        não é uma preferência, é o que a máquina aguenta — e quem pediria três
        conversões em paralelo estaria pedindo a mesma coisa mais devagar, com o
        risco de não terminar nenhuma.
        """
        self._settings = settings
        self._pool.setMaxThreadCount(max(1, settings.max_concurrent_jobs))

    # -- escrita ----------------------------------------------------------

    def submit(self, job: Job) -> Job:
        """Registra a tarefa e a entrega à pool."""
        self._jobs[job.job_id] = job
        self._order.append(job.job_id)
        self.job_added.emit(job)
        self._start(job)
        self.counts_changed.emit()
        return job

    def _start(self, job: Job) -> None:
        worker: DownloadWorker | ConvertWorker
        pool = self._pool
        if job.kind.runs_ffmpeg_locally:
            worker = ConvertWorker(job)
            pool = self._local
        else:
            worker = DownloadWorker(job)

        worker.signals.progress.connect(self._on_progress)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.failed.connect(self._on_failed)
        worker.signals.cancelled.connect(self._on_cancelled)

        self._workers[job.job_id] = worker
        job.status = JobStatus.PENDING
        job.error = None
        self.job_changed.emit(job)
        pool.start(worker)

    def cancel(self, job_id: int) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.status.is_final:
            return
        worker = self._workers.get(job_id)
        if worker is not None:
            worker.cancel()

    def cancel_all(self) -> None:
        for job_id in list(self._workers):
            self.cancel(job_id)

    def shutdown(self, timeout_ms: int = 4000) -> None:
        """Cancela tudo e espera um tempo limitado pelas threads.

        A espera importa: sair no meio de uma gravação deixa arquivo truncado e
        processos de ffmpeg órfãos. O limite também importa — o encerramento não
        pode ficar pendurado por causa de uma conexão travada, então depois do
        prazo o processo sai de todo modo.
        """
        self.cancel_all()
        # As duas filas, e o prazo é de cada uma: esperar as duas em sequência
        # pelo prazo inteiro dobraria o tempo de saída no pior caso, mas o pior
        # caso aqui é justamente o que não pode travar o fechamento. Metade para
        # cada uma mantém a promessa do prazo.
        self._pool.waitForDone(timeout_ms // 2)
        self._local.waitForDone(timeout_ms // 2)

    def retry(self, job_id: int) -> None:
        """Recoloca na fila uma tarefa que falhou ou foi cancelada."""
        job = self._jobs.get(job_id)
        if job is None or not job.status.is_final or job.status is JobStatus.DONE:
            return
        job.progress = None
        job.result_path = None
        job.result_size = None
        self._start(job)
        self.counts_changed.emit()

    def remove_finished(self) -> None:
        """Limpa da fila as tarefas já encerradas."""
        for job_id in [i for i, job in self._jobs.items() if job.status.is_final]:
            self._jobs.pop(job_id, None)
            self._workers.pop(job_id, None)
            if job_id in self._order:
                self._order.remove(job_id)
        self.counts_changed.emit()

    # -- reações aos workers ---------------------------------------------

    def _on_progress(self, job_id: int, progress: Progress) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.status.is_final:
            # Sinal atrasado de uma tarefa já encerrada: descartar. Sem esta
            # guarda, uma tarefa cancelada voltaria a exibir "Baixando".
            return
        job.progress = progress
        job.status = (
            JobStatus.RUNNING
            if progress.phase == PHASE_DOWNLOADING
            else JobStatus.PROCESSING
        )
        self.job_changed.emit(job)

    def _on_finished(self, job_id: int, result: object) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.status = JobStatus.DONE
        job.progress = None
        if isinstance(result, DownloadResult):
            job.result_path = result.path
            job.log = result.log
            if result.title and job.title in ("", job.url):
                job.title = result.title
        elif isinstance(result, Path):
            job.result_path = result
        job.result_size = _size_of(job.result_path)
        self._workers.pop(job_id, None)
        self.job_changed.emit(job)
        self.counts_changed.emit()

    def _on_failed(self, job_id: int, message: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.status = JobStatus.FAILED
        job.error = message
        job.progress = None
        worker = self._workers.pop(job_id, None)
        if isinstance(worker, DownloadWorker):
            job.log = worker.log
        self.job_changed.emit(job)
        self.counts_changed.emit()

    def _on_cancelled(self, job_id: int) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.status = JobStatus.CANCELLED
        job.progress = None
        self._workers.pop(job_id, None)
        self.job_changed.emit(job)
        self.counts_changed.emit()
