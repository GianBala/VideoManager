"""Linha do tempo: a cor e o ícone de cada espécie de bloco e o cabeçalho de trilha com ícone.

É só pintura (a geometria de acerto — ``_hit``, o ímã, as alças — tem os testes de gesto de sempre, com eventos
reais, e não foi tocada). O que a pintura nova pode errar sem exceção: o bloco de áudio na cor do vídeo, o texto
sem a cor dele, o cabeçalho sem o ladrilho, o emoji de volta no rótulo.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QPainter

from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.presentation.qt.panels import timeline as modulo
from videomanager.presentation.qt.panels.timeline import HEADER_WIDTH, Timeline
from videomanager.presentation.qt.theme import DARK, TIPOS_DE_BLOCO

pytestmark = pytest.mark.usefixtures("desktop_app")

VIDEO = MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=30, width=320, height=180, has_audio=True)
MUSICA = MediaRef(Path("/m/musica.mp3"), MediaKind.AUDIO, duration=30, has_audio=True)
FOTO = MediaRef(Path("/m/foto.png"), MediaKind.IMAGE, duration=5, width=100, height=100)


def _projeto() -> tuple[Project, dict[str, Clip]]:
    blocos = {
        "video": Clip(VIDEO, 0, 6),
        "audio": Clip(MUSICA, 0, 6),
        "text": Clip(MediaRef(Path("Texto_x"), MediaKind.IMAGE, duration=3.0), 0.5, 3.0, overlay_type="text",
                     text_content="Olá"),
        "filter": Clip(MediaRef(Path("Filtro_x"), MediaKind.IMAGE, duration=3.0), 4.0, 2.0, overlay_type="filter",
                       filter_name="sepia"),
        "image": Clip(FOTO, 1.0, 3.0),
    }
    esquerda, direita = Clip(VIDEO, 0, 3), Clip(VIDEO, 3, 3)
    transicao = Clip(MediaRef(Path("Transicao"), MediaKind.IMAGE, duration=1.0), 2.5, 1.0, overlay_type="transition",
                     transition_name="dissolve", transition_left_id=esquerda.clip_id, transition_right_id=direita.clip_id)
    blocos["transition"] = transicao
    projeto = Project(tracks=(
        Track(TrackKind.ADDITIONAL, clips=(blocos["text"], blocos["filter"]), name="Adicionais 1"),
        Track(TrackKind.VIDEO, clips=(blocos["image"],), name="Vídeo 2"),
        Track(TrackKind.VIDEO, clips=(esquerda, transicao, direita), name="Vídeo 1"),
        Track(TrackKind.AUDIO, clips=(blocos["audio"],), name="Áudio 1"),
    ), width=1280, height=720, fps=30.0)
    blocos["video"] = esquerda
    return projeto, blocos


@pytest.fixture
def linha():
    projeto, blocos = _projeto()
    timeline = Timeline(DARK)
    timeline.set_project(projeto)
    timeline.resize(1000, 320)
    timeline.set_view(0, 8)
    return timeline, blocos


def _faixa_de(timeline, bloco, trilha: int):
    return timeline._clip_rect(trilha, bloco)


# -- espécie --------------------------------------------------------------------------------------------------

def test_cada_bloco_tem_a_espécie_dele_e_nao_a_da_midia(linha):
    timeline, blocos = linha
    trilhas = timeline.project.tracks
    esperado = {"text": 0, "filter": 0, "image": 1, "video": 2, "transition": 2, "audio": 3}
    for tipo, indice in esperado.items():
        assert timeline._tipo(blocos[tipo], trilhas[indice]) == tipo, tipo
    # O áudio separado de um vídeo é áudio, mesmo vindo de um arquivo com imagem.
    separado = Clip(VIDEO, 0, 3, detached=True)
    assert timeline._tipo(separado, trilhas[3]) == "audio"


def test_as_espécies_tem_cor_e_icone_proprios():
    assert set(TIPOS_DE_BLOCO) == set(modulo._ICONES_DO_TIPO) == {"video", "audio", "text", "image", "filter", "transition"}
    assert len(set(TIPOS_DE_BLOCO.values())) == len(TIPOS_DE_BLOCO)


# -- pintura --------------------------------------------------------------------------------------------------

def _pixel_no_topo(timeline, bloco, trilha: int) -> QColor:
    imagem = timeline.grab().toImage()
    caixa = _faixa_de(timeline, bloco, trilha)
    return imagem.pixelColor(int(caixa.left()) + 12, int(caixa.top()) + 1)


@pytest.mark.parametrize("tipo,trilha", [("video", 2), ("audio", 3), ("text", 0), ("image", 1), ("filter", 0)])
def test_o_topo_de_cada_bloco_leva_a_cor_da_espécie(linha, tipo, trilha):
    timeline, blocos = linha
    obtido = _pixel_no_topo(timeline, blocos[tipo], trilha)
    esperado = QColor(TIPOS_DE_BLOCO[tipo])
    assert (obtido.red(), obtido.green(), obtido.blue()) == (esperado.red(), esperado.green(), esperado.blue()), tipo


def test_o_cabecalho_de_cada_trilha_leva_o_ladrilho_da_cor_dela(linha):
    timeline, _ = linha
    imagem = timeline.grab().toImage()
    for indice, tipo in enumerate(("text", "video", "video", "audio")):
        cabecalho = timeline._header_rect(indice)
        # O ladrilho de 24 px é cheio, da cor da espécie: dois pixels para dentro da borda esquerda dele, no meio da altura
        # (o ícone branco fica no centro, longe daí).
        pixel = imagem.pixelColor(int(cabecalho.left()) + 10 + 3, int(cabecalho.center().y()))
        alvo = QColor(TIPOS_DE_BLOCO[tipo])
        assert max(abs(a - b) for a, b in zip((pixel.red(), pixel.green(), pixel.blue()),
                                              (alvo.red(), alvo.green(), alvo.blue()))) <= 4, (indice, tipo)


def test_o_rotulo_do_bloco_nao_leva_mais_emoji_e_o_ícone_se_desenha(linha, monkeypatch):
    timeline, _ = linha
    escritos: list[str] = []
    original = QPainter.drawText

    def gravar(pintor, *args):
        escritos.extend(a for a in args if isinstance(a, str))
        return original(pintor, *args)

    monkeypatch.setattr(QPainter, "drawText", gravar)
    timeline.grab()
    rotulos = [t for t in escritos if t.strip()]
    assert any("Olá" in t for t in rotulos)
    assert not any(emoji in t for t in rotulos for emoji in ("🔤", "🎨", "⏳", "🖼"))


def test_o_titulo_comprido_da_trilha_nao_invade_os_botoes(linha):
    timeline, _ = linha
    projeto = timeline.project
    longo = projeto.tracks[2]
    from dataclasses import replace
    timeline.set_project(replace(projeto, tracks=tuple(replace(t, name="Um nome de trilha muito comprido") if t is longo else t
                                                       for t in projeto.tracks)))
    imagem = timeline.grab().toImage()
    assert not imagem.isNull()
    # A área do título termina antes do olho e do mudo: a geometria dos botões segue a de sempre.
    cabecalho = timeline._header_rect(2)
    assert timeline._mute_rect(2).left() < cabecalho.right() <= HEADER_WIDTH
