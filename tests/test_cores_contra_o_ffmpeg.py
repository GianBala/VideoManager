"""A conta dos filtros de cor em Python cai onde o ffmpeg cai, no mesmo caminho do compositor (``frame_command``)."""

from __future__ import annotations

import random
import re
import subprocess
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

from videomanager.domain.color_filters import SEPIA_MATRIX
from videomanager.domain.color_filters import apply_color_filter
from videomanager.domain.project import Clip
from videomanager.domain.project import OverlayType
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.domain.project import media_ref
from videomanager.domain.project import pseudo_media
from videomanager.infrastructure.ffmpeg.composer import _COLOR_FILTER_EXPRESSIONS
from videomanager.infrastructure.ffmpeg.composer import frame_command
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.system.binaries import find_tools
from videomanager.infrastructure.system.binaries import subprocess_kwargs

LARGURA, ALTURA = 256, 64
# Quanto a conta se afasta do ffmpeg, medido em ruído colorido e em rampas por canal (o cubo de cor inteiro).
LIMITE = {"inverter": 0, "pb": 1, "sepia": 2, "contraste": 4}


def test_a_matriz_do_sepia_do_dominio_e_a_do_compositor():
    numeros = [float(n) for n in re.findall(r"[.\d]+", _COLOR_FILTER_EXPRESSIONS["sepia"].split("=")[1])]
    assert len(numeros) == 11                                     # rr rg rb ra, gr gg gb ga, br bg bb
    assert SEPIA_MATRIX == (tuple(numeros[0:3]), tuple(numeros[4:7]), tuple(numeros[8:11]))


@pytest.fixture(scope="module")
def tools():
    achado = find_tools()
    if achado is None:
        pytest.skip("FFmpeg não disponível")
    return achado


@pytest.fixture(scope="module")
def cubo(tmp_path_factory) -> tuple[Path, bytes]:
    """Metade ruído colorido, metade rampas de cinza, vermelho, verde e azul. Devolve o PNG e os bytes RGB."""
    acaso = random.Random(7)
    cru = bytearray()
    for y in range(ALTURA):
        for x in range(LARGURA):
            if y < 32:
                cru += bytes(acaso.randrange(256) for _ in range(3))
            else:
                faixa = (y - 32) // 8
                cru += bytes((x, x, x) if faixa == 0 else (x, 0, 0) if faixa == 1 else (0, x, 0) if faixa == 2 else (0, 0, x))
    caminho = tmp_path_factory.mktemp("cubo") / "cubo.png"
    assert QImage(bytes(cru), LARGURA, ALTURA, LARGURA * 3, QImage.Format.Format_RGB888).save(str(caminho))
    return caminho, bytes(cru)


def _quadro(tools, caminho: Path, filtro: str | None) -> bytes:
    ref = probe_file(caminho, tools)
    trilhas = [Track(TrackKind.VIDEO, clips=(Clip(media_ref(ref), 0.0, 2.0),), name="V")]
    if filtro:
        bloco = Clip(pseudo_media(OverlayType.FILTER, filtro, 2.0), 0.0, 2.0, overlay_type="filter", filter_name=filtro)
        trilhas.insert(0, Track(TrackKind.ADDITIONAL, clips=(bloco,), name="F"))
    projeto = Project(tracks=tuple(trilhas), width=LARGURA, height=ALTURA, fps=30.0)
    saida = subprocess.run(frame_command(projeto, 0.5, (LARGURA, ALTURA), tools), check=True, timeout=60,
                           **subprocess_kwargs()).stdout
    assert len(saida) == LARGURA * ALTURA * 3
    return saida


@pytest.mark.ffmpeg
@pytest.mark.parametrize("nome", list(LIMITE))
def test_o_filtro_em_python_bate_com_o_do_ffmpeg(tools, cubo, nome):
    caminho, _ = cubo
    origem, filtrado = _quadro(tools, caminho, None), _quadro(tools, caminho, nome)
    rgbx = bytearray(LARGURA * ALTURA * 4)
    rgbx[0::4], rgbx[1::4], rgbx[2::4], rgbx[3::4] = origem[0::3], origem[1::3], origem[2::3], bytes([255]) * (LARGURA * ALTURA)
    meu = apply_color_filter(nome, bytes(rgbx))
    erro = max(abs(meu[4 * i + c] - filtrado[3 * i + c]) for i in range(LARGURA * ALTURA) for c in range(3))
    assert erro <= LIMITE[nome], erro
