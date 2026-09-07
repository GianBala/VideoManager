"""Inicialização da aplicação Qt."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from . import APP_DISPLAY_NAME, APP_NAME, __version__
from .core.settings import Settings
from .preflight import check_or_explain
from .ui.main_window import MainWindow
from .ui.theme import qpalette, stylesheet
from .ui.text_renderer import configure_text_renderer


def _icon_path() -> Path:
    """Ícone da aplicação, empacotado ou no repositório.

    O PyInstaller extrai os dados para ``sys._MEIPASS``; fora dele, os arquivos
    estão ao lado do código. Mesmo raciocínio de ``core.binaries.vendor_dir``.
    """
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent
    return root / "resources" / "videomanager.png"


def _load_app_icon() -> QIcon:
    """Carrega o ícone da aplicação em múltiplos tamanhos para máxima nitidez na barra de tarefas."""
    icon = QIcon()
    png_path = _icon_path()
    if png_path.is_file():
        pix = QPixmap(str(png_path))
        if not pix.isNull():
            for s in (16, 24, 32, 48, 64, 128, 256, 512):
                icon.addPixmap(
                    pix.scaled(
                        s,
                        s,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        else:
            icon.addFile(str(png_path))
    svg_path = png_path.with_suffix(".svg")
    if svg_path.is_file():
        icon.addFile(str(svg_path))
    return icon


def _ensure_linux_desktop_integration() -> None:
    """Garante que o ambiente desktop (GNOME, Zorin, KDE, etc.) encontre o ícone da aplicação.

    No Linux (Wayland e X11), docks e barras de tarefas buscam ícones associados
    ao app_id / StartupWMClass em ~/.local/share/icons e ~/.local/share/applications.
    Ao registrar o ícone e o .desktop em nível de usuário, a barra de tarefas
    encontra e exibe o novo logotipo imediatamente em qualquer execução.
    """
    try:
        data_home = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
        png_source = _icon_path()
        if not png_source.is_file():
            return

        icons_root = data_home / "icons" / "hicolor"
        target_512 = icons_root / "512x512" / "apps" / "videomanager.png"
        target_256 = icons_root / "256x256" / "apps" / "videomanager.png"

        need_update = (
            not target_512.is_file()
            or target_512.stat().st_mtime < png_source.stat().st_mtime
        )
        if need_update:
            target_512.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(png_source, target_512)
            target_256.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(png_source, target_256)

            svg_source = png_source.with_suffix(".svg")
            if svg_source.is_file():
                target_svg = icons_root / "scalable" / "apps" / "videomanager.svg"
                target_svg.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(svg_source, target_svg)

        apps_dir = data_home / "applications"
        desktop_file = apps_dir / "videomanager.desktop"

        appimage_path = os.environ.get("APPIMAGE")
        if appimage_path:
            exec_cmd = f'"{appimage_path}"'
        else:
            exec_cmd = f'"{sys.executable}" -m videomanager'

        desktop_content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Video Manager\n"
            "Comment=Baixe, edite e converta vídeo e áudio\n"
            f"Exec={exec_cmd}\n"
            "Icon=videomanager\n"
            "Terminal=false\n"
            "Categories=AudioVideo;Video;\n"
            "Keywords=vídeo;áudio;download;converter;editor;ffmpeg;\n"
            "StartupWMClass=VideoManager\n"
        )

        if not desktop_file.is_file() or need_update:
            apps_dir.mkdir(parents=True, exist_ok=True)
            desktop_file.write_text(desktop_content, encoding="utf-8")
    except Exception:
        pass


def build_app(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    """Cria a aplicação e a janela, sem entrar no laço de eventos.

    Separado de :func:`main` para que um teste possa montar a janela, inspecioná-la
    e fechá-la sem bloquear.
    """
    app = QApplication(argv if argv is not None else sys.argv)
    configure_text_renderer()
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("videomanager.desktop")

    from .ui.fonts import ensure_application_fonts

    ensure_application_fonts()

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_NAME}.1.0")
        except Exception:
            pass

    if sys.platform.startswith("linux"):
        _ensure_linux_desktop_integration()

    app_icon = _load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    app.setStyle("Fusion")

    settings = Settings.load()
    app.setPalette(qpalette(settings.theme))
    app.setStyleSheet(stylesheet(settings.theme))

    window = MainWindow(settings)
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
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
