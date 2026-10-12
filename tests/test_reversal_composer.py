"""Bordas do compositor para o bloco invertido, conferidas sem abrir o ffmpeg.

Os testes com ffmpeg de ``test_reversal.py`` usam trechos com sobra de mídia
dos dois lados e blocos que começam no começo do bloco. Os ramos abaixo só
aparecem quando falta mídia numa ponta, quando um bloco invertido encontra um
normal na mesma emenda, ou quando a janela de uma exportação herda a
interpolação da composição — e desfazê-los não derrubava teste nenhum.
"""

from pathlib import Path

import pytest

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.errors import ConversionError
from videomanager.domain.composition import Composition
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.infrastructure.ffmpeg import composer, parallel
from videomanager.infrastructure.ffmpeg.parallel import ParallelExport

TOOLS = FFmpegTools(Path("ffmpeg"), Path("ffprobe"), "teste")


def _midia(duration=4.0, fps=30.0):
    return MediaRef(Path("/m/clipe.mp4"), MediaKind.VIDEO, duration=duration, width=64, height=64, fps=fps,
                    has_audio=True, channels=2)


def _projeto(*clips, fps=30.0):
    return Project(tracks=(Track(TrackKind.VIDEO, clips=tuple(clips)),), width=64, height=64, fps=fps)


def _contexto(esquerda, direita, duracao=0.5):
    """O corte entre dois blocos encostados, com uma transição de ``duracao`` segundos."""
    projeto, _ = _projeto(esquerda, direita).with_transition(0, esquerda, direita, "fade", "Transição_fade",
                                                             duracao, False)
    return projeto.transition_contexts()[0]


class TestEmendaContinua:
    def test_as_metades_de_um_invertido_dividido_continuam_de_onde_pararam(self):
        clip = Clip(_midia(), 0.0, 3.0, in_point=0.5, reversed=True)
        esquerda, direita = _projeto(clip).split(clip.clip_id, 1.2).tracks[0].sorted_clips()
        assert composer._is_continuous_source_cut(_contexto(esquerda, direita))

    @pytest.mark.parametrize(("esquerda_invertida", "direita_invertida"), [(False, True), (True, False)],
                             ids=["normal_e_invertido", "invertido_e_normal"])
    def test_um_invertido_nunca_emenda_com_um_normal(self, esquerda_invertida, direita_invertida):
        """Mesmo quando o ponto onde um termina é o ponto onde o outro começa na mídia.

        O normal termina em ``out_point`` e o invertido começa em ``out_point``: as contas batem, mas um
        toca para cima e o outro para baixo, e tratá-los como o mesmo fluxo suprimia a transição.
        """
        esquerda = Clip(_midia(), 0.0, 1.5, in_point=0.5, reversed=esquerda_invertida)
        direita = Clip(_midia(), 1.5, 1.5, in_point=0.5, reversed=direita_invertida)
        assert esquerda.tail_point == pytest.approx(direita.head_point)
        assert not composer._is_continuous_source_cut(_contexto(esquerda, direita))


class TestSobraDeAudioNaTransicao:
    """O cross-fade do som só vale com material real dos dois lados da emenda (0,25 s cada, aqui)."""

    @pytest.mark.parametrize(("esquerda", "direita", "cabe"), [
        (dict(in_point=0.1, reversed=True), dict(in_point=2.0), False),
        (dict(in_point=0.3, reversed=True), dict(in_point=2.0), True),
        (dict(in_point=0.5), dict(in_point=2.4, reversed=True), False),   # sobram 4,0 − 3,9 = 0,1 s
        (dict(in_point=0.5), dict(in_point=2.0, reversed=True), True),    # sobram 4,0 − 3,5 = 0,5 s
        (dict(duration=1.0, speed=2.0, in_point=0.4, reversed=True), dict(in_point=2.0), False),  # 0,4 s de mídia = 0,2 s
        (dict(duration=1.0, speed=2.0, in_point=0.6, reversed=True), dict(in_point=2.0), True),   # 0,6 s de mídia = 0,3 s
    ], ids=["esquerda_sem_sobra", "esquerda_com_sobra", "direita_sem_sobra", "direita_com_sobra",
            "esquerda_a_2x_sem_sobra", "esquerda_a_2x_com_sobra"])
    def test_a_sobra_e_a_do_lado_que_o_bloco_toca(self, esquerda, direita, cabe):
        a = Clip(_midia(), 0.0, **{"duration": 1.5, **esquerda})
        b = Clip(_midia(), a.end, **{"duration": 1.5, **direita})
        assert composer._has_audio_handles(_contexto(a, b)) is cabe


class TestJanelaHerdaAInterpolacao:
    """Cada janela da exportação de um bloco invertido grande é um trecho comum da composição."""

    def _projeto(self):
        # Fonte abaixo da taxa da tela: é o único caso em que interpolar muda o grafo.
        return _projeto(Clip(_midia(fps=24.0), 0.0, 3.0, reversed=True), fps=30.0)

    def test_o_trecho_so_interpola_quando_pedido(self):
        projeto, destino = self._projeto(), Path("/o/t.mp4")
        sem = " ".join(composer.segment_video_args(projeto, 0.0, 1.0, destino, TOOLS, interpolate=False))
        com = " ".join(composer.segment_video_args(projeto, 0.0, 1.0, destino, TOOLS, interpolate=True))
        assert "minterpolate" not in sem
        assert "minterpolate" in com

    def test_a_exportacao_passa_a_interpolacao_da_composicao_a_cada_trecho(self, monkeypatch, tmp_path):
        pedidos = []

        def recusa(*args, **kwargs):
            pedidos.append(kwargs["interpolate"])
            raise RuntimeError("só interessa o pedido")

        monkeypatch.setattr(parallel, "segment_video_args", recusa)
        for interpolar in (False, True):
            composicao = Composition(self._projeto(), "mp4", interpolate=interpolar)
            ParallelExport(composicao, tmp_path / "x.mp4", TOOLS, 1, bounds=((0.0, 3.0),), workers=1)._render(
                0, tmp_path / "trecho.mp4")
        assert pedidos == [False, True]


class TestRecusaDoGif:
    """O GIF não se divide em janelas e recusa o que não cabe num processo só."""

    @staticmethod
    def _hd(nome, duration):
        return MediaRef(Path(f"/m/{nome}"), MediaKind.VIDEO, duration=duration, width=1920, height=1080, fps=30.0,
                        has_audio=False, channels=2)

    def test_a_mensagem_cita_o_bloco_que_estoura_e_nao_o_primeiro_invertido(self):
        curto = Clip(self._hd("curto.mp4", 10.0), 0.0, 3.0, reversed=True)       # cabe folgado numa janela
        longo = Clip(self._hd("longo.mp4", 600.0), 3.0, 300.0, reversed=True)    # é ele que precisa de janelas
        projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(curto, longo)),), width=1920, height=1080, fps=30.0)
        with pytest.raises(ConversionError, match="longo.mp4") as recusa:
            composer.check_reversal(projeto)
        assert "curto.mp4" not in str(recusa.value)

    def test_o_gif_de_um_invertido_pequeno_segue_sem_recusa(self):
        curto = Clip(self._hd("curto.mp4", 10.0), 0.0, 3.0, reversed=True)
        composer.check_reversal(Project(tracks=(Track(TrackKind.VIDEO, clips=(curto,)),), width=1920, height=1080,
                                        fps=30.0))
