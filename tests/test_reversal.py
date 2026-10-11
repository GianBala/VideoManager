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
from dataclasses import replace

import pytest

from videomanager.application.errors import ConversionError
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import Clip, Project, Track, TrackKind, media_ref
from videomanager.infrastructure.ffmpeg import composer
from videomanager.infrastructure.ffmpeg.converter import probe_file
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


def _erro_relativo(a, b):
    n = min(len(a), len(b))
    diferenca = math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(n)) / n)
    return diferenca / (math.sqrt(sum(v * v for v in b[:n]) / n) or 1.0)


def _quadros_da_reproducao(tools, projeto, instante):
    comando = composer.playback_command(projeto, instante, SIZE, tools, fps=FPS)
    dados = subprocess.run(comando, check=True, timeout=180, **subprocess_kwargs()).stdout
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
    normal = _amostras(tools, _exporta(tools, _projeto(Clip(fonte, 0.0, **campos)), tmp_path / "n.wav",
                                       container="wav", audio_only=True, audio_codec="wav"))
    invertido = _amostras(tools, _exporta(tools, _projeto(Clip(fonte, 0.0, reversed=True, **campos)),
                                          tmp_path / "i.wav", container="wav", audio_only=True, audio_codec="wav"))
    assert len(invertido) == len(normal) > 40_000
    assert _erro_relativo(invertido, normal[::-1]) < 1e-4
    assert _erro_relativo(invertido, normal) > 0.5  # e não é o som normal


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
# Teto de memória
# ---------------------------------------------------------------------------


def _grande(fonte):
    """Um bloco de 4K invertido de dois minutos: muito além do teto."""
    return replace(fonte, width=3840, height=2160, fps=30.0, duration=600.0)


def test_exportacao_recusa_bloco_invertido_acima_do_teto(tools, fonte, tmp_path):
    projeto = _projeto(Clip(_grande(fonte), 0.0, 120.0, reversed=True))
    with pytest.raises(ConversionError) as erro:
        composer.export_args(projeto, tmp_path / "x.mp4", tools)
    assert "invert" in str(erro.value).lower() or "reverse" in str(erro.value).lower()


def test_recusa_vale_tambem_para_o_gif_e_para_os_trechos_paralelos(tools, fonte, tmp_path):
    projeto = _projeto(Clip(_grande(fonte), 0.0, 120.0, reversed=True))
    with pytest.raises(ConversionError):
        composer.export_args(projeto, tmp_path / "x.gif", tools, container="gif")
    with pytest.raises(ConversionError):
        composer.segment_video_args(projeto, 0.0, 10.0, tmp_path / "t.mp4", tools)


def test_previa_nao_levanta_para_o_mesmo_projeto(tools, fonte):
    """A prévia monta o comando na thread da interface, onde uma exceção não tem quem a mostre."""
    projeto = _projeto(Clip(_grande(fonte), 0.0, 120.0, reversed=True))
    composer.frame_command(projeto, 1.0, SIZE, tools)
    composer.playback_command(projeto, 1.0, SIZE, tools, fps=FPS)


def test_exportacao_so_de_som_nao_tem_teto(tools, fonte, tmp_path):
    projeto = _projeto(Clip(_grande(fonte), 0.0, 120.0, reversed=True))
    assert composer.export_args(projeto, tmp_path / "x.wav", tools, container="wav", audio_only=True,
                                audio_codec="wav")
