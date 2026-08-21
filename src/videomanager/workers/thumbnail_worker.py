"""Download da miniatura numa thread de trabalho.

Uma imagem pequena, mas ainda uma requisição de rede: feita na thread da
interface, travaria a janela a cada análise de URL.
"""

from __future__ import annotations

from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .. import APP_NAME
from .signals import emit_safely

# Miniaturas legítimas não passam disso; o teto evita que uma URL trocada
# arraste um arquivo enorme para a memória.
_MAX_BYTES = 8 * 1024 * 1024

# A URL da capa vem dos metadados do site — ou seja, de fora. O ``urlopen``
# atende ``file:``, ``ftp:`` e ``data:`` além de http(s), então sem esta lista
# uma capa apontando para "file:///proc/self/environ" faria o aplicativo ler
# disco a mando de quem publicou a mídia. O teto de bytes acima não serve para
# isso: ele evita uma imagem grande, não uma leitura indevida.
_ALLOWED_SCHEMES = ("http", "https")


class ThumbnailSignals(QObject):
    loaded = Signal(bytes)
    # Emitido sempre, inclusive quando a imagem falha. Serve para o
    # WorkerRunner soltar a referência: um worker que termina sem sinalizar nada
    # ficaria retido para sempre.
    done = Signal()


class ThumbnailWorker(QRunnable):
    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url
        self.signals = ThumbnailSignals()

    @Slot()
    def run(self) -> None:
        try:
            if urlparse(self._url).scheme not in _ALLOWED_SCHEMES:
                return
            try:
                request = Request(self._url, headers={"User-Agent": f"{APP_NAME}"})
                # noqa abaixo: o esquema foi conferido logo acima.
                with urlopen(request, timeout=15) as response:  # noqa: S310
                    data = response.read(_MAX_BYTES)
            except (URLError, OSError, ValueError):
                # Falha ao carregar miniatura é puramente cosmética: o card mostra
                # o texto de reserva e o download continua normalmente.
                return
            if data:
                emit_safely(self.signals.loaded, data)
        finally:
            emit_safely(self.signals.done)
