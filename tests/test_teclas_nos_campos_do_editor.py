"""As teclas que são atalhos do editor continuam valendo nas listas: o Espaço abre a lista e a letra busca o item.

O atalho de uma tecla (Espaço, S, Q, W, F, vírgula, ponto) é do painel inteiro, e ``_dispatch`` não age quando o foco está num
campo. Mas o Qt descarta o toque assim que o atalho dispara: sem devolver a tecla ao campo, a lista da aba Propriedades não
abria com o Espaço e não buscava "Suave…" pela letra S, e nenhum erro dizia isso. O campo de texto não sofre (ele recusa a
tomada das teclas de edição), então o que se mede é a lista, e que o atalho segue valendo fora de um campo.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from videomanager.presentation.qt.panels.edit_panel import EditPanel


@pytest.fixture
def atalhos(monkeypatch):
    """Registra, no lugar das ações, quais atalhos agiram (antes de o painel instalar os atalhos)."""
    agiram: list[str] = []
    for nome, rotulo in (("_toggle_play", "espaço"), ("_split_here", "s")):
        monkeypatch.setattr(EditPanel, nome, lambda self, rotulo=rotulo: agiram.append(rotulo))
    return agiram


@pytest.fixture
def propriedades(atalhos, tema_do_app, painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    bloco = blocos_de_edicao["imagem"]
    painel.resize(1500, 1100)
    painel.show()
    painel._timeline.select(bloco.clip_id)
    painel._open_properties_tab(bloco.clip_id)
    painel._properties_widget.show()
    for _ in range(8):
        QApplication.processEvents()
    return painel


def test_o_espaco_abre_a_lista_da_aba_propriedades_e_nao_reproduz(propriedades, atalhos):
    lista = propriedades._properties_widget._combo_easing
    lista.setFocus()
    QApplication.processEvents()
    QTest.keyClick(lista, Qt.Key.Key_Space)
    for _ in range(4):
        QApplication.processEvents()
    try:
        assert lista.view().isVisible()
        assert atalhos == []
    finally:
        lista.hidePopup()


def test_a_letra_s_busca_o_item_da_lista_e_nao_divide_o_bloco(propriedades, atalhos):
    lista = propriedades._properties_widget._combo_easing
    lista.setFocus()
    QApplication.processEvents()
    assert not lista.currentText().startswith("Suave")
    QTest.keyClick(lista, "s")
    QApplication.processEvents()
    assert lista.currentText().startswith("Suave")
    assert atalhos == []


def test_fora_de_um_campo_os_atalhos_seguem_valendo(propriedades, atalhos):
    propriedades._timeline.setFocus()
    QApplication.processEvents()
    QTest.keyClick(propriedades._timeline, Qt.Key.Key_Space)
    QTest.keyClick(propriedades._timeline, "s")
    assert atalhos == ["espaço", "s"]
