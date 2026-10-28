"""O filtro móvel, medido na imagem que o ffmpeg de verdade entrega.

A fonte é ruído sem perda: o retângulo que mudou **é** a região, e o que está fora dele tem de sair byte a byte igual ao
projeto sem o filtro. Dentro dele, os filtros de cor têm de dar o que a tela inteira receberia; a vinheta, calculada no
recorte, escurece as bordas do retângulo e deixa o centro.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.domain.composition import Composition
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import Clip
from videomanager.domain.project import OverlayType
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.domain.project import media_ref
from videomanager.domain.project import pseudo_media
from videomanager.infrastructure.ffmpeg.composer import build_graph
from videomanager.infrastructure.ffmpeg.composer import frame_command
from videomanager.infrastructure.ffmpeg.converter import Converter
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.system.binaries import find_tools
from videomanager.infrastructure.system.binaries import subprocess_kwargs

pytestmark = pytest.mark.ffmpeg

TELA = (320, 180)
FPS = 30.0
DE_COR = ["pb", "sepia", "inverter", "contraste"]
TODOS = [*DE_COR, "vinheta"]


@pytest.fixture(scope="module")
def tools():
    found = find_tools()
    if found is None:
        pytest.skip("FFmpeg não disponível")
    return found


@pytest.fixture(scope="module")
def ruido(tools, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("ruido") / "ruido.mkv"
    subprocess.run(
        [tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
         "color=c=gray:s=320x180:r=30:d=4,noise=alls=90:allf=t+u",
         "-c:v", "ffv1", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=60, **subprocess_kwargs())
    return path


def _filtro(nome: str, inicio: float = 1.0, duracao: float = 1.5, *, movel: bool | None = None, x: float = 0.5,
            y: float = 0.5, escala: float = 0.3, **extra) -> Clip:
    """Um bloco de filtro. ``movel`` é o campo do bloco (o desfoque não o usa: é sempre um retângulo)."""
    movel = nome != "desfoque" if movel is None else movel
    regiao = movel or nome == "desfoque"
    pose = dict(x=x, y=y, scale=escala, scale_x=escala, scale_y=escala) if regiao else {}
    media = pseudo_media(OverlayType.FILTER, nome, duracao)
    return Clip(media, inicio, duracao, overlay_type="filter", filter_name=nome, movable=movel and nome != "desfoque",
                **pose, **extra)


def _projeto(tools, fonte: Path, *filtros: Clip, tela: tuple[int, int] = TELA) -> Project:
    video = Clip(media_ref(probe_file(fonte, tools)), 0.0, 4.0)
    trilhas = [Track(TrackKind.VIDEO, clips=(video,), name="Vídeo 1")]
    if filtros:
        trilhas.insert(0, Track(TrackKind.ADDITIONAL, clips=tuple(filtros), name="Adicionais 1"))
    return Project(tracks=tuple(trilhas), width=tela[0], height=tela[1], fps=FPS)


def _quadro(tools, projeto: Project, indice: int, tela: tuple[int, int] = TELA) -> bytes:
    dados = subprocess.run(frame_command(projeto, (indice + 0.5) / FPS, tela, tools), check=True, timeout=60,
                           **subprocess_kwargs()).stdout
    assert len(dados) == tela[0] * tela[1] * 3
    return dados


def _caixa_que_mudou(a: bytes, b: bytes, tela: tuple[int, int] = TELA) -> tuple[int, int, int, int] | None:
    largura, altura = tela
    esq, topo, dir_, base = largura, altura, -1, -1
    for y in range(altura):
        linha = slice(y * largura * 3, (y + 1) * largura * 3)
        ra, rb = a[linha], b[linha]
        if ra == rb:
            continue
        diferentes = [x for x in range(largura) if any(ra[x * 3 + c] != rb[x * 3 + c] for c in range(3))]
        if not diferentes:
            continue
        topo, base = min(topo, y), max(base, y)
        esq, dir_ = min(esq, diferentes[0]), max(dir_, diferentes[-1])
    return None if dir_ < 0 else (esq, topo, dir_ + 1, base + 1)


def _recorte(quadro: bytes, retangulo: tuple[int, int, int, int], tela: tuple[int, int] = TELA) -> list[tuple[int, int, int]]:
    esq, topo, w, h = retangulo
    return [tuple(quadro[((y * tela[0]) + x) * 3:((y * tela[0]) + x) * 3 + 3])
            for y in range(topo, topo + h) for x in range(esq, esq + w)]


def _retangulo(filtro: Clip, indice: int, tela: tuple[int, int] = TELA) -> tuple[int, int, int, int]:
    return filtro.region_rect(tela[0], tela[1], (indice + 0.5) / FPS - filtro.start)


# -- onde e quando -------------------------------------------------------------------------

@pytest.mark.parametrize("nome", TODOS)
def test_so_o_retangulo_muda_e_ele_e_o_que_o_dominio_calcula(tools, ruido, nome) -> None:
    filtro = _filtro(nome)
    a, b = _quadro(tools, _projeto(tools, ruido, filtro), 45), _quadro(tools, _projeto(tools, ruido), 45)
    esq, topo, w, h = _retangulo(filtro, 45)
    assert _caixa_que_mudou(a, b) == (esq, topo, esq + w, topo + h)


@pytest.mark.parametrize("nome", DE_COR)
def test_dentro_do_retangulo_o_filtro_e_o_que_a_tela_inteira_receberia(tools, ruido, nome) -> None:
    movel, inteira = _filtro(nome), _filtro(nome, movel=False)
    a = _quadro(tools, _projeto(tools, ruido, movel), 45)
    b = _quadro(tools, _projeto(tools, ruido, inteira), 45)
    retangulo = _retangulo(movel, 45)
    maior = max(abs(p - q) for pa, pb in zip(_recorte(a, retangulo), _recorte(b, retangulo)) for p, q in zip(pa, pb))
    assert maior <= 2, maior


def _media(quadro: bytes, caixa: tuple[int, int, int, int]) -> float:
    pixels = _recorte(quadro, caixa)
    return sum(sum(p) for p in pixels) / (3 * len(pixels))


def test_a_vinheta_escurece_as_bordas_do_retangulo_e_deixa_o_centro(tools, ruido) -> None:
    """A vinheta é calculada no recorte: o canto do retângulo (e não o da tela) fica a ~25% e o centro não muda."""
    filtro = _filtro("vinheta")
    com, sem = _quadro(tools, _projeto(tools, ruido, filtro), 45), _quadro(tools, _projeto(tools, ruido), 45)
    esq, topo, w, h = _retangulo(filtro, 45)
    canto, centro = (esq, topo, 6, 6), (esq + w // 2 - 3, topo + h // 2 - 3, 6, 6)
    assert _media(com, canto) < _media(sem, canto) * 0.45
    assert _media(com, centro) == pytest.approx(_media(sem, centro), rel=0.03)
    # Um canto da tela, fora do retângulo, fica como estava: a vinheta não é a da tela inteira.
    assert _recorte(com, (0, 0, 6, 6)) == _recorte(sem, (0, 0, 6, 6))


@pytest.mark.parametrize("indice, aplicado", [(29, False), (30, True), (74, True), (75, False)])
def test_o_filtro_movel_vale_so_dentro_da_janela_do_bloco(tools, ruido, indice, aplicado) -> None:
    com, sem = _projeto(tools, ruido, _filtro("sepia")), _projeto(tools, ruido)
    assert (_quadro(tools, com, indice) != _quadro(tools, sem, indice)) is aplicado


def test_a_posicao_anima_com_os_quadros_chave_e_o_tamanho_nao(tools, ruido) -> None:
    filtro = _filtro("sepia", x=0.25, escala=0.25, keyframes=(
        Keyframe(0.0, x=0.25, y=0.5, scale_x=0.25, scale_y=0.25),
        Keyframe(1.5, x=0.75, y=0.5, scale_x=0.25, scale_y=0.25)))
    com, sem = _projeto(tools, ruido, filtro), _projeto(tools, ruido)
    posicoes = []
    for indice in (30, 52, 74):
        esq, topo, w, h = _retangulo(filtro, indice)
        assert _caixa_que_mudou(_quadro(tools, com, indice), _quadro(tools, sem, indice)) == (esq, topo, esq + w, topo + h)
        posicoes.append((esq, w, h))
    assert posicoes[0][0] < posicoes[1][0] < posicoes[2][0]
    assert len({(w, h) for _, w, h in posicoes}) == 1


@pytest.mark.parametrize("x, y", [(-0.3, 0.5), (1.3, 0.5), (0.5, -0.3), (0.5, 1.3), (0.4003, 0.3991)])
def test_a_regiao_do_filtro_movel_nunca_sai_da_tela_nem_cai_em_pixel_impar(tools, ruido, x, y) -> None:
    filtro = _filtro("sepia", x=x, y=y)
    a, b = _quadro(tools, _projeto(tools, ruido, filtro), 45), _quadro(tools, _projeto(tools, ruido), 45)
    esq, topo, w, h = _retangulo(filtro, 45)
    assert esq % 2 == 0 and topo % 2 == 0 and 0 <= esq and esq + w <= TELA[0] and 0 <= topo and topo + h <= TELA[1]
    assert _caixa_que_mudou(a, b) == (esq, topo, esq + w, topo + h)


# -- o filtro de tela inteira não muda ------------------------------------------------------

@pytest.mark.parametrize("nome", TODOS)
def test_o_filtro_de_tela_inteira_continua_sem_recorte_e_o_movel_ganha_um(tools, ruido, nome) -> None:
    inteira = ";".join(build_graph(_projeto(tools, ruido, _filtro(nome, movel=False))).filters)
    movel = ";".join(build_graph(_projeto(tools, ruido, _filtro(nome))).filters)
    assert "crop=" not in inteira and "split=" not in inteira
    assert "crop=" in movel and "split=" in movel


# -- combinações ----------------------------------------------------------------------------

def test_varios_filtros_moveis_e_um_desfoque_no_mesmo_projeto_nao_repetem_rotulo(tools, ruido) -> None:
    filtros = (_filtro("sepia", x=0.2), _filtro("inverter", x=0.5), _filtro("pb", x=0.8),
               _filtro("desfoque", x=0.35, y=0.3, escala=0.2), _filtro("vinheta", x=0.65, y=0.7))
    projeto = replace(_projeto(tools, ruido), tracks=(
        *(Track(TrackKind.ADDITIONAL, clips=(f,), name=f"Adicionais {i}") for i, f in enumerate(filtros)),
        *_projeto(tools, ruido).tracks))
    a, b = _quadro(tools, projeto, 45), _quadro(tools, _projeto(tools, ruido), 45)
    caixa = _caixa_que_mudou(a, b)
    assert caixa is not None and caixa[0] < 100 and caixa[2] > 220          # do filtro mais à esquerda ao mais à direita


def _projeto_com_transicao(tools, fonte: Path, *filtros: Clip, afeta: bool) -> Project:
    esquerda = Clip(media_ref(probe_file(fonte, tools)), 0.0, 2.0)
    direita = Clip(media_ref(probe_file(fonte, tools)), 2.0, 2.0)
    marca = Clip(pseudo_media(OverlayType.TRANSITION, "Dissolve", 1.0), 1.5, 1.0, overlay_type="transition",
                 transition_name="dissolve", transition_left_id=esquerda.clip_id, transition_right_id=direita.clip_id,
                 transition_affects_additionals=afeta)
    return Project(tracks=(Track(TrackKind.ADDITIONAL, clips=filtros, name="Adicionais 1"),
                           Track(TrackKind.VIDEO, clips=(esquerda, marca, direita), name="Vídeo 1")),
                   width=TELA[0], height=TELA[1], fps=FPS)


@pytest.mark.parametrize("afeta", [False, True], ids=["transicao_sem_adicionais", "transicao_que_afeta_adicionais"])
@pytest.mark.parametrize("nome", ["sepia", "vinheta"])
def test_o_filtro_movel_atravessa_uma_transicao_sem_quebrar_a_montagem(tools, ruido, nome, afeta) -> None:
    """Dentro da janela da transição (1,5 s a 2,5 s) o filtro continua só no retângulo; fora dele, o quadro é o do
    projeto sem o filtro. Com "Afetar itens adicionais" o compositor leva o filtro para dentro da transição (rótulos)."""
    filtro = _filtro(nome, 1.0, 2.0)
    com = _projeto_com_transicao(tools, ruido, filtro, afeta=afeta)
    sem = _projeto_com_transicao(tools, ruido, afeta=afeta)
    a, b = _quadro(tools, com, 60), _quadro(tools, sem, 60)                 # meio da passagem
    esq, topo, w, h = _retangulo(filtro, 60)
    caixa = _caixa_que_mudou(a, b)
    assert caixa is not None and caixa[0] >= esq and caixa[1] >= topo and caixa[2] <= esq + w and caixa[3] <= topo + h


# -- exportação de verdade ------------------------------------------------------------------

def _exportar(tools, projeto: Project, fonte: Path, destino: Path) -> Path:
    Converter(probe_file(fonte, tools), Composition(projeto, "mp4"), destino, tools).run()
    return destino


def _ffprobe(tools, path: Path) -> dict:
    saida = subprocess.run(
        [tools.ffprobe_str, "-v", "quiet", "-print_format", "json", "-count_frames", "-show_format", "-show_streams",
         str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(saida)


def _quadro_do_arquivo(tools, path: Path, indice: int) -> bytes:
    return subprocess.run(
        [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{indice})",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True).stdout


def _croma(quadro: bytes, retangulo: tuple[int, int, int, int]) -> float:
    pixels = _recorte(quadro, retangulo)
    return sum(abs(r - g) + abs(g - b) for r, g, b in pixels) / len(pixels)


def test_a_exportacao_preserva_duracao_e_quadros_e_tira_a_cor_so_da_regiao(tools, ruido, tmp_path: Path) -> None:
    filtro = _filtro("pb")
    com = _exportar(tools, _projeto(tools, ruido, filtro), ruido, tmp_path / "com.mp4")
    sem = _exportar(tools, _projeto(tools, ruido), ruido, tmp_path / "sem.mp4")
    pc, ps = _ffprobe(tools, com), _ffprobe(tools, sem)
    assert float(pc["format"]["duration"]) == pytest.approx(float(ps["format"]["duration"]), abs=0.05)
    assert pc["streams"][0]["nb_read_frames"] == ps["streams"][0]["nb_read_frames"]
    retangulo = _retangulo(filtro, 45)
    dentro, antes = _croma(_quadro_do_arquivo(tools, com, 45), retangulo), _croma(_quadro_do_arquivo(tools, sem, 45), retangulo)
    assert dentro < antes / 5, (dentro, antes)                        # cinza dentro do retângulo
    fora = (0, 0, 60, 60)                                              # um canto longe da região
    assert _croma(_quadro_do_arquivo(tools, com, 45), fora) == pytest.approx(
        _croma(_quadro_do_arquivo(tools, sem, 45), fora), rel=0.1)    # e igual ao projeto sem o filtro fora dela
    # Fora da janela o arquivo é o mesmo.
    assert _croma(_quadro_do_arquivo(tools, com, 10), retangulo) == pytest.approx(
        _croma(_quadro_do_arquivo(tools, sem, 10), retangulo), rel=0.1)


def test_a_vinheta_movel_exporta_sem_quebrar_a_montagem(tools, ruido, tmp_path: Path) -> None:
    saida = _exportar(tools, _projeto(tools, ruido, _filtro("vinheta")), ruido, tmp_path / "vinheta.mp4")
    assert float(_ffprobe(tools, saida)["format"]["duration"]) == pytest.approx(4.0, abs=0.1)
