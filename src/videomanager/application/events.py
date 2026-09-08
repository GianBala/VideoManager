"""Resultados e progresso independentes do motor de download."""

from enum import Enum
from dataclasses import dataclass
from pathlib import Path

class ProgressStage(Enum):
    DOWNLOAD = "download"
    PROCESSING = "processing"


@dataclass(frozen=True)
class Progress:
    """Estado de progresso já normalizado, pronto para a interface.

    Os campos são todos opcionais porque o yt-dlp informa o que consegue: num
    stream HLS sem ``Content-Length`` não existe total, e forçar um número ali
    faria a barra andar para trás quando a estimativa fosse corrigida.
    """

    phase: str  # texto pronto para exibir ("Baixando", "Convertendo"…)
    percent: float | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    total_is_estimate: bool = False
    speed: float | None = None  # bytes/s
    eta: float | None = None  # segundos
    fragment_index: int | None = None
    fragment_count: int | None = None
    indeterminate: bool = False  # True = a barra deve ficar em modo contínuo

    stage: ProgressStage = ProgressStage.PROCESSING


@dataclass(frozen=True)
class DownloadResult:
    path: Path | None
    title: str
    log: tuple[str, ...] = ()

