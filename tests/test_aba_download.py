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
from videomanager.domain.formats import MediaInfo
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
    # O campo ocupa a largura toda da linha, por cima da coluna que era do rótulo.
    assert janela._url.geometry().left() <= janela._dest.geometry().left() - 1
