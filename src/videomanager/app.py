"""Inicialização da aplicação Qt."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_DISPLAY_NAME, APP_NAME, __version__
from .core.settings import Settings
from .preflight import check_or_explain
from .ui.main_window import MainWindow
from .ui.theme import qpalette, stylesheet


def _icon_path() -> Path:
    """Ícone da aplicação, empacotado ou no repositório.

    O PyInstaller extrai os dados para ``sys._MEIPASS``; fora dele, os arquivos
    estão ao lado do código. Mesmo raciocínio de ``core.binaries.vendor_dir``.
    """
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    # PNG e não SVG: renderizar SVG depende do plugin de imagem ``qsvg``, que
    # pode não ir junto no pacote — e o ícone sumiria sem erro nenhum.
    return root / "resources" / "videomanager.png"


def build_app(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    """Cria a aplicação e a janela, sem entrar no laço de eventos.

    Separado de :func:`main` para que um teste possa montar a janela, inspecioná-la
    e fechá-la sem bloquear.
    """
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setApplicationVersion(__version__)
    # Sem ícone explícito, o gerenciador de janelas mostra o genérico: ao abrir
    # pelo AppImage não há .desktop instalado de onde ele possa deduzir um.
    icon = _icon_path()
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    # Estilo Fusion como base: é o único idêntico no Windows e no Linux, então o
    # QSS produz o mesmo resultado nos dois sistemas.
    app.setStyle("Fusion")

    settings = Settings.load()
    app.setPalette(qpalette(settings.theme))
    app.setStyleSheet(stylesheet(settings.theme))

    window = MainWindow(settings)
    return app, window


def main() -> int:
    # Antes de tocar no Qt: se falta biblioteca do sistema, a criação do
    # QApplication aborta o processo e não sobra chance de explicar nada.
    problem = check_or_explain()
    if problem:
        print(problem, file=sys.stderr)
        return 1

    app, window = build_app()
    window.show()
    # O provisionamento do ffmpeg pode abrir diálogo; roda depois de a janela
    # aparecer, para que o diálogo tenha um pai visível a que se ancorar.
    QTimer.singleShot(0, window.bootstrap)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
