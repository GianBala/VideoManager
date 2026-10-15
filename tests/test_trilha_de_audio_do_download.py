"""A trilha de áudio em "Somente áudio" (``QualityPanel``): uma escolha só, vista nos dois modos.

A trilha decide qual stream da origem vira o arquivo (no formato "Original", é o arquivo) ou a matéria-prima da
recodificação. Ela sempre valeu no pedido de áudio, mas o campo só existia na página de vídeo; o que isto pode errar sem
exceção: os dois campos discordarem, a nota de bitrate e o aviso continuarem falando da melhor trilha da origem depois de
o usuário escolher outra, e um perfil rápido que desfaz a escolha.
"""

from __future__ import annotations

import pytest

from conftest import fixture_formats
from videomanager.application.formatting import format_bitrate
from videomanager.application.media.download_policy import audio_quality_warning
from videomanager.domain import i18n
from videomanager.domain.formats import AudioChoice, Mode
from videomanager.infrastructure.storage.settings import Settings
from videomanager.infrastructure.yt_dlp.formats import build_matrix
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.i18n import apply_language
from videomanager.presentation.qt.panels.quality_panel import QualityPanel

DURACAO = 600.0


def _painel(desktop_app, fixture: str | None, *, audio: bool = True):
    instancia = QualityPanel(Settings())
    if fixture is not None:
        instancia.set_matrix(build_matrix(fixture_formats(fixture)), DURACAO)
    if audio:
        instancia._radio_audio.setChecked(True)
    instancia.show()
    for _ in range(3):
        desktop_app.processEvents()
    return instancia


@pytest.fixture
def painel(desktop_app):
    instancia = _painel(desktop_app, "youtube_dash")
    yield instancia
    instancia.close()
    apply_language(i18n.PORTUGUESE)


def _trilhas(painel) -> list[AudioChoice]:
    return [painel._audio_page_track.itemData(i) for i in range(1, painel._audio_page_track.count())]


def _escolher(painel, trilha) -> None:
    campo = painel._audio_page_track
    campo.setCurrentIndex(next(i for i in range(campo.count()) if campo.itemData(i) is trilha))


def test_a_pagina_de_audio_mostra_a_trilha_na_terceira_coluna_da_primeira_fileira(painel):
    campo = painel._audio_page_track
    assert campo.isVisibleTo(painel) and campo.isEnabled()
    assert campo.count() == painel._audio_track.count() > 1  # os mesmos itens da página de vídeo
    assert campo.itemText(0) == strings.QUALITY_BEST_AVAILABLE
    posicao = lambda w: w.mapTo(painel, w.rect().topLeft())  # noqa: E731
    formato, qualidade, trilha = posicao(painel._audio_codec), posicao(painel._audio_quality), posicao(campo)
    assert formato.y() == qualidade.y() == trilha.y() and formato.x() < qualidade.x() < trilha.x()


def test_sem_nada_a_escolher_o_campo_do_modo_audio_tambem_fica_apagado_e_diz_por_que(desktop_app):
    vazio = _painel(desktop_app, None)
    mesclado = _painel(desktop_app, "archive_muxed")
    try:
        assert vazio._audio_page_track.isVisibleTo(vazio) and not vazio._audio_page_track.isEnabled()
        assert mesclado._audio_page_track.isVisibleTo(mesclado) and not mesclado._audio_page_track.isEnabled()
        assert mesclado._audio_page_track.currentText() == strings.QUALITY_AUDIO_TRACK_MUXED
        assert strings.QUALITY_AUDIO_TRACK_MUXED not in mesclado.summary()
    finally:
        for instancia in (vazio, mesclado):
            instancia.close()


def test_os_dois_campos_sao_uma_escolha_so(painel):
    menor = min((t for t in _trilhas(painel) if t.bitrate), key=lambda t: t.bitrate)
    _escolher(painel, menor)
    assert painel._audio_track.currentData() is menor and painel.current_audio_choice() is menor
    # E no outro sentido: trocar na página de vídeo é visto na de áudio.
    painel._audio_track.setCurrentIndex(0)
    assert painel._audio_page_track.currentIndex() == 0 and painel._audio_page_track.currentData() is None


def test_o_pedido_de_audio_e_o_de_video_levam_a_trilha_escolhida(painel):
    menor = min((t for t in _trilhas(painel) if t.bitrate), key=lambda t: t.bitrate)
    _escolher(painel, menor)
    assert painel.build_request().audio is menor
    painel._radio_video.setChecked(True)
    assert painel.build_request().audio is menor


def test_a_nota_de_bitrate_acompanha_a_trilha_escolhida(painel):
    melhor = painel._matrix.best_audio_bitrate
    assert painel._audio_source.text() == strings.AUDIO_SOURCE_INFO.format(bitrate=format_bitrate(melhor))
    menor = min((t for t in _trilhas(painel) if t.bitrate), key=lambda t: t.bitrate)
    _escolher(painel, menor)
    assert painel._audio_source.text() == strings.AUDIO_SOURCE_CHOSEN.format(bitrate=format_bitrate(menor.bitrate))
    painel._audio_page_track.setCurrentIndex(0)
    assert painel._audio_source.text() == strings.AUDIO_SOURCE_INFO.format(bitrate=format_bitrate(melhor))


def test_trilha_sem_bitrate_conhecido_nao_fala_da_melhor(painel):
    sem_bitrate = next(t for t in _trilhas(painel) if not t.bitrate)  # a extraída do vídeo MP4
    _escolher(painel, sem_bitrate)
    assert painel._audio_source.text() == ""
    painel._audio_codec.setCurrentIndex(painel._audio_codec.findData("mp3"))
    painel._audio_quality.setCurrentIndex(painel._audio_quality.findData("320"))
    assert not painel._warning.isVisibleTo(painel)  # sem o dado não se compara, e o aviso da melhor trilha não vale aqui


def test_o_aviso_de_qualidade_compara_com_a_trilha_escolhida_e_nao_com_a_melhor(painel):
    painel._audio_codec.setCurrentIndex(painel._audio_codec.findData("mp3"))
    painel._audio_quality.setCurrentIndex(painel._audio_quality.findData("128"))
    assert not painel._warning.isVisibleTo(painel)  # 128 cabe na melhor (129 kbps)
    menor = min((t for t in _trilhas(painel) if t.bitrate), key=lambda t: t.bitrate)
    _escolher(painel, menor)  # 49 kbps: pedir 128 de uma fonte de 49 só aumenta o arquivo
    assert painel._warning.isVisibleTo(painel) and format_bitrate(menor.bitrate) in painel._warning.text()


def test_a_politica_de_aviso_usa_o_bitrate_dado_no_lugar_do_da_melhor():
    matriz = build_matrix(fixture_formats("youtube_dash"))
    assert audio_quality_warning(matriz, "mp3", "128") is None
    assert audio_quality_warning(matriz, "mp3", "128", source_kbps=49.0) is not None
    assert audio_quality_warning(matriz, "flac", "128", source_kbps=49.0) is None


def test_o_resumo_do_modo_audio_diz_a_trilha_quando_ha_o_que_escolher(painel):
    assert painel.mode is Mode.AUDIO_ONLY
    assert painel.summary().endswith(strings.QUALITY_BEST_AVAILABLE)
    menor = min((t for t in _trilhas(painel) if t.bitrate), key=lambda t: t.bitrate)
    _escolher(painel, menor)
    assert painel._audio_page_track.currentText() in painel.summary()


def test_um_perfil_rapido_mantem_a_trilha_escolhida(painel):
    menor = min((t for t in _trilhas(painel) if t.bitrate), key=lambda t: t.bitrate)
    _escolher(painel, menor)
    painel.apply_profile(mode=Mode.AUDIO_ONLY, audio_codec="best")
    assert painel.current_audio_choice() is menor and painel._audio_page_track.currentData() is menor


def test_analisar_outra_midia_volta_os_dois_campos_a_melhor_disponivel(painel):
    _escolher(painel, _trilhas(painel)[-1])
    painel.set_matrix(build_matrix(fixture_formats("youtube_dash")), DURACAO)
    assert painel._audio_track.currentIndex() == painel._audio_page_track.currentIndex() == 0


def test_a_nota_e_os_itens_acompanham_o_idioma(painel):
    menor = min((t for t in _trilhas(painel) if t.bitrate), key=lambda t: t.bitrate)
    _escolher(painel, menor)
    apply_language(i18n.ENGLISH)
    assert painel._audio_source.text() == strings.AUDIO_SOURCE_CHOSEN.format(bitrate=format_bitrate(menor.bitrate))
    assert painel._audio_source.text().startswith("Chosen track")
    assert painel._audio_page_track.itemText(0) == "Best available"
