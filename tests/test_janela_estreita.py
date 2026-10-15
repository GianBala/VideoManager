"""A gaveta de tarefas não decide sozinha a largura mínima da janela (``REG-001``).

Na ``main`` a fila ficava embaixo e a janela encolhia até 375 px. Com a gaveta ao lado, de 344 px fixos, o mínimo de Download
e Convert subiu para 840 (947 com um vídeo analisado): o mesmo conteúdo, mais a gaveta que ninguém pediu para ver naquele
momento. Agora a gaveta é a primeira a sair quando falta largura — recolhe sozinha abaixo de ``menu + mínimo do conteúdo +
344`` e volta quando há espaço — e o item Tarefas a abre sob demanda, crescendo a janela até caber.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from PySide6.QtWidgets import QApplication

from videomanager.application.jobs.models import JobStatus
from videomanager.bootstrap import (build_desktop_runtime, build_download_service, build_editor_service,
                                    build_processing_service)
from videomanager.domain import i18n
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt.i18n import apply_language
from videomanager.presentation.qt.main_window import _TAB_CONVERT, _TAB_DOWNLOAD, _TAB_EDIT, _TAB_METADATA, MainWindow
from videomanager.presentation.qt.nav_rail import LARGURA as LARGURA_DO_MENU
from videomanager.presentation.qt.panels.queue_panel import DRAWER_WIDTH

ABAS = [_TAB_DOWNLOAD, _TAB_CONVERT, _TAB_EDIT, _TAB_METADATA]


@pytest.fixture
def janela(desktop_app, monkeypatch):
    monkeypatch.setattr("videomanager.presentation.qt.main_window.ensure_ffmpeg", lambda parent, **kw: None)
    w = MainWindow(Settings(), editor=build_editor_service(), processing=build_processing_service(),
                   downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))
    w.show()
    _assentar()
    yield w
    w._edit._project_actions.confirm_replace = lambda: True
    for job in w._queue.jobs:
        job.status = JobStatus.DONE
    w._edit.shutdown()
    w.close()
    apply_language(i18n.PORTUGUESE)


def _assentar() -> None:
    for _ in range(6):
        QApplication.processEvents()


def _ir(janela, indice: int) -> None:
    janela._tabs.setCurrentIndex(indice)
    _assentar()


def _largura(janela, pedida: int) -> int:
    janela.resize(pedida, 1000)
    _assentar()
    return janela.width()


def _limiar(janela) -> int:
    """A largura em que a gaveta deixa de caber ao lado do conteúdo: menu + mínimo do conteúdo + a gaveta."""
    return LARGURA_DO_MENU + janela._tabs.minimumSizeHint().width() + DRAWER_WIDTH


@pytest.mark.parametrize("aba", ABAS)
def test_a_janela_encolhe_ate_o_conteudo_em_qualquer_aba(janela, aba):
    _ir(janela, aba)
    minimo = _largura(janela, 100)
    assert minimo == LARGURA_DO_MENU + janela._tabs.minimumSizeHint().width(), "a gaveta contou no mínimo da janela"
    assert minimo < _limiar(janela), "o mínimo da janela ainda inclui a gaveta"


def test_a_gaveta_recolhe_sozinha_na_janela_estreita_e_volta_quando_ha_largura(janela):
    larga = _limiar(janela) + 200
    assert _largura(janela, larga) == larga and janela._queue_panel.isVisible()
    assert janela._queue_panel.width() == DRAWER_WIDTH
    estreita = _limiar(janela) - 60
    assert _largura(janela, estreita) == estreita
    assert not janela._queue_panel.isVisible() and not janela._nav_tasks.isChecked()
    # A preferência é do usuário, e a janela estreita não a revoga: voltou a caber, volta a gaveta.
    assert janela._drawer_open
    assert _largura(janela, larga) == larga
    assert janela._queue_panel.isVisible() and janela._nav_tasks.isChecked()
    assert janela._queue_panel.width() == DRAWER_WIDTH


def test_o_item_tarefas_abre_a_gaveta_na_janela_estreita_e_a_janela_cresce_ate_caber(janela):
    estreita = _limiar(janela) - 60
    _largura(janela, estreita)
    assert not janela._queue_panel.isVisible()
    janela._nav_tasks.click()
    _assentar()
    assert janela._queue_panel.isVisible() and janela._nav_tasks.isChecked()
    assert janela._queue_panel.width() == DRAWER_WIDTH
    assert janela.width() >= _limiar(janela), "a janela não cresceu para dar lugar à gaveta"
    janela._queue_panel._hide_button.click()
    _assentar()
    assert not janela._queue_panel.isVisible() and not janela._nav_tasks.isChecked()


def test_o_aviso_ver_tarefas_abre_a_gaveta_na_janela_estreita(janela):
    _largura(janela, _limiar(janela) - 60)
    janela._set_drawer(True)
    _assentar()
    assert janela._queue_panel.isVisible() and janela._queue_panel.width() == DRAWER_WIDTH


def test_aberta_na_janela_estreita_a_gaveta_continua_ao_trocar_de_aba(janela):
    """A janela cresceu para dar lugar a ela; ir ao editor não a esconde (o relato de 2026-10-15)."""
    _largura(janela, _limiar(janela) - 60)
    janela._nav_tasks.click()
    _assentar()
    assert janela._queue_panel.isVisible()
    _ir(janela, _TAB_EDIT)
    assert janela._queue_panel.isVisible() and janela._queue_panel.width() == DRAWER_WIDTH


def test_o_limiar_acompanha_o_conteudo_que_cresce_sem_que_a_janela_mude_de_tamanho(janela):
    """Analisar um vídeo alarga o mínimo do conteúdo (840 → 947 medido): a gaveta recolhe sem nenhum redimensionamento."""
    larga = _limiar(janela) + 40
    _largura(janela, larga)
    assert janela._queue_panel.isVisible()
    janela._tabs.setMinimumWidth(janela._tabs.minimumSizeHint().width() + 120)
    _assentar()
    assert not janela._queue_panel.isVisible(), "o conteúdo passou a pedir mais e a gaveta ficou espremida"
    janela._tabs.setMinimumWidth(0)
    _assentar()
    assert janela._queue_panel.isVisible() and janela._queue_panel.width() == DRAWER_WIDTH


_APAGAR_COM_WORKER_VIVO = '''
import os, threading, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QCoreApplication, QEvent, QRunnable, QThreadPool, Slot
from PySide6.QtWidgets import QApplication
import videomanager.presentation.qt.main_window as mw
from videomanager.bootstrap import (build_desktop_runtime, build_download_service, build_editor_service,
                                    build_processing_service)
from videomanager.infrastructure.storage.settings import Settings

mw.ensure_ffmpeg = lambda parent, **kw: None
app = QApplication([])
janela = mw.MainWindow(Settings(), editor=build_editor_service(), processing=build_processing_service(),
                       downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))
janela.show()
for _ in range(5):
    app.processEvents()
terminou = threading.Event()

class Tarefa(QRunnable):
    @Slot()
    def run(self):
        time.sleep(0.5)  # acorda e precisa do GIL para continuar
        terminou.set()

pool = QThreadPool(janela)  # filha da janela, como os workers da edição: o destrutor da janela a espera
pool.start(Tarefa())
time.sleep(0.1)
janela._edit.shutdown()
janela.close()
janela.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
print("APAGADA", terminou.is_set())
'''


def test_apagar_a_janela_com_um_worker_vivo_nao_trava(tmp_path):
    """O ``DeferredDelete`` que apaga a janela passa por ``event()``, e o destrutor do ``QThreadPool`` espera lá dentro.

    Com ``event()`` sobrescrito em Python esse ``delete this`` rodava num quadro que segura o GIL, e um worker ainda
    vivo, que precisa dele para terminar, travava o fechamento para sempre: foi o que o ``validate_language.py
    --cortes`` mostrou depois do recolhimento da gaveta. Num processo à parte porque o defeito é justamente não voltar.
    """
    ambiente = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_DATA_HOME": str(tmp_path / "data"),
                "XDG_CACHE_HOME": str(tmp_path / "cache")}
    resultado = subprocess.run([sys.executable, "-c", _APAGAR_COM_WORKER_VIVO], env=ambiente, capture_output=True,
                               text=True, timeout=60)
    assert "APAGADA True" in resultado.stdout, resultado.stdout + resultado.stderr
