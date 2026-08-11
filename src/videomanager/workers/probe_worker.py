"""Análise de URL numa thread de trabalho.

A análise leva de um a vários segundos e faz várias requisições. Feita na thread
da interface, congelaria a janela — inclusive a barra de título, que no Linux faz
o gerenciador de janelas marcar o app como "não responde".
"""

from __future__ import annotations

from PySide6.QtCore import QRunnable, Slot

from ..core.errors import VideoManagerError
from ..core.probe import probe
from ..core.settings import Settings
from .signals import ProbeSignals, emit_safely


class ProbeWorker(QRunnable):
    """Analisa uma URL e emite :class:`MediaInfo` ou :class:`PlaylistInfo`."""

    def __init__(self, url: str, settings: Settings) -> None:
        super().__init__()
        self._url = url
        self._settings = settings
        self.signals = ProbeSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = probe(self._url, self._settings)
        except VideoManagerError as exc:
            # Erro previsto: a mensagem já está em pt-BR e pronta para exibir.
            emit_safely(self.signals.failed, str(exc))
        except Exception as exc:  # noqa: BLE001
            # Um extrator pode falhar de formas que não mapeamos. Melhor mostrar
            # o tipo do erro que deixar a janela num estado de "analisando" que
            # nunca termina.
            emit_safely(
                self.signals.failed,
                f"Erro inesperado ao analisar a URL ({type(exc).__name__}): {exc}",
            )
        else:
            emit_safely(self.signals.finished, result)
