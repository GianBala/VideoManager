"""Infraestrutura comum dos testes."""

from __future__ import annotations

import importlib.util
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

    Sem PySide6 não há janela para sondar. O job ``internal`` da CI roda
    domínio, aplicação e arquitetura só com o pytest, e importar a janela ali
    derrubava todos esses testes antes de começarem.
    """
    if importlib.util.find_spec("PySide6") is None:
        return
    from videomanager.presentation.qt.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "_warm_hardware_probe", lambda self: None)


@pytest.fixture(autouse=True)
def idioma_padrao():
    """Todo teste termina em português, o idioma padrão.

    O idioma é estado do processo inteiro: um teste que trocasse para o inglês
    e falhasse antes de desfazer deixaria os seguintes comparando texto no
    idioma errado — falhando longe da causa.
    """
    yield
    from videomanager.domain import i18n
    # Com PySide6, a troca também devolve os textos do módulo strings; sem ele
    # (o job internal da CI) só existe o idioma do núcleo.
    if importlib.util.find_spec("PySide6") is not None:
        from videomanager.presentation.qt.i18n import apply_language
        apply_language(i18n.PORTUGUESE)
    i18n.set_language(i18n.PORTUGUESE)


@pytest.fixture(autouse=True)
def janelas_do_teste_apagadas():
    """Apaga, no fim de cada teste, as janelas que ele deixou para trás.

    Painel e janela criados num teste continuavam vivos até o fim da sessão:
    na altura dos testes de idioma eram 703 janelas de topo e 35 mil widgets,
    e a troca de idioma entrega os eventos do Qt a todos eles — um teste de
    idioma levava 2 s em vez de 0,5 s. Só as janelas sem pai que nasceram
    durante o teste: as dos fixtures de módulo e de sessão já existiam quando
    ele começou, e as filhas (listas, menus) vão junto com a mãe.
    """
    if importlib.util.find_spec("PySide6") is None:
        yield
        return
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    def janelas() -> dict[int, object]:
        if QApplication.instance() is None:
            return {}
        return {shiboken6.getCppPointer(w)[0]: w for w in QApplication.topLevelWidgets() if w.parent() is None}

    antes = set(janelas())
    yield
    novas = [janela for endereco, janela in janelas().items() if endereco not in antes]
    for janela in novas:
        janela.deleteLater()
    if novas:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _pseudo(valor):
    if isinstance(valor, str):
        return f"⟦{valor}⟧"
    if isinstance(valor, tuple):
        return tuple(_pseudo(v) for v in valor)
    if isinstance(valor, dict):
        return {chave: _pseudo(v) for chave, v in valor.items()}
    return valor


@pytest.fixture
def pseudo(monkeypatch, desktop_app):
    """Inglês trocado por um pseudoidioma: cada texto do catálogo da interface entre ⟦ ⟧.

    O que se confere com ele é o mecanismo da troca, que não pode depender de
    uma tradução existir — e texto sem as marcas depois da troca é texto que
    escapou do catálogo.
    """
    from videomanager.domain import i18n
    from videomanager.presentation.qt import i18n as idioma
    tabela = {nome: _pseudo(valor) for nome, valor in idioma._TABLES[i18n.PORTUGUESE].items()}
    monkeypatch.setitem(idioma._TABLES, i18n.ENGLISH, tabela)


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


def fatiar(itens: list, indice: int, total: int) -> tuple[list, list]:
    """Parte ``indice`` (de 1 a ``total``) da suíte, e o que ficou de fora.

    A divisão é por **posição na lista ordenada pelo id**, e não por arquivo:
    os testes de um mesmo arquivo custam parecido, e por arquivo uma fatia
    levaria o ``test_integration.py`` inteiro (36% do tempo da suíte). Em
    revezamento, vizinhos pesados caem em fatias diferentes. A **ordem de coleta
    é preservada** dentro da fatia: a suíte tem dependência de ordem latente (o
    ``QPushButton already deleted`` de ``test_probe_lifecycle`` apareceu quando a
    fatia foi reordenada por id), e a fatia só deve diferir da execução inteira
    pelos testes que saem, nunca pela ordem dos que ficam.
    """
    ordenados = sorted(itens, key=lambda item: item.nodeid)
    minha = set(ordenados[indice - 1::total])
    return [item for item in itens if item in minha], [item for item in itens if item not in minha]


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """``VM_SHARD="i/n"`` roda só a fatia ``i`` de ``n`` da suíte (a CI usa).

    Dividir entre máquinas rende mais do que dentro de uma: as integrações com o
    ffmpeg são ~85% do tempo e já ocupam os 4 núcleos do runner (o xdist ganhou
    só 24%), enquanto cada job da CI traz núcleos próprios. Roda por último para
    enxergar a lista já filtrada por ``-m``: **todas as fatias precisam do mesmo
    ``-m``**, senão a união delas deixa de ser a suíte. Sem a variável, não faz
    nada.
    """
    spec = os.environ.get("VM_SHARD")
    if not spec:
        return
    try:
        indice, total = (int(parte) for parte in spec.split("/"))
        valido = 1 <= indice <= total
    except ValueError:
        valido = False
    if not valido:
        raise pytest.UsageError(f'VM_SHARD="{spec}" inválido: use "i/n", com 1 <= i <= n')
    ficam, fora = fatiar(items, indice, total)
    items[:] = ficam
    config.hook.pytest_deselected(items=fora)
