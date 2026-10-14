"""Linha do tempo como no protótipo: cartão, cabeçalhos de 164 px com ladrilho cheio, blocos de corpo escuro com a pastilha do
rótulo, só o escolhido com anel e alças curtas, régua em m:ss, e a barra de ferramentas de ícones.

É só pintura e medidas (a geometria de acerto não foi tocada: os testes de gesto com eventos reais seguem valendo). O que a
pintura nova pode errar sem exceção: a miniatura que sumia por causa de uma largura ímpar pedida ao ffmpeg, a alça que deixava
de ser pegável por ficar curta, o rótulo que passa do bloco, o corpo do bloco na cor errada, a régua com o formato antigo.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QFrame

from test_linha_do_tempo_tipos import _projeto
from videomanager.domain.project import Clip, MediaKind, MediaRef
from videomanager.presentation.qt import strings, theme
from videomanager.presentation.qt.panels import timeline as modulo
from videomanager.presentation.qt.panels.timeline import (
    AUDIO_TRACK_HEIGHT, FILM_CELL_WIDTH, HEADER_WIDTH, THUMB_HEIGHT, TRACK_GAP, Timeline, VIDEO_TRACK_HEIGHT, WAVE_HEIGHT,
    _ruler_label)
from videomanager.presentation.qt.theme import CORPOS_DE_BLOCO, DARK, TIPOS_DE_BLOCO

pytestmark = pytest.mark.usefixtures("desktop_app")


@pytest.fixture
def linha():
    projeto, blocos = _projeto()
    timeline = Timeline(DARK)
    timeline.set_project(projeto)
    timeline.resize(1000, 320)
    timeline.set_view(0, 8)
    return timeline, blocos


def _papeis():
    return theme.papeis(*theme.atual())


def _cor(imagem, x: float, y: float) -> tuple[int, int, int]:
    pixel = imagem.pixelColor(int(x), int(y))
    return pixel.red(), pixel.green(), pixel.blue()


def _perto(a, b, folga: int = 4) -> bool:
    return max(abs(x - y) for x, y in zip(a, b)) <= folga


def test_a_miniatura_pedida_ao_ffmpeg_tem_largura_par_e_a_altura_da_trilha():
    # Largura ímpar (103) fazia o ffmpeg não gerar nada no formato que o Qt lê: as miniaturas sumiam, sem erro nenhum.
    assert FILM_CELL_WIDTH % 2 == 0 and THUMB_HEIGHT % 2 == 0
    assert THUMB_HEIGHT == VIDEO_TRACK_HEIGHT and abs(FILM_CELL_WIDTH / THUMB_HEIGHT - 16 / 9) < 0.04
    assert WAVE_HEIGHT >= 20 and WAVE_HEIGHT < AUDIO_TRACK_HEIGHT


def test_as_medidas_das_trilhas_e_dos_cabecalhos_sao_as_do_prototipo(linha):
    timeline, _ = linha
    assert (HEADER_WIDTH, TRACK_GAP, AUDIO_TRACK_HEIGHT) == (174, 6, 48)
    cabecalho, faixa = timeline._header_rect(0), timeline._lane_rect(0)
    assert cabecalho.width() == 164 and faixa.left() - cabecalho.right() == 10
    # O olho à direita e o mudo ao lado dele, quadrados de 24 px com 6 de vão; a trilha de áudio só tem o mudo.
    olho, mudo = timeline._eye_rect(2), timeline._mute_rect(2)
    assert (olho.width(), olho.height(), mudo.width(), mudo.height()) == (24, 24, 24, 24)
    assert cabecalho.right() - olho.right() == 10 and olho.left() - mudo.right() == 6
    assert timeline._mute_rect(3).right() == olho.right()
    # Sem sobreposição com o nome: o mudo e o olho ficam dentro do cabeçalho.
    assert mudo.left() > cabecalho.left() + 10 + 24 + 10
    # E a trilha seguinte começa 6 px depois, com a altura da espécie.
    assert timeline._lane_rect(1).top() - timeline._lane_rect(0).bottom() == TRACK_GAP
    assert timeline._lane_rect(3).height() == AUDIO_TRACK_HEIGHT


def test_o_cabecalho_e_o_plano_elevado_e_a_linha_do_tempo_nao_pinta_fundo_proprio(linha):
    timeline, _ = linha
    imagem = timeline.grab().toImage()
    papeis = _papeis()
    cab = timeline._header_rect(2)
    assert _perto(_cor(imagem, cab.left() + 4, cab.bottom() - 8), QColor(papeis["raised"]).getRgb()[:3], 3)
    # Fora das trilhas e dos cabeçalhos nada é pintado: o que se vê é o fundo que o ``grab`` dá ao widget transparente (o da
    # paleta do Qt), e no editor é o plano do cartão que aparece ali.
    assert imagem.pixelColor(2, imagem.height() - 2) == timeline.palette().window().color()


@pytest.mark.parametrize("tipo,trilha", [("text", 0), ("filter", 0), ("audio", 3), ("image", 1)])
def test_o_corpo_do_bloco_e_o_tom_escuro_da_especie(linha, tipo, trilha):
    timeline, blocos = linha
    imagem = timeline.grab().toImage()
    caixa = timeline._clip_rect(trilha, blocos[tipo])
    # No canto de baixo à direita: longe da pastilha, dos losangos e do centro (onde o áudio e a foto desenham).
    alvo = QColor(CORPOS_DE_BLOCO[tipo]).getRgb()[:3]
    assert _perto(_cor(imagem, caixa.right() - 14, caixa.bottom() - 6), alvo), tipo


def test_o_rotulo_e_uma_pastilha_escura_com_o_nome_dentro_do_bloco(linha):
    timeline, blocos = linha
    caixa = timeline._clip_rect(0, blocos["text"])
    imagem = timeline.grab().toImage()
    fundo = QColor(CORPOS_DE_BLOCO["text"]).getRgb()[:3]
    tela = QColor(_papeis()["screen"]).getRgb()[:3]
    # Dentro da pastilha (8 px da borda, abaixo da faixa de cor): mais escuro que o corpo, e perto do plano `screen`.
    dentro = _cor(imagem, caixa.left() + 10, caixa.top() + 3 + 5 + 4)
    assert sum(dentro) < sum(fundo) and max(abs(a - b) for a, b in zip(dentro, tela)) < 60
    # Antes dos 8 px de margem e depois do fim da pastilha, é o corpo do bloco.
    assert _perto(_cor(imagem, caixa.left() + 3, caixa.top() + 3 + 5 + 4), fundo)
    assert _perto(_cor(imagem, caixa.right() - 6, caixa.top() + 3 + 5 + 4), fundo)
    # Bloco estreito demais (menos de 36 px) não leva rótulo: a região da pastilha é só o corpo.
    curto = Clip(MediaRef(Path("Texto_y"), MediaKind.IMAGE, duration=0.2), 6.0, 0.2, overlay_type="text", text_content="Z")
    projeto = timeline.project
    trilhas = (replace(projeto.tracks[0], clips=(*projeto.tracks[0].clips, curto)), *projeto.tracks[1:])
    timeline.set_project(replace(projeto, tracks=trilhas))
    imagem = timeline.grab().toImage()
    caixa = timeline._clip_rect(0, curto)
    assert caixa.width() < 36
    assert _perto(_cor(imagem, caixa.left() + 10, caixa.top() + 3 + 5 + 4), fundo)


def test_so_o_bloco_escolhido_leva_o_anel_do_acento_e_alcas_curtas_no_meio(linha):
    timeline, blocos = linha
    clip = blocos["image"]
    caixa = timeline._clip_rect(1, clip)
    acento = QColor(timeline._c["accent"]).getRgb()[:3]
    antes = timeline.grab().toImage()
    meio_y = caixa.center().y()
    assert not _perto(_cor(antes, caixa.left() + 4, meio_y), acento)
    timeline.select(clip.clip_id)
    depois = timeline.grab().toImage()
    # A alça: uma barra de 4 px, a 3 px da borda, centrada na altura, de 28 px.
    assert _perto(_cor(depois, caixa.left() + 3 + 2, meio_y), acento)
    assert _perto(_cor(depois, caixa.right() - 3 - 2, meio_y), acento)
    assert not _perto(_cor(depois, caixa.left() + 3 + 2, meio_y - 20), acento), "a alça é curta: não vai de ponta a ponta"
    # O anel do bloco inteiro, na borda de cima (a faixa de cor da espécie passa por baixo dele).
    assert _perto(_cor(depois, caixa.center().x(), caixa.top()), acento, 40)
    # O gesto continua o mesmo: a zona de arrasto da alça é a altura inteira do bloco.
    for x, esperado in ((caixa.left() + 2, "inicio"), (caixa.right() - 2, "fim")):
        for y in (caixa.top() + 4, caixa.center().y(), caixa.bottom() - 4):
            assert timeline._hit(x, y) == (esperado, 1, clip.clip_id), (x, y)


def test_a_regua_usa_m_ss_com_o_decimo_so_quando_o_passo_e_menor_que_um_segundo():
    assert _ruler_label(0.0, 1) == "0:00" and _ruler_label(75.0, 15) == "1:15"
    assert _ruler_label(0.5, 0.5) == "0:00,5" and _ruler_label(3.5, 0.5) == "0:03,5" and _ruler_label(0.1, 0.1) == "0:00,1"
    assert _ruler_label(3600.0, 600) == "1:00:00" and _ruler_label(3661.0, 1) == "1:01:01"
    assert _ruler_label(59.99, 1) == "0:59"


def test_as_cores_das_especies_sao_as_medidas_nas_faixas_do_prototipo():
    assert TIPOS_DE_BLOCO["video"] == "#3b79e6" and TIPOS_DE_BLOCO["audio"] == "#2fa37a"
    assert TIPOS_DE_BLOCO["text"] == "#8b5cf6" and TIPOS_DE_BLOCO["filter"] == "#6b78f0"


def test_os_corpos_dos_blocos_sao_os_tons_medidos_no_prototipo():
    # Absolutos, medidos em editor.png (texto, filtro, áudio e transição); o corpo do vídeo só aparece sob a miniatura e o
    # da imagem é o plano escuro do protótipo.
    assert CORPOS_DE_BLOCO["text"] == "#33266b" and CORPOS_DE_BLOCO["filter"] == "#212b69"
    assert CORPOS_DE_BLOCO["audio"] == "#14382f" and CORPOS_DE_BLOCO["transition"] == "#d48722"


def test_a_cabeca_da_agulha_e_um_triangulo_e_o_corpo_da_transicao_e_o_unico_claro(linha):
    timeline, blocos = linha
    timeline.set_position(1.0)
    imagem = timeline.grab().toImage()
    x = timeline._x_of(1.0)
    erro = QColor(timeline._c["error"]).getRgb()[:3]
    topo = modulo.RULER_HEIGHT - 15
    # Largo em cima (a ponta do triângulo) e fino embaixo: a 3 px do eixo, o pixel é da cor da agulha na altura de cima.
    assert _perto(_cor(imagem, x - 4, topo + 2), erro, 30) and not _perto(_cor(imagem, x - 4, topo + 8), erro, 30)
    claro = sum(QColor(CORPOS_DE_BLOCO["transition"]).getRgb()[:3])
    assert all(claro > sum(QColor(c).getRgb()[:3]) for t, c in CORPOS_DE_BLOCO.items() if t != "transition")
    assert set(CORPOS_DE_BLOCO) == set(TIPOS_DE_BLOCO)


def test_a_barra_de_ferramentas_e_de_icones_com_a_pastilha_do_bloco_escolhido(tema_do_app, painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    painel.resize(1700, 1000)
    painel.show()
    for _ in range(5):
        QApplication.processEvents()
    for botao in (painel._undo, painel._redo, painel._split_button, painel._trim_left_button, painel._trim_right_button,
                  painel._delete_button, painel._zoom_out_button, painel._zoom_in_button):
        assert botao.property("role") == "tool" and (botao.width(), botao.height()) == (36, 36), botao.toolTip()
        assert botao.text() == "" and not botao.icon().isNull() and botao.accessibleName()
    # Um fio entre o grupo de desfazer e o das ferramentas de corte.
    fios = [f for f in painel._timeline_box.findChildren(QFrame) if f.property("role") == "divider"]
    assert len(fios) == 1 and (fios[0].width(), fios[0].height()) == (1, 22)
    # "Ver tudo" e as pastilhas de volume e velocidade levam ícone; os botões de acrescentar trilha ficam sem fundo.
    for botao in (painel._fit_button, painel._volume_btn, painel._speed_btn):
        assert not botao.icon().isNull(), botao.text()
    assert painel._fit_button.property("role") == "btn" and painel._volume_btn.property("role") == "chip-btn"
    for botao in (painel._add_video_button, painel._add_audio_button, painel._add_additional_button):
        assert botao.property("role") == "ghost"
    # Sem bloco, o texto discreto; com bloco, a pastilha do acento com o ícone da espécie.
    assert painel._clip_chip.property("active") == "false" and not painel._clip_icon.isVisibleTo(painel._clip_chip)
    painel._timeline.select(blocos_de_edicao["audio"].clip_id)
    QApplication.processEvents()
    assert painel._clip_chip.property("active") == "true" and painel._clip_icon.isVisibleTo(painel._clip_chip)
    assert not painel._clip_icon.pixmap().isNull()
    painel._timeline.select(-1)
    QApplication.processEvents()
    assert painel._clip_chip.property("active") == "false" and not painel._clip_icon.isVisibleTo(painel._clip_chip)


def test_a_linha_do_tempo_e_um_cartao_com_margem_de_14(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    caixa = painel._timeline_box
    assert caixa.property("role") == "pane"
    margens = caixa.layout().contentsMargins()
    assert (margens.left(), margens.top(), margens.right(), margens.bottom()) == (14, 12, 14, 8)


# -- zoom -----------------------------------------------------------------------------------------------------

def test_a_fracao_do_zoom_e_logaritmica_vai_de_zero_na_janela_mais_aberta_a_um_na_mais_fechada(linha):
    timeline, _ = linha
    largest = timeline._max_span
    timeline.set_zoom_fraction(0.0)
    assert timeline.view_span == pytest.approx(largest) and timeline.zoom_fraction() == pytest.approx(0.0, abs=1e-6)
    timeline.set_zoom_fraction(1.0)
    assert timeline.view_span == pytest.approx(modulo._MIN_VIEW) and timeline.zoom_fraction() == pytest.approx(1.0, abs=1e-6)
    # Cada passo multiplica a janela pelo mesmo fator: a do meio é a média geométrica das duas pontas.
    timeline.set_zoom_fraction(0.5)
    assert timeline.view_span == pytest.approx((largest * modulo._MIN_VIEW) ** 0.5, rel=1e-3)
    espans = []
    for passo in range(0, 11):
        timeline.set_zoom_fraction(passo / 10)
        espans.append(timeline.view_span)
    assert espans == sorted(espans, reverse=True)


def test_o_zoom_pelo_controle_mantem_o_cursor_no_mesmo_lugar_da_tela(linha):
    timeline, _ = linha
    timeline.set_view(0.0, 8.0)
    timeline.set_position(3.0)
    antes = timeline._x_of(3.0)
    timeline.set_zoom_fraction(0.8, anchor=3.0)
    assert abs(timeline._x_of(3.0) - antes) < 1.0
    assert timeline.view_span < 8.0


def test_o_controle_de_zoom_fica_entre_menos_e_mais_e_acompanha_a_janela(tema_do_app, painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    painel.resize(1700, 1000)
    painel.show()
    for _ in range(5):
        QApplication.processEvents()
    barra = painel._zoom_slider
    assert barra.width() == 110 and barra.toolTip() == strings.EDIT_ZOOM_SLIDER and barra.accessibleName()
    x = lambda w: w.mapTo(painel, w.rect().topLeft()).x()
    assert x(painel._zoom_out_button) < x(barra) < x(painel._zoom_in_button)
    # Ver tudo, aproximar pelo botão e pela roda: o controle vai junto, sem que ele mande de volta.
    painel._timeline.fit()
    fit = barra.value()
    assert fit == round(painel._timeline.zoom_fraction() * 1000)
    painel._zoom_in_button.click()
    assert barra.value() > fit and barra.value() == round(painel._timeline.zoom_fraction() * 1000)
    painel._zoom_out_button.click()
    painel._zoom_out_button.click()
    assert barra.value() < fit
    # E arrastar o controle muda a janela: a mais fechada mostra o piso de 0,4 s; a mais aberta, a maior possível.
    barra.setValue(1000)
    assert painel._timeline.view_span == pytest.approx(modulo._MIN_VIEW, rel=1e-3)
    barra.setValue(0)
    assert painel._timeline.view_span == pytest.approx(painel._timeline._max_span, rel=1e-3)
    assert barra.value() == 0


def test_o_controle_de_zoom_ao_acompanhar_a_janela_nao_a_move_de_volta(tema_do_app, painel_de_edicao, blocos_de_edicao, monkeypatch):
    # Se o ajuste do controle chegasse à linha do tempo, o arredondamento a cada passo (1/1000) faria a janela derivar
    # sozinha a cada toque na roda ou no botão: o que o usuário pediu não é o que ele recebe.
    painel = painel_de_edicao
    painel.resize(1700, 1000)
    painel.show()
    for _ in range(5):
        QApplication.processEvents()
    chamadas = []
    original = painel._timeline.set_zoom_fraction
    monkeypatch.setattr(painel._timeline, "set_zoom_fraction", lambda *a, **k: (chamadas.append(a), original(*a, **k)))
    painel._timeline.fit()
    painel._zoom_in_button.click()
    painel._zoom_in_button.click()
    painel._timeline.zoom(0.7, 1.0)
    assert chamadas == []


def test_o_controle_de_zoom_so_soma_o_proprio_minimo_a_barra_e_o_vao_ate_o_zoom_encolhe(
        tema_do_app, painel_de_edicao, blocos_de_edicao):
    """O primeiro desenho tinha largura fixa de 110 e um vão fixo de 72: somavam 116 px ao mínimo do editor, que passou de
    1141 para 1257 e cortou "Exportar" e "Ver tudo" numa janela de 1280 px. Folga e controle cedem antes de a barra crescer."""
    painel = painel_de_edicao
    barra = painel._zoom_slider
    x = lambda w: w.mapTo(painel, w.rect().topLeft()).x()
    vao = lambda: x(painel._zoom_out_button) - (x(painel._speed_btn) + painel._speed_btn.width())

    def assentar(largura):
        painel.resize(largura, 1000)
        painel.show()
        for _ in range(5):
            QApplication.processEvents()

    assentar(1700)
    assert barra.width() == 110 and vao() >= 72
    # Com o vão já inteiro, o controle também: ele pede os 110 e só cede junto com a folga (um fator de esticamento no
    # ``addWidget`` o fazia dividir a sobra com os espaçadores e ficar em 56 numa janela de 1500 px).
    inteiro = vao()
    for largura in range(1300, 1700, 40):
        assentar(largura)
        assert vao() < inteiro or barra.width() == 110, (largura, vao(), barra.width())
    com = painel.minimumSizeHint().width()
    barra.hide()
    QApplication.processEvents()
    sem = painel.minimumSizeHint().width()
    barra.show()
    QApplication.processEvents()
    assert com - sem <= 56 + 12, (com, sem)
    assentar(com)
    assert barra.width() < 110 and vao() < 72
    assert x(painel._fit_button) + painel._fit_button.width() <= painel.width()
