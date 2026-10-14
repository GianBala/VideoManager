"""A prévia encaixa o vídeo na tela como a exportação: sem fio preto onde ele a preencheria.

A tela da prévia é a do projeto reduzida, e cada lado da redução cai para o par
abaixo (1920×1080 na caixa 596×508 vira 592×334, que já não é 16:9). Encaixar o
vídeo por pixels nessa tela deixava 1 px preto em cima e embaixo — ou 2 px nas
laterais, conforme a janela — de um vídeo que preenche a tela do projeto, e a
borda de destaque da prévia ficava a um fio de distância da imagem. Nenhum erro,
nenhuma diferença de duração: só uma moldura que não encostava.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PySide6.QtGui import QPixmap

from videomanager.domain.preview import fit_size, reduced_fit
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, media_ref
from videomanager.infrastructure.ffmpeg.composer import frame_command
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.system import binaries

# Caixas que a janela de verdade produz (abrir em 1180×1000, maximizar, janela estreita…).
CAIXAS = [(596, 508), (1096, 609), (714, 324), (848, 479), (631, 277), (1000, 600)]


class TestContaDoEncaixe:
    def test_video_que_preenche_a_tela_preenche_a_tela_reduzida(self) -> None:
        assert reduced_fit(1920, 1080, 592, 334, 1920, 1080) == (592, 334)
        assert reduced_fit(1280, 720, 592, 334, 1920, 1080) == (592, 334)

    def test_proporcao_diferente_continua_com_barras(self) -> None:
        w, h = reduced_fit(1440, 1080, 592, 334, 1920, 1080)
        assert h == 334 and 440 <= w <= 448

    def test_sem_reducao_e_a_regra_de_sempre(self) -> None:
        assert reduced_fit(1440, 1080, 640, 360, 640, 360) == fit_size(1440, 1080, 640, 360)

    def test_largura_ou_altura_nunca_passam_da_tela(self) -> None:
        for canvas in ((592, 334), (576, 324), (568, 320), (1082, 608)):
            for media in ((1920, 1080), (1080, 1920), (1000, 1000), (3840, 1600)):
                w, h = reduced_fit(*media, *canvas, 1920, 1080)
                assert 2 <= w <= canvas[0] and 2 <= h <= canvas[1]


# ---------------------------------------------------------------------------
# O quadro que o ffmpeg entrega
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tools():
    found = binaries.find_tools()
    if found is None:
        pytest.skip("ffmpeg não disponível; rode a aplicação uma vez para provisioná-lo")
    return found


def _video(tools, pasta: Path, nome: str, tamanho: tuple[int, int]) -> MediaRef:
    arquivo = pasta / f"{nome}.mp4"
    subprocess.run([tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=lime:s={tamanho[0]}x{tamanho[1]}:r=30:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(arquivo)], check=True, capture_output=True)
    return media_ref(probe_file(arquivo, tools))


def _quadro(project: Project, caixa: tuple[int, int], tools) -> tuple[bytes, tuple[int, int]]:
    tamanho = fit_size(project.width, project.height, *caixa)
    dados = subprocess.run(frame_command(project, 0.5, tamanho, tools), capture_output=True, check=True).stdout
    assert len(dados) == tamanho[0] * tamanho[1] * 3
    return dados, tamanho


def _verde(dados: bytes, tamanho: tuple[int, int], x: int, y: int) -> bool:
    i = (y * tamanho[0] + x) * 3
    return dados[i + 1] > 150 and dados[i] < 150


@pytest.mark.ffmpeg
class TestQuadroDaPrevia:
    @pytest.mark.parametrize("caixa", CAIXAS)
    @pytest.mark.parametrize("tela", [(1920, 1080), (1280, 720), (1080, 1920)])
    def test_video_da_proporcao_da_tela_encosta_nas_quatro_bordas(self, tools, tmp_path, caixa, tela) -> None:
        midia = _video(tools, tmp_path, "v", tela)
        projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(midia, 0, 2),)),), width=tela[0], height=tela[1])
        dados, (w, h) = _quadro(projeto, caixa, tools)
        meio_x, meio_y = w // 2, h // 2
        pretos = {
            "esquerda": not _verde(dados, (w, h), 0, meio_y),
            "direita": not _verde(dados, (w, h), w - 1, meio_y),
            "topo": not _verde(dados, (w, h), meio_x, 0),
            "base": not _verde(dados, (w, h), meio_x, h - 1),
        }
        assert not any(pretos.values()), f"borda preta no quadro {w}×{h}: {pretos}"

    def test_proporcao_diferente_mantem_as_barras_pretas(self, tools, tmp_path) -> None:
        # O vão que se tira é o do arredondamento; a barra de um 4:3 numa tela 16:9 é conteúdo.
        midia = _video(tools, tmp_path, "v43", (1440, 1080))
        projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(midia, 0, 2),)),), width=1920, height=1080)
        dados, (w, h) = _quadro(projeto, (848, 479), tools)
        assert not _verde(dados, (w, h), 2, h // 2)
        assert _verde(dados, (w, h), w // 2, h // 2)
        assert _verde(dados, (w, h), w // 2, 0) and _verde(dados, (w, h), w // 2, h - 1)


# ---------------------------------------------------------------------------
# A caixa de seleção do Qt acompanha o que o ffmpeg desenhou
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("desktop_app")
@pytest.mark.parametrize("caixa", CAIXAS)
def test_caixa_do_video_sem_transformacao_e_a_tela_inteira(caixa) -> None:
    from videomanager.presentation.qt.panels.edit_widgets import _Preview

    clip = Clip(MediaRef(Path("v.mp4"), MediaKind.VIDEO, duration=4.0, width=1920, height=1080, fps=30.0), 0, 4)
    tamanho = fit_size(1920, 1080, *caixa)
    preview = _Preview()
    preview.resize(*tamanho)
    preview.set_frame_pixmap(QPixmap(*tamanho))
    preview.set_active_clip(clip, 1920, 1080)
    preview.set_position(1.0)
    cx, cy, w, h = preview._clip_geometry(clip)
    alvo = preview._video_rect()
    assert (cx - w / 2, cy - h / 2, w, h) == pytest.approx(
        (alvo.x(), alvo.y(), alvo.width(), alvo.height()), abs=1e-6)
