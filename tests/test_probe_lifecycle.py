"""Sinais Qt já enfileirados não podem instalar uma análise cancelada."""
from types import SimpleNamespace

import pytest

from videomanager.application.preferences import Preferences
from videomanager.bootstrap import (
    build_desktop_runtime, build_download_service, build_editor_service, build_processing_service,
)
from videomanager.domain.formats import FormatMatrix, MediaInfo
from videomanager.infrastructure.qt.workers.signals import ProbeSignals
from videomanager.presentation.qt.main_window import MainWindow

pytestmark = pytest.mark.usefixtures('desktop_app', 'isolated_audio')


def test_resposta_enfileirada_antes_do_cancelamento_nao_altera_nova_analise(desktop_app, monkeypatch):
    runtime = build_desktop_runtime()
    workers = []
    def probe(*args, **kwargs):
        worker = SimpleNamespace(signals=ProbeSignals(), cancel=lambda: None)
        workers.append(worker)
        return worker
    monkeypatch.setattr(runtime, 'probe_worker', probe)
    window = MainWindow(Preferences(), editor=build_editor_service(), processing=build_processing_service(),
                        downloads=build_download_service(), runtime=runtime)
    monkeypatch.setattr(window._runner, 'start', lambda *args: None)
    warnings = []
    monkeypatch.setattr('videomanager.presentation.qt.main_window.QMessageBox.warning',
                        lambda *args: warnings.append(args))
    try:
        window._url.setText('https://example.org/antiga')
        window._analyze()
        old = workers[-1]
        old.signals.finished.emit(MediaInfo('antiga', 'Antiga', FormatMatrix()))
        old.signals.failed.emit('Erro antigo')
        window._cancel_analyze()
        window._url.setText('https://example.org/nova')
        window._analyze()
        current = workers[-1]
        desktop_app.processEvents()
        assert window._media is None and not warnings
        assert window._probe_worker is current and not window._url.isEnabled()
        media = MediaInfo('nova', 'Nova', FormatMatrix())
        current.signals.finished.emit(media)
        desktop_app.processEvents()
        assert window._media is media
        assert window._probe_worker is None and window._url.isEnabled()
    finally:
        for worker in workers:
            worker.signals.done.emit()
        window.close()
