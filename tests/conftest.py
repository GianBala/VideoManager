"""Infraestrutura comum dos testes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

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
)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def fixture_formats(name: str) -> list[dict]:
    return load_fixture(name).get("formats") or []


@pytest.fixture(params=FIXTURE_NAMES)
def any_fixture(request) -> tuple[str, dict]:
    """Roda o teste uma vez para cada fixture real disponível."""
    return request.param, load_fixture(request.param)
