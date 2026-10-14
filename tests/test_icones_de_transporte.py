"""Transporte, desfazer, refazer e zoom: ícones desenhados, e não glifos de texto.

Eram texto (▶ ❚❚ ◀◀ ↶ ↷ − +) e dependiam de uma fonte com símbolos: sem ela cada um saía como um
quadrado (o Qt do Windows, por exemplo). Desenhados, saem iguais em qualquer sistema e na cor do tema.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMessageBox

from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import icons
from videomanager.presentation.qt.panels.edit_panel import EditPanel
from videomanager.presentation.qt.theme import apply as aplicar_tema
from videomanager.presentation.qt.theme import palette

_DESENHOS = ("play", "pause", "to_start", "to_end", "rewind", "fast_forward", "frame_back", "frame_forward",
             "undo", "redo", "plus", "minus")


def _imagem(icone, tamanho=18):
    return icone.pixmap(tamanho, tamanho).toImage()


def _pixels_opacos(imagem):
    return {(x, y) for x in range(imagem.width()) for y in range(imagem.height()) if imagem.pixelColor(x, y).alpha() > 200}


def _perto(a: str, b: str, tolerancia: int = 6) -> bool:
    """Cor igual, a menos do arredondamento do alfa pré-multiplicado nas bordas suaves."""
    ca, cb = QColor(a), QColor(b)
    return max(abs(ca.red() - cb.red()), abs(ca.green() - cb.green()), abs(ca.blue() - cb.blue())) <= tolerancia


def _so_a_cor(icone, cor: str) -> bool:
    imagem = _imagem(icone)
    return all(_perto(imagem.pixelColor(x, y).name(), cor) for x, y in _pixels_opacos(imagem))


@pytest.mark.parametrize("nome", _DESENHOS)
def test_cada_icone_desenha_algo_na_cor_pedida(desktop_app, nome):
    imagem = _imagem(getattr(icons, nome)("#ff8800"))
    opacos = _pixels_opacos(imagem)
    assert len(opacos) >= 6, f"{nome} saiu vazio"
    assert all(_perto(imagem.pixelColor(x, y).name(), "#ff8800") for x, y in opacos)


def test_os_icones_sao_diferentes_entre_si(desktop_app):
    formas = {nome: frozenset(_pixels_opacos(_imagem(getattr(icons, nome)("#ffffff")))) for nome in _DESENHOS}
    repetidos = [(a, b) for a in formas for b in formas if a < b and formas[a] == formas[b]]
    assert repetidos == []


def test_refazer_e_o_desfazer_espelhado(desktop_app):
    desfazer = _pixels_opacos(_imagem(icons.undo("#ffffff")))
    refazer = _pixels_opacos(_imagem(icons.redo("#ffffff")))
    espelhado = {(17 - x, y) for x, y in desfazer}
    # Bordas suaves não espelham pixel a pixel; a silhueta, sim.
    assert len(espelhado & refazer) / len(espelhado | refazer) >= 0.85
    assert desfazer != refazer


def test_play_e_pause_sao_pares_de_triangulo_e_duas_barras(desktop_app):
    play, pause = _pixels_opacos(_imagem(icons.play("#fff"))), _pixels_opacos(_imagem(icons.pause("#fff")))
    # As duas barras do pause deixam um vão vertical no meio; o triângulo do play não.
    meio = {x for x, _ in pause if 8 <= x <= 9}
    assert not meio and {x for x, _ in play if 8 <= x <= 9}


@pytest.fixture
def aplicacao(desktop_app):
    from videomanager.presentation.qt import theme
    antes = (desktop_app.palette(), desktop_app.styleSheet(), theme.atual())
    yield desktop_app
    desktop_app.setPalette(antes[0])
    desktop_app.setStyleSheet(antes[1])
    theme._atual = antes[2]


@pytest.fixture
def painel(aplicacao, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    instancia = EditPanel(Settings(), ensure_tools=lambda: None, editor=build_editor_service(),
                          processing=build_processing_service(), runtime=build_desktop_runtime())
    yield instancia
    instancia.shutdown()


def test_os_botoes_do_transporte_nao_tem_texto_e_tem_dica_e_icone(painel):
    for botao in painel._buttons[:7]:
        assert botao.text() == ""
        assert not botao.icon().isNull()
        assert botao.toolTip() != ""


def test_undo_redo_e_zoom_tem_icone_e_dica_sem_texto(painel):
    for botao in (painel._undo, painel._redo, painel._zoom_out_button, painel._zoom_in_button):
        assert botao.text() == "" and not botao.icon().isNull() and botao.toolTip() != ""


def test_o_play_vira_pause_e_volta(painel):
    play = _imagem(painel._play_button.icon())
    painel._playing = True
    painel._refresh_play_button()
    pause = _imagem(painel._play_button.icon())
    painel._playing = False
    painel._refresh_play_button()
    assert pause != play and _imagem(painel._play_button.icon()) == play


def test_trocar_de_tema_repinta_os_icones_do_transporte(painel, aplicacao):
    aplicar_tema(aplicacao, "dark")
    # Botão de ícone sem fundo leva a cor secundária (``.btn.ghost`` do protótipo), e não a do texto.
    assert _so_a_cor(painel._buttons[0].icon(), palette("dark")["text_dim"])
    aplicar_tema(aplicacao, "light")
    assert _so_a_cor(painel._buttons[0].icon(), palette("light")["text_dim"])
    # O play fica na cor do texto do botão primário, que é o fundo dele.
    assert _so_a_cor(painel._play_button.icon(), palette("light")["accent_text"])
