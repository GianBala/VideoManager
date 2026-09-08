"""Análise de URL numa thread de trabalho.

A análise leva de um a vários segundos e faz várias requisições. Feita na thread
da interface, congelaria a janela — inclusive a barra de título, que no Linux faz
o gerenciador de janelas marcar o app como "não responde".
"""

from __future__ import annotations

from PySide6.QtCore import QRunnable, Slot

from videomanager.application.errors import VideoManagerError
from dataclasses import asdict
from videomanager.application.preferences import Preferences
from videomanager.infrastructure.storage.settings import Settings
from videomanager.infrastructure.qt.workers.signals import ProbeSignals
from videomanager.infrastructure.qt.workers.signals import emit_safely


class ProbeWorker(QRunnable):
    """Analisa uma URL e emite :class:`MediaInfo` ou :class:`PlaylistInfo`."""

    def __init__(self, url: str, settings: Settings, *, service) -> None:
        super().__init__()
        self._url = url
        self._settings = Preferences.from_dict(asdict(settings))
        self._service = service
        self._cancelled = False
        self.signals = ProbeSignals()

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        if self._cancelled:
            emit_safely(self.signals.done)
            return
        try:
            result = self._service.analyze(self._url, self._settings)
        except VideoManagerError as exc:
            if self._cancelled:
                return
            # Erro previsto: a mensagem já está em pt-BR e pronta para exibir.
            emit_safely(self.signals.failed, str(exc))
        except Exception as exc:  # noqa: BLE001
            if self._cancelled:
                return
            # Um extrator pode falhar de formas que não mapeamos. Melhor mostrar
            # o tipo do erro que deixar a janela num estado de "analisando" que
            # nunca termina.
            emit_safely(
                self.signals.failed,
                f"Erro inesperado ao analisar a URL ({type(exc).__name__}): {exc}",
            )
        else:
            if not self._cancelled:
                emit_safely(self.signals.finished, result)

        finally:
            emit_safely(self.signals.done)

__all__ = [
    'VideoManagerError',
    'Preferences',
]
