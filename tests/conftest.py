"""Infraestrutura comum dos testes."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Permite rodar a suíte sem instalar o pacote.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# Respostas reais de extratores, cada uma escolhida por expor uma estrutura
# diferente. Ver tests/fixtures/README.md.
FIXTURE_NAMES = (
    "youtube_dash",
    "archive_muxed",
    "hls_no_metadata",
    "soundcloud_audio",
    "instagram_reel",
)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def fixture_formats(name: str) -> list[dict]:
    return load_fixture(name).get("formats") or []


@pytest.fixture(params=FIXTURE_NAMES)
def any_fixture(request) -> tuple[str, dict]:
    """Roda o teste uma vez para cada fixture real disponível."""
    return request.param, load_fixture(request.param)


@pytest.fixture(scope="session")
def desktop_app(tmp_path_factory):
    """A interface usa Qt real; testes offline não consultam a placa de som."""
    from PySide6.QtWidgets import QApplication
    from videomanager.presentation.qt.fonts import ensure_application_fonts
    from videomanager.infrastructure.storage import settings
    profile = tmp_path_factory.mktemp("desktop-profile")
    patch = pytest.MonkeyPatch()
    patch.setattr(settings, "config_dir", lambda: profile)
    app = QApplication.instance() or QApplication([])
    ensure_application_fonts()
    yield app
    patch.undo()


@pytest.fixture(autouse=True)
def sem_sondagem_de_placa(monkeypatch):
    """Testes não sondam a placa de vídeo em segundo plano.

    A janela agenda a sondagem dos encoders de placa para 1,5 s depois de
    criada, numa thread. Um teste que criasse a janela deixava o temporizador
    armado, e a sondagem de verdade gravava o resultado no meio de outro teste:
    ``test_hwaccel``, que conta as próprias sondagens, passava ou falhava
    conforme o tempo entre os arquivos — e o build recusava empacotar.
    """
    from videomanager.presentation.qt.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "_warm_hardware_probe", lambda self: None)


@pytest.fixture
def isolated_audio(monkeypatch):
    from videomanager.infrastructure.qt.audio import AudioPreview
    monkeypatch.setattr(AudioPreview, "available", property(lambda self: False))


@pytest.fixture
def wait_until(desktop_app):
    """Espera sinais Qt com prazo, mantendo a fila de eventos em movimento."""
    import time

    def wait(predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            desktop_app.processEvents()
            time.sleep(0.005)
        assert predicate(), "a operação assíncrona não terminou dentro do prazo"
    return wait
