"""Trocar de tema ou de paleta com o editor aberto: as cores seguem, e o resto não mexe.

``QApplication.setStyleSheet`` não alcança o que o editor pintou na construção: o dicionário de
cores que a linha do tempo guarda, os ícones da barra (pintados com a cor do texto) e a onda
sonora (renderizada pelo ffmpeg já na cor de destaque). Sem refazê-los, a troca de tema
deixava o editor na paleta antiga até reiniciar, e a aba Tema entregaria exatamente isso.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMessageBox

from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import theme
from videomanager.presentation.qt.panels.edit_panel import EditPanel
from videomanager.presentation.qt.theme import apply as aplicar_tema
from videomanager.presentation.qt.theme import palette


def _ouvintes_fortes() -> list:
    """Os ouvintes que o ``theme`` guarda por referência forte: função solta e ``lambda``. Só método tem referência fraca."""
    return [ouvinte for ouvinte in theme._ouvintes if not isinstance(ouvinte, weakref.ref)]


@pytest.fixture(scope="module", autouse=True)
def sem_ouvinte_forte_esquecido():
    """Nenhum teste deste arquivo deixa para trás um ouvinte de tema que nunca sai da lista (``TST-002``).

    ``on_theme_change`` guarda função solta e ``lambda`` por referência forte, e cada ``theme.apply`` seguinte da sessão
    os chama de novo: um que levanta enche o log de tracebacks, e um que acumula numa lista cresce para sempre.
    """
    antes = _ouvintes_fortes()
    yield
    assert _ouvintes_fortes() == antes, "um teste registrou um ouvinte de tema e não o desfez"


@pytest.fixture
def aplicacao(desktop_app):
    """A aplicação, devolvida ao tema que tinha: a troca é estado global e vazaria para outros testes."""
    antes = (desktop_app.palette(), desktop_app.styleSheet(), theme.atual(), list(theme._ouvintes))
    yield desktop_app
    desktop_app.setPalette(antes[0])
    desktop_app.setStyleSheet(antes[1])
    theme._atual = antes[2]
    # Os ouvintes registrados durante o teste (a função que levanta, o ``lambda``) saem junto: a lista é a mesma de antes.
    theme._ouvintes[:] = antes[3]


@pytest.fixture
def painel(aplicacao, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    instancia = EditPanel(Settings(), ensure_tools=lambda: None, editor=build_editor_service(),
                          processing=build_processing_service(), runtime=build_desktop_runtime())
    yield instancia
    instancia.shutdown()


@pytest.fixture
def projeto(painel):
    video = Clip(MediaRef(Path("a.mp4"), MediaKind.VIDEO, duration=6.0, width=1280, height=720, fps=30.0,
                          has_audio=True), start=0.0, duration=6.0)
    audio = Clip(MediaRef(Path("m.mp3"), MediaKind.AUDIO, duration=10.0, has_audio=True), start=0.0, duration=10.0)
    novo = Project(tracks=(Track(TrackKind.VIDEO, clips=(video,), name="Vídeo 1"),
                           Track(TrackKind.AUDIO, clips=(audio,), name="Áudio 1")),
                   width=1280, height=720, fps=30.0)
    painel._apply(novo)
    return SimpleProjeto(painel._project, audio)


class SimpleProjeto:
    def __init__(self, projeto, audio):
        self.projeto, self.audio = projeto, audio


def _cor_principal(icone) -> str:
    """A cor do pixel mais opaco do ícone: o traço, e não o anti-serrilhado em volta dele."""
    imagem = icone.pixmap(18, 18).toImage()
    pixels = [imagem.pixelColor(x, y) for x in range(imagem.width()) for y in range(imagem.height())]
    return max(pixels, key=lambda cor: cor.alpha()).name()


def test_trocar_de_modo_refaz_o_dicionario_no_mesmo_objeto(painel, aplicacao):
    dicionario = painel._colors
    aplicar_tema(aplicacao, "light")
    assert painel._colors is dicionario and painel._timeline._c is dicionario
    assert dicionario == palette("light")
    assert painel._timeline._color("bg").name() == palette("light")["bg"]
    aplicar_tema(aplicacao, "dark")
    assert dicionario == palette("dark")


def test_trocar_de_paleta_muda_o_destaque_que_a_linha_do_tempo_usa(painel, aplicacao):
    aplicar_tema(aplicacao, "dark", "aurora")
    assert painel._colors["accent"] == palette("dark", "aurora")["accent"]
    assert painel._colors["accent"] != palette("dark")["accent"]


def test_icones_da_barra_seguem_a_cor_secundaria_e_so_os_botoes_com_fundo_a_do_texto(painel, aplicacao):
    aplicar_tema(aplicacao, "dark")
    escuro = _cor_principal(painel._split_button.icon())
    aplicar_tema(aplicacao, "light")
    claro = _cor_principal(painel._split_button.icon())
    assert escuro == palette("dark")["text_dim"] and claro == palette("light")["text_dim"]
    # Os traços finos de alguns ícones saem 1 de diferença num canal depois da transparência: compara-se com tolerância.
    alvo = QColor(palette("light")["text_dim"])
    for botao in (painel._trim_left_button, painel._trim_right_button, painel._delete_button, painel._undo, painel._redo,
                  painel._zoom_out_button, painel._zoom_in_button):
        cor = QColor(_cor_principal(botao.icon()))
        assert max(abs(cor.red() - alvo.red()), abs(cor.green() - alvo.green()), abs(cor.blue() - alvo.blue())) <= 2, botao
    # "Ver tudo", volume e velocidade têm fundo (``.btn`` do protótipo, não ``.ghost``): ficam na cor do texto.
    for botao in (painel._fit_button, painel._volume_btn, painel._speed_btn):
        assert _cor_principal(botao.icon()) == palette("light")["text"]


def test_onda_sonora_ja_gerada_e_pedida_de_novo(painel, projeto, aplicacao):
    from PySide6.QtGui import QImage
    painel._timeline.set_wave(projeto.audio.clip_id, 0.0, 10.0, QImage(10, 4, QImage.Format.Format_ARGB32))
    assert painel._timeline.strip_range(projeto.audio.clip_id) is not None
    aplicar_tema(aplicacao, "light")
    assert painel._timeline.strip_range(projeto.audio.clip_id) is None


def test_trocar_de_tema_nao_mexe_no_projeto_nem_no_historico(painel, projeto, aplicacao):
    antes = painel._project
    tinha_alteracao = painel.has_unsaved_changes
    posicao, tocando = painel._position, painel._playing
    aplicar_tema(aplicacao, "light")
    aplicar_tema(aplicacao, "dark", "cinema")
    assert painel._project is antes
    assert painel.has_unsaved_changes == tinha_alteracao
    assert (painel._position, painel._playing) == (posicao, tocando)


def test_painel_fechado_nao_atrapalha_a_troca(aplicacao, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    morto = EditPanel(Settings(), ensure_tools=lambda: None, editor=build_editor_service(),
                      processing=build_processing_service(), runtime=build_desktop_runtime())
    morto.shutdown()
    morto.deleteLater()
    del morto
    aplicar_tema(aplicacao, "light")  # a referência fraca morreu: nada a chamar, e nada quebra


def test_ouvinte_de_metodo_nao_segura_o_objeto_vivo(aplicacao):
    import gc
    import weakref

    class Ouvinte:
        chamadas = 0

        def mudou(self):
            Ouvinte.chamadas += 1

    objeto = Ouvinte()
    referencia = weakref.ref(objeto)
    theme.on_theme_change(objeto.mudou)
    aplicar_tema(aplicacao, "dark")
    assert Ouvinte.chamadas == 1
    del objeto
    gc.collect()
    assert referencia() is None


def test_um_ouvinte_com_defeito_nao_deixa_os_outros_na_paleta_antiga(aplicacao):
    visto = []

    def quebra():
        raise RuntimeError("defeito proposital")

    theme.on_theme_change(quebra)
    theme.on_theme_change(lambda: visto.append(theme.atual()))
    aplicar_tema(aplicacao, "light", "mare")
    assert visto[-1] == ("light", "mare")
    assert theme.atual() == ("light", "mare")
