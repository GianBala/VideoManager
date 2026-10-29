"""O número de um campo da interface aparece: o campo de dentro do ``QSpinBox`` da ``FieldBox`` ocupa a caixa inteira.

No Qt 6.12 o ``QStyleSheetStyle`` entregava 1 px de largura ao campo de texto de um ``QSpinBox`` sem botões quando a
regra do QSS tinha borda ou preenchimento: o tamanho da fonte, a espessura do contorno e todos os campos da aba
Propriedades apareciam vazios, sem erro algum. O pacote do Windows sai da CI, que instala o PySide6 mais novo, e foi lá
que alguém viu; a suíte inteira passava porque nenhum teste olhava a largura do campo de dentro. Estes testes medem a
geometria com o tema real aplicado (como o aplicativo roda) e valem em qualquer versão do Qt.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QDoubleSpinBox, QSpinBox, QStyle, QStyleOptionSpinBox,
                               QVBoxLayout, QWidget)

from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt.panels.field_box import FieldBox


def _assentar() -> None:
    for _ in range(8):
        QApplication.processEvents()


def _preenche(spin: QAbstractSpinBox) -> bool:
    """O campo de dentro cobre o controle, a menos de 1 px de arredondamento de cada lado."""
    return spin.lineEdit().width() >= spin.width() - 2 and spin.lineEdit().height() >= spin.height() - 2


@pytest.mark.parametrize("classe", [QSpinBox, QDoubleSpinBox])
@pytest.mark.parametrize("alinhamento", [Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignHCenter, Qt.AlignmentFlag.AlignRight])
def test_o_campo_de_dentro_da_caixa_ocupa_o_controle_todo(tema_do_app, classe, alinhamento):
    janela = QWidget()
    coluna = QVBoxLayout(janela)
    spin = classe()
    spin.setRange(0, 1000)
    spin.setValue(48)
    coluna.addWidget(FieldBox(spin, lead="X", tail="px", align=alinhamento))
    janela.resize(300, 120)
    janela.show()
    _assentar()
    try:
        assert spin.width() > 100
        assert _preenche(spin), f"campo de dentro {spin.lineEdit().size()} num controle de {spin.size()}"
    finally:
        janela.close()


def test_o_campo_de_dentro_acompanha_o_controle_quando_a_janela_muda_de_tamanho(tema_do_app):
    janela = QWidget()
    coluna = QVBoxLayout(janela)
    spin = QSpinBox()
    coluna.addWidget(FieldBox(spin))
    janela.resize(300, 120)
    janela.show()
    _assentar()
    try:
        for largura in (180, 520, 240):
            janela.resize(largura, 120)
            _assentar()
            assert _preenche(spin), f"{largura} px: campo de dentro {spin.lineEdit().size()} num controle de {spin.size()}"
    finally:
        janela.close()


def test_o_campo_de_dentro_volta_a_cobrir_o_controle_depois_de_trocar_o_estilo(tema_do_app):
    """A troca de paleta refaz o QSS (``setStyleSheet``) com a janela aberta: o estilo recalcula o campo de dentro."""
    from videomanager.presentation.qt import theme

    janela = QWidget()
    coluna = QVBoxLayout(janela)
    spin = QSpinBox()
    coluna.addWidget(FieldBox(spin))
    janela.resize(300, 120)
    janela.show()
    _assentar()
    try:
        for nome in ("estudio", "grafite"):
            theme.apply(tema_do_app, "light", nome)
            _assentar()
            assert _preenche(spin), f"{nome}: campo de dentro {spin.lineEdit().size()} num controle de {spin.size()}"
    finally:
        janela.close()


def test_os_numeros_do_editor_aparecem_no_texto_e_na_aba_propriedades(tema_do_app, painel_de_edicao, blocos_de_edicao):
    """Tamanho da fonte e contorno (aba Texto) e todos os campos de número da aba Propriedades de um vídeo."""
    painel = painel_de_edicao
    painel.resize(1500, 1100)
    painel.show()
    painel._timeline.select(blocos_de_edicao["video com som"].clip_id)
    painel._open_properties_tab(blocos_de_edicao["video com som"].clip_id)
    painel._properties_widget.show()
    _assentar()
    propriedades = painel._properties_widget
    spins = [painel._font_size_spin, painel._stroke_spin, *(
        valor for valor in vars(propriedades).values()
        if isinstance(valor, QAbstractSpinBox) and isinstance(valor.parentWidget(), FieldBox))]
    visiveis = [spin for spin in spins if spin.isVisibleTo(spin.window()) and spin.width() > 20]
    assert len(visiveis) >= 8
    vazios = [type(spin).__name__ + ":" + spin.text() for spin in visiveis if not _preenche(spin)]
    assert not vazios, f"campos de número com o texto de dentro espremido: {vazios}"


def test_o_recuo_do_numero_nos_campos_com_setas_bate_com_o_qss(tema_do_app):
    """``SPIN_EDIT_INSET`` é a borda mais o preenchimento horizontal da regra genérica de campos do tema."""
    import re

    from videomanager.presentation.qt import theme

    regra = re.search(r"QLineEdit, QComboBox, QSpinBox[^{]*\{([^}]*)\}", tema_do_app.styleSheet()).group(1)
    borda = int(re.search(r"border:\s*(\d+)px", regra).group(1))
    lateral = int(re.search(r"padding:\s*\d+px\s+(\d+)px", regra).group(1))
    assert theme.SPIN_EDIT_INSET == borda + lateral


@pytest.mark.parametrize("largura", [110, 246, 400])
def test_o_numero_do_campo_com_setas_nasce_afastado_da_borda_e_antes_dos_botoes(tema_do_app, largura):
    """No Qt 6.12 o campo de dentro começava em x = 0: o número colava na borda arredondada (Configurações, bitrate livre)."""
    from videomanager.presentation.qt import theme
    from videomanager.presentation.qt.arrow_spin import ArrowSpinBox

    janela = QWidget()
    coluna = QVBoxLayout(janela)
    spin = ArrowSpinBox()
    spin.setRange(0, 9999)
    spin.setFixedWidth(largura)
    coluna.addWidget(spin)
    janela.resize(largura + 40, 120)
    janela.show()
    _assentar()
    try:
        edit = spin.lineEdit()
        assert edit.x() == theme.SPIN_EDIT_INSET, f"campo de dentro em x = {edit.x()}"
        assert edit.x() + edit.width() <= spin.width() - theme.SPIN_EDIT_INSET
        # O texto termina antes dos botões, sem invadi-los.
        opcao = QStyleOptionSpinBox()
        spin.initStyleOption(opcao)
        botoes = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, opcao, QStyle.SubControl.SC_SpinBoxUp, spin)
        assert edit.x() + edit.width() <= botoes.left()
    finally:
        janela.close()


def test_o_bitrate_livre_da_aba_download_tem_as_setas_desenhadas(tema_do_app, desktop_app):
    """Era um ``QSpinBox`` puro: sob o QSS os botões saíam como dois retângulos vazios."""
    from videomanager.presentation.qt.arrow_spin import ArrowSpinBox
    from videomanager.presentation.qt.panels.quality_panel import QualityPanel

    painel = QualityPanel(Settings())
    try:
        assert isinstance(painel._bitrate_custom, ArrowSpinBox)
    finally:
        painel.close()
