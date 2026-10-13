"""A aba Download reorganizada: perfis em cartões, "Personalizar" que se recolhe e o rodapé com o resultado.

A tela passou de duas colunas (qualidade e perfis) para uma coluna de cima para baixo, e o que a suíte antiga
não via é o que um reposicionamento perde em silêncio: o campo que esquece o que foi escolhido porque ficou
escondido, o rodapé que diz uma coisa e a fila recebe outra, o cartão de perfil que não enfileira. Os testes
conferem pelo que a fila recebe e pelo que o rodapé mostra.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from conftest import fixture_formats
from videomanager.application.capabilities import FFmpegTools
from videomanager.application.formatting import DASH
from videomanager.bootstrap import (build_desktop_runtime, build_download_service, build_editor_service,
                                    build_processing_service)
from videomanager.domain import i18n
from videomanager.domain.formats import MediaInfo, Mode
from videomanager.domain.selection import AudioRequest, VideoRequest
from videomanager.infrastructure.storage.settings import Settings
from videomanager.infrastructure.yt_dlp.formats import build_matrix
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.i18n import apply_language
from videomanager.presentation.qt.main_window import MainWindow
from videomanager.presentation.qt.panels.profiles_panel import PROFILES


@pytest.fixture
def janela(desktop_app, monkeypatch):
    monkeypatch.setattr("videomanager.presentation.qt.main_window.ensure_ffmpeg", lambda parent, **kw: None)
    w = MainWindow(Settings(), editor=build_editor_service(), processing=build_processing_service(),
                   downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))
    w._tools = FFmpegTools(Path("/x/ffmpeg"), Path("/x/ffprobe"), "sistema")
    w.show()
    for _ in range(5):
        desktop_app.processEvents()
    yield w
    w._edit._project_actions.confirm_replace = lambda: True
    w._edit.shutdown()
    w.close()
    apply_language(i18n.PORTUGUESE)


@pytest.fixture
def pedidos(janela, monkeypatch):
    """Tudo o que a aba manda para a fila, sem passar por ela."""
    recebidos = []
    monkeypatch.setattr(janela, "_enqueue", lambda media, request: recebidos.append(request))
    return recebidos


def _analisar(janela, desktop_app) -> MediaInfo:
    media = MediaInfo(url="https://exemplo/v", title="Vídeo", matrix=build_matrix(fixture_formats("youtube_dash")))
    janela._on_probed(media)
    for _ in range(3):
        desktop_app.processEvents()
    return media


# -- perfis ---------------------------------------------------------------------------------------------------

def test_os_quatro_perfis_aparecem_em_cartoes_na_ordem_de_sempre(janela):
    botoes = janela._profiles._buttons
    assert [b.text().split("\n")[0] for b in botoes] == [p.title() for p in PROFILES]
    assert [b.text().split("\n")[1] for b in botoes] == [p.subtitle() for p in PROFILES]
    # Em fileira (lado a lado), e não empilhados como eram.
    assert len({b.geometry().top() for b in botoes}) == 1
    assert [b.geometry().left() for b in botoes] == sorted(b.geometry().left() for b in botoes)


def test_os_cartoes_so_funcionam_com_midia_analisada(janela, desktop_app):
    assert not any(b.isEnabled() for b in janela._profiles._buttons)
    _analisar(janela, desktop_app)
    assert all(b.isEnabled() for b in janela._profiles._buttons)


def test_clicar_num_cartao_aplica_o_perfil_e_enfileira(janela, desktop_app, pedidos):
    _analisar(janela, desktop_app)
    cartao_mp3 = janela._profiles._buttons[2]
    QTest.mouseClick(cartao_mp3, Qt.MouseButton.LeftButton)
    assert len(pedidos) == 1 and isinstance(pedidos[0], AudioRequest)
    assert (pedidos[0].codec, pedidos[0].quality) == ("mp3", "320")
    QTest.mouseClick(janela._profiles._buttons[0], Qt.MouseButton.LeftButton)
    assert isinstance(pedidos[1], VideoRequest) and pedidos[1].container == "mp4"


def test_o_cartao_responde_ao_teclado(janela, desktop_app, pedidos):
    _analisar(janela, desktop_app)
    cartao = janela._profiles._buttons[1]
    cartao.setFocus()
    QTest.keyClick(cartao, Qt.Key.Key_Space)
    assert len(pedidos) == 1 and pedidos[0].container == "mkv"


# -- Personalizar ---------------------------------------------------------------------------------------------

def test_recolher_o_personalizar_nao_zera_a_escolha_e_o_rodape_enfileira_com_ela(janela, desktop_app, pedidos):
    _analisar(janela, desktop_app)
    resolucao = janela._quality._resolution
    alvo = next(i for i in range(resolucao.count()) if isinstance(resolucao.itemData(i), int) and resolucao.itemData(i) < 1000)
    resolucao.setCurrentIndex(alvo)
    escolhida = resolucao.currentData()
    texto = janela._quality.summary()
    janela._personalize.set_expanded(False)
    for _ in range(3):
        desktop_app.processEvents()
    assert not resolucao.isVisible() and not janela._quality.isVisible()
    assert resolucao.currentData() == escolhida
    assert janela._result_summary.text() == texto
    janela._add_button.click()
    assert pedidos[-1].video.height == escolhida
    janela._personalize.set_expanded(True)
    for _ in range(3):
        desktop_app.processEvents()
    assert resolucao.isVisible() and resolucao.currentData() == escolhida


def test_o_cabecalho_do_personalizar_abre_e_fecha_com_o_clique_e_com_o_teclado(janela, desktop_app):
    cartao = janela._personalize
    assert cartao.expanded
    QTest.mouseClick(cartao._toggle, Qt.MouseButton.LeftButton)
    assert not cartao.expanded and not janela._quality.isVisible()
    cartao._toggle.setFocus()
    QTest.keyClick(cartao._toggle, Qt.Key.Key_Space)
    assert cartao.expanded and janela._quality.isVisibleTo(cartao)


# -- rodapé ---------------------------------------------------------------------------------------------------

def test_sem_midia_o_rodape_nao_promete_nada(janela):
    assert janela._result_summary.text() == DASH and janela._result_size.text() == DASH
    assert not janela._add_button.isEnabled()


def test_o_rodape_mostra_o_que_a_fila_vai_receber(janela, desktop_app, pedidos):
    _analisar(janela, desktop_app)
    assert janela._add_button.isEnabled()
    assert janela._result_summary.text() == janela._quality.summary() != DASH
    assert janela._result_size.text() == janela._quality.estimated_size()
    # O resumo cita a resolução e o contêiner que os campos mostram.
    assert janela._quality._resolution.currentText() in janela._result_summary.text()
    assert janela._quality._container.currentText() in janela._result_summary.text()
    # Trocar de modo troca o resumo, e o botão do rodapé enfileira o modo mostrado.
    janela._quality._radio_audio.setChecked(True)
    assert janela._quality._audio_codec.currentText() in janela._result_summary.text()
    assert janela._quality._resolution.currentText() not in janela._result_summary.text()
    janela._add_button.click()
    assert isinstance(pedidos[-1], AudioRequest)


def test_o_rodape_acompanha_cada_campo(janela, desktop_app):
    _analisar(janela, desktop_app)
    container = janela._quality._container
    for indice in range(container.count()):
        container.setCurrentIndex(indice)
        assert container.currentText() in janela._result_summary.text()


def test_o_rodape_troca_de_idioma_com_os_campos(janela, desktop_app):
    _analisar(janela, desktop_app)
    janela._quality._resolution.setCurrentIndex(0)
    assert strings.QUALITY_BEST_AVAILABLE in janela._result_summary.text()
    apply_language(i18n.ENGLISH)
    assert janela._result_summary.text() == janela._quality.summary()
    assert strings.QUALITY_BEST_AVAILABLE == "Best available" and "Best available" in janela._result_summary.text()
    assert janela._result_estimated.text() == strings.RESULT_ESTIMATED == "estimated"


# -- endereço -------------------------------------------------------------------------------------------------

def test_o_endereco_continua_com_nome_acessivel_sem_o_rotulo(janela):
    assert janela._url.accessibleName() == strings.URL_LABEL
    assert janela._url.placeholderText() == strings.URL_PLACEHOLDER
    # A barra de endereço começa na mesma coluna em que começa a linha do destino (a margem da página), e não dentro dela.
    pagina = janela._tabs.widget(0)
    barra = janela._address.mapTo(pagina, janela._address.rect().topLeft()).x()
    destino = janela._dest_icon.mapTo(pagina, janela._dest_icon.rect().topLeft()).x()
    assert 0 <= destino - barra <= 6


# -- fidelidade ao protótipo: barra de endereço, destino, cartão de mídia, perfis, grade e rodapé -----------------------

def _cor(imagem, x: int, y: int) -> str:
    return imagem.pixelColor(x, y).name().lower()


def test_a_barra_de_endereco_e_um_quadro_so_com_o_campo_o_limpar_e_as_duas_acoes(tema_do_app, janela, desktop_app):
    barra = janela._address
    for filho in (janela._url, janela._paste, janela._analyze_button, barra.clear_button):
        assert barra.isAncestorOf(filho)
    # O limpar só tem o que fazer quando há texto, e limpa o campo.
    janela._url.clear()
    assert not barra.clear_button.isVisibleTo(barra)
    janela._url.setText("https://exemplo/v")
    assert barra.clear_button.isVisibleTo(barra)
    QTest.mouseClick(barra.clear_button, Qt.MouseButton.LeftButton)
    assert janela._url.text() == "" and not barra.clear_button.isVisibleTo(barra)


def test_o_anel_de_foco_e_do_quadro_inteiro_e_o_elo_vai_para_o_acento(tema_do_app, janela, desktop_app):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    from videomanager.presentation.qt import theme
    barra = janela._address
    cores = theme.papeis(*theme.atual())
    meio = barra.height() // 2
    sem_foco = barra.grab().toImage()
    assert barra.property("focused") == "false" and _cor(sem_foco, 0, meio) == cores["raised"].lower()
    elo_sem_foco = barra.link.pixmap().toImage()
    desktop_app.sendEvent(janela._url, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
    desktop_app.processEvents()
    com_foco = barra.grab().toImage()
    assert barra.property("focused") == "true"
    assert _cor(com_foco, 0, meio) == theme.derivadas(cores)["ring"].lower()
    assert barra.link.pixmap().toImage() != elo_sem_foco
    desktop_app.sendEvent(janela._url, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason))
    desktop_app.processEvents()
    assert barra.property("focused") == "false" and _cor(barra.grab().toImage(), 0, meio) == cores["raised"].lower()


def test_o_destino_e_texto_corrido_com_o_alterar_logo_depois_do_caminho(tema_do_app, janela, desktop_app, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    janela._dest.setText("/home/gian/Videos/Downloads")
    for _ in range(3):
        desktop_app.processEvents()
    texto = janela._dest.fontMetrics().horizontalAdvance(janela._dest.text())
    # O campo cabe o caminho inteiro (antes ele rolava e mostrava "me/gian/..."), e o "Alterar" fica colado nele.
    assert janela._dest.width() >= texto
    alterar = next(b for b in janela.findChildren(QPushButton) if b.text() == strings.DEST_CHANGE)
    folga = alterar.geometry().left() - janela._dest.geometry().right()
    assert 0 <= folga <= 20, folga
    escolhidos = []
    monkeypatch.setattr(janela, "_choose_dest", lambda: escolhidos.append(1))
    alterar.click()
    assert escolhidos == [1]


def test_o_cartao_da_midia_mostra_o_que_a_midia_oferece_e_a_duracao_no_selo(janela, desktop_app):
    from PySide6.QtWidgets import QLabel
    janela._on_probed(MediaInfo(url="https://exemplo/v", title="Vídeo", duration=635.0, uploader="Canal", extractor="Youtube",
                                matrix=build_matrix(fixture_formats("youtube_dash"))))
    cartao = janela._card
    selos = [s.text() for s in cartao.findChildren(QLabel) if s.property("role") == "chip"]
    assert selos == [strings.CARD_CHIP_UP_TO.format(height=2160), strings.EDIT_CANVAS_FPS.format(fps=60), "H.264 · AV1 · VP9"]
    assert cartao._thumb.badge() == "10:35"


def test_os_selos_so_prometem_o_que_a_matriz_tem():
    from videomanager.domain.formats import FormatMatrix
    from videomanager.presentation.qt.panels.media_card import chips
    assert chips(FormatMatrix()) == []


def test_os_selos_e_o_aviso_ao_vivo_trocam_de_idioma_sem_duplicar(janela, desktop_app):
    from PySide6.QtWidgets import QLabel
    _analisar(janela, desktop_app)
    cartao = janela._card

    def selos():
        return [s.text() for s in cartao.findChildren(QLabel) if s.property("role") == "chip"]

    antes = selos()
    apply_language(i18n.ENGLISH)
    depois = selos()
    assert len(depois) == len(antes) == 3
    assert depois[0] == strings.CARD_CHIP_UP_TO.format(height=2160) == "up to 2160p"


def test_ao_vivo_o_selo_da_miniatura_e_o_aviso_e_nao_a_duracao(janela, desktop_app):
    media = MediaInfo(url="https://exemplo/v", title="Ao vivo", is_live=True, duration=None,
                      matrix=build_matrix(fixture_formats("youtube_dash")))
    janela._on_probed(media)
    assert janela._card._thumb.badge() == strings.CARD_LIVE_BADGE


def test_o_cartao_de_cada_perfil_mostra_o_tamanho_que_o_rodape_mostra_depois_do_clique(janela, desktop_app, pedidos):
    _analisar(janela, desktop_app)
    for cartao in janela._profiles._buttons:
        assert cartao.size_text().startswith("~")
        QTest.mouseClick(cartao, Qt.MouseButton.LeftButton)
        desktop_app.processEvents()
        # O mesmo número, no mesmo formato compacto: a estimativa do cartão é a conta do rodapé aplicada ao perfil.
        rodape = janela._result_size.text()
        assert cartao.size_text().split()[1] == rodape.split()[1]  # mesma unidade
    # E sem mídia analisada nenhum cartão promete tamanho.
    janela._profiles.set_enabled(False)
    assert [c.size_text() for c in janela._profiles._buttons] == ["", "", "", ""]


def test_o_tamanho_compacto_nao_tem_decimal_ate_os_megabytes():
    from videomanager.application.formatting import format_size_compact
    assert format_size_compact(255 * 1024 * 1024 + 700_000, estimated=True) == "~256 MB"
    assert format_size_compact(int(1.4 * 1024 ** 3), estimated=True) == "~1,4 GB"
    assert format_size_compact(None) == DASH


def test_a_grade_do_personalizar_tem_tres_colunas_iguais_com_a_legenda_acima_do_campo(tema_do_app, janela, desktop_app):
    _analisar(janela, desktop_app)
    qualidade = janela._quality
    pagina = janela._tabs.widget(0)

    def caixa(widget):
        return widget.mapTo(pagina, widget.rect().topLeft()), widget.size()

    x1, x2, x3 = (caixa(w)[0].x() for w in (qualidade._resolution, qualidade._fps, qualidade._codec))
    larguras = [qualidade._resolution.width(), qualidade._fps.width(), qualidade._codec.width()]
    assert max(larguras) - min(larguras) <= 1, larguras
    assert x1 < x2 < x3
    # Campo de 38 px (o protótipo), com a legenda logo acima e na mesma coluna.
    assert qualidade._resolution.height() >= 36
    legenda = qualidade._resolution.parentWidget().findChild(type(janela._result_summary))
    assert legenda.text() == strings.LABEL_RESOLUTION and legenda.geometry().bottom() < qualidade._resolution.geometry().top()


def test_o_seletor_de_modo_mora_no_cabecalho_do_personalizar_e_troca_a_pagina(tema_do_app, janela, desktop_app):
    _analisar(janela, desktop_app)
    cartao, qualidade = janela._personalize, janela._quality
    assert cartao.isAncestorOf(qualidade.mode_selector) and not qualidade.isAncestorOf(qualidade.mode_selector)
    pagina = janela._tabs.widget(0)
    seletor_x = qualidade.mode_selector.mapTo(pagina, qualidade.mode_selector.rect().topLeft()).x()
    titulo_x = cartao._toggle.mapTo(pagina, cartao._toggle.rect().topLeft()).x()
    assert seletor_x > titulo_x + cartao._toggle.width()  # à direita do título
    assert qualidade._radio_video._glyph is not None and qualidade._radio_audio._glyph is not None
    qualidade._radio_audio.click()
    assert qualidade._stack.currentIndex() == 1 and qualidade.mode is Mode.AUDIO_ONLY
    qualidade._radio_video.click()
    assert qualidade._stack.currentIndex() == 0


def test_o_rodape_e_o_plano_acima_do_cartao_e_a_acao_e_grande_com_icone(tema_do_app, janela, desktop_app):
    from videomanager.presentation.qt import theme
    cores = theme.papeis(*theme.atual())
    rodape = janela._add_button.parentWidget()
    imagem = rodape.grab().toImage()
    assert _cor(imagem, 6, rodape.height() // 2) == cores["raised"].lower()
    assert not janela._add_button.icon().isNull() and janela._add_button.height() >= 42


def test_a_pagina_tem_28_px_de_margem_e_o_menu_lateral_nao_entra_na_conta(tema_do_app, janela, desktop_app):
    pagina = janela._tabs.widget(0)
    x = janela._address.mapTo(pagina, janela._address.rect().topLeft()).x()
    assert x == 28


def test_um_texto_comprido_no_combo_nao_empurra_as_colunas_vizinhas(tema_do_app, desktop_app):
    # O que decidia a largura da coluna era o texto mais longo do combo (o tamanho que ele pede ao aparecer): com um
    # item enorme, as outras duas colunas ficavam menores. Ele tem de caber nas reticências.
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.panels.quality_panel import QualityPanel
    painel = QualityPanel(Settings())
    try:
        painel._resolution.addItem("1920×1080 · H.264 · 60 fps · HDR · um rótulo muito mais comprido do que cabe na coluna")
        painel.resize(1500, 240)  # larga o bastante para a soma do que os combos pedem caber: aí a diferença aparece
        painel.show()
        for _ in range(5):
            desktop_app.processEvents()
        larguras = [painel._resolution.width(), painel._fps.width(), painel._codec.width()]
        assert max(larguras) - min(larguras) <= 1, larguras
    finally:
        painel.close()
