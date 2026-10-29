"""Um bloco de um quadro sai da exportação com um quadro, e o certo.

Com o piso de 50 ms isso não se podia pedir; agora se pode, e a exportação tem de
corresponder. Cada quadro da fonte leva o próprio número desenhado em listras (7 bits),
lido de volta quadro a quadro: tamanho, duração e brilho médio não enxergam um quadro
trocado pelo vizinho, que é o defeito de que isto se defende.
"""

import subprocess
from pathlib import Path

import pytest

from videomanager.domain.composition import Composition
from videomanager.domain.project import Clip, Project, Track, TrackKind, media_ref
from videomanager.infrastructure.ffmpeg.converter import Converter, probe_file
from videomanager.infrastructure.system.binaries import find_tools

pytestmark = pytest.mark.ffmpeg

FPS = 30
QUADRO = 1 / FPS
LADO = 64
QUADROS = 90


@pytest.fixture(scope="module")
def tools():
    found = find_tools()
    if found is None:
        pytest.skip("FFmpeg não disponível")
    return found


def gerar_fonte(tools, pasta: Path, taxa: str, segundos: int) -> Path:
    """``taxa`` na notação do ffmpeg (``30``, ``30000/1001``): o número do quadro em 7 listras e um tom."""
    caminho = pasta / f"fonte_{taxa.replace('/', '_')}.mp4"
    subprocess.run(
        [tools.ffmpeg_str, "-v", "error", "-y",
         "-f", "lavfi", "-i",
         f"color=c=black:s={LADO}x{LADO}:r={taxa}:d={segundos},"
         "geq=lum='if(gte(mod(floor(N/pow(2,floor(X/9))),2),1),200,40)':cb=128:cr=128",
         "-f", "lavfi", "-i", f"sine=f=440:r=48000:d={segundos}",
         "-shortest", "-c:v", "libx264", "-crf", "0", "-g", "30", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(caminho)],
        check=True)
    return caminho


@pytest.fixture(scope="module")
def fonte(tmp_path_factory, tools) -> Path:
    """30 q/s, 3 s."""
    return gerar_fonte(tools, tmp_path_factory.mktemp("quadro_unico"), "30", 3)


def numeros(caminho: Path, tools) -> list[int]:
    """O número de cada quadro do arquivo, lido das listras."""
    bruto = subprocess.run(
        [tools.ffmpeg_str, "-v", "error", "-i", str(caminho), "-vf", "format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True).stdout
    lidos = []
    for i in range(0, len(bruto), LADO * LADO):
        linha = bruto[i + 32 * LADO:i + 33 * LADO]
        lidos.append(sum(1 << b for b in range(7) if linha[9 * b + 4] > 120))
    return lidos


def duracoes(caminho: Path, tools) -> dict[str, float]:
    saida = subprocess.run(
        [tools.ffprobe_str, "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0",
         str(caminho)], capture_output=True, text=True, check=True).stdout
    achados = {}
    for linha in saida.split():
        tipo, _, duracao = linha.partition(",")
        achados[tipo] = float(duracao)
    return achados


def exportar(fonte: Path, tools, tmp_path: Path, trechos: list[tuple[int, int]], fps: float = FPS):
    """Exporta os trechos (primeiro quadro, quantos quadros), emendados na ordem dada."""
    media = media_ref(probe_file(fonte, tools))
    quadro = 1 / fps
    blocos, cursor = [], 0
    for primeiro, quantos in trechos:
        blocos.append(Clip(media, start=cursor * quadro, duration=quantos * quadro, in_point=primeiro * quadro))
        cursor += quantos
    projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=tuple(blocos)),), width=LADO, height=LADO, fps=fps)
    saida = tmp_path / "saida.mp4"
    Converter(probe_file(fonte, tools), Composition(projeto, "mp4"), saida, tools).run()
    return saida


def test_a_fonte_traz_cada_quadro_identificavel(fonte, tools):
    assert numeros(fonte, tools) == list(range(QUADROS))


def test_um_quadro_isolado_sai_com_um_quadro(fonte, tools, tmp_path):
    saida = exportar(fonte, tools, tmp_path, [(10, 1)])
    assert numeros(saida, tools) == [10]
    # O fundo mínimo era de 0,04 s: a 30 q/s, dois quadros, o segundo preto.
    assert duracoes(saida, tools)["video"] == pytest.approx(QUADRO, abs=1e-3)


def test_um_quadro_no_meio_de_outros_sai_no_lugar(fonte, tools, tmp_path):
    saida = exportar(fonte, tools, tmp_path, [(0, 10), (20, 1), (30, 5)])
    assert numeros(saida, tools) == [*range(10), 20, *range(30, 35)]
    tempos = duracoes(saida, tools)
    # O som acompanha a imagem; um quadro de áudio (33 ms) é maior que o bloco do AAC (21 ms).
    assert abs(tempos["audio"] - tempos["video"]) < 0.05


def test_quadros_alternados_um_por_bloco(fonte, tools, tmp_path):
    saida = exportar(fonte, tools, tmp_path, [(n, 1) for n in range(0, QUADROS, 2)])
    assert numeros(saida, tools) == list(range(0, QUADROS, 2))


def test_cada_quadro_em_seu_proprio_bloco_reproduz_a_fonte(fonte, tools, tmp_path):
    saida = exportar(fonte, tools, tmp_path, [(n, 1) for n in range(QUADROS)])
    assert numeros(saida, tools) == list(range(QUADROS))


TAXAS = (("24", 24.0), ("25", 25.0), ("30", 30.0), ("60", 60.0), ("30000/1001", 30000 / 1001), ("24000/1001", 24000 / 1001))


@pytest.mark.parametrize("taxa,fps", TAXAS, ids=[t for t, _ in TAXAS])
def test_cada_emenda_sobre_a_grade_sai_exata_em_qualquer_taxa(tools, tmp_path, taxa, fps):
    """Um bloco por quadro: toda emenda do 1 ao último quadro cai exatamente num limite de quadro.

    O limite de cada janela do compositor era escrito com seis casas decimais, e ``k/fps`` arredondado
    para cima (``2/30`` virava ``0,066667``) tirava do bloco o primeiro quadro dele e o dava, repetido,
    ao anterior: um terço das emendas a 24, 30 e 60 q/s, dois terços nas taxas NTSC.
    """
    origem = gerar_fonte(tools, tmp_path, taxa, 2)
    quadros = min(60, int(2 * fps) - 2)          # sem passar do fim da fonte, que tem 2 s
    saida = exportar(origem, tools, tmp_path, [(n, 1) for n in range(quadros)], fps)
    assert numeros(saida, tools) == list(range(quadros))


@pytest.mark.parametrize("taxa,fps", TAXAS, ids=[t for t, _ in TAXAS])
def test_um_quadro_isolado_sai_com_um_quadro_em_qualquer_taxa(tools, tmp_path, taxa, fps):
    origem = gerar_fonte(tools, tmp_path, taxa, 2)
    saida = exportar(origem, tools, tmp_path, [(7, 1)], fps)
    assert numeros(saida, tools) == [7]
