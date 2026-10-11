"""A curva de volume dos quadros-chave, medida no som que o compositor produz.

Chegar ao fim sem erro não diz nada aqui: um ``volume`` com o relógio errado exporta um arquivo com a
duração certa e o fade no lugar errado. O que se confere é o **nível** (RMS em janelas de 20 ms)
contra o mesmo trecho sem curva, no instante em que a curva diz quanto ele deve valer.
"""

import array
import math
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, media_ref
from videomanager.infrastructure.ffmpeg import composer
from videomanager.infrastructure.ffmpeg.composer import build_graph, frame_command, playback_command
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs

SIZE = (64, 64)
FPS = 30.0
SEGUNDOS = 6
TAXA = 48_000


def _projeto(*clips, fps=FPS):
    return Project(tracks=(Track(TrackKind.VIDEO, clips=tuple(clips)),), width=SIZE[0], height=SIZE[1], fps=fps)


def _midia_falsa() -> MediaRef:
    return MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=30.0, width=640, height=360, fps=FPS,
                    has_audio=True, channels=2)


def _rampa():
    """Fade-in: 30 dB abaixo do volume do bloco em 0,5 s, chegando nele em 2,5 s."""
    return (Keyframe(0.5, gain_offset_db=-30.0), Keyframe(2.5, gain_offset_db=0.0))


# ---------------------------------------------------------------------------
# O grafo, sem ffmpeg
# ---------------------------------------------------------------------------


def _filtros_de_som(projeto, **kw) -> str:
    return ";".join(build_graph(projeto, want_video=False, **kw).filters)


class TestGrafo:
    def test_sem_curva_o_filtro_e_o_de_sempre(self):
        texto = _filtros_de_som(_projeto(Clip(_midia_falsa(), 0.0, 4.0, gain_db=-6.0)))
        assert "volume=-6.00dB" in texto and "pow(10" not in texto

    def test_com_curva_o_volume_vira_expressao_no_tempo(self):
        texto = _filtros_de_som(_projeto(Clip(_midia_falsa(), 0.0, 4.0, gain_db=-6.0, keyframes=_rampa())))
        assert "pow(10," in texto and "eval=frame" in texto
        assert "volume=-6.00dB" not in texto, "o volume fixo está dentro da expressão"
        assert "max(-60" in texto and "min(12" in texto, "a soma fica nos limites do controle"

    def test_o_relogio_da_curva_e_o_do_trecho_lido(self):
        clip = Clip(_midia_falsa(), 0.0, 4.0, keyframes=_rampa())
        inteiro = _filtros_de_som(_projeto(clip))
        assert "lt(t,0.500000)" in inteiro and "lt(t,2.500000)" in inteiro
        # Lendo a partir de 1 s, o primeiro ponto já passou e o segundo cai em 1,5 s do trecho.
        do_meio = _filtros_de_som(_projeto(clip), at=1.0)
        assert "lt(t,1.500000)" in do_meio and "lt(t,2.500000)" not in do_meio

    def test_vídeo_com_som_e_curva_so_de_volume_mantem_o_caminho_barato_da_imagem(self):
        """Um fade de som não pode mudar a montagem da imagem: o comando do quadro e o da reprodução
        saem iguais aos do mesmo projeto sem quadros-chave."""
        tools = FFmpegTools(Path("ffmpeg"), Path("ffprobe"), "teste")
        sem = _projeto(Clip(_midia_falsa(), 0.0, 4.0))
        com = _projeto(replace(sem.clips[0], keyframes=_rampa()))
        assert frame_command(com, 1.0, SIZE, tools) == frame_command(sem, 1.0, SIZE, tools)
        assert playback_command(com, 0.0, SIZE, tools, fps=FPS) == playback_command(sem, 0.0, SIZE, tools, fps=FPS)

    @staticmethod
    def _grafo_do_corte(esquerda: Clip, direita: Clip) -> str:
        projeto, _ = _projeto(esquerda, direita).with_transition(0, esquerda, direita, "fade", "Transição_fade",
                                                                 0.5, False)
        return _filtros_de_som(projeto)

    def test_corte_sem_degrau_de_volume_nao_ganha_transicao_de_som(self):
        """Duas metades da mesma mídia, uma depois da outra: se o volume **ouvido** é o mesmo dos dois lados
        do corte, ele continua de onde parou. Comparar só o ``gain_db`` acusava degrau onde a curva o compensa."""
        media = _midia_falsa()
        esquerda = Clip(media, 0.0, 1.5, in_point=0.5, keyframes=(Keyframe(0.0), Keyframe(1.5, gain_offset_db=-6.0)))
        direita = Clip(media, 1.5, 1.5, in_point=2.0, gain_db=-6.0)       # −6 dB, onde a esquerda termina
        assert esquerda.gain_at(esquerda.duration) == pytest.approx(direita.gain_at(0.0))
        assert "acrossfade" not in self._grafo_do_corte(esquerda, direita)

    def test_corte_com_degrau_de_volume_ganha_a_transicao_de_som(self):
        media = _midia_falsa()
        esquerda = Clip(media, 0.0, 1.5, in_point=0.5)
        direita = Clip(media, 1.5, 1.5, in_point=2.0, gain_db=-6.0)
        assert "acrossfade" in self._grafo_do_corte(esquerda, direita)

    def test_pose_animada_continua_no_caminho_das_transformacoes(self):
        tools = FFmpegTools(Path("ffmpeg"), Path("ffprobe"), "teste")
        sem = _projeto(Clip(_midia_falsa(), 0.0, 4.0))
        animado = _projeto(replace(sem.clips[0], keyframes=(Keyframe(0.0, x=0.2), Keyframe(2.0, x=0.8))))
        assert frame_command(animado, 1.0, SIZE, tools) != frame_command(sem, 1.0, SIZE, tools)


# ---------------------------------------------------------------------------
# O som, com ffmpeg de verdade
# ---------------------------------------------------------------------------

ffmpeg = pytest.mark.ffmpeg


@pytest.fixture(scope="module")
def tools():
    found = find_tools()
    if found is None:
        pytest.skip("FFmpeg não disponível")
    return found


def _run(tools, *args):
    done = subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", *args], timeout=180,
                          **subprocess_kwargs())
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-800:]
    return done.stdout


@pytest.fixture(scope="module")
def fonte(tools, tmp_path_factory):
    """Seis segundos de seno estável em PCM: sem o atraso de início do AAC, o nível é medível em qualquer janela."""
    path = tmp_path_factory.mktemp("volume") / "seno.mov"
    _run(tools,
         "-f", "lavfi", "-i", f"color=c=black:s=64x64:r=30:d={SEGUNDOS},format=yuv420p",
         "-f", "lavfi", "-i", f"sine=f=440:r={TAXA}:d={SEGUNDOS}",
         "-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-ac", "2", str(path))
    return media_ref(probe_file(path, tools))


def _exporta_som(tools, projeto, destino) -> array.array:
    subprocess.run(composer.export_args(projeto, destino, tools, container="wav", audio_only=True, audio_codec="wav"),
                   check=True, timeout=180, **subprocess_kwargs())
    dados = _run(tools, "-i", str(destino), "-vn", "-ac", "2", "-ar", str(TAXA), "-f", "s16le", "-")
    saida = array.array("h")
    saida.frombytes(dados[: len(dados) // 4 * 4])
    return saida[0::2]


def _db(teste, referencia, instante, largura=0.02) -> float:
    """O nível de ``teste`` em relação a ``referencia``, numa janela de ``largura`` s em torno de ``instante``."""
    a, b = int((instante - largura / 2) * TAXA), int((instante + largura / 2) * TAXA)

    def rms(amostras):
        return math.sqrt(sum(v * v for v in amostras[a:b]) / (b - a))

    return 20 * math.log10(rms(teste) / rms(referencia))


def _erro_relativo(a, b) -> float:
    n = min(len(a), len(b))
    diferenca = math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(n)) / n)
    return diferenca / (math.sqrt(sum(v * v for v in b[:n]) / n) or 1.0)


INSTANTES = (0.25, 1.0, 1.5, 2.0, 3.5)


@ffmpeg
def test_exportacao_segue_a_curva_de_volume(tools, fonte, tmp_path):
    clip = Clip(fonte, 0.0, 4.0, keyframes=_rampa())
    referencia = _exporta_som(tools, _projeto(Clip(fonte, 0.0, 4.0)), tmp_path / "ref.wav")
    teste = _exporta_som(tools, _projeto(clip), tmp_path / "curva.wav")
    assert len(teste) == len(referencia)
    for t in INSTANTES:
        assert _db(teste, referencia, t) == pytest.approx(clip.gain_at(t), abs=0.8), t


@ffmpeg
def test_volume_do_bloco_e_curva_somam(tools, fonte, tmp_path):
    clip = Clip(fonte, 0.0, 4.0, gain_db=-6.0, keyframes=_rampa())
    referencia = _exporta_som(tools, _projeto(Clip(fonte, 0.0, 4.0)), tmp_path / "ref.wav")
    teste = _exporta_som(tools, _projeto(clip), tmp_path / "soma.wav")
    for t in INSTANTES:
        assert _db(teste, referencia, t) == pytest.approx(clip.gain_at(t), abs=0.8), t
    assert clip.gain_at(0.25) == pytest.approx(-36.0) and clip.gain_at(3.5) == pytest.approx(-6.0)


@ffmpeg
def test_previa_toca_o_mesmo_som_da_exportacao(tools, fonte, tmp_path):
    projeto = _projeto(Clip(fonte, 0.0, 4.0, keyframes=_rampa()))
    exportado = _exporta_som(tools, projeto, tmp_path / "e.wav")
    comando = composer.audio_command(projeto, 0.0, tools)
    pcm = array.array("h")
    pcm.frombytes(subprocess.run(comando, check=True, timeout=120, **subprocess_kwargs()).stdout)
    assert len(pcm[0::2]) == len(exportado)
    assert _erro_relativo(pcm[0::2], exportado) < 1e-4


@ffmpeg
def test_previa_a_partir_do_meio_da_curva_toca_o_que_a_exportacao_toca_dali(tools, fonte, tmp_path):
    projeto = _projeto(Clip(fonte, 0.0, 4.0, keyframes=_rampa()))
    exportado = _exporta_som(tools, projeto, tmp_path / "e.wav")
    pcm = array.array("h")
    pcm.frombytes(subprocess.run(composer.audio_command(projeto, 1.5, tools), check=True, timeout=120,
                                 **subprocess_kwargs()).stdout)
    esperado = exportado[int(1.5 * TAXA):]
    assert abs(len(pcm[0::2]) - len(esperado)) < 2_500
    assert _erro_relativo(pcm[0::2], esperado) < 2e-2, "a curva foi lida do ponto certo, e não do começo do bloco"


@ffmpeg
def test_bloco_invertido_segue_a_curva_no_relogio_da_edicao(tools, fonte, tmp_path):
    clip = Clip(fonte, 0.0, 4.0, reversed=True, keyframes=_rampa())
    referencia = _exporta_som(tools, _projeto(Clip(fonte, 0.0, 4.0, reversed=True)), tmp_path / "ref.wav")
    teste = _exporta_som(tools, _projeto(clip), tmp_path / "inv.wav")
    for t in INSTANTES:
        assert _db(teste, referencia, t) == pytest.approx(clip.gain_at(t), abs=0.8), t


@ffmpeg
def test_dividir_o_bloco_exporta_o_mesmo_nivel_em_todo_instante(tools, fonte, tmp_path):
    clip = Clip(fonte, 0.0, 4.0, keyframes=_rampa())
    inteiro = _projeto(clip)
    dividido = inteiro.split(clip.clip_id, 1.3)
    assert len(dividido.tracks[0].clips) == 2
    referencia = _exporta_som(tools, _projeto(Clip(fonte, 0.0, 4.0)), tmp_path / "ref.wav")
    a = _exporta_som(tools, inteiro, tmp_path / "inteiro.wav")
    b = _exporta_som(tools, dividido, tmp_path / "dividido.wav")
    for t in (0.25, 1.0, 1.25, 1.35, 1.5, 2.0, 3.5):
        assert _db(b, referencia, t) == pytest.approx(_db(a, referencia, t), abs=0.8), t


@ffmpeg
def test_curva_constante_e_igual_ao_volume_fixo_com_e_sem_transicao(tools, fonte, tmp_path):
    def com_transicao(esquerda, direita):
        projeto, _ = _projeto(esquerda, direita).with_transition(0, esquerda, direita, "fade", "Transição_fade",
                                                                 0.5, False)
        return projeto

    constante = (Keyframe(0.0, gain_offset_db=-9.0), Keyframe(1.5, gain_offset_db=-9.0))
    fixo = _exporta_som(tools, _projeto(Clip(fonte, 0.0, 4.0, gain_db=-9.0)), tmp_path / "fixo.wav")
    curva = _exporta_som(tools, _projeto(Clip(fonte, 0.0, 4.0, keyframes=(Keyframe(0.0, gain_offset_db=-9.0),
                                                                           Keyframe(4.0, gain_offset_db=-9.0)))),
                         tmp_path / "curva.wav")
    assert _erro_relativo(curva, fixo) < 1e-3

    # Com transição (sobra de mídia nos dois lados): o lado de cada bloco usa a mesma origem do relógio.
    fixas = com_transicao(Clip(fonte, 0.0, 1.5, in_point=0.5, gain_db=-9.0), Clip(fonte, 1.5, 1.5, in_point=2.5, gain_db=-9.0))
    curvas = com_transicao(Clip(fonte, 0.0, 1.5, in_point=0.5, keyframes=constante),
                           Clip(fonte, 1.5, 1.5, in_point=2.5, keyframes=constante))
    assert _erro_relativo(_exporta_som(tools, curvas, tmp_path / "tc.wav"),
                          _exporta_som(tools, fixas, tmp_path / "tf.wav")) < 1e-3


@ffmpeg
def test_curva_que_chega_ao_volume_do_bloco_no_corte_nao_atenua_a_transicao(tools, fonte, tmp_path):
    """O som do lado do bloco da esquerda, na janela da transição, lê a curva no ponto onde o bloco está.

    A rampa chega a 0 dB no fim do bloco; se o relógio do lado da transição partisse do começo da janela
    (e não do começo do bloco), a janela inteira cairia no trecho de −30 dB e o corte afundaria.
    """
    def com_transicao(esquerda, direita):
        projeto, _ = _projeto(esquerda, direita).with_transition(0, esquerda, direita, "fade", "Transição_fade",
                                                                 0.5, False)
        return projeto

    rampa_ate_o_fim = (Keyframe(0.0, gain_offset_db=-30.0), Keyframe(1.5, gain_offset_db=0.0))
    direita = Clip(fonte, 1.5, 1.5, in_point=2.5)
    sem = _exporta_som(tools, com_transicao(Clip(fonte, 0.0, 1.5, in_point=0.5), direita), tmp_path / "sem.wav")
    com = _exporta_som(tools, com_transicao(Clip(fonte, 0.0, 1.5, in_point=0.5, keyframes=rampa_ate_o_fim), direita),
                       tmp_path / "com.wav")
    # No centro da janela (1,5 s) o som da esquerda está a ~0 dB: a mistura é a de sem curva.
    assert _db(com, sem, 1.5) == pytest.approx(0.0, abs=1.0)
    # E bem antes do corte a rampa ainda está baixa.
    assert _db(com, sem, 0.3) == pytest.approx(Clip(fonte, 0.0, 1.5, keyframes=rampa_ate_o_fim).gain_at(0.3), abs=1.0)


@ffmpeg
def test_separar_o_audio_nao_muda_o_som(tools, fonte, tmp_path):
    clip = Clip(fonte, 0.0, 4.0, gain_db=-3.0, keyframes=_rampa())
    antes = _projeto(clip)
    depois = antes.detached_audio(clip.clip_id)
    assert any(c.audio_only for c in depois.clips)
    a = _exporta_som(tools, antes, tmp_path / "antes.wav")
    b = _exporta_som(tools, depois, tmp_path / "depois.wav")
    referencia = _exporta_som(tools, _projeto(Clip(fonte, 0.0, 4.0)), tmp_path / "ref.wav")
    for t in INSTANTES:
        assert _db(b, referencia, t) == pytest.approx(_db(a, referencia, t), abs=0.5), t
