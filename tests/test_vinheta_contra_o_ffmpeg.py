"""A conta da vinheta cai onde o filtro do ffmpeg cai."""

from __future__ import annotations

import subprocess

import pytest

from videomanager.domain.vignette import vignette_factors
from videomanager.infrastructure.system.binaries import find_tools


@pytest.mark.ffmpeg
@pytest.mark.parametrize("largura, altura", [(400, 200), (320, 180), (192, 108), (100, 100), (64, 200), (30, 12)])
def test_a_mascara_em_python_bate_com_a_do_ffmpeg_em_um_nivel_de_255(largura, altura):
    """Um quadro branco passado pela vinheta é a própria máscara; a diferença máxima medida é de 1."""
    tools = find_tools()
    if tools is None:
        pytest.skip("FFmpeg não disponível")
    saida = subprocess.run(
        [tools.ffmpeg_str, "-v", "error", "-f", "lavfi", "-i", f"color=c=white:s={largura}x{altura}:d=0.1,format=rgba",
         "-vf", "vignette=PI/4", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
        capture_output=True, check=True, timeout=30).stdout
    meu = vignette_factors(largura, altura)
    assert len(saida) == len(meu)
    assert max(abs(a - b) for a, b in zip(saida, meu)) <= 1
