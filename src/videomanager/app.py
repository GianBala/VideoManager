"""Inicialização da aplicação Qt."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import time
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
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_NAME}.2.0")
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
        # Download: o solver JavaScript do YouTube é lido como recurso, não
        # importado, e o mutagen só é carregado ao embutir a capa. Nenhum dos
        # dois falha ao abrir o pacote — só no primeiro download.
        from yt_dlp.extractor.youtube.jsc._builtin.vendor import load_script
        if not load_script('yt.solver.core.js'):
            raise RuntimeError('Scripts do solver JavaScript do yt-dlp ausentes do pacote.')
        import importlib
        importlib.import_module('mutagen')
        from videomanager.infrastructure.system.binaries import find_js_runtime
        runtime = find_js_runtime()
        print(f'VM_SMOKE_JS_RUNTIME: {runtime[0] if runtime else "nenhum"}', flush=True)
        # O cache da agulha guarda quadros em JPEG e depende do plugin de imagem
        # do Qt; sem ele o arrasto cai no quadro exato sem avisar.
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QImage
        probe = QImage(8, 8, QImage.Format.Format_RGB32)
        probe.fill(0xFF3366)
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not probe.save(buffer, 'JPG') or QImage.fromData(bytes(encoded.data()), 'JPG').isNull():
            raise RuntimeError('Suporte a JPEG do Qt ausente do pacote.')
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


class _CapturedRecords(logging.Handler):
    """Guarda os avisos emitidos durante o diagnóstico para o relatório."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(f"{record.levelname} {record.name}: {self.format(record)}")
        except Exception:  # noqa: BLE001 - o relatório não pode derrubar o diagnóstico
            pass


def _diagnose_url(app: QApplication, window: MainWindow, url: str, report: Path | None,
                  timeout: float = 120.0) -> None:
    """Refaz, no próprio pacote, o caminho de analisar uma URL pela janela.

    Existe porque a análise funcionava a partir do código-fonte e não no
    executável do Windows, onde não há console para ver o que falhou. Passa pelo
    mesmo ``MainWindow._analyze`` que o botão usa — worker, pool e slots que
    montam cartão e qualidades —, já que um erro dentro de um slot também deixa
    a tela sem opções e sem mensagem. Diálogos modais viram linhas do relatório.
    """
    import yt_dlp
    from PySide6.QtWidgets import QMessageBox

    captured = _CapturedRecords()
    logging.getLogger().addHandler(captured)
    dialogs: list[str] = []

    def record_dialog(*args, **_kwargs):
        dialogs.append(" | ".join(str(a) for a in args[1:3]))
        return QMessageBox.StandardButton.Ok

    QMessageBox.warning = record_dialog  # type: ignore[method-assign]
    QMessageBox.critical = record_dialog  # type: ignore[method-assign]
    began = time.monotonic()

    def finish() -> None:
        media = window._media  # noqa: SLF001 - diagnóstico da própria janela
        lines = [
            f"url: {url}",
            f"empacotado: {bool(getattr(sys, 'frozen', False))}",
            f"yt-dlp: {yt_dlp.version.__version__}",
            f"tempo: {time.monotonic() - began:.1f} s",
            f"midia: {media.title if media else None}",
            f"formatos: {len(media.matrix.video) + len(media.matrix.audio) if media else 0}",
            f"miniatura: {bool(media and media.thumbnail_url)}",
            f"botao_fila_habilitado: {window._add_button.isEnabled()}",  # noqa: SLF001
            *(f"dialogo: {text}" for text in dialogs),
            *captured.lines,
        ]
        text = "\n".join(lines) + "\n"
        ok = media is not None and window._add_button.isEnabled()  # noqa: SLF001
        text += "VM_DIAGNOSE_OK\n" if ok else "VM_DIAGNOSE_FAILED\n"
        if report is not None:
            report.write_text(text, encoding="utf-8")
        logging.getLogger(__name__).info("Diagnóstico de URL:\n%s", text)
        print(text, flush=True)
        window.close()
        app.exit(0 if ok else 1)

    def poll() -> None:
        busy = window._probe_worker is not None  # noqa: SLF001
        if busy and time.monotonic() - began < timeout:
            QTimer.singleShot(100, poll)
            return
        if busy:
            dialogs.append(f"análise não terminou em {timeout:.0f} s")
        # Os slots de conclusão rodam na mesma volta do laço; espera o cartão.
        QTimer.singleShot(1500, finish)

    window._url.setText(url)  # noqa: SLF001
    window._analyze()  # noqa: SLF001
    QTimer.singleShot(100, poll)


def _argument(name: str) -> str | None:
    if name in sys.argv:
        index = sys.argv.index(name)
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return None


def main() -> int:
    # Antes de tocar no Qt: se falta biblioteca do sistema, a criação do
    # QApplication aborta o processo e não sobra chance de explicar nada.
    problem = check_or_explain()
    if problem:
        print(problem, file=sys.stderr)
        return 1

    from videomanager.infrastructure.system.logs import configure_file_logging

    configure_file_logging()
    smoke = '--smoke-test' in sys.argv
    diagnose_url = _argument('--diagnose-url')
    headless = smoke or diagnose_url is not None
    app, window = build_app(audio_enabled=not headless)
    window.show()
    # O provisionamento do ffmpeg pode abrir diálogo; roda depois de a janela
    # aparecer, para que o diálogo tenha um pai visível a que se ancorar.
    if smoke:
        QTimer.singleShot(0, lambda: _smoke_check(app, window))
    elif diagnose_url is not None:
        report = _argument('--report')
        QTimer.singleShot(0, window.bootstrap)
        QTimer.singleShot(0, lambda: _diagnose_url(app, window, diagnose_url, Path(report) if report else None))
    else:
        QTimer.singleShot(0, window.bootstrap)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
