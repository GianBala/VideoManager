"""O desfoque de região, medido na imagem que o ffmpeg de verdade entrega.

Duração e streams iguais não enxergam um retângulo no lugar errado, uma janela
errada ou um desfoque fraco demais: por isso aqui se mede o quadro. A fonte é
ruído (``noise``) guardado sem perda: nenhum pixel do retângulo sobrevive ao
desfoque, então o retângulo que mudou **é** a região, e o que está fora dele
tem de sair byte a byte igual ao projeto sem o filtro.

Dois caminhos: o quadro parado da prévia (``frame_command``, exato, sem
codificar) e a exportação de verdade (``Converter``, com perdas, medida por
duração, quadros e energia de detalhe).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from fractions import Fraction
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
from videomanager.infrastructure.ffmpeg.composer import export_args
from videomanager.infrastructure.ffmpeg.composer import frame_command
from videomanager.infrastructure.ffmpeg.composer import playback_command
from videomanager.infrastructure.ffmpeg.converter import Converter
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.system.binaries import find_tools
from videomanager.infrastructure.system.binaries import subprocess_kwargs

pytestmark = pytest.mark.ffmpeg

TELA = (320, 180)
FPS = 30.0


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


def _desfoque(inicio: float, duracao: float, x: float = 0.5, y: float = 0.5, escala: float = 0.3, **extra) -> Clip:
    media = pseudo_media(OverlayType.FILTER, "Desfoque", duracao)
    return Clip(media, inicio, duracao, overlay_type="filter", filter_name="desfoque",
                x=x, y=y, scale=escala, scale_x=escala, scale_y=escala, **extra)


def _projeto(tools, fonte: Path, *filtros: Clip, tela: tuple[int, int] = TELA, duracao: float = 4.0) -> Project:
    video = Clip(media_ref(probe_file(fonte, tools)), 0.0, duracao)
    trilhas = [Track(TrackKind.VIDEO, clips=(video,), name="Vídeo 1")]
    if filtros:
        trilhas.insert(0, Track(TrackKind.ADDITIONAL, clips=tuple(filtros), name="Adicionais 1"))
    return Project(tracks=tuple(trilhas), width=tela[0], height=tela[1], fps=FPS)


def _quadro(tools, projeto: Project, indice: int, tela: tuple[int, int] = TELA) -> bytes:
    """O quadro ``indice`` da composição, em rgb24 cru, como a prévia o desenha."""
    dados = subprocess.run(frame_command(projeto, (indice + 0.5) / FPS, tela, tools), check=True, timeout=60,
                           **subprocess_kwargs()).stdout
    assert len(dados) == tela[0] * tela[1] * 3
    return dados


def _caixa_que_mudou(a: bytes, b: bytes, tela: tuple[int, int] = TELA, limiar: int = 0) -> tuple[int, int, int, int] | None:
    """``(esquerda, topo, direita, base)`` dos pixels que diferem em mais de ``limiar`` níveis, ou ``None``."""
    largura, altura = tela
    esq, topo, dir_, base = largura, altura, -1, -1
    for y in range(altura):
        linha = slice(y * largura * 3, (y + 1) * largura * 3)
        ra, rb = a[linha], b[linha]
        if ra == rb:
            continue
        diferentes = [x for x in range(largura)
                      if max(abs(ra[x * 3 + c] - rb[x * 3 + c]) for c in range(3)) > limiar]
        if not diferentes:
            continue
        topo, base = min(topo, y), max(base, y)
        esq, dir_ = min(esq, diferentes[0]), max(dir_, diferentes[-1])
    return None if dir_ < 0 else (esq, topo, dir_ + 1, base + 1)


def _detalhe(quadro: bytes, retangulo: tuple[int, int, int, int], tela: tuple[int, int] = TELA) -> float:
    """Energia de detalhe do verde dentro do retângulo: soma das diferenças entre pixels vizinhos."""
    largura, _ = tela
    esq, topo, w, h = retangulo
    total = 0
    for y in range(topo, topo + h):
        linha = quadro[(y * largura + esq) * 3 + 1:(y * largura + esq + w) * 3:3]
        total += sum(abs(linha[i + 1] - linha[i]) for i in range(len(linha) - 1))
    return total / (w * h)


def _retangulo(filtro: Clip, indice: int, tela: tuple[int, int] = TELA) -> tuple[int, int, int, int]:
    """Onde o domínio diz que a região está no quadro ``indice`` da prévia.

    A prévia compõe no **instante pedido** (aqui o meio do quadro), e a caixa de seleção do
    editor lê a pose no mesmo instante; só a exportação usa o pts do quadro.
    """
    return filtro.region_rect(tela[0], tela[1], (indice + 0.5) / FPS - filtro.start)


# -- onde e quando ---------------------------------------------------------------

def test_so_o_retangulo_muda_e_ele_e_o_que_o_dominio_calcula(tools, ruido) -> None:
    filtro = _desfoque(1.0, 1.5)
    com, sem = _projeto(tools, ruido, filtro), _projeto(tools, ruido)
    a, b = _quadro(tools, com, 45), _quadro(tools, sem, 45)
    esq, topo, w, h = _retangulo(filtro, 45)
    assert _caixa_que_mudou(a, b) == (esq, topo, esq + w, topo + h)


def test_dentro_do_retangulo_o_detalhe_some(tools, ruido) -> None:
    filtro = _desfoque(1.0, 1.5)
    a, b = _quadro(tools, _projeto(tools, ruido, filtro), 45), _quadro(tools, _projeto(tools, ruido), 45)
    retangulo = _retangulo(filtro, 45)
    assert _detalhe(a, retangulo) < _detalhe(b, retangulo) / 10


@pytest.mark.parametrize("indice, borrado", [
    (29, False),    # o último quadro antes da janela (começa em 1,0 s = quadro 30)
    (30, True),     # o primeiro da janela
    (74, True),     # o último da janela (termina em 2,5 s = quadro 75, exclusivo)
    (75, False),    # o primeiro depois dela
])
def test_o_desfoque_vale_so_dentro_da_janela_do_bloco(tools, ruido, indice, borrado) -> None:
    com, sem = _projeto(tools, ruido, _desfoque(1.0, 1.5)), _projeto(tools, ruido)
    assert (_quadro(tools, com, indice) != _quadro(tools, sem, indice)) is borrado



# -- animação e bordas ---------------------------------------------------------------

def test_a_posicao_anima_com_os_quadros_chave_e_o_tamanho_nao(tools, ruido) -> None:
    filtro = _desfoque(1.0, 1.5, x=0.25, escala=0.25, keyframes=(
        Keyframe(0.0, x=0.25, y=0.5, scale_x=0.25, scale_y=0.25),
        Keyframe(1.5, x=0.75, y=0.5, scale_x=0.25, scale_y=0.25),
    ))
    com, sem = _projeto(tools, ruido, filtro), _projeto(tools, ruido)
    posicoes = []
    for indice in (30, 52, 74):
        esq, topo, w, h = _retangulo(filtro, indice)
        assert _caixa_que_mudou(_quadro(tools, com, indice), _quadro(tools, sem, indice)) == (esq, topo, esq + w, topo + h)
        posicoes.append((esq, w, h))
    assert posicoes[0][0] < posicoes[1][0] < posicoes[2][0]
    assert len({(w, h) for _, w, h in posicoes}) == 1


@pytest.mark.parametrize("x, y", [(-0.3, 0.5), (1.3, 0.5), (0.5, -0.3), (0.5, 1.3), (0.4003, 0.3991)])
def test_a_regiao_nunca_sai_da_tela_nem_cai_em_pixel_impar(tools, ruido, x, y) -> None:
    filtro = _desfoque(1.0, 1.5, x=x, y=y)
    a, b = _quadro(tools, _projeto(tools, ruido, filtro), 45), _quadro(tools, _projeto(tools, ruido), 45)
    esq, topo, w, h = _retangulo(filtro, 45)
    assert esq % 2 == 0 and topo % 2 == 0
    assert 0 <= esq and esq + w <= TELA[0] and 0 <= topo and topo + h <= TELA[1]
    assert _caixa_que_mudou(a, b) == (esq, topo, esq + w, topo + h)


@pytest.mark.parametrize("tela, fonte_escala", [((640, 360), "maior"), ((160, 90), "menor")])
def test_a_regiao_e_fracao_da_tela_do_projeto(tools, ruido, tela, fonte_escala) -> None:
    filtro = _desfoque(1.0, 1.5, x=0.3, y=0.6, escala=0.4)
    com, sem = _projeto(tools, ruido, filtro, tela=tela), _projeto(tools, ruido, tela=tela)
    a, b = _quadro(tools, com, 45, tela), _quadro(tools, sem, 45, tela)
    esq, topo, w, h = _retangulo(filtro, 45, tela)
    assert (w, h) == (int(tela[0] * 0.4) // 2 * 2, int(tela[1] * 0.4) // 2 * 2)
    assert _caixa_que_mudou(a, b, tela) == (esq, topo, esq + w, topo + h)


def test_dois_desfoques_no_mesmo_projeto_nao_repetem_rotulo(tools, ruido) -> None:
    primeiro, segundo = _desfoque(0.0, 2.0, x=0.2), _desfoque(0.0, 2.0, x=0.8)
    projeto = replace(_projeto(tools, ruido, primeiro), tracks=(
        Track(TrackKind.ADDITIONAL, clips=(primeiro,), name="Adicionais 1"),
        Track(TrackKind.ADDITIONAL, clips=(segundo,), name="Adicionais 2"),
        *_projeto(tools, ruido).tracks))
    a, b = _quadro(tools, projeto, 15), _quadro(tools, _projeto(tools, ruido), 15)
    r1, r2 = _retangulo(primeiro, 15), _retangulo(segundo, 15)
    esq, topo, dir_, base = _caixa_que_mudou(a, b)
    assert (esq, dir_) == (r1[0], r2[0] + r2[2]) and (topo, base) == (r1[1], r1[1] + r1[3])


# -- exportação de verdade ---------------------------------------------------------------

def _exportar(tools, projeto: Project, fonte: Path, destino: Path, container: str = "mp4") -> Path:
    Converter(probe_file(fonte, tools), Composition(projeto, container), destino, tools).run()
    return destino


def _ffprobe(tools, path: Path) -> dict:
    saida = subprocess.run(
        [tools.ffprobe_str, "-v", "quiet", "-print_format", "json", "-count_frames", "-show_format",
         "-show_streams", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(saida)


def _quadro_do_arquivo(tools, path: Path, indice: int) -> bytes:
    return subprocess.run(
        [tools.ffmpeg_str, "-hide_banner", "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{indice})",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True).stdout


def test_a_exportacao_preserva_duracao_e_quadros_e_borra_so_a_regiao(tools, ruido, tmp_path: Path) -> None:
    filtro = _desfoque(1.0, 1.5)
    com = _exportar(tools, _projeto(tools, ruido, filtro), ruido, tmp_path / "com.mp4")
    sem = _exportar(tools, _projeto(tools, ruido), ruido, tmp_path / "sem.mp4")
    pc, ps = _ffprobe(tools, com), _ffprobe(tools, sem)
    assert float(pc["format"]["duration"]) == pytest.approx(float(ps["format"]["duration"]), abs=0.05)
    assert pc["streams"][0]["nb_read_frames"] == ps["streams"][0]["nb_read_frames"]
    retangulo = _retangulo(filtro, 45)
    assert _detalhe(_quadro_do_arquivo(tools, com, 45), retangulo) < _detalhe(_quadro_do_arquivo(tools, sem, 45), retangulo) / 5
    # Fora da janela o arquivo é o mesmo (a codificação com perdas não deixa comparar byte a byte).
    assert _detalhe(_quadro_do_arquivo(tools, com, 10), retangulo) == pytest.approx(
        _detalhe(_quadro_do_arquivo(tools, sem, 10), retangulo), rel=0.1)


def test_a_janela_que_termina_entre_dois_quadros_borra_o_ultimo(tools, ruido, tmp_path: Path) -> None:
    """O último quadro da janela continua borrado quando ela termina entre dois quadros.

    O ramo já foi aparado por um ``trim``, que descarta o quadro cujo **fim** passa de ``end``: 4 de 10 janelas de borda
    arbitrária perdiam exatamente um quadro de região, e a duração, a contagem de quadros e o código de saída não
    mostravam nada. Sem o ``trim`` quem liga e desliga o efeito é só o ``enable``; o caso fica medido porque só a
    exportação mede o quadro pelo pts (a prévia compõe no instante pedido).
    """
    filtro = _desfoque(1.016, 1.967)                     # termina em 2,983 s: entre os quadros 89 e 90
    com = _exportar(tools, _projeto(tools, ruido, filtro), ruido, tmp_path / "com.mp4")
    sem = _exportar(tools, _projeto(tools, ruido), ruido, tmp_path / "sem.mp4")
    retangulo = filtro.region_rect(TELA[0], TELA[1], 0.0)
    # O quadro 89 (pts 2,9667 s) está dentro da janela; o 90 (3,0 s), fora.
    assert _detalhe(_quadro_do_arquivo(tools, com, 89), retangulo) < _detalhe(_quadro_do_arquivo(tools, sem, 89), retangulo) / 5
    assert _detalhe(_quadro_do_arquivo(tools, com, 90), retangulo) == pytest.approx(
        _detalhe(_quadro_do_arquivo(tools, sem, 90), retangulo), rel=0.1)


def test_o_desfoque_sobre_uma_transicao_nao_quebra_a_exportacao(tools, ruido, tmp_path: Path) -> None:
    esquerda = Clip(media_ref(probe_file(ruido, tools)), 0.0, 2.0)
    direita = Clip(media_ref(probe_file(ruido, tools)), 2.0, 2.0)
    marca = Clip(pseudo_media(OverlayType.TRANSITION, "Dissolve", 1.0), 1.5, 1.0, overlay_type="transition",
                 transition_name="dissolve", transition_left_id=esquerda.clip_id, transition_right_id=direita.clip_id)
    filtro = _desfoque(1.0, 2.0)                       # atravessa a janela da transição (1,5 s a 2,5 s)
    projeto = Project(tracks=(
        Track(TrackKind.ADDITIONAL, clips=(filtro,), name="Adicionais 1"),
        Track(TrackKind.VIDEO, clips=(esquerda, marca, direita), name="Vídeo 1"),
    ), width=TELA[0], height=TELA[1], fps=FPS)
    saida = _exportar(tools, projeto, ruido, tmp_path / "transicao.mp4")
    assert float(_ffprobe(tools, saida)["format"]["duration"]) == pytest.approx(4.0, abs=0.1)
    # Um quadro no meio da transição: a região está borrada, nem a emenda a perdeu.
    quadro = _quadro_do_arquivo(tools, saida, 60)
    sem = _exportar(tools, replace(projeto, tracks=projeto.tracks[1:]), ruido, tmp_path / "sem.mp4")
    retangulo = filtro.region_rect(TELA[0], TELA[1], 0.0)
    assert _detalhe(quadro, retangulo) < _detalhe(_quadro_do_arquivo(tools, sem, 60), retangulo) / 3


def test_o_projeto_com_desfoque_exporta_gif_e_so_audio(tools, ruido, tmp_path: Path) -> None:
    projeto = _projeto(tools, ruido, _desfoque(1.0, 1.5))
    gif = tmp_path / "saida.gif"
    Converter(probe_file(ruido, tools), Composition(replace(projeto, fps=10.0), "gif"), gif, tools).run()
    assert gif.stat().st_size > 0
    audio = tmp_path / "saida.mp3"
    # Sem trilha de som o pedido não faz sentido; basta que o filtro não derrube a montagem do grafo.
    from videomanager.infrastructure.ffmpeg.composer import build_graph
    grafo = build_graph(projeto, want_video=False, want_audio=True)
    assert grafo.video_label is None
    assert not audio.exists()


def test_a_exportacao_paralela_com_interpolacao_borra_a_regiao_como_a_serial(tools, ruido, tmp_path: Path, monkeypatch) -> None:
    """Cada trecho da exportação paralela compõe numa janela própria: a posição animada e a janela
    do desfoque têm de continuar certas nas emendas, e o arquivo, igual ao serial em quadros."""
    from videomanager.infrastructure.ffmpeg import converter as converter_mod
    from videomanager.infrastructure.ffmpeg import parallel as parallel_mod

    filtro = _desfoque(1.0, 2.0, x=0.25, escala=0.25, keyframes=(
        Keyframe(0.0, x=0.25, y=0.5, scale_x=0.25, scale_y=0.25),
        Keyframe(2.0, x=0.75, y=0.5, scale_x=0.25, scale_y=0.25)))
    projeto = replace(_projeto(tools, ruido, filtro), fps=60.0)
    sem = replace(_projeto(tools, ruido), fps=60.0)

    consultas: list[int] = []

    def exporta(proj: Project, nome: str, trechos: int) -> Path:
        def plano(_c, n=trechos) -> int:
            consultas.append(n)
            return n
        monkeypatch.setattr(parallel_mod, "plan_segments", plano)
        monkeypatch.setattr(converter_mod, "plan_segments", plano)
        destino = tmp_path / nome
        Converter(probe_file(ruido, tools), Composition(proj, "mp4", interpolate=True), destino, tools).run()
        return destino

    serial, paralelo = exporta(projeto, "serial.mp4", 1), exporta(projeto, "paralelo.mp4", 3)
    base = exporta(sem, "sem.mp4", 1)
    assert 3 in consultas, "a exportação de três trechos não passou pelo plano: o caminho paralelo não rodou"
    ps, pp = _ffprobe(tools, serial), _ffprobe(tools, paralelo)
    assert float(pp["format"]["duration"]) == pytest.approx(float(ps["format"]["duration"]), abs=0.05)
    assert pp["streams"][0]["nb_read_frames"] == ps["streams"][0]["nb_read_frames"]
    # Quadros nas emendas (1,33 s e 2,67 s a 60 fps), dentro da janela: borrados nos dois arquivos.
    for indice in (60, 79, 80, 120, 159, 160, 179):
        retangulo = filtro.region_rect(TELA[0], TELA[1], indice / 60.0 - filtro.start)
        referencia = _detalhe(_quadro_do_arquivo(tools, base, indice), retangulo)
        for arquivo in (serial, paralelo):
            assert _detalhe(_quadro_do_arquivo(tools, arquivo, indice), retangulo) < referencia / 4, (arquivo.name, indice)


def test_dividir_o_bloco_com_quadros_chave_nao_muda_onde_a_regiao_esta(tools, ruido) -> None:
    """A tesoura desloca os quadros-chave da metade de trás; a região tem de continuar no mesmo pixel dos dois lados."""
    filtro = _desfoque(1.0, 2.0, x=0.25, escala=0.25, keyframes=(
        Keyframe(0.0, x=0.25, y=0.5, scale_x=0.25, scale_y=0.25),
        Keyframe(2.0, x=0.75, y=0.5, scale_x=0.25, scale_y=0.25)))
    inteiro = _projeto(tools, ruido, filtro)
    dividido = inteiro.split(filtro.clip_id, 2.0)
    assert sum(len(t.clips) for t in dividido.additional_tracks) == 2
    for indice in (31, 44, 59, 60, 61, 74, 88):                # antes, na emenda (2,0 s = quadro 60) e depois
        assert _quadro(tools, dividido, indice) == _quadro(tools, inteiro, indice), indice


# -- memória: o desfoque no fim do projeto não custa mais que no começo ------------------------------

SEM_WAIT4 = pytest.mark.skipif(not hasattr(os, "wait4"), reason="o pico do filho vem do wait4 (só Unix)")
# O ruído entre duas execuções do mesmo ffmpeg é de poucos MB; o defeito que isto pega somava ~265 MB.
FOLGA_MB = 100


@pytest.fixture(scope="module")
def fonte_longa(tools, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("longa") / "longa.mp4"
    subprocess.run(
        [tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=45",
         "-c:v", "libx264", "-preset", "ultrafast", "-g", "60", str(path)],
        check=True, timeout=60, **subprocess_kwargs())
    return path


# O ``ru_maxrss`` de um filho tem como piso o pico histórico do pai (o Linux o herda no ``exec``), e o pytest já
# passou de 300 MB lendo fluxos: por isso quem mede é um interpretador pequeno e limpo, não o próprio teste.
_MEDIDOR = """
import json, os, subprocess, sys
p = subprocess.Popen(json.loads(sys.argv[1]), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
while p.stdout.read(1 << 20):    # a reprodução despeja os quadros no cano; a exportação não escreve nada nele
    pass
_, estado, uso = os.wait4(p.pid, 0)
p.stdout.close()
print(os.waitstatus_to_exitcode(estado), uso.ru_maxrss / 1024)
"""


def _pico_de_memoria_mb(comando: list[str]) -> float:
    """Pico de memória do ffmpeg, em MB: o ``ru_maxrss`` do próprio filho, que o ``wait4`` devolve."""
    saida = subprocess.run([sys.executable, "-I", "-c", _MEDIDOR, json.dumps([str(a) for a in comando])],
                           capture_output=True, text=True, check=True, timeout=120).stdout
    codigo, pico = saida.split()
    assert int(codigo) == 0, "o ffmpeg falhou"
    return float(pico)


@SEM_WAIT4
def test_o_pico_de_memoria_da_exportacao_nao_cresce_com_o_instante_do_desfoque(tools, fonte_longa, tmp_path: Path) -> None:
    """O ``trim`` do ramo fazia o ``overlay`` guardar todo quadro anterior ao bloco: ~228 MB por segundo de
    antecedência a 1080p (medido), ou seja, ~14 GB para um desfoque aos 60 s. Os outros testes põem o bloco
    entre 0 e 1,5 s e não enxergam isto."""
    def pico(inicio: float) -> float:
        projeto = _projeto(tools, fonte_longa, _desfoque(inicio, 3.0), duracao=45.0)
        return _pico_de_memoria_mb(export_args(projeto, tmp_path / "saida.mp4", tools))
    assert pico(40.0) < pico(0.0) + FOLGA_MB


@SEM_WAIT4
def test_o_pico_de_memoria_da_reproducao_nao_cresce_com_o_desfoque_adiante(tools, fonte_longa) -> None:
    """O mesmo defeito na reprodução, que parte da agulha: o primeiro quadro só saía depois de o ffmpeg
    decodificar toda a antecedência, e ele a guardava."""
    def pico(inicio: float) -> float:
        projeto = _projeto(tools, fonte_longa, _desfoque(inicio, 3.0), duracao=45.0)
        return _pico_de_memoria_mb(playback_command(projeto, 0.0, TELA, tools, fps=FPS))
    assert pico(40.0) < pico(0.0) + FOLGA_MB


# -- a exportação em pts, medida no grafo (sem codificar) ---------------------------------------

def _quadros_exportados(tools, projeto: Project, tela: tuple[int, int] = TELA) -> list[bytes]:
    """Os quadros que a exportação compõe, em rgb24 cru: o grafo de ``export_args``, medido no pts de cada quadro."""
    grafo = build_graph(projeto.for_export())
    filtros = ";".join([*grafo.filters, f"{grafo.video_label}format=rgb24[saida]"])
    saida = subprocess.run(
        [tools.ffmpeg_str, "-nostdin", "-v", "error", *grafo.inputs, "-filter_complex", filtros, "-map", "[saida]",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], check=True, capture_output=True, timeout=120).stdout
    tamanho = tela[0] * tela[1] * 3
    assert saida and len(saida) % tamanho == 0
    return [saida[i:i + tamanho] for i in range(0, len(saida), tamanho)]


def _ruido_em(tools, pasta: Path, taxa: str, segundos: int = 2) -> Path:
    path = pasta / f"ruido_{taxa.replace('/', '_')}.mkv"
    subprocess.run(
        [tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
         f"color=c=gray:s=320x180:r={taxa}:d={segundos},noise=alls=90:allf=t+u",
         "-c:v", "ffv1", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=60, **subprocess_kwargs())
    return path


@pytest.mark.parametrize("taxa", ["24000/1001", "30000/1001", "60000/1001"])
def test_a_exportacao_cai_no_retangulo_do_dominio_em_taxa_fracionaria(tools, tmp_path: Path, taxa: str) -> None:
    """O plano pedia taxa inteira **e** NTSC. A exportação compõe no pts do quadro (i·1001/30000 s, e não i/30), então a
    posição animada e a janela do bloco têm de continuar no pixel certo com taxas que não fecham em igualdade."""
    fps = float(Fraction(taxa))
    fonte = _ruido_em(tools, tmp_path, taxa)
    filtro = _desfoque(0.4, 1.2, x=0.25, escala=0.25, keyframes=(
        Keyframe(0.0, x=0.25, y=0.5, scale_x=0.25, scale_y=0.25),
        Keyframe(1.2, x=0.75, y=0.5, scale_x=0.25, scale_y=0.25)))
    com = replace(_projeto(tools, fonte, filtro, duracao=2.0), fps=fps)
    sem = replace(_projeto(tools, fonte, duracao=2.0), fps=fps)
    quadros_com, quadros_sem = _quadros_exportados(tools, com), _quadros_exportados(tools, sem)
    assert len(quadros_com) == len(quadros_sem) > 0
    dentro = 0
    for indice, (a, b) in enumerate(zip(quadros_com, quadros_sem)):
        instante = indice / fps
        caixa = _caixa_que_mudou(a, b)
        if filtro.start <= instante < filtro.start + filtro.duration:
            esq, topo, w, h = filtro.region_rect(TELA[0], TELA[1], instante - filtro.start)
            assert caixa == (esq, topo, esq + w, topo + h), (indice, instante)
            dentro += 1
        else:
            assert caixa is None, (indice, instante)
    assert dentro >= int(1.2 * fps) - 1


@pytest.mark.parametrize("inicio, duracao", [(1.0, 2.0), (1.0, 0.8), (2.1, 1.0)],
                         ids=["atravessa o corte", "termina dentro da janela", "começa dentro da janela"])
def test_o_desfoque_na_transicao_que_afeta_adicionais_fica_no_retangulo(tools, ruido, inicio, duracao) -> None:
    """Com "Afetar itens adicionais" cada lado da transição recebe os pixels já compostos e o filtro age sobre eles: é o
    caminho que recompõe o quadro. O desfoque tem de seguir no mesmo retângulo. O limiar de 2 níveis é do ffmpeg 9,
    que arredonda o resto do quadro em ±1 (``premultiply``/``unpremultiply``) com e sem o desfoque."""
    esquerda = Clip(media_ref(probe_file(ruido, tools)), 0.0, 2.0)
    direita = Clip(media_ref(probe_file(ruido, tools)), 2.0, 2.0)
    marca = Clip(pseudo_media(OverlayType.TRANSITION, "Dissolve", 1.0), 1.5, 1.0, overlay_type="transition",
                 transition_name="dissolve", transition_left_id=esquerda.clip_id, transition_right_id=direita.clip_id,
                 transition_affects_additionals=True)
    filtro = _desfoque(inicio, duracao)
    video = Track(TrackKind.VIDEO, clips=(esquerda, marca, direita), name="Vídeo 1")
    com = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(filtro,), name="Adicionais 1"), video),
                  width=TELA[0], height=TELA[1], fps=FPS)
    sem = replace(com, tracks=(video,))
    quadros_com, quadros_sem = _quadros_exportados(tools, com), _quadros_exportados(tools, sem)
    assert len(quadros_com) == len(quadros_sem) > 0
    esq, topo, w, h = filtro.region_rect(TELA[0], TELA[1], 0.0)
    for indice, (a, b) in enumerate(zip(quadros_com, quadros_sem)):
        instante = indice / FPS
        esperado = (esq, topo, esq + w, topo + h) if inicio <= instante < inicio + duracao - 1e-9 else None
        assert _caixa_que_mudou(a, b, limiar=2) == esperado, (indice, instante)


# -- a força: um traço de letra some, e nenhuma cor nasce --------------------------------------------

@pytest.fixture(scope="module")
def listras(tools, tmp_path_factory) -> Path:
    """Listras vermelhas e azuis de 15 px: o contraste de um traço de letra, em cores que acusam um canal que se mexe sozinho."""
    path = tmp_path_factory.mktemp("listras") / "listras.mkv"
    subprocess.run(
        [tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
         "color=c=black:s=320x180:r=30:d=2,format=rgb24,"
         "geq=r='if(lt(mod(X,30),15),255,0)':g='0':b='if(lt(mod(X,30),15),0,255)'",
         "-c:v", "ffv1", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=60, **subprocess_kwargs())
    return path


def _miolo(quadro: bytes, retangulo: tuple[int, int, int, int], folga: int = 12) -> tuple[float, int]:
    """``(contraste médio entre pixels vizinhos nos três canais, maior verde)`` do miolo do retângulo."""
    esq, topo, w, h = retangulo
    total, pares, verde = 0, 0, 0
    for y in range(topo + folga, topo + h - folga):
        for x in range(esq + folga, esq + w - folga - 1):
            i = (y * TELA[0] + x) * 3
            total += sum(abs(quadro[i + c] - quadro[i + 3 + c]) for c in range(3))
            pares += 1
            verde = max(verde, quadro[i + 1])
    return total / pares, verde


def test_o_desfoque_apaga_um_traco_de_letra_e_nao_inventa_cor(tools, listras) -> None:
    """Medido na imagem (a fonte de ruído dos outros testes é destruída por qualquer desfoque, até por um fraco demais).

    Com as constantes certas o contraste do miolo cai a ~3% e a fonte, que não tem verde, continua sem verde (máximo 1).
    Com σ de 0,1 do lado sobram ~57% do contraste (o texto de uma placa ainda se lê); com o ``gblur`` em ``yuv420p``
    nascem faixas verdes de até 205 num recorte de 16 px.
    """
    filtro = _desfoque(0.5, 1.0)
    com, sem = _projeto(tools, listras, filtro, duracao=2.0), _projeto(tools, listras, duracao=2.0)
    retangulo = _retangulo(filtro, 30)
    contraste_antes, _ = _miolo(_quadro(tools, sem, 30), retangulo)
    contraste_depois, verde = _miolo(_quadro(tools, com, 30), retangulo)
    assert contraste_depois < contraste_antes * 0.1
    assert verde <= 10
