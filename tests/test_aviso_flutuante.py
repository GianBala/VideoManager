"""Aviso flutuante: aparece, empilha, some sozinho, e ocupa o lugar da barra de status.

A barra de status dava a única resposta a certos gestos (clicar em "Adicionar à fila" com a fila
escondida no editor; uma falha ao gravar as preferências), e a renovação visual a tira. O aviso
precisa fazer o que ela fazia: ser visto, durar o suficiente, e não segurar o que está embaixo.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStatusBar, QWidget

from videomanager.application.jobs.models import Job, JobKind
from videomanager.bootstrap import (build_desktop_runtime, build_download_service, build_editor_service,
                                    build_processing_service)
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.main_window import MainWindow
from videomanager.presentation.qt.toast import ToastHost


@pytest.fixture
def janela(desktop_app):
    pai = QWidget()
    pai.resize(900, 600)
    pai.show()
    desktop_app.processEvents()
    yield pai, ToastHost(pai)
    pai.close()
    pai.deleteLater()


def test_o_aviso_aparece_embaixo_no_centro(janela):
    pai, host = janela
    aviso = host.mostrar("2 tarefa(s) adicionada(s) à fila")
    assert aviso.isVisible() and aviso.mensagem.text() == "2 tarefa(s) adicionada(s) à fila"
    centro = aviso.x() + aviso.width() / 2
    assert abs(centro - pai.width() / 2) <= 1
    assert aviso.y() + aviso.height() <= pai.height() and aviso.y() + aviso.height() >= pai.height() - 40


def test_some_sozinho_depois_do_tempo(janela):
    _, host = janela
    host.mostrar("passageiro", ms=40)
    assert len(host.ativos) == 1
    QTest.qWait(200)
    assert host.ativos == []


def test_ms_zero_deixa_o_aviso_ate_ser_fechado(janela):
    _, host = janela
    aviso = host.mostrar("fica", ms=0)
    QTest.qWait(150)
    assert host.ativos == [aviso] and aviso.isVisible()
    aviso.botao_fechar.click()
    assert host.ativos == [] and not aviso.isVisible()


def test_dois_avisos_empilham_sem_se_sobrepor(janela):
    _, host = janela
    a, b = host.mostrar("primeiro", ms=0), host.mostrar("segundo", ms=0)
    ra, rb = QRect(a.pos(), a.size()), QRect(b.pos(), b.size())
    assert not ra.intersects(rb)
    assert b.y() > a.y() or a.y() > b.y()
    # Fechar o de baixo faz o outro descer para o lugar dele.
    ultimo = b if b.y() > a.y() else a
    outro = a if ultimo is b else b
    ultimo.fechar()
    assert outro.y() + outro.height() >= janela[0].height() - 40


def test_a_acao_chama_e_fecha(janela):
    _, host = janela
    chamadas = []
    aviso = host.mostrar("adicionada", acao=("Ver tarefas", lambda: chamadas.append(1)), ms=0)
    assert aviso.acao.text() == "Ver tarefas"
    aviso.acao.click()
    assert chamadas == [1] and host.ativos == []


def test_o_aviso_acompanha_o_redimensionamento_da_janela(janela):
    pai, host = janela
    aviso = host.mostrar("segue", ms=0)
    pai.resize(1200, 800)
    QTest.qWait(30)
    assert abs((aviso.x() + aviso.width() / 2) - 600) <= 1
    assert aviso.y() + aviso.height() <= 800


def test_o_erro_tem_tipo_proprio_e_dica_de_fechar(janela):
    _, host = janela
    aviso = host.mostrar("falhou", tipo="error", ms=0)
    assert aviso.property("tipo") == "error" and aviso.property("role") == "toast"
    assert aviso.botao_fechar.toolTip() == strings.TOAST_CLOSE
    assert aviso.accessibleName() == "falhou"


# --------------------------------------------------- na janela principal
@pytest.fixture
def principal(desktop_app, monkeypatch):
    monkeypatch.setattr("videomanager.presentation.qt.main_window.ensure_ffmpeg", lambda parent, **kw: None)
    janela = MainWindow(Settings(), editor=build_editor_service(), processing=build_processing_service(),
                        downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))
    janela.show()
    desktop_app.processEvents()
    yield janela
    janela._edit._project_actions.confirm_replace = lambda: True
    janela._edit.shutdown()
    janela.close()


def test_adicionar_a_fila_responde_com_o_aviso_e_o_botao_ver_tarefas(principal, monkeypatch):
    monkeypatch.setattr(principal._queue, "submit", lambda job: None)
    principal._submit_jobs([Job("", "a", "", kind=JobKind.EXPORT), Job("", "b", "", kind=JobKind.EXPORT)])
    esperado = strings.STATUS_ENQUEUED.format(count=2)
    assert [a.mensagem.text() for a in principal._toasts.ativos] == [esperado]
    assert not principal.findChildren(QStatusBar)


def test_falha_ao_gravar_preferencias_avisa_como_erro(principal, monkeypatch):
    def falha(_settings):
        raise OSError("Permissão negada")

    monkeypatch.setattr(principal._runtime, "save_settings", falha)
    principal._save_settings()
    ativos = principal._toasts.ativos
    assert len(ativos) == 1 and ativos[0].property("tipo") == "error"
    assert "Permissão negada" in ativos[0].mensagem.text()


def test_o_x_do_aviso_tem_nome_acessivel(janela):
    """O botão só tem ícone: sem nome, o leitor de tela anuncia só "botão" (``FRT-001``)."""
    from PySide6.QtGui import QAccessible
    _, host = janela
    aviso = host.mostrar("aviso de teste")
    interface = QAccessible.queryAccessibleInterface(aviso.botao_fechar)
    assert interface.text(QAccessible.Text.Name) == strings.TOAST_CLOSE == aviso.botao_fechar.toolTip()
