"""Barra superior do editor: ícones no lugar dos botões de texto, a marca de "não salvo" e o seletor único de tela.

O que uma barra reorganizada perde em silêncio é o que aparecia por extenso: o botão sem nome para a leitura de tela, o
"Salvar como" que sumiu da vista, a escolha de tela que deixou de acompanhar o projeto. Os testes conferem pelo que cada
controle faz e pelo texto que mostra, e não por onde ele está.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from videomanager.domain import i18n
from videomanager.domain.project import TrackKind
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.i18n import apply_language


def _imagem(botao):
    return botao.icon().pixmap(20, 20).toImage()


@pytest.fixture
def idioma_portugues():
    yield
    apply_language(i18n.PORTUGUESE)


def test_os_botoes_do_projeto_sao_so_icone_com_nome_e_dica(painel_de_edicao):
    painel = painel_de_edicao
    esperados = ((painel._new_btn, strings.EDIT_NEW_BUTTON, "Ctrl+N"), (painel._open_btn, strings.EDIT_OPEN_BUTTON, "Ctrl+O"),
                 (painel._save_btn, strings.EDIT_SAVE_BUTTON, "Ctrl+S"))
    for botao, nome, atalho in esperados:
        assert botao.text() == "" and not botao.icon().isNull(), nome
        assert botao.accessibleName() == nome
        assert atalho in botao.toolTip()
    # Cada um com o seu desenho: três ícones iguais seriam três botões que a vista não distingue.
    imagens = [_imagem(b) for b, _, _ in esperados]
    assert all(a != b for i, a in enumerate(imagens) for b in imagens[i + 1:])


def test_cada_icone_da_barra_aciona_o_que_o_botao_de_texto_acionava(painel_de_edicao, monkeypatch):
    painel = painel_de_edicao
    chamadas = []
    for nome in ("new_project", "open_project", "save_project", "_toggle_collapsed", "_toggle_fullscreen", "_open_export_dialog"):
        monkeypatch.setattr(painel, nome, lambda *a, _n=nome, **k: chamadas.append(_n))
    for botao in (painel._new_btn, painel._open_btn, painel._save_btn, painel._collapse, painel._fullscreen_button,
                  painel._export_button):
        botao.setEnabled(True)
        botao.click()
    assert chamadas == ["new_project", "open_project", "save_project", "_toggle_collapsed", "_toggle_fullscreen",
                        "_open_export_dialog"]


def test_salvar_como_mora_no_botao_direito_do_salvar(painel_de_edicao, monkeypatch):
    painel = painel_de_edicao
    menu = painel.build_save_menu()
    assert [a.text() for a in menu.actions()] == [strings.EDIT_SAVE_BUTTON, strings.EDIT_SAVE_AS_BUTTON]
    chamadas = []
    monkeypatch.setattr(painel, "save_project", lambda *a: chamadas.append("salvar"))
    monkeypatch.setattr(painel, "save_project_as", lambda *a: chamadas.append("salvar como"))
    for acao in painel.build_save_menu().actions():
        acao.trigger()
    assert chamadas == ["salvar", "salvar como"]
    # O botão direito é o que abre o menu: sem a política, o pedido nunca chegava a ``_show_save_menu``.
    assert painel._save_btn.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


def test_os_icones_da_barra_acompanham_o_tema(painel_de_edicao, monkeypatch):
    # Troca só o que o painel lê (``atual``) e chama o ``_retheme`` dele: aplicar um tema no ``QApplication`` deixaria
    # estilo e paleta trocados para os testes de geometria seguintes, que medem com o que estava antes.
    from videomanager.presentation.qt.panels import edit_panel
    painel = painel_de_edicao
    botoes = (painel._new_btn, painel._open_btn, painel._save_btn, painel._collapse, painel._fullscreen_button)
    modo, paleta = edit_panel.atual()
    antes = [_imagem(b) for b in botoes]
    monkeypatch.setattr(edit_panel, "atual", lambda: ("light" if modo == "dark" else "dark", paleta))
    painel._retheme()
    depois = [_imagem(b) for b in botoes]
    assert all(a != d for a, d in zip(antes, depois))


def test_retrair_a_previa_troca_o_icone_e_o_nome_e_mantem_a_dica(painel_de_edicao):
    painel = painel_de_edicao
    dica, aberto = painel._collapse.toolTip(), _imagem(painel._collapse)
    assert painel._collapse.accessibleName() == strings.EDIT_COLLAPSE
    painel._toggle_collapsed()
    assert painel._collapse.accessibleName() == strings.EDIT_EXPAND
    assert _imagem(painel._collapse) != aberto and painel._collapse.toolTip() == dica
    painel._toggle_collapsed()
    assert painel._collapse.accessibleName() == strings.EDIT_COLLAPSE and _imagem(painel._collapse) == aberto


def test_a_marca_de_nao_salvo_so_aparece_com_alteracao_e_o_nome_fica_sem_prefixo(painel_de_edicao):
    painel = painel_de_edicao
    assert painel._project_label.text() == strings.EDIT_UNTITLED
    assert not painel._dirty_mark.isVisibleTo(painel)
    painel._apply(painel._project.with_track(TrackKind.VIDEO))
    painel._update_project_label()
    assert painel._dirty_mark.isVisibleTo(painel)
    textos = [w.text() for w in painel._dirty_mark.findChildren(type(painel._project_label))]
    assert strings.EDIT_UNSAVED in textos


# -- seletor de tela -------------------------------------------------------------------------------------------

def test_os_controles_de_tela_continuam_os_mesmos_dentro_do_painel_do_seletor(painel_de_edicao):
    painel = painel_de_edicao
    popup = painel._canvas_popup
    for controle in (painel._aspect_box, painel._canvas_box, painel._slideshow_button):
        assert popup.isAncestorOf(controle)
    assert painel._canvas_selector.popup is popup and popup.windowType() == Qt.WindowType.Popup


def test_o_resumo_diz_a_tela_do_projeto_e_se_ela_e_automatica(painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    projeto = painel._project
    esperado = strings.EDIT_CANVAS_SUMMARY_AUTO.format(
        aspect="16:9", size=strings.EDIT_CANVAS_SIZE.format(width=projeto.width, height=projeto.height),
        rate=strings.EDIT_CANVAS_FPS.format(fps="30"))
    assert painel._canvas_selector.summary() == esperado
    # Escolher uma proporção troca "automática" por tela fixa, e o tamanho do resumo é o do projeto de agora.
    caixa = painel._aspect_box
    caixa.setCurrentIndex(next(i for i in range(caixa.count()) if caixa.itemData(i) == "4:3"))
    resumo = painel._canvas_selector.summary()
    assert resumo.startswith(strings.EDIT_CANVAS_SUMMARY.split("{")[0]) and "4:3" in resumo
    assert strings.EDIT_CANVAS_SUMMARY_AUTO.split("{")[0] not in resumo
    assert strings.EDIT_CANVAS_SIZE.format(width=painel._project.width, height=painel._project.height) in resumo
    caixa.setCurrentIndex(0)
    assert painel._canvas_selector.summary().startswith(strings.EDIT_CANVAS_SUMMARY_AUTO.split("{")[0])


def test_o_resumo_troca_de_idioma(painel_de_edicao, idioma_portugues):
    painel = painel_de_edicao
    assert painel._canvas_selector.summary().startswith("Tela automática")
    apply_language(i18n.ENGLISH)
    assert painel._canvas_selector.summary().startswith("Automatic canvas")


def test_escondido_o_texto_fica_inteiro_e_ao_aparecer_se_ajusta_a_largura(painel_de_edicao):
    # A aba Editar escondida não refaz layout. Cortar o texto novo com a largura velha (o que acontecia na troca de
    # idioma com outra aba à frente) deixava "…30 f…" no botão até alguém olhar de novo — e a janela aberta já no
    # idioma novo mostrava o texto inteiro (achado pelo ``validate_language``, nos modos pseudo e inglês).
    painel = painel_de_edicao
    seletor = painel._canvas_selector
    seletor.setFixedWidth(150)
    seletor.set_summary("Tela · 4:3 · 1440 × 1080 · 29,97 fps · um texto bem mais longo do que cabe em 150 px")
    assert not seletor.isVisible() and seletor.text() == seletor.summary()
    painel.show()
    try:
        for _ in range(5):
            QApplication.processEvents()
        assert seletor.text().endswith("…") and seletor.text() != seletor.summary()
    finally:
        painel.hide()


def test_sem_largura_o_texto_se_corta_mas_o_resumo_e_a_dica_ficam_inteiros(painel_de_edicao):
    painel = painel_de_edicao
    seletor = painel._canvas_selector
    # Widget escondido só recebe o ``resizeEvent`` ao aparecer: na janela de verdade ele sempre está à vista.
    painel.show()
    for _ in range(3):
        QApplication.processEvents()
    try:
        seletor.setFixedWidth(seletor.sizeHint().width())
        assert seletor.text() == seletor.summary()
        assert seletor.minimumSizeHint().width() < seletor.sizeHint().width()
        seletor.setFixedWidth(seletor.minimumSizeHint().width())
        assert seletor.text().endswith("…") and seletor.text() != seletor.summary()
        assert seletor.toolTip() == seletor.summary()
    finally:
        painel.hide()


def test_o_clique_abre_o_painel_alinhado_a_borda_direita_e_abaixo_do_botao(painel_de_edicao):
    painel = painel_de_edicao
    painel.resize(1200, 700)
    painel.show()
    for _ in range(5):
        QApplication.processEvents()
    seletor, popup = painel._canvas_selector, painel._canvas_popup
    try:
        QTest.mouseClick(seletor, Qt.MouseButton.LeftButton)
        assert popup.isVisible()
        canto = seletor.mapToGlobal(QPoint(seletor.width(), seletor.height()))
        # Tolerância de 3 px: o plugin offscreen soma ao popup a margem de janela (2 px nos dois eixos).
        assert abs(popup.geometry().right() + 1 - canto.x()) <= 3
        assert popup.geometry().top() >= canto.y()
        assert popup.width() >= seletor.width()
    finally:
        popup.hide()
        painel.hide()
