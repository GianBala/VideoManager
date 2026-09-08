"""Modelo de uma tarefa da fila.

Independente de Qt: a fila que executa
estas tarefas vive em :mod:`videomanager.infrastructure.qt.workers.queue` e é essa camada que sabe
de threads e sinais.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from videomanager.application.events import Progress
from videomanager.application.jobs.requests import JobRequest


class JobStatus(Enum):
    """Situação de uma tarefa. Valores estáveis; os rótulos pertencem à apresentação."""

    PENDING = "pending"
    RUNNING = "running"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_final(self) -> bool:
        return self in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)

    @property
    def is_active(self) -> bool:
        return self in (JobStatus.RUNNING, JobStatus.PROCESSING)


class JobKind(Enum):
    DOWNLOAD = "download"
    CONVERT = "conversão"
    TRIM = "recorte"
    EXPORT = "exportação"

    @property
    def runs_ffmpeg_locally(self) -> bool:
        """Se a tarefa é executada pelo conversor, e não pelo downloader."""
        return self in (JobKind.CONVERT, JobKind.TRIM, JobKind.EXPORT)


_counter = itertools.count(1)


@dataclass(eq=False)
class Job:
    """Uma unidade de trabalho da fila.

    Mutável de propósito: a fila atualiza ``status`` e ``progress`` no lugar e
    avisa a interface por sinal, em vez de recriar o objeto a cada quadro de
    progresso — que chegam várias vezes por segundo.

    Igualdade por identidade (``eq=False``): a fila é dona dos objetos e passa
    sempre o mesmo adiante. A comparação campo a campo do dataclass, além de
    percorrer pedidos completos a cada repintura, confundiria tarefas com
    os mesmos valores. A identidade de cada tarefa permanece estável.
    """

    url: str
    title: str
    description: str
    kind: JobKind = JobKind.DOWNLOAD
    request: JobRequest | None = field(default=None, repr=False)
    attempt_id: int = 0
    job_id: int = field(default_factory=lambda: next(_counter))
    status: JobStatus = JobStatus.PENDING
    progress: Progress | None = None
    result_path: Path | None = None
    # Tamanho do arquivo produzido, medido **uma vez**, quando a tarefa termina.
    # A coluna de velocidade da fila mostrava isso perguntando ao disco a cada
    # repintura de célula — duas chamadas de sistema por quadro, por tarefa
    # concluída visível, e uma corrida entre o ``exists`` e o ``stat`` que
    # levantava ``FileNotFoundError`` de dentro do modelo se o arquivo saísse do
    # lugar nesse intervalo.
    result_size: int | None = None
    error: str | None = None
    log: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    # Guardado para permitir "Tentar de novo" sem reconstruir o pedido.
    source_label: str = ""

    @property
    def percent(self) -> float | None:
        return self.progress.percent if self.progress else None

