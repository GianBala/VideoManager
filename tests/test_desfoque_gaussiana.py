"""A gaussiana da prévia do arrasto cai onde o ``gblur`` do ffmpeg cai."""

from __future__ import annotations

import random
import subprocess

import pytest

from videomanager.domain.constants import REGION_BLUR_STEPS
from videomanager.domain.gaussian import gaussian_blur
from videomanager.domain.geometry import region_work_size
from videomanager.infrastructure.system.binaries import find_tools
from videomanager.infrastructure.system.binaries import subprocess_kwargs


@pytest.mark.ffmpeg
@pytest.mark.parametrize("regiao", [(288, 162), (160, 160), (480, 160), (100, 400), (900, 40)],
                         ids=lambda r: f"{r[0]}x{r[1]}")
def test_a_gaussiana_em_python_bate_com_o_gblur_do_ffmpeg(regiao):
    """Medido em ruído (o pior caso para um filtro de suavização): no máximo 1 em 255, que é o arredondamento de float."""
    tools = find_tools()
    if tools is None:
        pytest.skip("FFmpeg não disponível")
    w, h, sigma = region_work_size(*regiao)
    assert min(w, h) == 16        # abaixo disso o gblur do ffmpeg deixa linhas sem filtrar
    ruido = bytes(random.Random(w * h).randrange(256) for _ in range(w * h * 3))
    saida = subprocess.run(
        [tools.ffmpeg_str, "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-i", "pipe:0",
         "-vf", f"format=gbrp,gblur=sigma={sigma:.4f}:steps={REGION_BLUR_STEPS},format=rgb24",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        input=ruido, capture_output=True, check=True, timeout=30,
        **{k: v for k, v in subprocess_kwargs().items() if k not in ("stdin", "stdout", "stderr")}).stdout
    for canal in range(3):
        meu = gaussian_blur(list(ruido[canal::3]), w, h, sigma, REGION_BLUR_STEPS)
        dele = list(saida[canal::3])
        assert max(abs(a - b) for a, b in zip(meu, dele)) <= 1, canal
