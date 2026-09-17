"""Miniatura do acervo e capa dos arquivos gerados mostram o meio do vídeo.

O primeiro quadro costuma ser preto ou um título de abertura; o do meio
representa melhor o conteúdo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.project import MediaKind, MediaRef


def test_acervo_pede_o_quadro_do_meio_do_video(desktop_app, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
    from videomanager.domain.preview import filmstrip_times
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.panels.edit_panel import EditPanel

    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    tools = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")
    runtime = build_desktop_runtime(audio_enabled=False)
    requests = []

    class Worker:
        def __init__(self, path, start, end, count, size, tools, token):
            requests.append((path, start, end, count))
            from videomanager.infrastructure.qt.workers.signals import PreviewSignals
            self.signals = PreviewSignals()

    monkeypatch.setattr(runtime, "filmstrip_worker", Worker)
    panel = EditPanel(Settings(), ensure_tools=lambda: tools, editor=build_editor_service(),
                      processing=build_processing_service(), runtime=runtime)
    monkeypatch.setattr(panel._background, "start", lambda *args: None)
    try:
        video = MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=90, width=320, height=180)
        foto = MediaRef(Path("/m/foto.jpg"), MediaKind.IMAGE, width=320, height=180)
        panel._create_thumbnail_for(video)
        panel._create_thumbnail_for(foto)
        by_path = {path: (start, end, count) for path, start, end, count in requests}
        start, end, count = by_path[video.path]
        assert filmstrip_times(start, end, count) == (45.0,)
        # Imagem continua sem busca: -ss num JPEG lido como image2 devolve nada.
        assert by_path[foto.path][:2] == (0.0, 0.0)
    finally:
        panel.shutdown()


@pytest.fixture
def ffmpeg():
    from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs
    tools = find_tools()
    if tools is None:
        pytest.skip("ffmpeg/ffprobe indisponíveis")

    def run(*args):
        return subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", *map(str, args)],
                              check=True, timeout=60, **subprocess_kwargs())
    return tools, run


def _tricolor(run, path: Path) -> None:
    """Vermelho, verde e azul em terços: o meio é verde."""
    graph = ("color=c=red:s=160x90:r=25:d=2[a];color=c=lime:s=160x90:r=25:d=2[b];"
             "color=c=blue:s=160x90:r=25:d=2[c];[a][b][c]concat=n=3:v=1:a=0")
    run("-f", "lavfi", "-i", graph, "-c:v", "libx264", "-pix_fmt", "yuv420p", path)


def _dominant(image_bytes: bytes) -> str:
    from PySide6.QtGui import QImage
    image = QImage.fromData(image_bytes)
    assert not image.isNull()
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    channels = {"vermelho": color.red(), "verde": color.green(), "azul": color.blue()}
    return max(channels, key=channels.get)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("container", ["mp4", "mkv"])
def test_capa_da_conversao_e_o_quadro_do_meio(desktop_app, ffmpeg, tmp_path, container) -> None:
    from videomanager.domain.media import VideoTarget
    from videomanager.infrastructure.ffmpeg.converter import Converter, probe_file

    tools, run = ffmpeg
    source = tmp_path / "origem.mp4"
    _tricolor(run, source)
    destination = tmp_path / f"saida.{container}"
    destination.write_bytes(b"")
    Converter(probe_file(source, tools), VideoTarget(container=container, video_codec="h264"),
              destination, tools).run()
    if container == "mp4":
        from mutagen.mp4 import MP4
        cover = bytes(MP4(destination)["covr"][0])
    else:
        cover_path = tmp_path / "capa.png"
        run("-i", destination, "-map", "0:v:1", "-frames:v", "1", cover_path)
        cover = cover_path.read_bytes()
    assert _dominant(cover) == "verde"


@pytest.mark.ffmpeg
def test_capa_da_exportacao_do_editor_e_o_quadro_do_meio(desktop_app, ffmpeg, tmp_path) -> None:
    from mutagen.mp4 import MP4

    from videomanager.domain.composition import Composition
    from videomanager.domain.project import media_ref, new_project
    from videomanager.infrastructure.ffmpeg.converter import Converter, probe_file

    tools, run = ffmpeg
    source = tmp_path / "origem.mp4"
    _tricolor(run, source)
    local = probe_file(source, tools)
    destination = tmp_path / "exportado.mp4"
    destination.write_bytes(b"")
    Converter(local, Composition(new_project(media_ref(local))), destination, tools).run()
    assert _dominant(bytes(MP4(destination)["covr"][0])) == "verde"
