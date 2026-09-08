"""Inspeção cancelável da conversão mantém a UI ativa e descarta lotes antigos."""
from pathlib import Path
import threading

from PySide6.QtCore import QTimer
import pytest

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.preferences import Preferences
from videomanager.bootstrap import build_desktop_runtime, build_processing_service
from videomanager.domain.media import LocalMedia, LocalStream
from videomanager.presentation.qt.panels.convert_panel import ConvertPanel

pytestmark = pytest.mark.usefixtures('desktop_app', 'isolated_audio')


def test_inspecao_nao_bloqueia_eventos_e_limpar_descarta_resposta(monkeypatch, wait_until):
    started, release = threading.Event(), threading.Event()
    threads = []
    def inspect(path, tools, *, control):
        threads.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        control.check()
        # Converter não exige duração conhecida para aceitar o arquivo.
        return LocalMedia(path, None, 'mp3', 100, (LocalStream(0, 'audio', 'mp3'),))
    monkeypatch.setattr('videomanager.infrastructure.qt.workers.media_worker.probe_file', inspect)
    tools = FFmpegTools(Path('ffmpeg'), Path('ffprobe'), 'teste')
    panel = ConvertPanel(Preferences(), lambda: tools, processing=build_processing_service(),
                         runtime=build_desktop_runtime())
    a, b = Path('a.mp3'), Path('b.mp3')
    ticked = []
    try:
        panel.add_files([a, a])
        QTimer.singleShot(0, lambda: ticked.append(True))
        wait_until(lambda: started.is_set() and bool(ticked))
        assert all(thread != threading.get_ident() for thread in threads)
        assert not panel._start.isEnabled()
        assert panel._inspection_paths == [a]
        panel.clear_files()
        release.set()
        wait_until(lambda: panel._inspection_runner.active == 0)
        assert panel._media == [] and panel._list.count() == 0
        panel.add_files([a, a, b])
        wait_until(lambda: panel._inspection_worker is None)
        assert [media.path for media in panel._media] == [a, b]
        assert panel._start.isEnabled()
    finally:
        release.set()
        panel.shutdown()
