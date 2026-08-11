"""Inicialização da aplicação Qt."""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import APP_DISPLAY_NAME, APP_NAME, __version__
from .core.settings import Settings
from .preflight import check_or_explain
from .ui.main_window import MainWindow
from .ui.theme import qpalette, stylesheet


def build_app(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    """Cria a aplicação e a janela, sem entrar no laço de eventos.

    Separado de :func:`main` para que um teste possa montar a janela, inspecioná-la
    e fechá-la sem bloquear.
    """
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setApplicationVersion(__version__)
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
