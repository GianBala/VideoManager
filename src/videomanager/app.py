"""Inicialização da aplicação Qt."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from videomanager import APP_DISPLAY_NAME
from videomanager import APP_NAME
from videomanager import __version__
from videomanager.preflight import check_or_explain
from videomanager.presentation.qt.main_window import MainWindow
from videomanager.bootstrap import build_desktop_runtime
from videomanager.bootstrap import build_editor_service
from videomanager.bootstrap import build_processing_service
from videomanager.bootstrap import build_download_service
from videomanager.bootstrap import load_preferences
from videomanager.presentation.qt.theme import qpalette
from videomanager.presentation.qt.theme import stylesheet


def _icon_path() -> Path:
    """Ícone da aplicação, empacotado ou no repositório.

    O PyInstaller extrai os dados para ``sys._MEIPASS``; fora dele, os arquivos
    estão ao lado do código. Mesmo raciocínio de ``infrastructure.system.binaries.vendor_dir``.
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


def build_app(argv: list[str] | None = None, *, audio_enabled: bool = True) -> tuple[QApplication, MainWindow]:
    """Cria a aplicação e a janela, sem entrar no laço de eventos.

    Separado de :func:`main` para que um teste possa montar a janela, inspecioná-la
    e fechá-la sem bloquear.
    """
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("videomanager.desktop")

    from videomanager.presentation.qt.fonts import ensure_application_fonts

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

    settings = load_preferences()
    app.setPalette(qpalette(settings.theme))
    app.setStyleSheet(stylesheet(settings.theme))

    window = MainWindow(settings, editor=build_editor_service(), processing=build_processing_service(),
                        downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=audio_enabled))
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    return app, window


def _smoke_check(app: QApplication, window: MainWindow) -> None:
    """Diagnóstico do pacote: Qt, fontes e vídeo real; acionado apenas por CLI."""
    from dataclasses import replace
    import tempfile
    from PySide6.QtGui import QFontDatabase
    from videomanager.bootstrap import build_text_rasterizer
    from videomanager.domain.project import Clip, MediaKind, MediaRef, new_project
    from videomanager.domain.composition import Composition
    from videomanager.infrastructure.system.binaries import find_tools
    from videomanager.infrastructure.ffmpeg.composer import frame_command
    from videomanager.infrastructure.ffmpeg.preview import frame_from_command
    from videomanager.infrastructure.ffmpeg.converter import Converter, probe_file

    code = 1
    try:
        if 'Carlito' not in QFontDatabase.families():
            raise RuntimeError('Fonte Carlito ausente do pacote.')
        tools = find_tools()
        if tools is None:
            raise RuntimeError('FFmpeg/ffprobe ausentes; provisione ou inclua no PATH.')
        clip = Clip(MediaRef(Path('Texto'), MediaKind.IMAGE), 0, 1,
                    overlay_type='text', text_content='Video Manager', font_family='Carlito')
        project = replace(new_project().with_clip(0, clip), width=320, height=180, fps=24)
        rasterizer = build_text_rasterizer()
        assets = {clip.clip_id: rasterizer.render(clip)}
        command = frame_command(project, 0, (320, 180), tools, text_assets=assets)
        frame = frame_from_command(command, (320, 180))
        if frame is None or not frame.is_complete or max(frame.data) == 0:
            raise RuntimeError('A prévia com texto não produziu imagem.')
        with tempfile.TemporaryDirectory(prefix='videomanager-smoke-') as directory:
            destination = Path(directory) / 'smoke.mp4'
            Converter(None, Composition(project), destination, tools, text_assets=assets).run()
            output = probe_file(destination, tools)
            if not output.has_video or not output.duration or abs(output.duration - 1) > 0.2:
                raise RuntimeError('A exportação de diagnóstico gerou mídia inválida.')
        print('VM_SMOKE_OK: janela, fontes, prévia e exportação verificadas', flush=True)
        code = 0
    except Exception as exc:
        print(f'VM_SMOKE_FAILED: {exc}', file=sys.stderr, flush=True)
    finally:
        window.close()
        app.exit(code)


def main() -> int:
    # Antes de tocar no Qt: se falta biblioteca do sistema, a criação do
    # QApplication aborta o processo e não sobra chance de explicar nada.
    problem = check_or_explain()
    if problem:
        print(problem, file=sys.stderr)
        return 1

    smoke = '--smoke-test' in sys.argv
    app, window = build_app(audio_enabled=not smoke)
    window.show()
    # O provisionamento do ffmpeg pode abrir diálogo; roda depois de a janela
    # aparecer, para que o diálogo tenha um pai visível a que se ancorar.
    if smoke:
        QTimer.singleShot(0, lambda: _smoke_check(app, window))
    else:
        QTimer.singleShot(0, window.bootstrap)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
