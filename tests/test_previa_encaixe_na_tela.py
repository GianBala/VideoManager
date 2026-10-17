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

    def test_o_encaixe_e_o_par_mais_proximo_da_conta_exata(self) -> None:
        """Truncar ao par de baixo erra até 2 px (mídia 1920×1080 na tela 1080×1920, caixa 302×536: o exato é 169,69 de altura, e
        o par de baixo, 168); arredondar ao par mais próximo erra no máximo 1. Os testes de antes só usavam mídia 16:9 numa tela
        16:9, em que a conta sai exata e as duas regras coincidem."""
        assert reduced_fit(1920, 1080, 302, 536, 1080, 1920) == (302, 170)
        assert reduced_fit(1920, 1080, 308, 548, 1080, 1920) == (308, 174)
        assert reduced_fit(1000, 1000, 592, 334, 1920, 1080) == (334, 334)
        for media in ((1920, 1080), (1920, 800), (1440, 1080), (1080, 1920), (1000, 1000), (3840, 1600)):
            for cheia in ((1920, 1080), (1280, 720), (1080, 1920)):
                for largura in range(300, 1200, 14):
                    altura = round(largura * cheia[1] / cheia[0]) // 2 * 2
                    escala = min(cheia[0] / media[0], cheia[1] / media[1])
                    exato = (media[0] * escala * largura / cheia[0], media[1] * escala * altura / cheia[1])
                    w, h = reduced_fit(*media, largura, altura, *cheia)
                    assert abs(w - exato[0]) <= 1.0 and abs(h - exato[1]) <= 1.0, (media, (largura, altura), cheia, (w, h), exato)

    def test_a_conta_do_compositor_e_a_do_dominio_dao_o_mesmo_tamanho(self) -> None:
        """O encaixe tem duas contas, a da caixa de seleção (``reduced_fit``) e a do ``scale`` do ffmpeg (``_fit_scale``), e duas
        contas para a mesma decisão acabam discordando: a caixa deixava de encostar na imagem. A expressão do ffmpeg é
        avaliada aqui (``round`` do ffmpeg arredonda a metade para longe do zero) contra a do domínio, numa grade."""
        import math
        import re
        from videomanager.infrastructure.ffmpeg.composer import _fit_scale

        def avaliar(expressao: str, dar: float) -> float:
            return eval(expressao, {"__builtins__": {}}, {"min": min, "round": lambda v: math.floor(v + 0.5),
                                                          "trunc": math.trunc, "dar": dar})

        verificadas = 0
        for media in ((1920, 1080), (1920, 800), (1440, 1080), (1080, 1920), (1000, 1000), (3840, 1600), (854, 480)):
            for cheia in ((1920, 1080), (1280, 720), (1080, 1920)):
                for largura in range(300, 1200, 14):
                    altura = round(largura * cheia[1] / cheia[0]) // 2 * 2
                    if (largura, altura) == cheia:
                        continue
                    partes = re.fullmatch(r"scale=w='(.+)':h='(.+)'", _fit_scale(largura, altura, cheia))
                    assert partes is not None
                    dar = media[0] / media[1]
                    do_ffmpeg = (avaliar(partes.group(1), dar), avaliar(partes.group(2), dar))
                    assert do_ffmpeg == reduced_fit(*media, largura, altura, *cheia), (media, (largura, altura), cheia)
                    verificadas += 1
        assert verificadas > 1000

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


def _video(tools, pasta: Path, nome: str, tamanho: tuple[int, int], duracao: int = 2) -> MediaRef:
    arquivo = pasta / f"{nome}.mp4"
    subprocess.run([tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"color=lime:s={tamanho[0]}x{tamanho[1]}:r=30:d={duracao}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(arquivo)], check=True, capture_output=True)
    return media_ref(probe_file(arquivo, tools))


def _quadro(project: Project, caixa: tuple[int, int], tools, instante: float = 0.5) -> tuple[bytes, tuple[int, int]]:
    tamanho = fit_size(project.width, project.height, *caixa)
    dados = subprocess.run(frame_command(project, instante, tamanho, tools), capture_output=True, check=True).stdout
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

    @pytest.mark.parametrize("caixa", CAIXAS)
    def test_video_que_preenche_so_a_altura_encosta_no_topo_e_na_base(self, tools, tmp_path, caixa) -> None:
        """Mídia quadrada numa tela 16:9 preenche a altura: encosta no topo e na base, e as barras dos lados são conteúdo. É o
        caso fora do 16:9 em que o eixo que limita é a altura; o outro eixo (largura 333, ímpar, na caixa 592×334) é o que
        a conta do arredondamento decide, coberto pelas comparações entre ``reduced_fit`` e o ``scale`` do ffmpeg."""
        midia = _video(tools, tmp_path, "quadrado", (1000, 1000))
        projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(midia, 0, 2),)),), width=1920, height=1080)
        dados, (w, h) = _quadro(projeto, caixa, tools)
        assert _verde(dados, (w, h), w // 2, 0) and _verde(dados, (w, h), w // 2, h - 1), f"fio preto no quadro {w}×{h}"
        assert not _verde(dados, (w, h), 0, h // 2) and not _verde(dados, (w, h), w - 1, h // 2)  # as barras dos lados são conteúdo

    @pytest.mark.parametrize("caixa", CAIXAS)
    @pytest.mark.parametrize("instante", [1.0, 3.0])
    def test_o_meio_de_uma_transicao_tambem_encosta_nas_quatro_bordas(self, tools, tmp_path, caixa, instante) -> None:
        """A transição monta as duas pontas por outro caminho do compositor, e o conserto do fio preto tinha ficado
        só no caminho do bloco comum: dentro dela o quadro voltava a sair com 1 px preto em cima e embaixo."""
        # A mídia tem de cobrir os blocos e as folgas da transição: depois do fim do arquivo o ``dissolve`` mistura com o
        # vazio e o quadro sai salpicado de preto por razão nenhuma do encaixe.
        midia = _video(tools, tmp_path, "v", (1920, 1080), duracao=4)
        a, b = Clip(midia, 0, 3), Clip(midia, 3, 3)
        transicao = Clip(MediaRef(Path("Transicao"), MediaKind.IMAGE, duration=1.0), 2.5, 1.0, overlay_type="transition",
                         transition_name="dissolve", transition_left_id=a.clip_id, transition_right_id=b.clip_id)
        projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(a, transicao, b)),), width=1920, height=1080)
        dados, (w, h) = _quadro(projeto, caixa, tools, instante)
        pretos = {
            "esquerda": not _verde(dados, (w, h), 0, h // 2),
            "direita": not _verde(dados, (w, h), w - 1, h // 2),
            "topo": not _verde(dados, (w, h), w // 2, 0),
            "base": not _verde(dados, (w, h), w // 2, h - 1),
        }
        assert not any(pretos.values()), f"borda preta no quadro {w}×{h} em {instante} s: {pretos}"

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
