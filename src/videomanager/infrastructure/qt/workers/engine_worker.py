"""Provisionamento do ffmpeg e atualização da engine, em thread de trabalho.

Ambas as operações fazem download e podem levar minutos; na thread da interface,
congelariam a janela inteira.
"""

from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from videomanager.infrastructure.system import binaries
from videomanager.application.errors import JobCancelled
from videomanager.application.errors import VideoManagerError
from videomanager.domain.i18n import t
from videomanager.infrastructure.qt.workers.signals import emit_safely


class FFmpegSetupSignals(QObject):
    progress = Signal(int, object)  # bytes recebidos, total (ou None)
    finished = Signal(object)  # FFmpegTools
    failed = Signal(str)
    cancelled = Signal()


class FFmpegSetupWorker(QRunnable):
    """Baixa e instala ffmpeg/ffprobe."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = FFmpegSetupSignals()
        self._cancelled = False

    def cancel(self) -> None:
        """Pede a interrupção; o efeito vem no próximo pedaço recebido."""
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            tools = binaries.download_tools(
                lambda received, total: emit_safely(self.signals.progress, received, total),
                lambda: self._cancelled,
            )
        except JobCancelled:
            emit_safely(self.signals.cancelled)
        except VideoManagerError as exc:
            emit_safely(self.signals.failed, str(exc))
        except Exception as exc:  # noqa: BLE001
            emit_safely(self.signals.failed, f"{type(exc).__name__}: {exc}")
        else:
            emit_safely(self.signals.finished, tools)


class EngineUpdateSignals(QObject):
    finished = Signal(str, bool)  # versão resultante, houve mudança
    failed = Signal(str)


def is_packaged() -> bool:
    """Se estamos rodando de dentro de um pacote do PyInstaller.

    Público porque quem decide **não** oferecer a atualização é a interface, que
    é onde mora o texto que explica isso ao usuário. Ver
    :class:`EngineUpdateWorker`.
    """
    return bool(getattr(sys, "frozen", False))


class EngineUpdateWorker(QRunnable):
    """Atualiza o yt-dlp no ambiente em que a aplicação está rodando.

    Usa o canal de pré-lançamento (``--pre``) porque é o recomendado pelo próprio
    projeto: extratores quebram quando as plataformas mudam, e as correções saem
    nas builds noturnas muito antes da versão estável seguinte.

    **Nunca inicie isto num pacote — confira :func:`is_packaged` antes.**
    ``sys.executable`` é o interpretador Python apenas quando se roda do
    código-fonte; num pacote do PyInstaller ele é o próprio executável do Video
    Manager, e não há pip embutido. O comando vira ``VideoManager -m pip install
    …``, e esses argumentos o bootloader repassa como ``sys.argv``: o
    ``QApplication`` ignora o que não reconhece e **abre uma segunda janela do
    aplicativo**, enquanto a primeira fica dez minutos de prazo esperando uma
    instalação que ninguém está fazendo. Vale igual para
    :meth:`_installed_version`.
    """

    def __init__(self, current_version: str) -> None:
        super().__init__()
        self._current = current_version
        self.signals = EngineUpdateSignals()

    @Slot()
    def run(self) -> None:
        command = [
            sys.executable, "-m", "pip", "install", "--upgrade", "--pre",
            "--disable-pip-version-check", "--no-input", "yt-dlp",
        ]
        try:
            proc = subprocess.run(
                command, timeout=600, check=False, **binaries.subprocess_kwargs()
            )
        except (OSError, subprocess.SubprocessError) as exc:
            emit_safely(self.signals.failed, str(exc))
            return

        if proc.returncode != 0:
            detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
            tail = detail.splitlines()[-3:] if detail else [t("ERROR_NO_DETAIL")]
            emit_safely(self.signals.failed, "\n".join(tail))
            return

        version = self._installed_version()
        emit_safely(self.signals.finished, version, version != self._current)

    def _installed_version(self) -> str:
        """Lê a versão instalada num processo separado.

        O módulo ``yt_dlp`` já está carregado nesta sessão, então reimportar
        devolveria a versão antiga. Um processo novo enxerga o que acabou de ser
        instalado.
        """
        try:
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import yt_dlp; print(yt_dlp.version.__version__)"],
                timeout=60, check=False, **binaries.subprocess_kwargs()
            )
            if proc.returncode == 0:
                return (proc.stdout or b"").decode("utf-8", "replace").strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return "desconhecida"

__all__ = [
    'JobCancelled',
    'VideoManagerError',
]
