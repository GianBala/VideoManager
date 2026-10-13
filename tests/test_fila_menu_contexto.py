"""Contrato da fila: quais itens o menu de contexto oferece em cada situação da tarefa.

Os itens entram só quando fazem sentido (``QueuePanel._show_context_menu``): "Tentar de novo"
só em falha ou cancelamento, "Abrir arquivo" só se o arquivo existe, "Copiar mensagem de erro"
só com erro. A fila vai deixar de ser uma tabela e virar uma lista de cartões, e é fácil, na
troca, perder um desses itens — ou oferecê-lo onde não vale — sem que nada levante exceção.
Os valores abaixo são os de hoje.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, QTimer
from PySide6.QtWidgets import QApplication

from videomanager.application.jobs.models import Job, JobKind, JobStatus
from videomanager.infrastructure.qt.workers import queue as fila
from videomanager.presentation.qt.panels import queue_panel

_ARQUIVO = "arquivo"


@pytest.fixture
def cenario(desktop_app, monkeypatch, tmp_path):
    pronto = tmp_path / "pronto.mp4"
    pronto.write_bytes(b"x")
    fila_de_tarefas = fila.JobQueue(SimpleNamespace(max_concurrent_jobs=3))
    painel = queue_panel.QueuePanel(fila_de_tarefas, runtime=None)
    tarefas = {
        "andamento": Job("", "baixando", "MP4", kind=JobKind.DOWNLOAD, status=JobStatus.RUNNING),
        "na fila": Job("", "esperando", "MP4", kind=JobKind.DOWNLOAD, status=JobStatus.PENDING),
        "falhou": Job("", "falha", "MP4", kind=JobKind.DOWNLOAD, status=JobStatus.FAILED,
                      error="HTTP 403", log="[download] 403"),
        "cancelada": Job("", "cancelada", "MP4", kind=JobKind.DOWNLOAD, status=JobStatus.CANCELLED),
        "concluida": Job("", "pronta", "MP4", kind=JobKind.EXPORT, status=JobStatus.DONE,
                         result_path=pronto, log="ffmpeg ok"),
        "concluida sem arquivo": Job("", "sumiu", "MP4", kind=JobKind.EXPORT, status=JobStatus.DONE,
                                     result_path=tmp_path / "nao-existe.mp4"),
    }
    for tarefa in tarefas.values():
        fila_de_tarefas.service.add(tarefa)
        fila_de_tarefas.job_added.emit(tarefa)
        fila_de_tarefas.job_changed.emit(tarefa)
    linhas = {nome: indice for indice, nome in enumerate(tarefas)}
    yield SimpleNamespace(painel=painel, linhas=linhas, tarefas=tarefas)
    fila_de_tarefas.shutdown(timeout_ms=2000)
    desktop_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    painel.deleteLater()
    fila_de_tarefas.deleteLater()
    desktop_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _menu_para(cenario, *nomes: str) -> list[str] | None:
    tabela = cenario.painel._table
    tabela.clearSelection()
    modelo = tabela.model()
    for nome in nomes:
        indice = modelo.index(cenario.linhas[nome], 0)
        tabela.selectionModel().select(
            indice, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    # ``QMenu.exec`` não pode ser trocado no PySide6 (CLAUDE.md): o menu real abre, e um
    # temporizador, que roda dentro do laço de eventos que o ``exec`` inicia, lê os itens e o fecha.
    lido: list[list[str]] = []

    def ler() -> None:
        menu = QApplication.activePopupWidget()
        if menu is not None:
            lido.append([acao.text() for acao in menu.actions() if acao.text()])
            menu.close()

    temporizador = QTimer()
    temporizador.setSingleShot(True)
    temporizador.timeout.connect(ler)
    temporizador.start(150)
    cenario.painel._show_context_menu(QPoint(5, 5))
    temporizador.stop()
    return lido[0] if lido else None


@pytest.mark.parametrize("situacao, itens", [
    ("andamento", ["Cancelar"]),
    ("na fila", ["Cancelar"]),
    ("falhou", ["Tentar de novo", "Copiar mensagem de erro", "Ver detalhes técnicos"]),
    ("cancelada", ["Tentar de novo"]),
    ("concluida", ["Abrir arquivo", "Abrir pasta do arquivo", "Ver detalhes técnicos"]),
    ("concluida sem arquivo", None),
])
def test_menu_de_contexto_por_situacao(cenario, situacao, itens):
    assert _menu_para(cenario, situacao) == itens


def test_varias_tarefas_somam_cancelar_e_tentar_de_novo(cenario):
    # O primeiro da seleção manda nos itens de arquivo e de erro; Cancelar e Tentar de novo valem
    # se qualquer uma da seleção os permite.
    assert _menu_para(cenario, "andamento", "falhou") == ["Cancelar", "Tentar de novo"]


def test_sem_selecao_nao_abre_menu(cenario):
    assert _menu_para(cenario) is None
