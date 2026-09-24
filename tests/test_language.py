"""Troca de idioma com a janela aberta: o mecanismo de presentation/qt/i18n.py.

O inglês daqui é um pseudoidioma (cada texto do catálogo entre ⟦ ⟧): o que se
confere é o mecanismo, que não pode depender de uma tradução existir.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel, QWidget

from videomanager.domain import i18n
from videomanager.presentation.qt import i18n as idioma
from videomanager.presentation.qt import strings


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
    tabela = {nome: _pseudo(valor) for nome, valor in idioma._TABLES[i18n.PORTUGUESE].items()}
    monkeypatch.setitem(idioma._TABLES, i18n.ENGLISH, tabela)


class _Dono(QWidget):
    def __init__(self):
        super().__init__()
        self.chamadas = 0
        self.congelada = None

    def refazer(self):
        self.chamadas += 1
        self.congelada = not self.updatesEnabled()


def test_catalogo_e_texto_preso_seguem_a_troca(pseudo):
    rotulo = idioma.bind(QLabel(), "setText", lambda: strings.EDIT_PLAY)
    assert rotulo.text() == "Reproduzir"
    idioma.apply_language(i18n.ENGLISH)
    assert strings.EDIT_PLAY == "⟦Reproduzir⟧"
    assert strings.QUEUE_COLUMNS[0] == "⟦Título⟧"
    assert rotulo.text() == "⟦Reproduzir⟧"
    assert i18n.language() == i18n.ENGLISH
    idioma.apply_language(i18n.PORTUGUESE)
    assert rotulo.text() == "Reproduzir"
    assert strings.EDIT_PLAY == "Reproduzir"


def test_origem_com_estado_volta_igual_no_idioma_novo(pseudo):
    contagem = 3
    rotulo = idioma.bind(QLabel(), "setToolTip", lambda: strings.EDIT_MEDIA_COUNT.format(count=contagem))
    idioma.apply_language(i18n.ENGLISH)
    assert rotulo.toolTip() == "⟦3 mídia(s)⟧"


def test_texto_escrito_depois_do_bind_nao_e_apagado(pseudo):
    rotulo = idioma.bind(QLabel(), "setText", lambda: strings.EDIT_PLAY)
    rotulo.setText("clip.mp4 · 4,25 s")
    idioma.apply_language(i18n.ENGLISH)
    assert rotulo.text() == "clip.mp4 · 4,25 s"


def test_segundo_bind_substitui_o_primeiro(pseudo):
    botao = idioma.bind(QLabel(), "setText", lambda: strings.EDIT_PLAY)
    idioma.bind(botao, "setText", lambda: strings.EDIT_PAUSE)
    idioma.apply_language(i18n.ENGLISH)
    assert botao.text() == "⟦Pausar⟧"


def test_widget_destruido_sai_do_registro(pseudo):
    rotulo = idioma.bind(QLabel(), "setText", lambda: strings.EDIT_PLAY)
    rotulo.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    idioma.apply_language(i18n.ENGLISH)
    assert all(obj is not rotulo for obj in list(idioma._bound.keys()))


def test_metodo_roda_na_troca_com_a_janela_congelada(pseudo):
    dono = _Dono()
    dono.show()
    idioma.on_language_change(dono.refazer)
    idioma.apply_language(i18n.ENGLISH)
    assert dono.chamadas == 1
    assert dono.congelada is True
    assert dono.updatesEnabled()
    idioma.apply_language(i18n.ENGLISH)  # mesmo idioma: nada a refazer
    assert dono.chamadas == 1
    dono.close()


def test_metodo_de_dono_destruido_nao_roda(pseudo):
    dono = _Dono()
    idioma.on_language_change(dono.refazer)
    dono.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    idioma.apply_language(i18n.ENGLISH)  # não levanta RuntimeError de objeto C++ apagado


def test_bind_e_on_language_change_recusam_o_que_nao_saberiam_refazer(desktop_app):
    with pytest.raises(ValueError):
        idioma.bind(QLabel(), "setAccessibleName", lambda: strings.EDIT_PLAY)
    with pytest.raises(TypeError):
        idioma.on_language_change(lambda: None)
