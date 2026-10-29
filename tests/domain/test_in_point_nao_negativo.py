"""``in_point`` nunca é negativo por resto de ponto flutuante.

Puxar a ponta inicial de um bloco até o primeiro quadro da mídia dava ``in_point`` = -4e-16 (a conta de ida e volta de
``start - in_point / speed`` erra por 1 ulp). O .vmp gravava o número e o leitor o recusava: o projeto não reabria. O
teste aleatório do modelo (32 000 operações) achou; a regra mora no ``Clip``, que é por onde toda conta passa.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, TrackKind

VIDEO = MediaRef(Path("v.mp4"), MediaKind.VIDEO, duration=20.0, width=1920, height=1080, fps=30.0, has_audio=True)
AUDIO = MediaRef(Path("a.mp3"), MediaKind.AUDIO, duration=30.0, has_audio=True)


def test_um_resto_de_ponto_flutuante_negativo_vira_zero():
    assert Clip(VIDEO, 0.0, 2.0, in_point=-4.440892098500626e-16).in_point == 0.0


def test_um_negativo_de_verdade_continua_negativo_para_o_defeito_aparecer():
    assert Clip(VIDEO, 0.0, 2.0, in_point=-0.25).in_point == -0.25


@pytest.mark.parametrize("velocidade", [0.25, 0.5, 1.0, 1.5, 2.0, 4.0])
def test_puxar_a_ponta_inicial_ate_o_comeco_da_midia_deixa_o_in_point_em_zero(velocidade):
    sorteio = random.Random(11)
    for _ in range(300):
        midia = sorteio.choice((VIDEO, AUDIO))
        bloco = Clip(midia, round(sorteio.uniform(0.5, 9), 3), round(sorteio.uniform(0.5, 4), 3),
                     in_point=round(sorteio.uniform(0.05, 6), 3), speed=velocidade)
        projeto = Project(tracks=(), width=1920, height=1080, fps=30.0).with_track(
            TrackKind.AUDIO if midia is AUDIO else TrackKind.VIDEO).with_clip(0, bloco)
        depois = projeto.resized(bloco.clip_id, "inicio", 0.0).tracks[0].clips[0]
        assert depois.in_point >= 0.0, f"in_point {depois.in_point!r} (início {bloco.start}, in {bloco.in_point}, vel {velocidade})"


def test_dividir_e_soltar_em_outra_trilha_tambem_nao_dao_in_point_negativo():
    sorteio = random.Random(5)
    for _ in range(300):
        bloco = Clip(VIDEO, round(sorteio.uniform(0.0, 5), 3), round(sorteio.uniform(1.0, 4), 3),
                     in_point=round(sorteio.uniform(0, 6), 3), speed=sorteio.choice((0.5, 1.0, 1.5, 2.0)))
        projeto = Project(tracks=(), width=1920, height=1080, fps=30.0).with_track(TrackKind.VIDEO).with_track(
            TrackKind.VIDEO).with_clip(0, bloco)
        dividido = projeto.split(bloco.clip_id, round(bloco.start + bloco.duration * sorteio.uniform(0.1, 0.9), 3))
        movido = dividido.moved(bloco.clip_id, 1, round(sorteio.uniform(0, 8), 3))
        for variante in (dividido, movido):
            assert all(c.in_point >= 0.0 for t in variante.tracks for c in t.clips)
