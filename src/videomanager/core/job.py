"""Modelo de uma tarefa da fila.

Deliberadamente livre de Qt, como todo o pacote ``core``: a fila que executa
estas tarefas vive em :mod:`videomanager.workers.queue` e é essa camada que sabe
de threads e sinais.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .downloader import Progress


class JobStatus(Enum):
    """Situação de uma tarefa. O valor é o texto exibido na fila."""

    PENDING = "Na fila"
    RUNNING = "Baixando"
    PROCESSING = "Processando"
    DONE = "Concluído"
    FAILED = "Falhou"
    CANCELLED = "Cancelado"

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

    @property
    def runs_ffmpeg_locally(self) -> bool:
        """Se a tarefa é executada pelo conversor, e não pelo downloader."""
        return self in (JobKind.CONVERT, JobKind.TRIM)


_counter = itertools.count(1)


@dataclass(eq=False)
class Job:
    """Uma unidade de trabalho da fila.

    Mutável de propósito: a fila atualiza ``status`` e ``progress`` no lugar e
    avisa a interface por sinal, em vez de recriar o objeto a cada quadro de
    progresso — que chegam várias vezes por segundo.

    Igualdade por identidade (``eq=False``): a fila é dona dos objetos e passa
    sempre o mesmo adiante. A comparação campo a campo do dataclass, além de
    percorrer o dicionário de opções a cada busca de linha na tabela — várias
    vezes por segundo, por tarefa —, casaria duas tarefas idênticas na fila e
    atualizaria a linha errada.
    """

    url: str
    title: str
    description: str
    kind: JobKind = JobKind.DOWNLOAD
    opts: dict[str, Any] = field(default_factory=dict, repr=False)
    job_id: int = field(default_factory=lambda: next(_counter))
    status: JobStatus = JobStatus.PENDING
    progress: Progress | None = None
    result_path: Path | None = None
    error: str | None = None
    log: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    # Guardado para permitir "Tentar de novo" sem reconstruir o pedido.
    source_label: str = ""

    @property
    def percent(self) -> float | None:
        return self.progress.percent if self.progress else None

    @property
    def status_text(self) -> str:
        """Texto de situação, com o detalhe da etapa quando houver."""
        if self.status is JobStatus.FAILED and self.error:
            return f"Falhou: {self.error}"
        if self.status.is_active and self.progress:
            return self.progress.phase
        return self.status.value
