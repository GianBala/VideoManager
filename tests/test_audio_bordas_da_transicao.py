"""As bordas de uma transição de som, medidas na saída: sem estouro, sem buraco e com o de-click que se pede.

O mudo das peças durante o crossfade e as rampas de de-click eram ``volume`` com ``enable``/``eval=frame``, que o ffmpeg
avalia **por quadro de áudio** — e o quadro é o da fonte. Chegar ao fim sem erro não diz nada aqui: o arquivo sai com a
duração certa e o corte errado. Medido, com um seno de 440 Hz em fase nos dois lados (o envelope de cada bloco de
poucos milissegundos sai da projeção no próprio seno), numa fonte PCM em MOV (quadros de ~21 ms):

- com alças, o lado que devia calar seguia soando no começo da janela (envelope **2,0, +6 dB, por ~25 ms**) e o que devia
  voltar só voltava um quadro depois do fim dela (um buraco de ~3 ms);
- sem alças, o de-click de 12 ms não existia: o som cortava seco e a peça seguinte vinha **~20 ms de silêncio** depois.

Numa fonte FLAC de 16384 amostras (quadros de ~340 ms) os buracos passam de dezenas de milissegundos.
"""

import array
import math
import subprocess
from pathlib import Path

import pytest

from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, media_ref
from videomanager.infrastructure.ffmpeg import composer
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs

TAXA = 48_000
SEGUNDOS = 8
ffmpeg = pytest.mark.ffmpeg

FONTES = {
    "pcm em mov": ("seno.mov", ["-c:a", "pcm_s16le"]),
    "flac de 16384 em mkv": ("seno.mkv", ["-c:a", "flac", "-frame_size", "16384"]),
}


@pytest.fixture(scope="module")
def tools():
    found = find_tools()
    if found is None:
        pytest.skip("FFmpeg não disponível")
    return found


def _run(tools, *args) -> bytes:
    done = subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", *args], timeout=180, **subprocess_kwargs())
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-800:]
    return done.stdout


@pytest.fixture(scope="module", params=list(FONTES))
def fonte(request, tools, tmp_path_factory) -> MediaRef:
    """Seno de 440 Hz: em segundos inteiros da mídia a fase é a mesma, então os dois lados soam em fase."""
    nome, codec = FONTES[request.param]
    path = tmp_path_factory.mktemp("bordas") / nome
    _run(tools,
         "-f", "lavfi", "-i", f"color=c=black:s=64x64:r=30:d={SEGUNDOS},format=yuv420p",
         "-f", "lavfi", "-i", f"sine=f=440:r={TAXA}:d={SEGUNDOS}",
         "-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p", *codec, "-ac", "2", str(path))
    return media_ref(probe_file(path, tools))


def _exporta(tools, esquerda: Clip, direita: Clip, duracao: float, destino: Path):
    projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(esquerda, direita)),), width=64, height=64, fps=30.0)
    projeto, _ = projeto.with_transition(0, esquerda, direita, "fade", "Transição_fade", duracao, False)
    subprocess.run(composer.export_args(projeto, destino, tools, container="wav", audio_only=True, audio_codec="wav"),
                   check=True, timeout=180, **subprocess_kwargs())
    dados = _run(tools, "-i", str(destino), "-vn", "-ac", "2", "-ar", str(TAXA), "-f", "s16le", "-")
    saida = array.array("h")
    saida.frombytes(dados[: len(dados) // 4 * 4])
    return saida[0::2]


def _seno(i: int) -> float:
    return math.sin(2 * math.pi * 440 * i / TAXA)


def _envelope(amostras, instante: float, bloco: float) -> float:
    """Amplitude do seno de referência no bloco de ``bloco`` s em torno de ``instante`` (projeção por mínimos quadrados)."""
    n = round(bloco * TAXA)
    a = round(instante * TAXA) - n // 2
    return sum(amostras[i] * _seno(i) for i in range(a, a + n)) / sum(_seno(i) ** 2 for i in range(a, a + n))


def _maior_desvio(amostras, referencia: float, ideal, de: float, ate: float, bloco: float) -> tuple[float, float]:
    """O maior desvio do envelope medido contra o ideal, em blocos de ``bloco`` s entre ``de`` e ``ate``."""
    pior, onde = 0.0, de
    instante = de
    while instante <= ate:
        desvio = abs(_envelope(amostras, instante, bloco) / referencia - ideal(instante))
        if desvio > pior:
            pior, onde = desvio, instante
        instante += bloco
    return pior, onde


def test_as_duas_pontas_do_acrossfade_chegam_em_quadros_pequenos():
    """O ``acrossfade`` com os quadros da fonte nas duas entradas às vezes não entrega nada (FLAC de 16384 amostras:
    ~1 de cada 4 exportações saía com a janela inteira muda). É não determinístico, então a medida abaixo pode passar por
    sorte; o que se fixa aqui é o que a evita: as duas pontas passam pelo limite de 480 amostras antes do cruzamento."""
    media = MediaRef(Path("v.mp4"), MediaKind.VIDEO, duration=12.0, width=64, height=64, fps=30.0, has_audio=True, channels=2)
    esquerda, direita = Clip(media, 0.0, 4.0, in_point=2.0), Clip(media, 4.0, 4.0, in_point=7.0)
    projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(esquerda, direita)),), width=64, height=64, fps=30.0)
    projeto, _ = projeto.with_transition(0, esquerda, direita, "fade", "Transição_fade", 1.0, False)
    filtros = composer.build_graph(projeto, want_video=False).filters
    pontas = [f for f in filtros if f.endswith(("[tra0a]", "[tra0b]"))]
    assert len(pontas) == 2 and all(",asetnsamples=n=480:p=0[tra0" in f for f in pontas), pontas


def test_peca_com_ponta_chega_ao_amix_em_quadros_pequenos():
    """No ffmpeg 6.1 (o do Ubuntu 24.04) o ``amix`` perde o fim da peça cujo último quadro é grande quando a outra
    entrada vem atrasada: numa fonte FLAC de 16384 amostras o lado que sai ficava mudo nos últimos quadros antes do
    corte, com ou sem rampa. A medida acima só falha lá; o que se fixa aqui é o que a evita."""
    media = MediaRef(Path("v.mp4"), MediaKind.VIDEO, duration=4.0, width=64, height=64, fps=30.0, has_audio=True, channels=2)
    esquerda, direita = Clip(media, 0.0, 4.0), Clip(media, 4.0, 4.0)       # sem alças: de-click nas duas pontas
    projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(esquerda, direita)),), width=64, height=64, fps=30.0)
    projeto, _ = projeto.with_transition(0, esquerda, direita, "fade", "Transição_fade", 1.0, False)
    pecas = [f for f in composer.build_graph(projeto, want_video=False).filters if f.endswith(("[a0]", "[a1]"))]
    assert len(pecas) == 2
    for peca in pecas:
        assert peca.index(",asetnsamples=n=480:p=0,afade=") > 0, peca


@ffmpeg
def test_crossfade_com_alcas_sem_estouro_no_comeco_nem_buraco_no_fim(tools, fonte, tmp_path):
    """Janela [1,25 s; 1,75 s] entre dois blocos com sobra de mídia: o envelope é o do crossfade de potência constante
    (``qsin``), em fase: cos(πu/2) + sin(πu/2), de 1,0 a 1,41 e de volta — e 1,0 fora dela."""
    esquerda, direita = Clip(fonte, 0.0, 1.5, in_point=0.5), Clip(fonte, 1.5, 1.5, in_point=2.5)
    som = _exporta(tools, esquerda, direita, 0.5, tmp_path / "crossfade.wav")
    referencia = max(abs(v) for v in som[int(0.6 * TAXA): int(1.1 * TAXA)])

    def ideal(t: float) -> float:
        u = (t - 1.25) / 0.5
        return 1.0 if not 0.0 <= u <= 1.0 else math.cos(u * math.pi / 2) + math.sin(u * math.pi / 2)

    # De 10 ms antes da janela a 25 ms depois dela, em blocos de 2,5 ms: é onde o mudo por quadro errava.
    pior, onde = _maior_desvio(som, referencia, ideal, 1.24, 1.775, 0.0025)
    assert pior < 0.06, f"envelope {pior:.2f} longe do ideal em {onde:.4f} s"
    pior, onde = _maior_desvio(som, referencia, ideal, 1.74, 1.775, 0.0025)
    assert pior < 0.06, f"buraco no fim da janela: desvio {pior:.2f} em {onde:.4f} s"


@ffmpeg
def test_sem_alcas_o_declick_de_12_ms_existe_e_nao_deixa_silencio_depois_do_corte(tools, fonte, tmp_path):
    """Sem sobra de mídia (o primeiro bloco termina no fim do arquivo e o segundo começa no início) não há crossfade de
    som: só uma rampa de 12 ms em cada lado do corte, cos antes e sin depois. Por quadro, o som cortava seco e o outro
    lado voltava um quadro depois."""
    esquerda, direita = Clip(fonte, 0.0, 1.5, in_point=6.5), Clip(fonte, 1.5, 1.5, in_point=0.0)
    som = _exporta(tools, esquerda, direita, 0.5, tmp_path / "declick.wav")
    referencia = max(abs(v) for v in som[int(0.3 * TAXA): int(1.0 * TAXA)])

    def ideal(t: float) -> float:
        if 1.488 <= t < 1.5:
            return math.cos((t - 1.488) / 0.012 * math.pi / 2)
        if 1.5 <= t < 1.512:
            return math.sin((t - 1.5) / 0.012 * math.pi / 2)
        return 1.0

    pior, onde = _maior_desvio(som, referencia, ideal, 1.470, 1.540, 0.001)
    assert pior < 0.12, f"de-click fora do ideal: desvio {pior:.2f} em {onde:.4f} s"
