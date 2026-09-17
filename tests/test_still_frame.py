"""Quadro parado da prévia no meio de um quadro, nos cortes e no fim.

A fonte tem brilho ``40 + 3 × número do quadro``, então o brilho diz qual quadro
a prévia mostrou. Antes da correção, com a agulha no meio do quadro 10 vinha o
11, e meio quadro antes de um corte ou do fim a tela ficava preta — com um GIF e
zoom máximo isso aparecia na hora.
"""

import math
import subprocess

import pytest

from videomanager.domain.project import Clip, Project, Track, TrackKind, media_ref
from videomanager.infrastructure.ffmpeg.composer import frame_command
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs

pytestmark = pytest.mark.ffmpeg
SIZE = (64, 36)


@pytest.fixture
def tools():
    found = find_tools()
    if found is None:
        pytest.skip("FFmpeg não disponível")
    return found


def _numbered(tools, path, fps, *extra):
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c=black:s=64x36:r={fps:.6f}:d=2", "-vf",
                    "geq=lum='40+N*3':cb=128:cr=128,format=yuv444p", *extra, str(path)],
                   check=True, timeout=60, **subprocess_kwargs())
    return media_ref(probe_file(path, tools))


def _shown(tools, project, seconds):
    data = subprocess.run(frame_command(project, seconds, SIZE, tools), check=True, timeout=60,
                          **subprocess_kwargs()).stdout
    assert len(data) == SIZE[0] * SIZE[1] * 3
    red = sum(data[0::3]) / (len(data) / 3)
    if red < 8:
        return None  # preto: nenhum quadro
    return (red * 219 / 255 + 16 - 40) / 3


@pytest.mark.parametrize(("name", "fps", "extra", "project_fps"), [
    ("numerado.mkv", 30, ("-c:v", "ffv1"), 30),
    ("numerado.gif", 10, (), 10),
    ("numerado.gif", 10, (), 30),
    # Quadros B e tempos arredondados do mp4: o caso mais sensível à busca.
    ("numerado.mp4", 30000 / 1001, ("-c:v", "libx264", "-bf", "3", "-g", "12", "-crf", "4",
                                    "-pix_fmt", "yuv420p"), 30000 / 1001),
])
def test_quadro_parado_mostra_o_quadro_que_contem_o_instante(tools, tmp_path, name, fps, extra, project_fps):
    media = _numbered(tools, tmp_path / name, fps, *extra)
    first, second = Clip(media, 0, 2.0), Clip(media, 2.0, 2.0)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(first, second)),), width=64, height=36,
                      fps=project_fps)
    step, last = 1 / fps, math.ceil(fps * 2 - 1e-6) - 1
    for moment, expected in ((10 * step, 10), (10.4 * step, 10), (10.9 * step, 10),
                             (2.0 - 0.5 * step, last), (2.0, 0), (4.0 - 0.5 * step, last), (4.0, last)):
        shown = _shown(tools, project, moment)
        assert shown is not None, f"preto em {moment:.4f} s"
        assert shown == pytest.approx(expected, abs=0.5), f"em {moment:.4f} s"
