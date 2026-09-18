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
from videomanager.domain.timing import last_frame_time
from videomanager.infrastructure.ffmpeg.composer import frame_command, playback_command
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
    # Primeiro quadro da grade do projeto que já cai no segundo bloco — com
    # 29,97 q/s o corte não coincide com a grade, e o instante 2,0 ainda mostra
    # o fim do primeiro bloco.
    depois = math.ceil(2.0 * project_fps - 1e-6) / project_fps
    for moment, expected in ((10 * step, 10), (10.4 * step, 10), (10.9 * step, 10),
                             (2.0 - 0.5 * step, last), (depois, math.floor((depois - 2.0) * fps + 1e-6)),
                             (4.0 - 0.5 * step, last), (4.0, last)):
        shown = _shown(tools, project, moment)
        assert shown is not None, f"preto em {moment:.4f} s"
        assert shown == pytest.approx(expected, abs=0.5), f"em {moment:.4f} s"


@pytest.mark.parametrize("pausa", [4, 60, 200])
def test_gif_com_pausa_no_fim_mostra_o_ultimo_quadro(tools, tmp_path, pausa):
    """Um GIF pode segurar o último quadro por segundos.

    A taxa declarada não descreve isso: com uma pausa de 2 s no fim, a grade
    aponta para um instante onde não há quadro nenhum e a tela ficava preta. O
    instante real do último quadro é lido do arquivo (ver ``lastframe``).
    """
    path = tmp_path / f"pausa{pausa}.gif"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=160x90:r=10", "-frames:v", "40", "-final_delay", str(pausa), str(path)],
                   check=True, timeout=60, **subprocess_kwargs())
    media = media_ref(probe_file(path, tools))
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(media, 0, media.duration),)),),
                      width=160, height=90, fps=30.0)
    último = last_frame_time(project.duration, project.fps)
    parado = subprocess.run(frame_command(project, último, (160, 90), tools), check=True, timeout=60,
                            **subprocess_kwargs()).stdout
    assert len(parado) == 160 * 90 * 3
    assert sum(parado) / len(parado) > 8, f"tela preta com pausa de {pausa} cs no fim"


def test_gif_de_passo_irregular_mostra_o_ultimo_quadro(tools, tmp_path):
    """O fim de um GIF não pode ficar preto (o caso que apareceu no uso real).

    Um GIF guarda a duração de cada quadro em centésimos de segundo: a 30 q/s
    os passos alternam 3 e 4 cs, e ao fim de 128 quadros o último começa 37 ms
    antes do que a grade da taxa declarada diz — mais de um quadro. Buscar
    direto ali não achava quadro nenhum.
    """
    path = tmp_path / "irregular.gif"
    # 128 quadros a 30 q/s e o último com 4 cs: duração 4,27 s, mas o último
    # quadro começa em 4,23 s. É o arquivo que apareceu no uso real.
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=160x90:r=30", "-frames:v", "128", "-final_delay", "4", str(path)],
                   check=True, timeout=60, **subprocess_kwargs())
    media = media_ref(probe_file(path, tools))
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(media, 0, media.duration),)),),
                      width=160, height=90, fps=30.0)
    size = (160, 90)
    último = last_frame_time(project.duration, project.fps)
    parado = subprocess.run(frame_command(project, último, size, tools), check=True, timeout=60,
                            **subprocess_kwargs()).stdout
    assert sum(parado) / len(parado) > 8, "a tela ficou preta no fim do GIF"

    # E é o mesmo quadro que a reprodução mostra ali: ela começa antes e segue
    # até o fim, então o último quadro entregue é o deste instante.
    fluxo = subprocess.run(playback_command(project, último - 5 / project.fps, size, tools,
                                            fps=project.fps), timeout=60, **subprocess_kwargs()).stdout
    inteiros = len(fluxo) // len(parado)
    assert inteiros >= 5, "a reprodução do fim entregou poucos quadros"
    tocado = fluxo[(inteiros - 1) * len(parado):inteiros * len(parado)]
    diferença = sum(abs(a - b) for a, b in zip(parado, tocado)) / len(parado)
    assert diferença < 8, f"quadro parado e reprodução diferem (média {diferença:.1f})"


def test_imagem_animada_e_composta_no_instante_exato_da_agulha(tools, tmp_path):
    """A imagem animada é desenhada no mesmo instante em que a caixa é calculada.

    O quadro parado chegou a ser composto no começo do quadro da grade enquanto
    a caixa de seleção seguia o instante exato da agulha: com escala e posição
    animadas, as duas se desencontravam em até 8 px (regressão de f2a8905).
    Numa animação linear, o meio de dois quadros tem de cair no meio deles.
    """
    from videomanager.domain.keyframe import Keyframe
    from videomanager.domain.project import MediaKind, MediaRef

    foto = tmp_path / "foto.png"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=64x64", "-frames:v", "1", str(foto)], check=True, timeout=60,
                   **subprocess_kwargs())
    imagem = MediaRef(foto, MediaKind.IMAGE, width=64, height=64)
    anda = (Keyframe(0.0, x=0.2, y=0.5, scale_x=0.3, scale_y=0.3),
            Keyframe(2.0, x=0.8, y=0.5, scale_x=0.3, scale_y=0.3))
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(imagem, 0, 3.0, x=0.2, scale=0.3, scale_x=0.3,
                                                                 scale_y=0.3, keyframes=anda),)),),
                      width=640, height=360, fps=30.0)
    size = (640, 360)

    def centro(instante):
        dados = subprocess.run(frame_command(project, instante, size, tools), check=True, timeout=60,
                               **subprocess_kwargs()).stdout
        linha = 180 * 640 * 3
        xs = [x for x in range(640) if dados[linha + x * 3] > 150 and dados[linha + x * 3 + 1] < 80]
        assert xs, f"imagem não encontrada em {instante}"
        return (min(xs) + max(xs) + 1) / 2

    antes, depois = centro(15 / 30), centro(16 / 30)
    meio = centro(15.5 / 30)
    assert abs(depois - antes) > 5, "a animação precisa andar entre um quadro e outro"
    assert meio == pytest.approx((antes + depois) / 2, abs=1.0)
