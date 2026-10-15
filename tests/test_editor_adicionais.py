"""Colunas de adicionais como no protótipo: Texto, Filtros e Transições com margem de 14 px, campos em caixas de 34 px,
atalhos de tamanho que marcam o que vale, amostras com o anel do acento e a lista de opções de 36 px.

O que uma troca de desenho perde em silêncio: o atalho de tamanho que não acompanha o campo, o anel que fica na amostra
errada (ou em nenhuma depois de uma cor própria), a opção que muda de altura ao ser marcada, a coluna que deixa de nascer
com a largura do protótipo. Os testes medem a geometria e os pixels, com o tema aplicado como no aplicativo real.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.presentation.qt import strings, theme
from videomanager.presentation.qt.panels.field_box import FieldBox, WrapCheck
from videomanager.presentation.qt.panels.swatch import Swatch


def _mostrar(painel, aba: int, largura: int = 1900):
    painel.resize(largura, 1000)
    painel.show()
    painel._extras_tabs.setCurrentIndex(aba)
    for _ in range(6):
        QApplication.processEvents()
    return painel._extras_tabs.widget(aba).widget()


def _origem(filho, pagina):
    return filho.mapTo(pagina, filho.rect().topLeft())


def test_as_colunas_nascem_com_a_largura_do_prototipo(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    _mostrar(painel, 0)
    assert painel._top_splitter.sizes()[:2] == [252, 304]


def test_as_tres_abas_tem_margem_de_14_px_e_10_entre_os_grupos(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    for aba, primeiro in ((0, painel._text_input), (1, painel._filter_buttons[0]), (2, painel._trans_buttons[0])):
        pagina = _mostrar(painel, aba)
        assert _origem(primeiro, pagina).x() == 14, aba
        assert primeiro.width() == pagina.width() - 28, aba
    pagina = _mostrar(painel, 1)
    topo = _origem(painel._filter_buttons[0], pagina).y()
    assert topo >= 14 + 10, "o título da escolha fica entre a margem de cima e a primeira opção"


def test_a_aba_texto_tem_campos_de_34_px_e_o_seletor_de_fonte_sem_emoji(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    pagina = _mostrar(painel, 0)
    assert painel._text_input.height() == 34 and painel._text_input.property("role") == "field"
    botao = painel._font_selector._toggle_btn
    assert botao.height() == 34 and botao.property("role") == "select"
    assert botao.text() == "Sans Serif" and botao.text().isascii()
    # A seta gira quando a lista abre, e o texto continua sendo só o nome da fonte.
    QTest.mouseClick(botao, Qt.MouseButton.LeftButton)
    assert botao._open and botao.text() == "Sans Serif"
    QTest.mouseClick(botao, Qt.MouseButton.LeftButton)
    assert not botao._open
    assert _origem(botao, pagina).y() - (_origem(painel._text_input, pagina).y() + 34) == 10


def test_o_tamanho_da_fonte_tem_menos_valor_e_mais_na_mesma_linha_de_34_px(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    pagina = _mostrar(painel, 0)
    menos = next(b for b in pagina.findChildren(QPushButton) if b.toolTip() == strings.EDIT_FONT_SMALLER)
    mais = next(b for b in pagina.findChildren(QPushButton) if b.toolTip() == strings.EDIT_FONT_LARGER)
    caixa = painel._font_size_spin.parentWidget()
    assert isinstance(caixa, FieldBox) and caixa.height() == 34
    assert (menos.width(), menos.height(), mais.width(), mais.height()) == (34, 34, 34, 34)
    assert _origem(caixa, pagina).x() - (_origem(menos, pagina).x() + 34) == 6
    assert _origem(mais, pagina).x() - (_origem(caixa, pagina).x() + caixa.width()) == 6
    assert painel._font_size_spin.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert painel._font_size_spin.accessibleName() == strings.EDIT_FONT_SIZE
    # Sem o rótulo "Tamanho:" na tela: a caixa diz "48 pt".
    assert strings.EDIT_FONT_SIZE not in [f.text() for f in pagina.findChildren(type(painel._pool_count_label))]


def test_o_atalho_de_tamanho_que_vale_agora_fica_marcado(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    pagina = _mostrar(painel, 0)
    marcados = lambda: [t for t, b in painel._size_presets if b.property("active") == "true"]
    assert marcados() == [48]
    painel._font_size_spin.setValue(30)
    assert marcados() == []
    botao = dict(painel._size_presets)[18]
    QTest.mouseClick(botao, Qt.MouseButton.LeftButton)
    assert painel._font_size_spin.value() == 18 and marcados() == [18]
    larguras = [b.width() for _, b in painel._size_presets]
    assert max(larguras) - min(larguras) <= 1 and all(b.height() == 28 for _, b in painel._size_presets)
    assert _origem(painel._size_presets[0][1], pagina).x() == 14
    right = _origem(painel._size_presets[-1][1], pagina).x() + painel._size_presets[-1][1].width()
    assert right == pagina.width() - 14
    # O marcado leva o tom do segmento marcado, com o anel; o outro, o fundo elevado.
    cores = theme.papeis("dark", "grafite")
    derivado = theme.derivadas(cores)
    painel._font_size_spin.setValue(24)
    QApplication.processEvents()
    imagem = dict(painel._size_presets)[24].grab().toImage()
    assert imagem.pixelColor(imagem.width() // 2, 4).name().lower() == derivado["seg_on"].lower()
    imagem = dict(painel._size_presets)[36].grab().toImage()
    assert imagem.pixelColor(imagem.width() // 2, 4).name().lower() == cores["raised"].lower()


def test_negrito_e_italico_sao_quadrados_de_34_px_que_ficam_marcados(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    _mostrar(painel, 0)
    for botao in (painel._bold_btn, painel._italic_btn):
        assert (botao.width(), botao.height()) == (34, 34) and botao.isCheckable()
        assert botao.property("role") == "tile"
    assert painel._bold_btn.font().bold() and painel._italic_btn.font().italic()
    QTest.mouseClick(painel._bold_btn, Qt.MouseButton.LeftButton)
    assert painel._bold_btn.isChecked()


def test_as_amostras_de_cor_tem_passo_de_32_e_o_anel_do_acento_na_escolhida(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    pagina = _mostrar(painel, 0)
    cores = theme.papeis("dark", "grafite")
    amostras = painel._text_swatches._swatches
    assert [s.color() for s in amostras][:2] == ["#ffffff", "#ffeb3b"]
    xs = [_origem(s, pagina).x() for s in amostras]
    assert xs[0] == 14, "a fileira começa na margem; o ar do anel de 3 px fica dentro da primeira amostra"
    assert all(b - a == 32 for a, b in zip(xs, xs[1:])), "passo de 32 px: 24 de cor, 3 de ar de cada lado e 2 de vão"
    assert all(isinstance(s, Swatch) and (s.width(), s.height()) == (30, 30) for s in amostras)
    # A branca é a escolhida de nascença: o anel do acento fica a 2 px da cor, e as outras não o têm.
    assert [s.selected() for s in amostras] == [True, False, False, False, False, False]
    anel = amostras[0].grab().toImage().pixelColor(amostras[0].width() // 2, 1).name().lower()
    assert anel == cores["accent"].lower()
    assert amostras[1].grab().toImage().pixelColor(amostras[1].width() // 2, 1).name().lower() != cores["accent"].lower()
    # A cor tem 24 px no meio do ar de 3.
    meio = amostras[1].grab().toImage()
    assert meio.pixelColor(15, 15).name().lower() == "#ffeb3b" and meio.pixelColor(1, 15).name().lower() != "#ffeb3b"
    # Escolher outra move o anel e muda a cor do texto; uma cor fora da paleta tira o anel de todas.
    QTest.mouseClick(amostras[2], Qt.MouseButton.LeftButton)
    assert painel._text_color == "#f44336" and [s.selected() for s in amostras] == [False, False, True, False, False, False]
    assert painel._color_indicator.color() == "#f44336"
    painel._set_text_color("#123456")
    assert not any(s.selected() for s in amostras) and painel._color_indicator.color() == "#123456"


def test_o_contorno_tem_caixa_de_34_px_amostra_e_paleta_desligadas_ate_marcar(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    pagina = _mostrar(painel, 0)
    assert isinstance(painel._stroke_checkbox, WrapCheck) and painel._stroke_checkbox.text() == strings.EDIT_STROKE
    caixa = painel._stroke_spin.parentWidget()
    assert caixa.height() == 34 and not painel._stroke_spin.isEnabled() and not painel._stroke_color_indicator.isEnabled()
    assert (painel._stroke_color_indicator.width(), painel._stroke_color_indicator.height()) == (34, 34)
    assert painel._stroke_color_indicator.color() == "#000000"
    painel._stroke_checkbox.setChecked(True)
    assert painel._stroke_spin.isEnabled() and painel._stroke_color_indicator.isEnabled()
    # O fio entre o texto e o contorno, e a paleta do contorno com a preta escolhida.
    from PySide6.QtWidgets import QFrame
    fios = [f for f in pagina.findChildren(QFrame) if f.property("role") == "hline"]
    assert len(fios) == 1 and fios[0].height() == 1
    assert [s.selected() for s in painel._stroke_swatches._swatches][:2] == [True, False]


def test_o_botao_de_acao_das_tres_abas_tem_44_px_e_fica_no_pe(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    for aba, botao in ((0, painel._insert_text_btn), (1, painel._apply_filter_btn), (2, painel._apply_trans_btn)):
        pagina = _mostrar(painel, aba)
        assert botao.property("emphasis") == "large" and botao.height() == 44, aba
        assert _origem(botao, pagina).y() + 44 + 14 <= pagina.height(), aba
        assert botao.width() == pagina.width() - 28, aba


def test_as_opcoes_de_filtro_e_transicao_tem_36_px_com_10_entre_elas_e_nao_mudam_ao_marcar(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    cores = theme.papeis("dark", "grafite")
    derivado = theme.derivadas(cores)
    for aba, botoes, escolher in ((1, painel._filter_buttons, painel._select_filter),
                                   (2, painel._trans_buttons, painel._select_transition)):
        pagina = _mostrar(painel, aba)
        assert {b.height() for b in botoes} == {36}, aba
        ys = [_origem(b, pagina).y() for b in botoes]
        assert all(b - a == 46 for a, b in zip(ys, ys[1:])), aba
        marcado = botoes[1]
        escolher(painel._filter_specs[1] if aba == 1 else painel._trans_specs[1])
        QApplication.processEvents()
        assert marcado.isChecked() and {b.height() for b in botoes} == {36}
        imagem = marcado.grab().toImage()
        assert imagem.pixelColor(imagem.width() // 2, 8).name().lower() == derivado["seg_on"].lower()
        assert imagem.pixelColor(imagem.width() // 2, 0).name().lower() == derivado["seg_ring"].lower()
        outra = botoes[3].grab().toImage()
        assert outra.pixelColor(outra.width() // 2, 8).name().lower() == cores["raised"].lower()


def test_a_duracao_de_filtro_e_transicao_e_uma_caixa_de_110_px_encostada_a_direita(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    for aba, spin in ((1, painel._filter_dur), (2, painel._trans_dur)):
        pagina = _mostrar(painel, aba)
        caixa = spin.parentWidget()
        assert isinstance(caixa, FieldBox) and (caixa.width(), caixa.height()) == (110, 34)
        assert _origem(caixa, pagina).x() + 110 == pagina.width() - 14
        assert spin.accessibleName() == strings.EDIT_EXTRA_DURATION and spin.suffix() == " s"


def test_o_titulo_da_escolha_e_o_aviso_da_aba_transicoes_seguem_o_protótipo(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    pagina = _mostrar(painel, 2)
    from PySide6.QtWidgets import QLabel
    rotulos = {r.property("role"): r for r in pagina.findChildren(QLabel) if r.property("role") in ("heading", "hint")}
    assert rotulos["heading"].text() == strings.EDIT_CHOOSE_TRANSITION and not rotulos["heading"].text().endswith(":")
    assert rotulos["hint"].text() == strings.EDIT_TRANSITION_TRACK_HINT and rotulos["hint"].wordWrap()
    assert isinstance(painel._trans_affect_additionals, WrapCheck)
    assert rotulos["hint"].height() >= 3 * rotulos["hint"].fontMetrics().height() * 0.9, "o aviso quebra em linhas"


def test_a_aba_mais_alta_rola_em_vez_de_empurrar_a_linha_do_tempo(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    _mostrar(painel, 2)
    pagina = painel._extras_tabs.widget(2)
    # Oito opções de 36 px pedem mais de 471 px, mas a coluna só pede 471: o resto está na barra de rolagem, e a divisão
    # vertical (que reparte pelo que as abas pedem) deixa para a linha do tempo a altura que ela tinha.
    assert pagina.widget().sizeHint().height() > 471
    assert pagina.sizeHint().height() == 471
    assert painel._extras_box.sizeHint().height() <= 471 + painel._extras_tabs.tabBar().height() + 8
    # E nada fica fora de alcance: no fim da rolagem, o botão de ação está inteiro à vista.
    barra = pagina.verticalScrollBar()
    barra.setValue(barra.maximum())
    QApplication.processEvents()
    botao = painel._apply_trans_btn
    base = botao.mapTo(pagina.viewport(), botao.rect().bottomLeft()).y()
    assert base <= pagina.viewport().height()


def _texto(clip_id: int, inicio: float, **estilo) -> Clip:
    return Clip(MediaRef(Path(f"Texto_{clip_id}"), MediaKind.IMAGE, duration=3.0), inicio, 3.0, clip_id=clip_id,
                overlay_type="text", text_content=f"Texto {clip_id}", **estilo)


def _pintado(amostra) -> str:
    """A cor que a amostra de fato mostra: o pixel do meio dela, e não o que o código acha que pintou."""
    imagem = amostra.grab().toImage()
    return imagem.pixelColor(imagem.width() // 2, imagem.height() // 2).name().lower()


def test_selecionar_um_bloco_de_texto_leva_as_cores_dele_as_amostras(tema_do_app, painel_de_edicao):
    """As amostras de cor do texto e do contorno acompanham o bloco selecionado (``REG-004``).

    A amostra é pintada à mão e ignora QSS: a carga do bloco que ainda mandava ``setStyleSheet`` a deixava na cor do
    bloco anterior, com o dado certo e a tela errada. Os testes de clique só conferiam o caminho em que o usuário escolhe.
    """
    painel = painel_de_edicao
    _mostrar(painel, 0)
    vermelho = _texto(901, 0.0, text_color="#f44336", stroke_width=6, stroke_color="#0284c7")
    amarelo = _texto(902, 3.0, text_color="#ffeb3b")
    projeto = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(vermelho, amarelo)),), width=1280, height=720, fps=30.0)
    painel.install_project(projeto, None, [], {})
    for _ in range(4):
        QApplication.processEvents()

    painel._timeline.select(901)
    QApplication.processEvents()
    assert painel._color_indicator.color() == "#f44336" and _pintado(painel._color_indicator) == "#f44336"
    assert painel._stroke_color_indicator.color() == "#0284c7" and _pintado(painel._stroke_color_indicator) == "#0284c7"
    # A fileira de amostras rápidas marca a que tem a cor do bloco: a terceira do texto e a última do contorno.
    assert [s.selected() for s in painel._text_swatches._swatches] == [False, False, True, False, False, False]
    assert [s.selected() for s in painel._stroke_swatches._swatches] == [False, False, False, False, False, True]

    painel._timeline.select(902)
    QApplication.processEvents()
    assert painel._color_indicator.color() == "#ffeb3b" and _pintado(painel._color_indicator) == "#ffeb3b"
    assert painel._stroke_color_indicator.color() == "#000000"
    assert [s.selected() for s in painel._text_swatches._swatches] == [False, True, False, False, False, False]
    assert [s.selected() for s in painel._stroke_swatches._swatches][:2] == [True, False]
    # Carregar o bloco é leitura: nada disso vira edição nem sobra uma marca de "não salvo".
    assert not painel.has_unsaved_changes
