"""Fundo desfocado: os caminhos que levam o bloco a mostrar (ou não) o fundo.

``TestFundoDesfocadoExportado`` (em ``test_integration.py``) prova que o fundo
existe na imagem. Aqui o que se mede é **onde ele aparece** em cada combinação
de proporção, pose, opacidade, trilha e tempo, com a mesma pergunta em todas:

    comparado ao mesmo projeto sem a opção, o que mudou?

A resposta certa tem três partes e cada teste afirma as que lhe cabem:

1. **Dentro da frente nada muda** — o fundo fica por baixo e só ocupa o que era
   preto (ou a trilha de baixo).
2. **Onde a frente deixa a tela descoberta, aparece imagem** — um buraco preto
   com a opção ligada é o defeito que nenhuma duração nem contagem de quadros
   enxerga.
3. **Onde ela cobre a tela inteira, o quadro sai byte a byte igual** — ligar a
   opção onde ela não aparece não pode custar nada.

Os quadros vêm de ``frame_command`` (o mesmo grafo da exportação, em rgb24 cru
e sem perdas), e não de um arquivo codificado: o ruído do x264 faria o "igual"
virar "quase igual".
"""

from __future__ import annotations

import json
import random
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.domain.geometry import image_base_size
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.preview import fit_size
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, media_ref
from videomanager.infrastructure.ffmpeg.composer import build_graph, frame_command
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.system import binaries

pytestmark = pytest.mark.ffmpeg

TELA = (320, 180)
VERTICAL = (180, 320)
QUADRADA = (180, 180)

# Tamanho de cada fonte: "v" é vídeo, "f" é foto. A proporção, não o tamanho,
# é o que decide quanto da tela a frente deixa descoberta.
FONTES = {
    "v169": (320, 180), "v43": (240, 180), "v916": (90, 160), "v11": (180, 180), "v219": (336, 144),
    "f169": (320, 180), "f43": (240, 180), "f916": (90, 160),
}


@pytest.fixture(scope="module")
def tools():
    found = binaries.find_tools()
    if found is None:
        pytest.skip("ffmpeg não disponível; rode a aplicação uma vez para provisioná-lo")
    return found


@pytest.fixture(scope="module")
def midias(tools, tmp_path_factory) -> dict[str, MediaRef]:
    pasta = tmp_path_factory.mktemp("fundo-caminhos")
    resultado = {}
    for nome, (w, h) in FONTES.items():
        if nome.startswith("f"):
            arquivo, args = pasta / f"{nome}.png", ["-f", "lavfi", "-i", f"testsrc2=s={w}x{h}", "-frames:v", "1"]
        else:
            arquivo, args = pasta / f"{nome}.mp4", [
                "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r=30:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p"]
        subprocess.run([tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", *args, str(arquivo)],
                       check=True, capture_output=True)
        resultado[nome] = media_ref(probe_file(arquivo, tools))
    # Chão liso e verde, para enxergar a trilha de baixo sem ambiguidade: a
    # lateral esquerda do ``testsrc2`` é vermelha, então vermelho não serviria.
    verde = pasta / "verde.mp4"
    subprocess.run([tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=lime:s=320x180:r=30:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(verde)],
                   check=True, capture_output=True)
    resultado["verde"] = media_ref(probe_file(verde, tools))
    return resultado


# ---------------------------------------------------------------------------
# Medição
# ---------------------------------------------------------------------------

def projeto(*trilhas: tuple[Clip, ...], tela: tuple[int, int] = TELA, fps: float = 30.0) -> Project:
    return Project(tracks=tuple(Track(kind=TrackKind.VIDEO, clips=c) for c in trilhas),
                   width=tela[0], height=tela[1], fps=fps)


def quadro(proj: Project, t: float, tools) -> bytes:
    tam = (proj.width, proj.height)
    dados = subprocess.run(frame_command(proj, t, tam, tools), capture_output=True, check=True).stdout
    assert len(dados) == tam[0] * tam[1] * 3, f"quadro de tamanho inesperado em {t} s"
    return dados


def exportar(proj: Project, destino: Path, tools) -> Path:
    from videomanager.domain.composition import Composition
    from videomanager.infrastructure.ffmpeg.converter import Converter
    primeiro = next(c for t in proj.tracks for c in t.clips if c.media is not None)
    Converter(probe_file(primeiro.media.path, tools), Composition(proj, "mp4"), destino, tools).run()
    return destino


def quadro_do_arquivo(arquivo: Path, t: float, tam: tuple[int, int], tools) -> bytes:
    dados = subprocess.run(
        [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-ss", f"{t:.3f}", "-i", str(arquivo),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        capture_output=True, check=True).stdout
    assert len(dados) == tam[0] * tam[1] * 3, f"sem quadro em {t} s"
    return dados


def contagem(arquivo: Path, tools) -> tuple[int, float]:
    saida = subprocess.run(
        [tools.ffprobe_str, "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
         "stream=nb_read_frames:format=duration", "-of", "json", str(arquivo)],
        capture_output=True, text=True, check=True).stdout
    dados = json.loads(saida)
    return int(dados["streams"][0]["nb_read_frames"]), float(dados["format"]["duration"])


def _recorte(dados: bytes, tam: tuple[int, int], r: tuple[int, int, int, int], canais=(0, 1, 2)) -> bytes:
    x0, y0, x1, y1 = r
    linhas = (dados[(y * tam[0] + x0) * 3:(y * tam[0] + x1) * 3] for y in range(y0, y1))
    pedaco = b"".join(linhas)
    return pedaco if canais == (0, 1, 2) else b"".join(pedaco[c::3] for c in canais)


def media_da(dados: bytes, tam, r, canais=(0, 1, 2)) -> float:
    pedaco = _recorte(dados, tam, r, canais)
    return sum(pedaco) / len(pedaco)


def diferenca(a: bytes, b: bytes, tam, r) -> float:
    pa, pb = _recorte(a, tam, r), _recorte(b, tam, r)
    return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)


def pegada(media: MediaRef, tela, clip: Clip) -> tuple[float, float, float, float]:
    """Retângulo que a frente ocupa na tela, sem rotação."""
    ajuste = image_base_size if media.kind is MediaKind.IMAGE else fit_size
    fw, fh = ajuste(media.width, media.height, *tela)
    w, h = fw * clip.scale_x, fh * clip.scale_y
    cx, cy = clip.x * tela[0], clip.y * tela[1]
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def descobertas(r, tela, espessura: int = 6, folga: int = 3) -> list[tuple[int, int, int, int]]:
    """Faixas da tela que a frente não cobre, recuadas para fugir da borda dela.

    Só entram as com ``espessura`` ou mais: a regra tolera 2 px de sobra (arredondamento
    do encaixe), e uma faixa dessas é preta de propósito.
    """
    x0, y0, x1, y1 = (round(v) for v in r)
    w, h = tela
    faixas = []
    if x0 >= espessura:
        faixas.append((folga, folga, x0 - folga, h - folga))
    if w - x1 >= espessura:
        faixas.append((x1 + folga, folga, w - folga, h - folga))
    if y0 >= espessura:
        faixas.append((folga, folga, w - folga, y0 - folga))
    if h - y1 >= espessura:
        faixas.append((folga, y1 + folga, w - folga, h - folga))
    return [f for f in faixas if f[2] > f[0] and f[3] > f[1]]


def miolo(r, tela, folga: int = 4) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = r
    return (max(0, round(x0) + folga), max(0, round(y0) + folga),
            min(tela[0], round(x1) - folga), min(tela[1], round(y1) - folga))


def par(clip: Clip) -> tuple[Clip, Clip]:
    return clip, replace(clip, blur_background=True)


def cantos(tela, lado: int = 6):
    w, h = tela
    return [(0, 0, lado, lado), (w - lado, 0, w, lado), (0, h - lado, lado, h), (w - lado, h - lado, w, h)]


# ---------------------------------------------------------------------------
# Proporção × pose: a matriz
# ---------------------------------------------------------------------------

# (nome, fonte, tela, pose, descobre, no_grafo)
#   descobre: a frente deixa a tela descoberta (o fundo tem de aparecer);
#   no_grafo: a regra do modelo manda o fundo para o grafo.
# "Coberto" é o caso que custa ramo no grafo sem mudar um pixel.
MATRIZ = [
    # Neutro: só a proporção decide.
    ("video_16x9_na_16x9", "v169", TELA, {}, False, False),
    ("foto_16x9_na_16x9", "f169", TELA, {}, False, False),
    ("video_4x3_na_16x9", "v43", TELA, {}, True, True),
    ("foto_4x3_na_16x9", "f43", TELA, {}, True, True),
    ("video_vertical_na_16x9", "v916", TELA, {}, True, True),
    ("foto_vertical_na_16x9", "f916", TELA, {}, True, True),
    ("video_quadrado_na_16x9", "v11", TELA, {}, True, True),
    ("video_21x9_na_16x9", "v219", TELA, {}, True, True),
    ("video_vertical_na_vertical", "v916", VERTICAL, {}, False, False),
    ("video_16x9_na_vertical", "v169", VERTICAL, {}, True, True),
    ("video_quadrado_na_quadrada", "v11", QUADRADA, {}, False, False),
    # Pose num bloco que, parado, preencheria a tela (o que o CapCut chama de
    # canvas: o fundo é o que sobra atrás do bloco, qualquer que seja o motivo).
    ("16x9_reduzido", "v169", TELA, dict(scale=0.5), True, True),
    ("foto_16x9_reduzida", "f169", TELA, dict(scale=0.5), True, True),
    ("16x9_so_na_largura", "v169", TELA, dict(scale_x=0.5), True, True),
    ("16x9_movido_na_horizontal", "v169", TELA, dict(x=0.3), True, True),
    ("16x9_movido_na_vertical", "v169", TELA, dict(y=0.7), True, True),
    ("16x9_girado", "v169", TELA, dict(rotation=15.0), True, True),
    ("foto_16x9_girada", "f169", TELA, dict(rotation=15.0), True, True),
    # Pose que não descobre nada: o ramo existe e a imagem não muda.
    ("16x9_ampliado", "v169", TELA, dict(scale=1.5), False, False),
    ("16x9_ampliado_e_movido_ainda_cobre", "v169", TELA, dict(scale=1.5, x=0.6), False, True),
    ("16x9_ampliado_e_girado_ainda_cobre", "v169", TELA, dict(scale=1.2, rotation=5.0), False, True),
]


@pytest.mark.parametrize("nome,fonte,tela,pose,descobre,no_grafo", MATRIZ, ids=[c[0] for c in MATRIZ])
def test_matriz_de_proporcao_e_pose(midias, tools, nome, fonte, tela, pose, descobre, no_grafo) -> None:
    media = midias[fonte]
    sem_clip, com_clip = par(Clip(media, 0.0, 2.0, **pose))
    sem, com = projeto((sem_clip,), tela=tela), projeto((com_clip,), tela=tela)
    assert ("gblur" in ";".join(build_graph(com).filters)) is no_grafo, "a regra do modelo e o grafo discordam"

    a, b = quadro(sem, 1.0, tools), quadro(com, 1.0, tools)
    if not descobre:
        assert a == b, "ligar a opção onde nada fica descoberto mudou a imagem"
        return
    if com_clip.rotation:
        # Girado, a frente é um losango: o que se garante é o miolo e os quatro cantos.
        assert diferenca(a, b, tela, (tela[0] // 4, tela[1] // 4, 3 * tela[0] // 4, 3 * tela[1] // 4)) < 2.0
        for canto in cantos(tela):
            assert media_da(a, tela, canto) < 1.5, "o canto devia ser preto sem a opção"
            assert media_da(b, tela, canto) > 10, "o canto girado ficou preto com a opção ligada"
        return
    r = pegada(media, tela, com_clip)
    faixas = descobertas(r, tela)
    assert faixas, "o caso não deixa nada descoberto; o teste ficou vazio"
    assert diferenca(a, b, tela, miolo(r, tela)) < 1.5, "o fundo invadiu a frente"
    for faixa in faixas:
        assert media_da(a, tela, faixa) < 1.5
        assert media_da(b, tela, faixa) > 10, f"faixa {faixa} ficou preta com a opção ligada"


def test_sorteio_de_poses_nunca_deixa_buraco_preto(midias, tools) -> None:
    """Pose sorteada: se a frente descobre a tela, o fundo aparece; se cobre, nada muda.

    É a mesma conta da matriz sem eu escolher os casos — o que acusa um canto
    da regra (``Clip.shows_blur_background``) que ninguém lembrou de listar.
    """
    tela = (160, 90)
    sorteio = random.Random(20260710)
    fontes = list(FONTES)
    for _ in range(14):
        fonte = sorteio.choice(fontes)
        pose = dict(scale_x=round(sorteio.uniform(0.35, 1.4), 2), scale_y=round(sorteio.uniform(0.35, 1.4), 2),
                    x=round(sorteio.uniform(0.3, 0.7), 2), y=round(sorteio.uniform(0.3, 0.7), 2))
        sem_clip, com_clip = par(Clip(midias[fonte], 0.0, 2.0, **pose))
        a = quadro(projeto((sem_clip,), tela=tela), 1.0, tools)
        b = quadro(projeto((com_clip,), tela=tela), 1.0, tools)
        r = pegada(midias[fonte], tela, com_clip)
        faixas = descobertas(r, tela)
        contexto = f"{fonte} {pose}"
        if not faixas:
            # Sobra de até 5 px é a tolerância da regra: pode ou não ter fundo.
            continue
        assert com_clip.shows_blur_background(*tela), f"descobre a tela e a regra nega o fundo: {contexto}"
        assert diferenca(a, b, tela, miolo(r, tela)) < 1.5, f"o fundo invadiu a frente: {contexto}"
        for faixa in faixas:
            assert media_da(b, tela, faixa) > 5, f"faixa {faixa} preta com a opção ligada: {contexto}"


# ---------------------------------------------------------------------------
# Opacidade, chroma key, quadros-chave
# ---------------------------------------------------------------------------

def test_opacidade_fixa_leva_o_fundo_junto(midias, tools) -> None:
    media = midias["v43"]
    lateral = (0, 0, 40, 180)
    cheio = quadro(projeto((Clip(media, 0.0, 2.0, blur_background=True),)), 1.0, tools)
    metade = quadro(projeto((Clip(media, 0.0, 2.0, blur_background=True, opacity=0.5),)), 1.0, tools)
    razao = media_da(metade, TELA, lateral) / media_da(cheio, TELA, lateral)
    assert razao == pytest.approx(0.5, abs=0.12)


def test_fundo_de_video_borra_a_cor_como_o_de_uma_foto_do_mesmo_quadro(tools, tmp_path: Path) -> None:
    """Num vídeo yuv420p o ``gblur`` rodava nos planos de cor em meia resolução.

    O mesmo sigma valia o dobro em pixels de tela e o fundo do vídeo saía com a
    cor mais lavada que a da foto do mesmo quadro (medido: 6,5 a 13,4 em 255, máx. 92).
    Sem perdas na fonte, para a diferença ser só do desfoque.
    """
    base = [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
            "testsrc2=s=240x180:r=30:d=2"]
    subprocess.run([*base, "-c:v", "libx264", "-crf", "0", "-pix_fmt", "yuv420p", str(tmp_path / "v.mp4")],
                   check=True, capture_output=True)
    subprocess.run([*base, "-frames:v", "1", str(tmp_path / "f.png")], check=True, capture_output=True)
    video, foto = (quadro(projeto((Clip(media_ref(probe_file(tmp_path / arquivo, tools)), 0.0, 2.0,
                                       blur_background=True),)), 0.0, tools)
                   for arquivo in ("v.mp4", "f.png"))
    for lateral in ((0, 0, 40, 180), (280, 0, 320, 180)):
        assert diferenca(video, foto, TELA, lateral) < 2.0, f"fundo do vídeo difere do da foto em {lateral}"


def test_chroma_key_ligado_deixa_a_opcao_sem_efeito(midias, tools) -> None:
    sem_clip, com_clip = par(Clip(midias["v43"], 0.0, 2.0, chromakey_enabled=True))
    assert not com_clip.shows_blur_background(*TELA)
    assert quadro(projeto((sem_clip,)), 1.0, tools) == quadro(projeto((com_clip,)), 1.0, tools)


def test_quadros_chave_do_neutro_ao_reduzido_acendem_o_fundo_no_meio_do_bloco(midias, tools) -> None:
    """Parado o bloco preenche a tela; o fundo só aparece à medida que ele encolhe."""
    animacao = (Keyframe(0.0), Keyframe(2.0, scale_x=0.5, scale_y=0.5))
    sem_clip, com_clip = par(Clip(midias["v169"], 0.0, 2.0, keyframes=animacao))
    assert com_clip.shows_blur_background(*TELA), "a regra olha só a pose parada e perde os quadros-chave"
    sem, com = projeto((sem_clip,)), projeto((com_clip,))
    assert quadro(sem, 0.0, tools) == quadro(com, 0.0, tools), "no instante neutro o quadro devia ser igual"
    a, b = quadro(sem, 1.9, tools), quadro(com, 1.9, tools)
    for canto in cantos(TELA):
        assert media_da(a, TELA, canto) < 1.5
        assert media_da(b, TELA, canto) > 10, "bloco já reduzido e canto preto"


def test_giro_completo_por_quadros_chave_acende_o_fundo_no_meio_do_giro(midias, tools) -> None:
    """Os dois extremos (0° e 360°) são neutros, mas no meio do giro a frente é um retângulo em pé.

    A regra olhava só a pose de cada quadro-chave: o grafo saía sem o fundo e as
    laterais ficavam pretas a 90°, com duração e quadros certos e nenhum erro.
    """
    animacao = (Keyframe(0.0, rotation=0.0), Keyframe(2.0, rotation=360.0))
    sem_clip, com_clip = par(Clip(midias["v169"], 0.0, 2.0, keyframes=animacao))
    assert com_clip.shows_blur_background(*TELA)
    sem, com = projeto((sem_clip,)), projeto((com_clip,))
    a, b = quadro(sem, 0.5, tools), quadro(com, 0.5, tools)  # 90°: o retângulo em pé ocupa x de 70 a 250
    assert media_da(a, TELA, (3, 3, 37, 177)) < 1.5, "a lateral devia ser preta sem a opção"
    assert media_da(b, TELA, (3, 3, 37, 177)) > 10, "a lateral ficou preta no meio do giro com a opção ligada"
    assert diferenca(a, b, TELA, (80, 10, 240, 170)) < 1.5, "o fundo invadiu a frente"
    assert quadro(sem, 0.0, tools) == quadro(com, 0.0, tools), "no instante neutro a frente cobre a tela e nada muda"


def test_quadros_chave_do_reduzido_ao_neutro_apagam_o_fundo_no_fim(midias, tools) -> None:
    animacao = (Keyframe(0.0, scale_x=0.5, scale_y=0.5), Keyframe(2.0))
    sem_clip, com_clip = par(Clip(midias["v169"], 0.0, 2.0, keyframes=animacao))
    sem, com = projeto((sem_clip,)), projeto((com_clip,))
    assert media_da(quadro(com, 0.05, tools), TELA, cantos(TELA)[0]) > 10
    final_sem, final_com = quadro(sem, 2.0, tools), quadro(com, 2.0, tools)
    assert diferenca(final_sem, final_com, TELA, (6, 6, 314, 174)) < 1.5


# ---------------------------------------------------------------------------
# Trilhas e tempo
# ---------------------------------------------------------------------------

def test_o_fundo_so_cobre_a_trilha_de_baixo_na_janela_do_bloco(midias, tools, tmp_path: Path) -> None:
    """Medido no arquivo: ``frame_command`` recorta a um quadro e não enxerga a janela do bloco."""
    embaixo = Clip(midias["verde"], 0.0, 3.5)
    em_cima = Clip(midias["v43"], 1.0, 1.0)
    lateral = (3, 3, 37, 177)
    sem = exportar(projeto((em_cima,), (embaixo,)), tmp_path / "sem.mp4", tools)
    com = exportar(projeto((replace(em_cima, blur_background=True),), (embaixo,)), tmp_path / "com.mp4", tools)
    # Antes e depois do bloco o chão verde aparece igual nos dois — inclusive
    # logo depois do fim, onde a cauda retida do fundo ainda existe no fluxo.
    for t in (0.5, 2.1, 2.5):
        a, b = quadro_do_arquivo(sem, t, TELA, tools), quadro_do_arquivo(com, t, TELA, tools)
        assert diferenca(a, b, TELA, (0, 0, *TELA)) < 1.5, f"o fundo vazou fora da janela do bloco ({t} s)"
    dentro_sem, dentro_com = quadro_do_arquivo(sem, 1.5, TELA, tools), quadro_do_arquivo(com, 1.5, TELA, tools)
    assert media_da(dentro_sem, TELA, lateral, canais=(1,)) > 200 and media_da(dentro_sem, TELA, lateral, canais=(0,)) < 40
    assert media_da(dentro_com, TELA, lateral, canais=(1,)) < 120, "o verde de baixo continua à mostra"
    assert media_da(dentro_com, TELA, lateral, canais=(0,)) > 100


def test_bloco_com_vao_nao_deixa_o_fundo_nem_antes_nem_depois(midias, tools, tmp_path: Path) -> None:
    """Sem trilha nenhuma por baixo, fora do bloco o quadro é preto como sempre."""
    bloco = Clip(midias["v43"], 0.5, 1.0)
    outro = Clip(midias["v169"], 2.5, 1.0)
    sem = exportar(projeto((bloco, outro)), tmp_path / "sem.mp4", tools)
    com = exportar(projeto((replace(bloco, blur_background=True), outro)), tmp_path / "com.mp4", tools)
    for t in (0.2, 1.7, 2.2):
        a, b = quadro_do_arquivo(sem, t, TELA, tools), quadro_do_arquivo(com, t, TELA, tools)
        assert media_da(b, TELA, (0, 0, *TELA)) < 1.5, f"imagem de fundo fora do bloco ({t} s)"
        assert diferenca(a, b, TELA, (0, 0, *TELA)) < 1.5
    lateral = (3, 3, 37, 177)
    assert media_da(quadro_do_arquivo(com, 1.0, TELA, tools), TELA, lateral) > 10
    assert media_da(quadro_do_arquivo(sem, 1.0, TELA, tools), TELA, lateral) < 1.5


@pytest.mark.parametrize("fps_da_fonte", (24, 25, 30))
@pytest.mark.parametrize("fps_da_tela", (30.0, 60.0))
def test_ultimo_quadro_do_bloco_ainda_tem_fundo(tools, tmp_path: Path, fps_da_fonte: int, fps_da_tela: float) -> None:
    """Defeito medido: com a tela em 60 fps e a fonte em 30, o quadro 89 de 90 saía sem fundo.

    O fluxo do fundo carregava a taxa da fonte e acabava um instante da tela
    antes da frente; ``tpad`` sem taxa conhecida não clona nada. Em cada emenda
    entre blocos com fundo, um quadro de laterais pretas — duração, contagem de
    quadros e streams certos, nenhum erro.
    """
    pasta = tmp_path / "fontes"
    pasta.mkdir()
    fontes = {}
    for nome, filtro in (("bloco", f"testsrc2=s=240x180:r={fps_da_fonte}:d=4"), ("depois", "testsrc2=s=320x180:r=30:d=4")):
        arquivo = pasta / f"{nome}.mp4"
        subprocess.run([tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", filtro,
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(arquivo)], check=True, capture_output=True)
        fontes[nome] = media_ref(probe_file(arquivo, tools))
    bloco = Clip(fontes["bloco"], 0.5, 1.0, blur_background=True)
    saida = exportar(projeto((bloco, Clip(fontes["depois"], 2.5, 1.0)), fps=fps_da_tela), tmp_path / "saida.mp4", tools)
    lateral = (3, 3, 37, 177)
    # Um quarto de quadro antes do instante do quadro: o ``-ss`` entrega o primeiro com pts >= ao pedido.
    for k in (1, 2, 3):
        t = 1.5 - (k + 0.25) / fps_da_tela
        assert media_da(quadro_do_arquivo(saida, t, TELA, tools), TELA, lateral) > 10, f"{k}º quadro antes do fim sem fundo"


# (nome, fonte, tela, clip, fps do projeto)
EXPORTADOS = [
    ("video_4x3", "v43", dict(), 30.0),
    ("foto_vertical", "f916", dict(), 30.0),
    ("velocidade_dobrada", "v43", dict(speed=2.0, in_point=0.5), 30.0),
    ("velocidade_pela_metade", "v43", dict(speed=0.5), 30.0),
    ("fade_de_opacidade", "v43", dict(keyframes=(Keyframe(0.0, opacity=1.0), Keyframe(1.5, opacity=0.0))), 30.0),
    ("encolhendo", "v169", dict(keyframes=(Keyframe(0.0), Keyframe(1.5, scale_x=0.4, scale_y=0.4))), 30.0),
    ("taxa_da_tela_diferente_da_fonte", "v43", dict(), 24.0),
    ("taxa_ntsc", "v43", dict(), 30000 / 1001),
]


@pytest.mark.parametrize("nome,fonte,extra,fps", EXPORTADOS, ids=[c[0] for c in EXPORTADOS])
def test_exportado_tem_a_mesma_duracao_e_os_mesmos_quadros(midias, tools, tmp_path: Path, nome, fonte, extra, fps) -> None:
    """O fundo acrescenta um ramo ao grafo; contar quadros é como se vê um ramo que encurta ou alonga o bloco."""
    sem_clip, com_clip = par(Clip(midias[fonte], 0.0, 1.5, **extra))
    sem = exportar(projeto((sem_clip,), fps=fps), tmp_path / "sem.mp4", tools)
    com = exportar(projeto((com_clip,), fps=fps), tmp_path / "com.mp4", tools)
    (quadros_a, duracao_a), (quadros_b, duracao_b) = contagem(sem, tools), contagem(com, tools)
    assert quadros_b == quadros_a, f"{quadros_a} quadros sem o fundo e {quadros_b} com ele"
    assert duracao_b == pytest.approx(duracao_a, abs=0.02)


@pytest.mark.parametrize("velocidade", (0.5, 2.0))
def test_velocidade_do_bloco_nao_desloca_o_fundo(midias, tools, velocidade: float) -> None:
    sem_clip, com_clip = par(Clip(midias["v43"], 0.0, 1.5, in_point=0.5, speed=velocidade))
    a, b = quadro(projeto((sem_clip,)), 0.75, tools), quadro(projeto((com_clip,)), 0.75, tools)
    assert diferenca(a, b, TELA, (45, 3, 275, 177)) < 1.5
    assert media_da(b, TELA, (3, 3, 37, 177)) > 10


def test_divisao_do_bloco_mantem_o_fundo_nas_duas_metades(midias, tools) -> None:
    proj = projeto((Clip(midias["v43"], 0.0, 2.0, blur_background=True),))
    primeiro = proj.tracks[0].clips[0]
    dividido = proj.split(primeiro.clip_id, 1.0)
    assert len(dividido.tracks[0].clips) == 2
    for t in (0.5, 1.5):
        assert media_da(quadro(dividido, t, tools), TELA, (3, 3, 37, 177)) > 10, f"metade sem fundo em {t} s"


# ---------------------------------------------------------------------------
# Camadas acima e transições
# ---------------------------------------------------------------------------

def test_filtro_acima_tinge_tambem_o_fundo(midias, tools) -> None:
    """O filtro age sobre a composição, e o fundo faz parte dela."""
    bloco = Clip(midias["v43"], 0.0, 2.0, blur_background=True)
    filtro = Clip(MediaRef(Path("Filtro_pb"), MediaKind.IMAGE, duration=2.0), 0.0, 2.0,
                  overlay_type="filter", filter_name="pb")
    proj = Project(tracks=(Track(kind=TrackKind.ADDITIONAL, clips=(filtro,)),
                           Track(kind=TrackKind.VIDEO, clips=(bloco,))),
                   width=TELA[0], height=TELA[1], fps=30.0)
    dados = quadro(proj, 1.0, tools)
    lateral = (3, 3, 37, 177)
    r, g, b = (media_da(dados, TELA, lateral, canais=(c,)) for c in (0, 1, 2))
    assert (r + g + b) / 3 > 10, "o fundo sumiu sob o filtro"
    assert max(abs(r - g), abs(g - b)) < 2.5, f"o filtro preto e branco não alcançou o fundo: {(r, g, b)}"


def test_transicao_entre_bloco_com_fundo_e_bloco_sem_dissolve_o_fundo(midias, tools) -> None:
    esquerda = Clip(midias["v43"], 0.0, 2.0, in_point=0.5, blur_background=True)
    direita = Clip(midias["v43"], 2.0, 2.0, in_point=0.5)
    marcador = Clip(MediaRef(Path("Transição_Dissolve"), MediaKind.IMAGE, 0.5), start=1.75, duration=0.5,
                    overlay_type="transition", transition_name="dissolve",
                    transition_left_id=esquerda.clip_id, transition_right_id=direita.clip_id)
    proj = projeto((esquerda, direita, marcador))
    lateral = (3, 3, 37, 177)
    antes = media_da(quadro(proj, 1.0, tools), TELA, lateral)
    meio = media_da(quadro(proj, 2.0, tools), TELA, lateral)
    depois = media_da(quadro(proj, 3.0, tools), TELA, lateral)
    assert antes > 10 and depois < 1.5, "o fundo devia existir só no bloco da esquerda"
    assert 0.25 * antes < meio < 0.75 * antes, f"a transição não dissolveu o fundo: {antes:.1f} → {meio:.1f} → {depois:.1f}"
