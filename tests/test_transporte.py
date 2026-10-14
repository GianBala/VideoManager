"""Transporte e prévia como no protótipo: uma fileira só, o play de 46 px, o tempo em tipo monoespaçado, os extras só com
ícone, o aviso sobre o canto do cartão da prévia e o cartão de cantos arredondados.

O que uma troca de desenho perde em silêncio: a fileira que volta a quebrar em duas com largura de sobra, o botão ligado
que não mostra que está ligado (o loop e o ímã só têm o ícone e o tom de fundo), o aviso de "carregando" que volta a
tirar altura da prévia, a dica do mudo que não acompanha o estado. Os testes medem a geometria e os pixels, com o tema
aplicado como no aplicativo real.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from videomanager.domain import i18n
from videomanager.presentation.qt import fonts, strings, theme
from videomanager.presentation.qt.i18n import apply_language


def _mostrar(painel, largura: int = 1900, altura: int = 1000):
    painel.resize(largura, altura)
    painel.show()
    for _ in range(6):
        QApplication.processEvents()
    return painel._transport_bar


def _y(widget, ancora) -> int:
    return widget.mapTo(ancora, widget.rect().topLeft()).y()


def test_com_largura_de_sobra_o_transporte_e_uma_fileira_so(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    barra = _mostrar(painel)
    assert not barra._wrapped
    grupos = barra._groups
    centros = [g.mapTo(barra, g.rect().center()).y() for g in grupos]
    assert max(centros) - min(centros) <= 2, "tempo, botões e extras na mesma linha"
    assert barra.height() <= 50, "uma fileira: o play de 46 px e a margem de cima"


def test_sem_largura_os_extras_descem_para_a_segunda_fileira(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    barra = _mostrar(painel, largura=1280, altura=800)
    assert barra._wrapped
    leituras, controles, extras = barra._groups
    assert _y(extras, barra) > _y(controles, barra) + controles.height() - 4


def test_o_play_e_um_circulo_de_46_px_em_degrade_e_os_outros_botoes_36_sem_fundo(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    _mostrar(painel)
    play = painel._play_button
    assert (play.width(), play.height()) == (46, 46) and play.property("role") == "play"
    imagem = play.grab().toImage()
    cores = theme.papeis("dark", "grafite")
    # Os cantos ficam fora do círculo (transparentes ou do fundo), e o meio é o degradê do botão primário.
    assert imagem.pixelColor(2, 2).alpha() == 0 or imagem.pixelColor(2, 2).name().lower() != cores["fill_a"].lower()
    meio = imagem.pixelColor(23, 23)
    assert meio.alpha() == 255 and meio.name().lower() not in (cores["canvas"].lower(), cores["raised"].lower())
    assert not play.icon().isNull()
    for botao in painel._buttons[:3] + painel._buttons[4:7]:
        assert (botao.width(), botao.height()) == (36, 36) and botao.property("role") == "tool"
        assert not botao.icon().isNull() and botao.text() == ""
    # Os botões ficam a 2 px, com 4 de ar de cada lado do play: 36 + 2 entre eles.
    xs = [b.mapTo(painel._transport_bar, b.rect().topLeft()).x() for b in painel._buttons[:3]]
    assert xs[1] - xs[0] == xs[2] - xs[1] == 38
    # O play tem 4 px de ar de cada lado além dos 2 de sempre: 6 entre ele e os vizinhos.
    barra = painel._transport_bar
    esquerda = painel._buttons[2].mapTo(barra, painel._buttons[2].rect().topRight()).x()
    direita = painel._buttons[4].mapTo(barra, painel._buttons[4].rect().topLeft()).x()
    inicio = play.mapTo(barra, play.rect().topLeft()).x()
    assert inicio - esquerda == 6 + 1 and direita - (inicio + 46) == 6


def test_o_tempo_e_mono_de_22_px_com_o_total_e_o_quadro_menores_na_mesma_linha(tema_do_app, painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    barra = _mostrar(painel)
    for rotulo in (painel._time_label, painel._total_label, painel._frame_label):
        rotulo.ensurePolished()
    assert painel._time_label.font().pixelSize() == 22 and painel._total_label.font().pixelSize() == 13
    assert painel._time_label.font().family() == fonts.mono(22).family()
    assert painel._time_label.text() == "0:00:00" and painel._total_label.text().startswith("/ ")
    assert painel._frame_label.property("role") == "hint"
    # Apoiados na base do tempo grande.
    base = lambda w: w.mapTo(barra, w.rect().bottomLeft()).y()
    assert abs(base(painel._time_label) - base(painel._total_label)) <= 2
    assert abs(base(painel._time_label) - base(painel._frame_label)) <= 2
    # A largura do tempo é travada: o número que muda a cada quadro não faz a barra tremer.
    antes = (painel._time_label.width(), painel._total_label.width(), painel._frame_label.width())
    painel._seek_to(3.5)
    painel._update_time_labels()
    assert painel._time_label.text() == "0:00:03"
    assert (painel._time_label.width(), painel._total_label.width(), painel._frame_label.width()) == antes


def test_os_extras_so_tem_icone_e_o_ligado_leva_o_tom_suave_com_o_icone_no_acento(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    _mostrar(painel)
    cores = theme.papeis("dark", "grafite")
    for botao in (painel._prev_key, painel._next_key, painel._loop, painel._snap_btn, painel._mute):
        assert botao.text() == "" and not botao.icon().isNull() and botao.property("role") == "tool"
        assert botao.toolTip() and botao.accessibleName() == botao.toolTip() or botao is painel._loop
    assert painel._loop.accessibleName() == strings.EDIT_LOOP
    # O pill dos dois saltos de keyframe: um cartão de 32 px com os botões de 26.
    pilula = painel._prev_key.parentWidget()
    assert pilula.property("role") == "segments" and pilula.height() == 32
    assert (painel._prev_key.width(), painel._prev_key.height()) == (26, 26)
    # Desligado, o ícone é o da cor secundária; ligado, o do acento — e o fundo é o tom suave.
    desligado = painel._loop.icon().pixmap(18, 18).toImage()
    painel._loop.setChecked(True)
    QApplication.processEvents()
    ligado = painel._loop.icon().pixmap(18, 18).toImage()
    assert desligado != ligado
    def perto(imagem, cor) -> int:
        alvo = QColor(cor)
        return sum(1 for y in range(18) for x in range(18)
                   if imagem.pixelColor(x, y).alpha() > 120
                   and abs(imagem.pixelColor(x, y).red() - alvo.red()) + abs(imagem.pixelColor(x, y).green() - alvo.green())
                   + abs(imagem.pixelColor(x, y).blue() - alvo.blue()) < 60)
    # As cores do painel são as da paleta dele (``palette``), as mesmas dos ícones da barra e das abas.
    assert perto(ligado, painel._colors["accent"]) > 8 and perto(desligado, painel._colors["accent"]) == 0, \
        "o ícone ligado vai ao acento"
    assert perto(desligado, painel._colors["text_dim"]) > 8 and perto(desligado, painel._colors["text"]) == 0
    fundo = painel._loop.grab().toImage().pixelColor(18, 3)
    assert fundo.alpha() > 0 and fundo.name().lower() != cores["canvas"].lower()
    painel._loop.setChecked(False)
    QApplication.processEvents()
    assert painel._loop.icon().pixmap(18, 18).toImage() == desligado


def test_o_mudo_troca_o_icone_e_a_dica_com_o_estado_e_com_o_idioma(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    _mostrar(painel)
    assert painel._mute.toolTip() == strings.EDIT_MUTE
    som = painel._mute.icon().pixmap(18, 18).toImage()
    painel._mute.setChecked(True)
    assert painel._mute.toolTip() == strings.EDIT_UNMUTE == painel._mute.accessibleName()
    assert painel._mute.icon().pixmap(18, 18).toImage() != som
    apply_language(i18n.ENGLISH)
    try:
        assert painel._mute.toolTip() == "Unmute"
        painel._mute.setChecked(False)
        assert painel._mute.toolTip() == "Mute"
    finally:
        apply_language(i18n.PORTUGUESE)
    assert painel._volume.width() == 90


def test_o_aviso_de_carregando_fica_sobre_o_canto_do_cartao_e_nao_gasta_altura(tema_do_app, painel_de_edicao):
    painel = painel_de_edicao
    barra = _mostrar(painel)
    quadro, aviso = painel._preview_frame, painel._loading_label
    aviso.setText("")  # nasce com o "Carregando quadro…" de quem ainda não tem quadro
    assert aviso.parentWidget() is quadro and not aviso.isVisible()
    altura = quadro.height()
    aviso.setText("Carregando quadro…")
    QApplication.processEvents()
    assert aviso.isVisibleTo(quadro) and quadro.height() == altura, "o aviso sai do fluxo: a prévia não encolhe"
    geo = aviso.geometry()
    assert geo.left() == 16 and geo.bottom() <= quadro.height() - 14 and geo.right() <= quadro.width() - 16
    assert aviso.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    aviso.setText("")
    assert not aviso.isVisibleTo(quadro)
    # Redimensionar a janela leva o aviso junto, sempre colado ao canto de baixo.
    aviso.setText("Carregando quadro…")
    painel.resize(1700, 900)
    for _ in range(4):
        QApplication.processEvents()
    assert aviso.geometry().bottom() <= quadro.height() - 14 and aviso.geometry().bottom() >= quadro.height() - 14 - 2
    assert barra is painel._transport_bar


def test_a_previa_e_um_cartao_de_18_px_de_raio_no_plano_screen(tema_do_app, painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    _mostrar(painel)
    cores = theme.papeis("dark", "grafite")
    previa = painel._preview
    # Sem quadro (o texto de "carregando") o cartão é o do QSS; com quadro, o do ``paintEvent``: nos dois o canto é
    # redondo (o quadrado de 3 px do canto fica de fora, transparente) e por dentro vai o plano `screen` do tema.
    for com_quadro in (False, True):
        if com_quadro:
            previa.set_frame_pixmap(QPixmap(640, 360))
        QApplication.processEvents()
        imagem = previa.grab().toImage()
        assert imagem.pixelColor(1, 1).alpha() == 0, com_quadro
        assert imagem.pixelColor(10, 10).alpha() == 255, com_quadro
        faixa = imagem.pixelColor(10, previa.height() // 2)
        assert faixa.alpha() == 255
        assert abs(faixa.lightness() - QColor(cores["screen"]).lightness()) <= 6, com_quadro
    assert painel._preview_frame.layout().contentsMargins().left() == 0
    from videomanager.presentation.qt.panels import edit_widgets
    assert edit_widgets._PREVIEW_RADIUS == 18
    assert previa.styleSheet() == "", "sem a folha de estilo com #141418 fixo"
