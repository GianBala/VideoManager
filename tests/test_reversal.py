"""Bloco invertido, medido na saída do ffmpeg de verdade.

Chegar ao fim sem erro não diz nada aqui: um ``reverse`` no lugar errado ainda
exporta um arquivo com a duração certa. O que se confere é a **ordem dos
quadros** e das amostras — a fonte tem brilho ``16 + 1,8 × número do quadro`` e
um tom que sobe de 200 a 1200 Hz, então a ordem aparece no número — e que o
quadro parado da prévia é o mesmo que a exportação mostra no mesmo instante.
"""

import array
import math
import subprocess
import time
from dataclasses import replace

import pytest

from videomanager.application.errors import ConversionError
from videomanager.domain.composition import Composition
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import Clip, Project, Track, TrackKind, media_ref
from videomanager.infrastructure.ffmpeg import composer
from videomanager.infrastructure.ffmpeg.command_assets import filter_script
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.ffmpeg.parallel import ParallelExport, reversal_bounds
from videomanager.infrastructure.ffmpeg.preview import FramePump
from videomanager.infrastructure.ffmpeg.stages import open_process
from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs

pytestmark = pytest.mark.ffmpeg
SIZE = (64, 64)
FPS = 30.0
SECONDS = 4


@pytest.fixture(scope="module")
def tools():
    found = find_tools()
    if found is None:
        pytest.skip("FFmpeg não disponível")
    return found


def _run(tools, *args):
    done = subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", *args],
                          timeout=180, **subprocess_kwargs())
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-800:]
    return done.stdout


@pytest.fixture(scope="module")
def fonte(tools, tmp_path_factory):
    """Quatro segundos: o brilho conta os quadros e o tom sobe com o tempo."""
    path = tmp_path_factory.mktemp("inversao") / "contador.mp4"
    _run(tools,
         "-f", "lavfi", "-i", f"color=c=black:s=64x64:r=30:d={SECONDS},format=yuv420p,"
                              "geq=lum='16+mod(N*1.8,219)':cb=128:cr=128",
         "-f", "lavfi", "-i", f"aevalsrc='sin(2*PI*(200*t+125*t*t))':d={SECONDS}:s=48000:c=stereo",
         "-c:v", "libx264", "-crf", "0", "-g", "15", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
         str(path))
    return media_ref(probe_file(path, tools))


def _projeto(*clips, fps=FPS):
    return Project(tracks=(Track(TrackKind.VIDEO, clips=tuple(clips)),), width=SIZE[0], height=SIZE[1], fps=fps)


def _exporta(tools, projeto, destino, **opcoes):
    subprocess.run(composer.export_args(projeto, destino, tools, **opcoes), check=True,
                   timeout=180, **subprocess_kwargs())
    return destino


def _brilhos(tools, path):
    """Brilho médio de cada quadro do arquivo, na ordem em que ele toca."""
    dados = _run(tools, "-i", str(path), "-vf", "scale=16:16:flags=area", "-pix_fmt", "gray", "-f", "rawvideo", "-")
    return [sum(dados[i:i + 256]) / 256 for i in range(0, len(dados) - 255, 256)]


def _amostras(tools, path):
    dados = _run(tools, "-i", str(path), "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "-")
    saida = array.array("h")
    saida.frombytes(dados[: len(dados) // 2 * 2])
    return saida


def _canal_esquerdo(tools, path):
    dados = _run(tools, "-i", str(path), "-vn", "-ac", "2", "-ar", "48000", "-f", "s16le", "-")
    saida = array.array("h")
    saida.frombytes(dados[: len(dados) // 4 * 4])
    return saida[0::2]


def _erro_relativo(a, b):
    n = min(len(a), len(b))
    diferenca = math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(n)) / n)
    return diferenca / (math.sqrt(sum(v * v for v in b[:n]) / n) or 1.0)


def _lidos(tools, comando, tamanho):
    """Todos os bytes que um comando (ou uma sequência de comandos) entrega."""
    with filter_script(comando) as pronto:
        processo = open_process(pronto, **subprocess_kwargs())
        dados = processo.stdout.read(-1)
        processo.wait(timeout=60)
    assert processo.returncode == 0
    return dados


def _quadros_da_reproducao(tools, projeto, instante):
    comando = composer.playback_command(projeto, instante, SIZE, tools, fps=FPS)
    dados = _lidos(tools, comando, SIZE)
    tam = SIZE[0] * SIZE[1] * 3
    return [sum(0.299 * dados[i + j] + 0.587 * dados[i + j + 1] + 0.114 * dados[i + j + 2]
                for j in range(0, tam, 3)) / (tam / 3) for i in range(0, len(dados) - tam + 1, tam)]


# ---------------------------------------------------------------------------
# Imagem e som da exportação
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("campos", [
    dict(duration=4.0),
    dict(duration=2.0, in_point=1.0),
    dict(duration=1.37, in_point=0.83),
    dict(duration=2.0, in_point=0.5, speed=0.5),
], ids=["inteiro", "trecho", "tempos_quebrados", "metade_da_velocidade"])
def test_exportacao_invertida_e_o_espelho_da_normal(tools, fonte, tmp_path, campos):
    normal = _brilhos(tools, _exporta(tools, _projeto(Clip(fonte, 0.0, **campos)), tmp_path / "n.mp4"))
    invertido = _brilhos(tools, _exporta(tools, _projeto(Clip(fonte, 0.0, reversed=True, **campos)), tmp_path / "i.mp4"))
    assert len(invertido) == len(normal) > 20
    assert all(abs(invertido[k] - normal[-1 - k]) < 0.5 for k in range(len(normal)))
    assert len(set(round(v) for v in invertido)) > 10  # a fonte varia: o espelho não é trivial


def test_velocidade_dobrada_toca_o_trecho_inteiro_ao_contrario(tools, fonte, tmp_path):
    """Com 2× o ffmpeg descarta um quadro a cada dois e a paridade muda ao ler ao
    contrário, então o espelho exato não existe; vale a ordem e a contagem."""
    campos = dict(duration=1.0, in_point=1.0, speed=2.0)
    normal = _brilhos(tools, _exporta(tools, _projeto(Clip(fonte, 0.0, **campos)), tmp_path / "n.mp4"))
    invertido = _brilhos(tools, _exporta(tools, _projeto(Clip(fonte, 0.0, reversed=True, **campos)), tmp_path / "i.mp4"))
    assert len(invertido) == len(normal)
    assert all(a >= b - 1 for a, b in zip(invertido, invertido[1:]))  # só desce
    assert abs(invertido[0] - normal[-1]) <= 5 and abs(invertido[-1] - normal[0]) <= 5


@pytest.mark.parametrize("campos", [
    dict(duration=4.0),
    dict(duration=2.0, in_point=1.0),
], ids=["inteiro", "trecho"])
def test_som_invertido_amostra_a_amostra(tools, fonte, tmp_path, campos):
    """O som invertido é o trecho exato da fonte, de trás para frente.

    A referência é a decodificação da própria fonte, e não a exportação normal: o
    bloco normal que começa no meio do arquivo perde cerca de 1000 amostras no
    começo (o primeiro quadro do AAC sai sem o vizinho de sobreposição), e o
    invertido lê mais cedo para não carregar esse defeito (``_PREROLL``).
    """
    invertido = _amostras(tools, _exporta(tools, _projeto(Clip(fonte, 0.0, reversed=True, **campos)),
                                          tmp_path / "i.wav", container="wav", audio_only=True, audio_codec="wav"))
    exata = _amostras(tools, fonte.path)
    inicio = round(campos.get("in_point", 0.0) * 48_000)
    trecho = exata[inicio:inicio + round(campos["duration"] * 48_000)]
    assert len(invertido) == len(trecho) > 40_000
    assert _erro_relativo(invertido, trecho[::-1]) < 1e-4  # sobra só o arredondamento do descendente para mono
    assert _erro_relativo(invertido, trecho) > 0.5  # e não é o som normal


def test_volume_do_bloco_vale_no_som_invertido(tools, fonte, tmp_path):
    rms = lambda a: math.sqrt(sum(v * v for v in a) / len(a))
    base = _amostras(tools, _exporta(tools, _projeto(Clip(fonte, 0.0, 2.0, in_point=1.0, reversed=True)),
                                     tmp_path / "a.wav", container="wav", audio_only=True, audio_codec="wav"))
    baixo = _amostras(tools, _exporta(tools, _projeto(Clip(fonte, 0.0, 2.0, in_point=1.0, reversed=True, gain_db=-6.0)),
                                      tmp_path / "b.wav", container="wav", audio_only=True, audio_codec="wav"))
    assert rms(baixo) / rms(base) == pytest.approx(10 ** (-6 / 20), rel=0.02)


def test_dividir_o_invertido_nao_muda_a_exportacao(tools, fonte, tmp_path):
    """Dividir o invertido e exportar tem de dar o mesmo arquivo que não dividir."""
    inteiro = _projeto(Clip(fonte, 0.0, 4.0, reversed=True))
    dividido = inteiro.split(inteiro.clips[0].clip_id, 1.5)
    a = _brilhos(tools, _exporta(tools, inteiro, tmp_path / "a.mp4"))
    b = _brilhos(tools, _exporta(tools, dividido, tmp_path / "b.mp4"))
    assert len(a) == len(b)
    assert max(abs(x - y) for x, y in zip(a, b)) < 0.5


def test_aparar_o_comeco_do_invertido_e_recortar_o_invertido_inteiro(tools, fonte, tmp_path):
    inteiro = _projeto(Clip(fonte, 0.0, 4.0, reversed=True))
    aparado = inteiro.resized(inteiro.clips[0].clip_id, "inicio", 1.0)
    a = _brilhos(tools, _exporta(tools, inteiro, tmp_path / "a.mp4"))
    b = _brilhos(tools, _exporta(tools, aparado, tmp_path / "b.mp4"))
    assert len(a) == len(b)
    assert max(b[:30]) < 1  # o primeiro segundo ficou vazio
    assert max(abs(x - y) for x, y in zip(a[30:], b[30:])) < 0.5


def test_quadros_chave_correm_no_relogio_da_edicao(tools, tmp_path):
    """Numa fonte de brilho constante a inversão não muda o quadro: o fade é o mesmo."""
    cinza = tmp_path / "cinza.mp4"
    _run(tools, "-f", "lavfi", "-i", "color=c=gray:s=64x64:r=30:d=3", "-c:v", "libx264", "-crf", "0",
         "-pix_fmt", "yuv420p", str(cinza))
    midia = media_ref(probe_file(cinza, tools))
    fade = (Keyframe(0.0, opacity=0.0), Keyframe(2.0, opacity=1.0))
    normal = _brilhos(tools, _exporta(tools, _projeto(Clip(midia, 0.0, 2.0, keyframes=fade)), tmp_path / "n.mp4"))
    invertido = _brilhos(tools, _exporta(tools, _projeto(Clip(midia, 0.0, 2.0, keyframes=fade, reversed=True)),
                                         tmp_path / "i.mp4"))
    assert len(normal) == len(invertido)
    assert normal[-1] - normal[0] > 40  # o fade existe
    assert max(abs(x - y) for x, y in zip(normal, invertido)) < 1.0


# ---------------------------------------------------------------------------
# Prévia
# ---------------------------------------------------------------------------


def test_quadro_parado_e_o_quadro_que_a_exportacao_mostra(tools, fonte, tmp_path):
    projeto = _projeto(Clip(fonte, 0.0, 4.0, reversed=True))
    exportado = _brilhos(tools, _exporta(tools, projeto, tmp_path / "e.mp4"))
    for instante in (0.0, 0.01, 0.5, 1.234, 2.0, 3.9, 3.9667, 3.99):
        dados = subprocess.run(composer.frame_command(projeto, instante, SIZE, tools), check=True,
                               timeout=60, **subprocess_kwargs()).stdout
        parado = sum(0.299 * dados[i] + 0.587 * dados[i + 1] + 0.114 * dados[i + 2]
                     for i in range(0, len(dados), 3)) / (len(dados) / 3)
        esperado = exportado[min(len(exportado) - 1, int(instante * FPS + 1e-6))]
        assert parado == pytest.approx(esperado, abs=2.5), f"em {instante} s"


def test_quadro_parado_de_um_trecho_do_arquivo(tools, fonte, tmp_path):
    projeto = _projeto(Clip(fonte, 0.0, 2.0, in_point=1.0, reversed=True))
    exportado = _brilhos(tools, _exporta(tools, projeto, tmp_path / "e.mp4"))
    for instante in (0.0, 0.7, 1.3, 1.95):
        dados = subprocess.run(composer.frame_command(projeto, instante, SIZE, tools), check=True,
                               timeout=60, **subprocess_kwargs()).stdout
        parado = sum(0.299 * dados[i] + 0.587 * dados[i + 1] + 0.114 * dados[i + 2]
                     for i in range(0, len(dados), 3)) / (len(dados) / 3)
        assert parado == pytest.approx(exportado[int(instante * FPS + 1e-6)], abs=2.5), f"em {instante} s"


@pytest.mark.parametrize("instante", [0.0, 1.3, 2.51, 3.2])
def test_reproducao_a_partir_do_meio_acompanha_a_exportacao(tools, fonte, tmp_path, instante):
    projeto = _projeto(Clip(fonte, 0.0, 4.0, reversed=True))
    exportado = _brilhos(tools, _exporta(tools, projeto, tmp_path / "e.mp4"))
    quadros = _quadros_da_reproducao(tools, projeto, instante)
    esperado = exportado[round(instante * FPS):]
    assert len(quadros) == len(esperado)
    assert max(abs(a - b) for a, b in zip(quadros, esperado)) < 2.5


def test_reproducao_de_bloco_que_comeca_depois_do_zero(tools, fonte, tmp_path):
    projeto = _projeto(Clip(fonte, 1.0, 2.0, in_point=1.0, reversed=True))
    exportado = _brilhos(tools, _exporta(tools, projeto, tmp_path / "e.mp4"))
    quadros = _quadros_da_reproducao(tools, projeto, 1.5)
    esperado = exportado[45:]
    assert len(quadros) == len(esperado)
    assert max(abs(a - b) for a, b in zip(quadros, esperado)) < 2.5


# ---------------------------------------------------------------------------
# Transições: o mesmo projeto montado com um arquivo invertido de verdade
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fonte_invertida(tools, fonte, tmp_path_factory):
    """A mesma fonte invertida pelo ffmpeg, em MOV com PCM: busca exata no som."""
    path = tmp_path_factory.mktemp("inversao_fisica") / "contador_invertido.mov"
    _run(tools, "-i", str(fonte.path), "-vf", "reverse", "-af", f"atrim=0:{SECONDS},areverse", "-c:v", "libx264",
         "-crf", "0", "-g", "1", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-t", str(SECONDS), str(path))
    return media_ref(probe_file(path, tools))


@pytest.mark.parametrize(("nome", "esquerda_invertida", "direita_invertida"),
                         [("ambos", True, True), ("so_esquerda", True, False), ("so_direita", False, True)])
def test_transicao_com_bloco_invertido_igual_ao_arquivo_invertido(tools, fonte, fonte_invertida, tmp_path, nome,
                                                                  esquerda_invertida, direita_invertida):
    # Trechos: esquerda [0,5; 2,0) e direita [2,0; 3,5). No arquivo invertido o
    # instante t da origem é D − t, então cada trecho vira [D − fim; D − início).
    a = Clip(fonte, 0.0, 1.5, in_point=0.5, reversed=esquerda_invertida)
    b = Clip(fonte, 1.5, 1.5, in_point=2.0, reversed=direita_invertida)
    a_fisico = (Clip(fonte_invertida, 0.0, 1.5, in_point=2.0) if esquerda_invertida
                else Clip(fonte, 0.0, 1.5, in_point=0.5))
    b_fisico = (Clip(fonte_invertida, 1.5, 1.5, in_point=0.5) if direita_invertida
                else Clip(fonte, 1.5, 1.5, in_point=2.0))

    def com_transicao(esq, dir_):
        projeto, _ = _projeto(esq, dir_).with_transition(0, esq, dir_, "fade", "Transição_fade", 0.5, False)
        return projeto

    obtido = _brilhos(tools, _exporta(tools, com_transicao(a, b), tmp_path / "a.mp4"))
    oraculo = _brilhos(tools, _exporta(tools, com_transicao(a_fisico, b_fisico), tmp_path / "b.mp4"))
    assert len(obtido) == len(oraculo) == 90
    assert max(abs(x - y) for x, y in zip(obtido, oraculo)) < 0.5


def test_dois_blocos_invertidos_em_sequencia_igual_ao_arquivo_invertido(tools, fonte, fonte_invertida, tmp_path):
    obtido = _projeto(Clip(fonte, 0.0, 1.5, in_point=0.5, reversed=True), Clip(fonte, 1.5, 1.5, in_point=2.0, reversed=True))
    oraculo = _projeto(Clip(fonte_invertida, 0.0, 1.5, in_point=2.0), Clip(fonte_invertida, 1.5, 1.5, in_point=0.5))
    a = _brilhos(tools, _exporta(tools, obtido, tmp_path / "a.mp4"))
    b = _brilhos(tools, _exporta(tools, oraculo, tmp_path / "b.mp4"))
    assert len(a) == len(b) == 90
    assert max(abs(x - y) for x, y in zip(a, b)) < 0.5


def test_trechos_paralelos_da_interpolacao_emendam_o_invertido_igual_ao_serial(tools, tmp_path):
    """Cada trecho lê só a janela dele do bloco invertido; na emenda não pode sobrar nem faltar quadro."""
    fonte = tmp_path / "contador24.mp4"
    _run(tools, "-f", "lavfi", "-i", "color=c=black:s=64x64:r=24:d=4,format=yuv420p,"
                                     "geq=lum='16+mod(N*2,219)':cb=128:cr=128",
         "-c:v", "libx264", "-crf", "0", "-g", "12", "-pix_fmt", "yuv420p", str(fonte))
    projeto = _projeto(Clip(media_ref(probe_file(fonte, tools)), 0.0, 4.0, reversed=True), fps=60.0)
    serial = _brilhos(tools, _exporta(tools, projeto, tmp_path / "serial.mp4", interpolate=True))

    partes = []
    for i, (inicio, duracao) in enumerate(composer.segment_bounds(4.0, 2)):
        parte = tmp_path / f"parte{i}.mp4"
        subprocess.run(composer.segment_video_args(projeto, inicio, duracao, parte, tools), check=True,
                       timeout=180, **subprocess_kwargs())
        partes.append(parte)
    lista = tmp_path / "partes.txt"
    lista.write_text("".join(f"file '{parte.as_posix()}'\n" for parte in partes), encoding="utf-8")
    emendado = tmp_path / "emendado.mp4"
    subprocess.run(composer.concat_args(lista, emendado, tools), check=True, timeout=180, **subprocess_kwargs())

    juntos = _brilhos(tools, emendado)
    assert len(juntos) == len(serial) == 240
    assert max(abs(a - b) for a, b in zip(juntos, serial)) < 1.0


# ---------------------------------------------------------------------------
# Janelas: o que limita a memória do bloco invertido
# ---------------------------------------------------------------------------

# Orçamento que o quadro de 64×64 não alcançaria sozinho: com ele a fonte de
# 4 s é lida em janelas de 1,6 s, e é o caminho das janelas que se exercita.
_ORCAMENTO_PEQUENO = 600_000


@pytest.fixture
def previa_em_janelas(monkeypatch):
    """A prévia lê em janelas de 1 s; a exportação de referência segue num processo só."""
    monkeypatch.setattr(composer, "PREVIEW_WINDOW_SECONDS", 1.0)


@pytest.fixture
def agulha_em_janelas(monkeypatch):
    monkeypatch.setattr(composer, "MAX_REVERSE_BYTES", _ORCAMENTO_PEQUENO)


def _grande(fonte):
    """Um bloco de 4K invertido de dois minutos: muito além do que um processo aguenta."""
    return replace(fonte, width=3840, height=2160, fps=30.0, duration=600.0)


def test_bloco_grande_e_dividido_em_janelas_e_nao_recusado(tools, fonte):
    """Era o defeito: um vídeo de 1080p com mais de ~11 s ficava sem poder ser invertido."""
    composicao = Composition(_projeto(Clip(_grande(fonte), 0.0, 120.0, reversed=True)), "mp4")
    janelas = reversal_bounds(composicao)
    assert len(janelas) > 40
    assert sum(duracao for _, duracao in janelas) == pytest.approx(120.0)
    assert all(abs(a - b[0] - b[1]) < 1e-6 for (_, _), a, b in zip(janelas, [j[0] for j in janelas[1:]], janelas))


def test_um_processo_so_recusa_o_que_precisaria_de_janelas(tools, fonte, tmp_path):
    projeto = _projeto(Clip(_grande(fonte), 0.0, 120.0, reversed=True))
    with pytest.raises(ConversionError):
        composer.export_args(projeto, tmp_path / "x.gif", tools, container="gif")
    with pytest.raises(ConversionError):
        composer.export_args(projeto, tmp_path / "x.mp4", tools)


def test_exportacao_so_de_som_nao_se_divide(tools, fonte, tmp_path):
    projeto = _projeto(Clip(_grande(fonte), 0.0, 120.0, reversed=True))
    composicao = Composition(projeto, "wav", audio_only=True, audio_codec="wav")
    assert reversal_bounds(composicao) == ()
    assert composer.export_args(projeto, tmp_path / "x.wav", tools, container="wav", audio_only=True,
                                audio_codec="wav")


def test_edicao_sem_bloco_invertido_nao_se_divide(tools, fonte):
    assert reversal_bounds(Composition(_projeto(Clip(fonte, 0.0, 4.0)), "mp4")) == ()


def _exporta_em_janelas(tools, projeto, destino):
    composicao = Composition(projeto, "mp4")
    janelas = reversal_bounds(composicao)
    assert len(janelas) > 1
    ParallelExport(composicao, destino, tools, len(janelas), bounds=janelas, workers=1).run()
    return destino, len(janelas)


@pytest.mark.parametrize("campos", [dict(duration=4.0), dict(duration=2.5, in_point=0.7)],
                         ids=["inteiro", "trecho"])
def test_exportacao_em_janelas_igual_a_de_um_processo_so(tools, fonte, tmp_path, monkeypatch, campos):
    projeto = _projeto(Clip(fonte, 0.0, reversed=True, **campos))
    um_so = _brilhos(tools, _exporta(tools, projeto, tmp_path / "um.mp4"))
    som_um_so = _amostras(tools, _exporta(tools, projeto, tmp_path / "um.wav", container="wav", audio_only=True,
                                          audio_codec="wav"))
    monkeypatch.setattr(composer, "MAX_REVERSE_BYTES", _ORCAMENTO_PEQUENO)
    janelas, quantas = _exporta_em_janelas(tools, projeto, tmp_path / "janelas.mp4")
    assert quantas >= 2
    em_janelas = _brilhos(tools, janelas)
    assert len(em_janelas) == len(um_so)
    assert max(abs(a - b) for a, b in zip(em_janelas, um_so)) < 2.0
    # O som sai num passe só: a duração e o conteúdo são os do caminho serial.
    assert abs(len(_amostras(tools, janelas)) - len(som_um_so)) < 2_500


def test_exportacao_em_janelas_com_bloco_normal_antes_e_invertido_por_cima(tools, fonte, tmp_path, monkeypatch):
    base = Clip(fonte, 0.0, 4.0)
    por_cima = Clip(fonte, 1.0, 2.5, in_point=0.5, reversed=True, opacity=0.6)
    projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(por_cima,)), Track(TrackKind.VIDEO, clips=(base,))),
                      width=SIZE[0], height=SIZE[1], fps=FPS)
    um_so = _brilhos(tools, _exporta(tools, projeto, tmp_path / "um.mp4"))
    monkeypatch.setattr(composer, "MAX_REVERSE_BYTES", _ORCAMENTO_PEQUENO)
    janelas, quantas = _exporta_em_janelas(tools, projeto, tmp_path / "janelas.mp4")
    em_janelas = _brilhos(tools, janelas)
    assert quantas >= 2 and len(em_janelas) == len(um_so)
    assert max(abs(a - b) for a, b in zip(em_janelas, um_so)) < 3.0


@pytest.mark.parametrize("instante", [0.0, 1.3, 2.51])
def test_reproducao_em_janelas_acompanha_a_exportacao(tools, fonte, tmp_path, previa_em_janelas, instante):
    projeto = _projeto(Clip(fonte, 0.0, 4.0, reversed=True))
    comando = composer.playback_command(projeto, instante, SIZE, tools, fps=FPS)
    assert hasattr(comando, "commands") and len(comando.commands) >= 2  # é uma sequência de janelas
    quadros = _quadros_da_reproducao(tools, projeto, instante)
    exportado = _brilhos(tools, _exporta(tools, projeto, tmp_path / "e.mp4"))
    esperado = exportado[round(instante * FPS):]
    assert abs(len(quadros) - len(esperado)) <= 1
    assert max(abs(a - b) for a, b in zip(quadros, esperado)) < 2.5


def test_reproducao_em_janelas_chega_ao_fim_no_ritmo_e_sem_pausa_nas_emendas(tools, fonte, previa_em_janelas):
    """A janela seguinte abre antes de a atual acabar: a reprodução não percebe a emenda."""
    projeto = _projeto(Clip(fonte, 0.0, 3.0, reversed=True))
    comando = composer.playback_command(projeto, 0.0, SIZE, tools, fps=FPS)
    assert len(comando.commands) == 3
    instantes, quadros = [], []
    inicio = time.perf_counter()
    for quadro in FramePump(comando, 0.0, SIZE, fps=FPS).frames():
        instantes.append(time.perf_counter())
        quadros.append(quadro)
    assert len(quadros) == 90
    assert max(b - a for a, b in zip(instantes, instantes[1:])) < 0.35
    assert instantes[-1] - inicio == pytest.approx(3.0, abs=0.7)
    assert [round(q.seconds * FPS) for q in quadros] == list(range(90))


def test_som_da_previa_em_janelas_e_o_do_passe_unico_sem_estalo_nas_emendas(tools, fonte, tmp_path, previa_em_janelas):
    projeto = _projeto(Clip(fonte, 0.0, 4.0, reversed=True))
    comando = composer.audio_command(projeto, 0.0, tools)
    assert hasattr(comando, "commands") and len(comando.commands) >= 3
    pcm = array.array("h")
    pcm.frombytes(_lidos(tools, comando, None))
    esquerdo = pcm[0::2]
    referencia = _canal_esquerdo(tools, _exporta(tools, projeto, tmp_path / "r.wav", container="wav",
                                                 audio_only=True, audio_codec="wav"))
    assert len(esquerdo) == len(referencia) == 4 * 48_000
    assert _erro_relativo(esquerdo, referencia) < 1e-4


def test_som_da_previa_ate_um_instante_tem_a_duracao_pedida(tools, fonte, previa_em_janelas):
    projeto = _projeto(Clip(fonte, 0.0, 4.0, reversed=True))
    comando = composer.audio_command(projeto, 0.5, tools, until=3.5)
    assert len(_lidos(tools, comando, None)) == round(3.0 * 48_000) * 2 * 2


def test_cache_da_agulha_pede_so_a_primeira_janela(tools, fonte, agulha_em_janelas):
    """O que sobra continua sem quadro, e o painel volta a pedir."""
    projeto = _projeto(Clip(fonte, 0.0, 4.0, reversed=True))
    comando = composer.scrub_command(projeto, 0.0, 4.0, SIZE, tools, fps=FPS)
    quadros = comando[comando.index("-frames:v") + 1]
    assert int(quadros) == 48  # 1,6 s a 30 q/s, e não os 120 pedidos


def test_cache_da_agulha_sem_bloco_invertido_pede_o_trecho_todo(tools, fonte, agulha_em_janelas):
    projeto = _projeto(Clip(fonte, 0.0, 4.0))
    comando = composer.scrub_command(projeto, 0.0, 4.0, SIZE, tools, fps=FPS)
    assert int(comando[comando.index("-frames:v") + 1]) == 120


def test_quadro_parado_nao_depende_do_tamanho_do_bloco(tools, fonte):
    """O quadro parado lê um quadro de frente, sem ``reverse``: bloco de qualquer tamanho."""
    projeto = _projeto(Clip(_grande(fonte), 0.0, 120.0, reversed=True))
    comando = composer.frame_command(projeto, 1.0, SIZE, tools)
    assert "reverse" not in " ".join(comando)


# ---------------------------------------------------------------------------
# Bordas: sem sobra de mídia na emenda, e animação nas janelas
# ---------------------------------------------------------------------------


def _arranjos_sem_sobra(fonte, invertida):
    """Para cada arranjo, os blocos do app e os do oráculo (onde a mídia já vem invertida de verdade)."""
    normal = Clip(fonte, 0.0, 1.5, in_point=0.5)
    direita = Clip(fonte, 1.5, 1.5, in_point=2.0)
    return {
        # A direita invertida começa no FIM da mídia (out_point = duração): não há mídia antes da ponta dela.
        "direita_sem_sobra": ((normal, Clip(fonte, 1.5, 1.5, in_point=SECONDS - 1.5, reversed=True)),
                              (normal, Clip(invertida, 1.5, 1.5, in_point=0.0))),
        # A esquerda invertida termina no COMEÇO da mídia (in_point = 0): não há mídia depois da ponta dela.
        # É o caso de inverter o arquivo inteiro e pôr uma transição depois.
        "esquerda_sem_sobra": ((Clip(fonte, 0.0, 1.5, in_point=0.0, reversed=True), direita),
                               (Clip(invertida, 0.0, 1.5, in_point=SECONDS - 1.5), direita)),
        # Sobra meio quadro antes de a mídia acabar (os pontos precisam estar na grade de 30 q/s, ou o
        # oráculo espelhado cai em quadros diferentes já fora da transição): o recuo da leitura é cortado
        # só em parte, e este caso já saía certo — fica como guarda do meio-termo.
        "esquerda_quase_sem_sobra": ((Clip(fonte, 0.0, 1.5, in_point=8 / 30, reversed=True), direita),
                                     (Clip(invertida, 0.0, 1.5, in_point=SECONDS - 1.5 - 8 / 30), direita)),
        # Falta um quadro inteiro: a janela é cortada em zero e o recuo some.
        "esquerda_sem_um_quadro": ((Clip(fonte, 0.0, 1.5, in_point=7 / 30, reversed=True), direita),
                                   (Clip(invertida, 0.0, 1.5, in_point=SECONDS - 1.5 - 7 / 30), direita)),
        "ambos_sem_sobra": ((Clip(fonte, 0.0, 1.5, in_point=0.0, reversed=True),
                             Clip(fonte, 1.5, 1.5, in_point=SECONDS - 1.5, reversed=True)),
                            (Clip(invertida, 0.0, 1.5, in_point=SECONDS - 1.5),
                             Clip(invertida, 1.5, 1.5, in_point=0.0))),
    }


@pytest.mark.parametrize("nome", ["direita_sem_sobra", "esquerda_sem_sobra", "esquerda_quase_sem_sobra",
                                  "esquerda_sem_um_quadro", "ambos_sem_sobra"])
def test_transicao_com_invertido_sem_sobra_de_midia_igual_ao_arquivo_invertido(tools, fonte, fonte_invertida, tmp_path,
                                                                              nome):
    """Falta mídia na ponta do bloco invertido: o lado dele segura o quadro do fim, e não o do começo."""
    (esquerda, direita), (esquerda_fisica, direita_fisica) = _arranjos_sem_sobra(fonte, fonte_invertida)[nome]

    def com_transicao(a, b):
        projeto, _ = _projeto(a, b).with_transition(0, a, b, "fade", "Transição_fade", 0.5, False)
        return projeto

    obtido = _brilhos(tools, _exporta(tools, com_transicao(esquerda, direita), tmp_path / "a.mp4"))
    oraculo = _brilhos(tools, _exporta(tools, com_transicao(esquerda_fisica, direita_fisica), tmp_path / "b.mp4"))
    assert len(obtido) == len(oraculo) == 90
    assert max(abs(x - y) for x, y in zip(obtido, oraculo)) < 0.5


@pytest.mark.parametrize("campos", [dict(duration=4.0), dict(duration=2.5, in_point=0.7)],
                         ids=["inteiro", "trecho"])
def test_quadros_chave_do_invertido_em_janelas_igual_a_um_processo_so(tools, fonte, tmp_path, monkeypatch, campos):
    """A janela que começa no meio do bloco tem de achar o ponto da animação onde o bloco está.

    O relógio da animação é o da edição desde o começo do bloco; só a primeira janela começa lá. As outras
    sabem quanto do bloco já passou por ``_Piece.elapsed`` — e sem ele o trecho inteiro, de um processo só,
    continuava certo.
    """
    animacao = (Keyframe(0.0, opacity=1.0), Keyframe(campos["duration"], opacity=0.3))
    projeto = _projeto(Clip(fonte, 0.0, reversed=True, keyframes=animacao, **campos))
    um_so = _brilhos(tools, _exporta(tools, projeto, tmp_path / "um.mp4"))
    sem_animacao = _brilhos(tools, _exporta(tools, _projeto(Clip(fonte, 0.0, reversed=True, **campos)),
                                            tmp_path / "sem.mp4"))
    # A opacidade cai de 1 a 0,3 sobre o preto: em média ~0,65 do brilho. Sem isto a igualdade abaixo não provaria nada.
    assert 0.55 < sum(um_so) / sum(sem_animacao) < 0.8
    monkeypatch.setattr(composer, "MAX_REVERSE_BYTES", _ORCAMENTO_PEQUENO)
    janelas, quantas = _exporta_em_janelas(tools, projeto, tmp_path / "janelas.mp4")
    em_janelas = _brilhos(tools, janelas)
    assert quantas >= 2 and len(em_janelas) == len(um_so)
    assert max(abs(a - b) for a, b in zip(em_janelas, um_so)) < 2.0
