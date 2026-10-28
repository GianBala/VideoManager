"""Aba Propriedades como no protótipo: campos em caixas, controles deslizantes ligados aos campos, atalhos de rotação
marcados, fio entre as seções e texto que quebra linha.

O que uma troca de desenho perde em silêncio: o rótulo que sai de dentro da caixa, o controle deslizante que passa a
escrever no painel por um segundo caminho (e o campo, a mexer duas vezes), o atalho de rotação marcado que não
acompanha o campo, o fio de cima da primeira seção, o texto do checkbox cortado na coluna estreita. Os testes medem
a geometria com o tema aplicado como no aplicativo real, e o comportamento pelos sinais que o painel recebe.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from videomanager.domain import i18n
from videomanager.presentation.qt import strings, theme
from videomanager.presentation.qt.i18n import apply_language
from videomanager.presentation.qt.panels.field_box import FieldBox, WrapCheck


def _abrir(painel, bloco, largura: int = 1500):
    painel.resize(largura, 1100)
    painel._timeline.select(bloco.clip_id)
    painel._open_properties_tab(bloco.clip_id)
    painel._properties_widget.show()
    painel.show()
    for _ in range(6):
        QApplication.processEvents()
    return painel._properties_widget


def _caixa(widget, spin) -> FieldBox:
    return spin.parentWidget()


def _origem(filho, widget):
    return filho.mapTo(widget, filho.rect().topLeft())


@pytest.fixture
def propriedades(tema_do_app, painel_de_edicao, blocos_de_edicao):
    return _abrir(painel_de_edicao, blocos_de_edicao["video com som"]), painel_de_edicao, blocos_de_edicao


def test_o_cabecalho_mostra_o_nome_do_bloco_e_nao_o_nome_da_aba(propriedades):
    widget, _, blocos = propriedades
    assert widget._title_lbl.text() == "a.mp4"
    assert widget._title_lbl.property("role") == "section-title"
    assert widget._lbl_clip_type.property("role") == "hint"


def test_as_coordenadas_sao_caixas_de_34_px_com_rotulo_dentro_e_unidade_apagada(propriedades):
    widget, _, _ = propriedades
    caixas = [_caixa(widget, s) for s in (widget._spin_x, widget._spin_y, widget._spin_w, widget._spin_h)]
    assert all(isinstance(c, FieldBox) and c.height() == 34 for c in caixas)
    assert [c.lead.text() for c in caixas] == ["X", "Y", "L", "A"]
    assert all(c.tail.text() == "px" and c.tail.property("role") == "unit" for c in caixas)
    # Duas colunas iguais com 8 px entre elas, e duas linhas com 9 px.
    x, y, w, h = caixas
    assert abs(x.width() - y.width()) <= 1 and abs(x.width() - w.width()) <= 1
    assert _origem(y, widget).x() - (_origem(x, widget).x() + x.width()) == 8
    assert _origem(w, widget).y() - (_origem(x, widget).y() + x.height()) == 9
    # O rótulo à esquerda, o número encostado na unidade, à direita.
    assert x.lead.x() < widget._spin_x.x() and widget._spin_x.alignment() & Qt.AlignmentFlag.AlignRight
    assert widget._spin_x.x() + widget._spin_x.width() <= x.tail.x()
    # O campo continua sendo um QSpinBox de verdade, sem setinhas nem moldura.
    assert widget._spin_x.buttonSymbols().name == "NoButtons" and not widget._spin_x.hasFrame()
    assert widget._spin_x.accessibleName() == strings.PROP_POS_X


def test_clicar_no_rotulo_da_caixa_leva_o_foco_ao_campo(propriedades):
    widget, painel, _ = propriedades
    QTest.mouseClick(_caixa(widget, widget._spin_y).lead, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert widget._spin_y.lineEdit().hasFocus()


def test_o_anel_de_foco_e_da_caixa_inteira(propriedades, desktop_app):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    widget, _, _ = propriedades
    caixa = _caixa(widget, widget._spin_y)
    cores = theme.papeis("dark", "grafite")
    anel = theme.derivadas(cores)["ring"].lower()
    meio = caixa.height() // 2
    assert caixa.property("focused") == "false"
    assert caixa.grab().toImage().pixelColor(0, meio).name().lower() == cores["raised"].lower()
    # Os eventos vão direto ao campo de dentro: o servidor de janelas do teste não ativa a janela.
    desktop_app.sendEvent(widget._spin_y.lineEdit(), QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
    desktop_app.processEvents()
    assert caixa.property("focused") == "true"
    assert caixa.grab().toImage().pixelColor(0, meio).name().lower() == anel
    desktop_app.sendEvent(widget._spin_y.lineEdit(), QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason))
    desktop_app.processEvents()
    assert caixa.property("focused") == "false"


def test_escala_opacidade_e_rotacao_tem_rotulo_controle_e_caixa_na_mesma_coluna(propriedades):
    widget, _, _ = propriedades
    linhas = [(widget._slider_scale, widget._spin_scale), (widget._slider_opacity, widget._spin_opacity),
              (widget._slider_rot, widget._spin_rot)]
    # O controle começa na coluna do rótulo (84 px) e as caixas de valor encostam na direita, com 62 × 30.
    xs = {_origem(s, widget).x() for s, _ in linhas}
    assert len(xs) == 1
    esquerda = _origem(widget._chk_lock_ratio, widget).x()
    assert xs == {esquerda + 84}
    direita = _origem(widget._slider_scale.parentWidget(), widget).x() + widget._slider_scale.parentWidget().width()
    for slider, spin in linhas:
        caixa = _caixa(widget, spin)
        assert (caixa.width(), caixa.height()) == (62, 30)
        assert _origem(caixa, widget).x() + caixa.width() == direita
        assert _origem(slider, widget).x() + slider.width() + 10 <= _origem(caixa, widget).x() + 1
    ys = [_origem(_caixa(widget, spin), widget).y() for _, spin in linhas]
    assert ys[1] - ys[0] == ys[2] - ys[1] == 39


def test_o_controle_da_escala_move_o_campo_e_o_painel_recebe_uma_vez_so(propriedades):
    widget, _, blocos = propriedades
    recebidos = []
    widget.property_changed.connect(lambda cid, mudancas: recebidos.append(mudancas))
    widget._slider_scale.setValue(150)
    assert widget._spin_scale.value() == pytest.approx(1.5)
    assert len(recebidos) == 1 and recebidos[0]["scale"] == pytest.approx(1.5)
    # O campo move o controle sem devolver o valor ao painel por um segundo caminho.
    recebidos.clear()
    widget._spin_scale.setValue(0.5)
    assert widget._slider_scale.value() == 50 and len(recebidos) == 1


def test_escala_acima_da_faixa_do_controle_fica_no_extremo_e_o_campo_guarda_o_valor(propriedades):
    widget, _, _ = propriedades
    widget._spin_scale.setValue(4.0)
    assert widget._slider_scale.value() == widget._slider_scale.maximum() == 250
    assert widget._spin_scale.value() == pytest.approx(4.0)


def test_o_controle_da_rotacao_vai_de_menos_180_a_180_e_o_campo_guarda_de_0_a_360(propriedades):
    widget, _, _ = propriedades
    assert (widget._slider_rot.minimum(), widget._slider_rot.maximum()) == (-180, 180)
    widget._spin_rot.setValue(270.0)
    assert widget._slider_rot.value() == -90
    widget._spin_rot.setValue(90.0)
    assert widget._slider_rot.value() == 90
    widget._slider_rot.setValue(-90)
    assert widget._spin_rot.value() == pytest.approx(270.0)
    widget._slider_rot.setValue(0)
    assert widget._spin_rot.value() == pytest.approx(0.0)


def test_o_atalho_de_rotacao_que_vale_fica_marcado_e_clicar_gira_o_bloco(propriedades):
    widget, _, _ = propriedades
    marcados = lambda: [int(a) for a, b in widget._rotation_presets if b.isChecked()]
    assert marcados() == [0]
    widget._spin_rot.setValue(90.0)
    assert marcados() == [90]
    widget._spin_rot.setValue(45.0)
    assert marcados() == []
    botao = dict(widget._rotation_presets)[180.0]
    QTest.mouseClick(botao, Qt.MouseButton.LeftButton)
    assert widget._spin_rot.value() == 180.0 and marcados() == [180]
    # Clicar no que já está marcado não o desmarca: quem diz o que vale é o campo.
    QTest.mouseClick(botao, Qt.MouseButton.LeftButton)
    assert marcados() == [180]
    larguras = [b.width() for _, b in widget._rotation_presets]
    assert max(larguras) - min(larguras) <= 1 and all(b.height() == 22 for _, b in widget._rotation_presets)


def test_so_a_primeira_secao_que_aparece_fica_sem_o_fio_de_cima(propriedades):
    widget, painel, blocos = propriedades
    assert widget._transform_group._first and not widget._speed_group._first and not widget._volume_group._first
    # Num bloco de áudio não há Transformação: quem abre a aba passa a ser a Velocidade.
    widget = _abrir(painel, blocos["audio"])
    assert widget._speed_group._first and not widget._volume_group._first and not widget._transform_group._first
    # E o fio é pintado: 15 px abaixo do topo da seção, no tom `raised`, e ausente na primeira.
    imagem = widget.grab().toImage()
    cor = theme.papeis("dark", "grafite")["raised"].lower()
    topo = _origem(widget._volume_group, widget)
    assert imagem.pixelColor(topo.x() + 40, topo.y() + 15).name().lower() == cor
    topo = _origem(widget._speed_group, widget)
    assert imagem.pixelColor(topo.x() + 40, topo.y() + 15).name().lower() != cor


def test_velocidade_e_volume_tem_o_valor_a_esquerda_e_a_faixa_ou_a_unidade_apagada_a_direita(propriedades):
    widget, _, _ = propriedades
    velocidade, volume = _caixa(widget, widget._spin_speed), _caixa(widget, widget._spin_gain)
    assert velocidade.height() == volume.height() == 34
    assert velocidade.tail.text() == strings.PROP_SPEED_RANGE and volume.tail.text() == "dB"
    assert widget._spin_speed.alignment() & Qt.AlignmentFlag.AlignLeft
    assert widget._spin_speed.suffix() == "×" and widget._spin_gain.suffix() == ""
    assert widget._spin_speed.x() < velocidade.tail.x()


def test_quadro_chave_tem_tres_botoes_quadrados_de_30_px_e_o_estado_ao_lado(propriedades):
    widget, _, _ = propriedades
    botoes = (widget._btn_kf_prev, widget._btn_kf_toggle, widget._btn_kf_next)
    assert all((b.width(), b.height()) == (30, 30) and not b.icon().isNull() for b in botoes)
    assert [b.property("role") for b in botoes] == ["tile"] * 3
    assert not widget._btn_kf_prev.isEnabled() and not widget._btn_kf_next.isEnabled()
    assert widget._lbl_kf_status.text() == strings.PROP_KEYFRAMES_NONE
    # Anterior, alternar e próximo lado a lado, com 6 px entre eles.
    xs = [_origem(b, widget).x() for b in botoes]
    assert xs[1] - xs[0] == xs[2] - xs[1] == 36


def test_listas_da_animacao_tem_34_px_e_comecam_na_coluna_do_rotulo(propriedades):
    widget, _, _ = propriedades
    listas = (widget._combo_easing, widget._combo_presets)
    assert all(c.height() == 34 for c in listas)
    assert len({_origem(c, widget).x() for c in listas}) == 1
    assert _origem(widget._combo_easing, widget).x() - _origem(widget._chk_lock_ratio, widget).x() == 92
    rotulos = [f.text() for f in widget._animation_group.body.findChildren(QLabel)]
    assert strings.EDIT_KEYFRAME_EASING in rotulos and strings.PROP_QUICK_EFFECT in rotulos
    assert not any(t.endswith(":") for t in rotulos)


def test_o_texto_do_checkbox_quebra_na_largura_que_tem_e_a_caixa_continua_marcavel(propriedades):
    widget, _, _ = propriedades
    caixa = widget._chk_blur
    assert isinstance(caixa, WrapCheck)
    estreita, larga = caixa.heightForWidth(200), caixa.heightForWidth(900)
    assert estreita >= 2 * larga - 8 and larga <= 24, "na largura de uma linha o texto não ocupa duas"
    antes = widget._blur_group.height()
    assert caixa.isEnabled() and not caixa.isChecked()
    QTest.mouseClick(caixa, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
    assert caixa.isChecked()
    assert widget._blur_group.height() == antes


def test_as_amostras_de_cor_levam_a_cor_do_bloco_e_a_borda_do_tema(propriedades):
    widget, _, _ = propriedades
    assert (widget._btn_chroma_color.width(), widget._btn_chroma_color.height()) == (34, 24)
    assert [(b.width(), b.height()) for b, _ in widget._chroma_presets] == [(24, 24)] * 3
    cores = theme.papeis("dark", "grafite")
    # Desligado o fundo verde, as amostras ficam esmaecidas (os controles dele estão desligados): a cor pura é a de ligado.
    widget._chk_chroma.setChecked(True)
    # A cor é a do bloco e a borda é do tema: nada de folha de estilo com cor escrita à mão.
    for botao, cor in [(widget._btn_chroma_color, "#00ff00"), *[(b, c.lower()) for b, c in widget._chroma_presets]]:
        assert botao.styleSheet() == "" and botao.color().lower() == cor
        imagem = botao.grab().toImage()
        assert imagem.pixelColor(botao.width() // 2, botao.height() // 2).name().lower() == cor
        assert imagem.pixelColor(botao.width() // 2, 0).name().lower() == cores["raised2"].lower()
    widget._set_chroma_color("#112233")
    assert widget._btn_chroma_color.grab().toImage().pixelColor(17, 12).name() == "#112233"


def test_a_troca_de_idioma_refaz_os_rotulos_das_caixas(propriedades):
    widget, _, _ = propriedades
    apply_language(i18n.ENGLISH)
    try:
        assert [_caixa(widget, s).lead.text() for s in (widget._spin_w, widget._spin_h)] == ["W", "H"]
        assert _caixa(widget, widget._spin_speed).tail.text() == "0.1× to 10×"
        assert widget._spin_x.accessibleName() == "Position X"
    finally:
        apply_language(i18n.PORTUGUESE)
    assert _caixa(widget, widget._spin_w).lead.text() == "L"


def test_a_lista_de_transicoes_traz_so_o_nome_e_o_icone_vem_do_desenho(tema_do_app, painel_de_edicao, blocos_de_edicao):
    widget = _abrir(painel_de_edicao, blocos_de_edicao["transicao"])
    combo = widget._combo_trans_type
    nomes = [combo.itemText(i) for i in range(combo.count())]
    # Sem o emoji do catálogo (ele é do identificador do bloco): o ícone é desenhado na cor do tema.
    assert "Dissolve" in nomes and all(nome.isascii() for nome in nomes)
    assert all(not combo.itemIcon(i).isNull() for i in range(combo.count()))
    assert combo.height() == 34 and combo.currentData() == "dissolve"
    # E a duração é uma caixa só do tamanho do número, encostada à direita.
    caixa = _caixa(widget, widget._spin_trans_dur)
    assert caixa.width() == 110 and caixa.height() == 34
    assert _origem(caixa, widget).x() + caixa.width() == _origem(combo, widget).x() + combo.width()


def test_o_bloco_sem_ajustes_diz_isso_com_ar_embaixo_do_cabecalho(tema_do_app, painel_de_edicao, blocos_de_edicao):
    """Hoje todo tipo de bloco tem alguma seção (o filtro ganhou a caixa "Filtro móvel"), então o aviso fica de reserva
    para um tipo sem nenhuma: o teste o mostra à força para conferir o ar embaixo do cabeçalho, que é dele."""
    widget = _abrir(painel_de_edicao, blocos_de_edicao["filtro"])
    aviso = widget._lbl_no_settings
    assert not aviso.isVisibleTo(widget)
    aviso.setVisible(True)
    assert aviso.text() == strings.PROP_NO_SETTINGS
    cabecalho = widget._lbl_clip_type
    vao = _origem(aviso, widget).y() - (_origem(cabecalho, widget).y() + cabecalho.height())
    # O ar é a margem de cima do próprio rótulo, e o texto começa depois dela.
    assert vao + aviso.contentsMargins().top() >= 14


@pytest.mark.parametrize("bloco", ["video com som", "transicao"])
def test_o_conteudo_da_aba_cabe_na_coluna_de_304_px_sem_rolar_para_o_lado(tema_do_app, painel_de_edicao, blocos_de_edicao, bloco):
    widget = _abrir(painel_de_edicao, blocos_de_edicao[bloco])
    # A coluna tem 304 px e a barra de rolagem vertical leva 10: o que a aba pede no mínimo tem de caber nos 294. As
    # listas de animação pediam o tamanho do maior nome ("Efeito Rápido": 261 px) e a seção passava de 350.
    assert widget._container.minimumSizeHint().width() <= 294
    for lista in (widget._combo_easing, widget._combo_presets, widget._combo_trans_type):
        assert lista.minimumSizeHint().width() < 200


def test_o_x_da_aba_propriedades_tem_nome_acessivel_nos_dois_idiomas(tema_do_app, painel_de_edicao, blocos_de_edicao):
    """Era um botão com o texto "✕" e virou só ícone: o nome acessível passa a ser o da dica, e acompanha o idioma.

    O painel nasce solto (fora da janela), então o ``name_controls`` da construção não o alcança.
    """
    from PySide6.QtGui import QAccessible
    painel = painel_de_edicao
    propriedades = _abrir(painel, blocos_de_edicao["video com som"])
    botao = propriedades._btn_close
    nome = lambda: QAccessible.queryAccessibleInterface(botao).text(QAccessible.Text.Name)  # noqa: E731
    assert nome() == strings.PROP_CLOSE_TIP and nome() != ""
    apply_language(i18n.ENGLISH)
    assert nome() == strings.PROP_CLOSE_TIP and botao.toolTip() == strings.PROP_CLOSE_TIP


def test_a_caixa_de_marcar_aceita_o_clique_em_qualquer_ponto_da_linha(desktop_app):
    """O ``QCheckBox`` só responde no indicador e no texto de uma linha: o texto que quebra, a parte vazia à direita e a folga em cima e embaixo ficavam surdas.

    E o clique ignorado subia pelos pais até o filtro do editor, que desmarcava o bloco da linha do tempo — a aba
    continuava aberta nele, e a edição seguinte voltava ao valor antigo na tela.
    """
    caixa = WrapCheck()
    caixa.setText("Preencher as bordas com o bloco desfocado, que quebra em duas linhas na coluna estreita")
    caixa.setFixedWidth(276)
    caixa.setFixedHeight(caixa.heightForWidth(276))
    caixa.show()
    for _ in range(3):
        QApplication.processEvents()
    pontos = {"indicador": QPoint(6, caixa.height() // 2), "meio": QPoint(caixa.width() // 2, caixa.height() // 2),
              "direita": QPoint(caixa.width() - 4, caixa.height() // 2), "topo": QPoint(caixa.width() // 2, 2),
              "base": QPoint(caixa.width() // 2, caixa.height() - 3)}
    for nome, ponto in pontos.items():
        antes = caixa.isChecked()
        QTest.mouseClick(caixa, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
        assert caixa.isChecked() != antes, f"o clique em {nome} ({ponto.x()}, {ponto.y()}) não alternou a caixa"
    caixa.deleteLater()


def test_o_piso_da_coluna_de_adicionais_cobre_as_quatro_abas_em_ingles(tema_do_app, painel_de_edicao, blocos_de_edicao):
    """Com a gaveta de tarefas aberta no editor, a coluna cai ao piso: em inglês as quatro abas pedem 262 px e o piso era 260.

    Em português elas pedem 287 e já passavam do piso; o que o ``validate_language.py --cortes`` cobra é que o inglês não
    corte onde o português não corta, e foi ele que achou os 2 px.
    """
    try:
        apply_language(i18n.ENGLISH)
        _abrir(painel_de_edicao, blocos_de_edicao["texto"])
        barra = painel_de_edicao._extras_tabs.tabBar()
        assert barra.count() == 4
        assert painel_de_edicao._extras_box.minimumWidth() >= barra.sizeHint().width(), (
            f"as abas pedem {barra.sizeHint().width()} px e o piso da coluna é {painel_de_edicao._extras_box.minimumWidth()}")
    finally:
        apply_language(i18n.PORTUGUESE)
