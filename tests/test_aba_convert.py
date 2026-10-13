"""A aba Convert reorganizada: linhas de arquivo com antes → depois, modos segmentados, resumo e rodapé.

O que um reposicionamento perde em silêncio: o × que remove a linha errada (ou deixa a lista e ``_media``
discordando), o modo que muda no desenho e não no painel, o rodapé que promete um tamanho diferente do que o
resumo diz. Os testes conferem pelo estado do painel e pelo que a lista e o rodapé mostram.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.formatting import DASH
from videomanager.application.preferences import Preferences
from videomanager.bootstrap import build_desktop_runtime, build_processing_service
from videomanager.domain import i18n
from videomanager.domain.media import LocalMedia, LocalStream
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.i18n import apply_language
from videomanager.presentation.qt.panels import convert_rows
from videomanager.presentation.qt.panels.convert_panel import ConvertPanel


def _video(nome: str, tamanho: int = 262_800, audio: bool = True) -> LocalMedia:
    fluxos = [LocalStream(0, "video", "h264", height=720, width=1280, fps=30.0)]
    if audio:
        fluxos.append(LocalStream(1, "audio", "aac"))
    return LocalMedia(Path(nome), 7.0, "mov,mp4", tamanho, tuple(fluxos))


def _musica(nome: str, tamanho: int = 52_800) -> LocalMedia:
    return LocalMedia(Path(nome), 6.0, "mp3", tamanho, (LocalStream(0, "audio", "mp3"),))


@pytest.fixture
def painel(desktop_app, monkeypatch):
    tools = FFmpegTools(Path("ffmpeg"), Path("ffprobe"), "teste")
    instancia = ConvertPanel(Preferences(), lambda: tools, processing=build_processing_service(),
                             runtime=build_desktop_runtime(audio_enabled=False))
    instancia._tools = tools
    instancia.resize(900, 700)
    instancia.show()
    for _ in range(3):
        desktop_app.processEvents()
    yield instancia
    instancia.shutdown()
    instancia.close()
    apply_language(i18n.PORTUGUESE)


def _inspecionado(painel, desktop_app, *midias: LocalMedia) -> None:
    """Entrega à aba o resultado de uma inspeção, como o trabalhador entregaria."""
    resultado = SimpleNamespace(probed={m.path: m for m in midias}, rejected=[])
    painel._on_inspected(painel._inspection_token, resultado)
    for _ in range(3):
        desktop_app.processEvents()


# -- as linhas ------------------------------------------------------------------------------------------------

def test_os_selos_da_linha_dizem_vídeo_áudio_e_duração():
    com_som = [texto for texto, _ in convert_rows.chips(_video("a.mp4"))]
    assert com_som == ["H.264 · 1280×720", "AAC", "0:07"]
    sem_som = convert_rows.chips(_video("b.mp4", audio=False))
    assert (strings.CONVERT_NO_AUDIO, "warn") in sem_som
    assert [texto for texto, _ in convert_rows.chips(_musica("c.mp3"))] == ["MP3", "0:06"]


def test_a_mudanca_de_tamanho_e_o_percentual_do_antes_para_o_depois():
    midia = _video("a.mp4", tamanho=1000)
    assert convert_rows.change_percent(midia, 1350) == 35
    assert convert_rows.change_percent(midia, 780) == -22
    assert convert_rows.change_percent(midia, None) is None
    assert convert_rows.change_percent(_video("b.mp4", tamanho=0), 100) is None


def test_cada_arquivo_vira_uma_linha_com_a_midia_e_a_estimativa(painel, desktop_app):
    _inspecionado(painel, desktop_app, _video("a.mp4"), _musica("b.mp3"))
    lista = painel._list
    assert lista.count() == 2
    for linha in range(2):
        item = lista.item(linha)
        assert item.data(convert_rows.ROLE_MEDIA) is painel._media[linha]
        # O texto do item continua existindo, para quem lê a lista sem vê-la.
        assert painel._media[linha].path.name in item.text()
        assert item.data(convert_rows.ROLE_AFTER) is not None


def test_a_linha_se_pinta_sem_erro_nos_tres_modos(painel, desktop_app):
    _inspecionado(painel, desktop_app, _video("a.mp4"), _musica("b.mp3"))
    for botao in (painel._to_video, painel._to_audio):
        botao.setChecked(True)
        for _ in range(3):
            desktop_app.processEvents()
        imagem = painel._list.viewport().grab().toImage()
        assert not imagem.isNull()


# -- remover --------------------------------------------------------------------------------------------------

def _clicar_no_x(painel, desktop_app, linha: int) -> None:
    item = painel._list.item(linha)
    retangulo = painel._list.visualItemRect(item)
    alvo = retangulo.topLeft() + convert_rows.RowDelegate.remove_rect(retangulo.width()).center()
    QTest.mouseClick(painel._list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, alvo)
    desktop_app.processEvents()


def test_o_x_tira_so_a_linha_dele_e_mantem_a_lista_e_as_midias_em_sincronia(painel, desktop_app):
    a, b, c = _video("a.mp4"), _video("b.mp4"), _musica("c.mp3")
    _inspecionado(painel, desktop_app, a, b, c)
    painel._list.item(0).setSelected(True)  # outra linha selecionada: o × não é "remover selecionados"
    _clicar_no_x(painel, desktop_app, 1)
    assert [m.path.name for m in painel._media] == ["a.mp4", "c.mp3"]
    assert [painel._list.item(i).text().split("   ·   ")[0] for i in range(painel._list.count())] == ["a.mp4", "c.mp3"]
    assert painel._list.item(0).isSelected()


def test_remover_selecionados_tira_varias_sem_embaralhar(painel, desktop_app):
    midias = [_video(f"{n}.mp4") for n in "abcd"]
    _inspecionado(painel, desktop_app, *midias)
    for linha in (0, 2):
        painel._list.item(linha).setSelected(True)
    painel._remove.click()
    assert [m.path.name for m in painel._media] == ["b.mp4", "d.mp4"]
    assert painel._list.count() == 2


def test_o_cursor_vira_mao_so_sobre_o_x(painel, desktop_app):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    _inspecionado(painel, desktop_app, _video("a.mp4"))
    retangulo = painel._list.visualItemRect(painel._list.item(0))
    for ponto, esperado in ((convert_rows.RowDelegate.remove_rect(retangulo.width()).center(), Qt.CursorShape.PointingHandCursor),
                            (retangulo.center() - retangulo.topLeft(), Qt.CursorShape.ArrowCursor)):
        alvo = retangulo.topLeft() + ponto
        painel._list.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(alvo), QPointF(painel._list.viewport().mapToGlobal(alvo)),
                                                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        assert painel._list.viewport().cursor().shape() == esperado


# -- cabeçalho ------------------------------------------------------------------------------------------------

def test_o_selo_do_titulo_conta_arquivos_e_tamanho(painel, desktop_app):
    assert not painel._files_chip.isVisibleTo(painel)
    _inspecionado(painel, desktop_app, _video("a.mp4", 1_000_000))
    assert painel._files_chip.isVisibleTo(painel) and painel._files_chip.text().startswith("1 arquivo ·")
    _inspecionado(painel, desktop_app, _musica("b.mp3", 500_000))
    assert painel._files_chip.text().startswith("2 arquivos ·")
    apply_language(i18n.ENGLISH)
    assert painel._files_chip.text().startswith("2 files ·")
    painel.clear_files()
    assert not painel._files_chip.isVisibleTo(painel)


# -- modos segmentados ----------------------------------------------------------------------------------------

def test_os_tres_modos_continuam_exclusivos_e_as_setas_trocam_de_modo(painel, desktop_app):
    botoes = (painel._to_audio, painel._to_video, painel._to_compress)
    assert [b.isChecked() for b in botoes] == [True, False, False]
    painel._to_video.click()
    assert [b.isChecked() for b in botoes] == [False, True, False]
    assert painel._container.isVisibleTo(painel) and not painel._audio_codec.isVisibleTo(painel)
    painel._to_video.setFocus()
    QTest.keyClick(painel._to_video, Qt.Key.Key_Right)
    assert painel._to_compress.isChecked() and painel._level_table.isVisibleTo(painel)
    QTest.keyClick(painel._to_compress, Qt.Key.Key_Left)
    assert painel._to_video.isChecked()


def test_o_modo_marcado_se_distingue_no_desenho(painel, desktop_app):
    antes = painel._to_video.grab().toImage()
    painel._to_video.click()
    for _ in range(2):
        desktop_app.processEvents()
    assert painel._to_video.grab().toImage() != antes


# -- resumo e rodapé ------------------------------------------------------------------------------------------

def test_o_resumo_so_aparece_com_arquivos_e_traz_o_titulo(painel, desktop_app):
    assert not painel._plan_box.isVisibleTo(painel) and painel._plan.isHidden()
    _inspecionado(painel, desktop_app, _video("a.mp4"))
    assert painel._plan_box.isVisibleTo(painel) and not painel._plan.isHidden()
    # O título ("O que vai acontecer") é do destaque; o texto do resumo não o repete.
    assert strings.CONVERT_PLAN_TITLE.lower() not in painel._plan.text().lower()
    painel.clear_files()
    assert not painel._plan_box.isVisibleTo(painel)


def test_o_rodape_mostra_o_mesmo_tamanho_que_o_resumo(painel, desktop_app):
    assert painel._estimate_label.text() == DASH and not painel._start.isEnabled()
    _inspecionado(painel, desktop_app, _video("a.mp4"), _musica("b.mp3"))
    assert painel._start.isEnabled()
    assert painel._estimate_label.text() != DASH
    assert painel._estimate_label.text() in painel._plan.text()
    painel._to_video.click()
    assert painel._estimate_label.text() in painel._plan.text()
    painel.clear_files()
    assert painel._estimate_label.text() == DASH and not painel._start.isEnabled()


def test_salvar_na_mesma_pasta_continua_no_rodape_e_marcado(painel):
    assert painel._same_folder.isChecked()
    assert painel._same_folder.parent() is painel._start.parent()
