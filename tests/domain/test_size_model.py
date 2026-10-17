"""A conta que leva o que foi medido em trechos ao tamanho do arquivo inteiro (``domain/size_model.py``)."""

import pytest

from videomanager.domain import size_model as sm


def _curve(rate_at, seconds: int) -> sm.SourceCurve:
    """Curva da fonte com ``rate_at(s)`` bytes no segundo ``s``."""
    return sm.SourceCurve.from_packets([(s + 0.5, rate_at(s)) for s in range(seconds)], seconds)


class TestSourceCurve:
    def test_soma_por_trecho_e_total(self) -> None:
        curve = _curve(lambda s: 1000, 10)
        assert curve.total == 10_000
        assert curve.between(2, 5) == 3000

    def test_pontas_fora_de_segundos_inteiros_interpolam(self) -> None:
        curve = _curve(lambda s: 1000 if s < 5 else 3000, 10)
        assert curve.between(4.5, 5.5) == pytest.approx(500 + 1500)

    def test_pacote_depois_do_fim_nao_perde_bytes(self) -> None:
        curve = sm.SourceCurve.from_packets([(0.2, 10), (99.0, 5)], 10)
        assert curve.total == 15

    def test_intervalo_invertido_ou_vazio_e_zero(self) -> None:
        curve = _curve(lambda s: 1000, 10)
        assert curve.between(5, 5) == 0
        assert curve.between(6, 5) == 0


class TestPlanWindows:
    def test_sem_duracao_nao_ha_o_que_medir(self) -> None:
        assert sm.plan_windows(0, None) == []

    def test_arquivo_curto_e_medido_inteiro(self) -> None:
        assert sm.plan_windows(10.0, None) == [(0.0, 10.0)]
        limit = sm.STRATA * sm.MIN_LENGTH
        assert sm.plan_windows(limit, None) == [(0.0, limit)]

    def test_um_trecho_por_estrato_centrado_sem_a_curva(self) -> None:
        windows = sm.plan_windows(120.0, None)
        assert len(windows) == sm.STRATA
        span = 120.0 / sm.STRATA
        for index, (start, length) in enumerate(windows):
            assert length == sm.MIN_LENGTH
            assert start + length / 2 == pytest.approx(span * (index + 0.5))

    def test_cada_trecho_fica_dentro_do_proprio_estrato(self) -> None:
        curve = _curve(lambda s: 500 + (s * 37) % 900, 300)
        span = 300 / sm.STRATA
        for index, (start, length) in enumerate(sm.plan_windows(300.0, curve)):
            assert span * index - 1e-9 <= start and start + length <= span * (index + 1) + 1e-9

    def test_fonte_de_taxa_constante_mede_o_meio_e_nao_a_borda(self) -> None:
        # Todo trecho empata; sem o desempate o primeiro (a borda do estrato) vencia sempre.
        curve = _curve(lambda s: 1000, 120)
        span = 120.0 / sm.STRATA
        for index, (start, length) in enumerate(sm.plan_windows(120.0, curve)):
            assert abs((start + length / 2) - span * (index + 0.5)) <= 1.0

    def test_trecho_representativo_foge_do_pico(self) -> None:
        # O meio do primeiro estrato (10–20 s) é um pico de 10×; a média do estrato pede um trecho fora dele.
        curve = _curve(lambda s: 10_000 if 13 <= s < 17 else 1000, 120)
        start, length = sm.plan_windows(120.0, curve)[0]
        spike_in_window = curve.between(start, start + length) / length
        mean = curve.between(0, 20) / 20
        assert abs(spike_in_window - mean) < abs(10_000 - mean)
        assert not (start < 17 and start + length > 13 and spike_in_window > 5000)


class TestPlanDesign:
    def test_arquivo_curto_e_medido_inteiro(self) -> None:
        assert sm.plan_design(20.0, 0.5) == (1, 20.0)

    def test_encoder_rapido_mede_o_arquivo_inteiro(self) -> None:
        # 218 s a 15× custa 14,5 s: cabe no orçamento, e o resultado é exato.
        assert sm.plan_design(218.0, 15.0) == (1, 218.0)

    def test_encoder_lento_fica_no_desenho_minimo(self) -> None:
        assert sm.plan_design(300.0, 1.7) == (sm.STRATA, pytest.approx(34 / sm.STRATA, rel=0.01))
        strata, length = sm.plan_design(300.0, 0.5)
        assert (strata, length) == (sm.STRATA, sm.MIN_LENGTH)

    def test_encoder_medio_cobre_mais_com_trechos_maiores(self) -> None:
        strata, length = sm.plan_design(3600.0, 5.0)
        assert length == sm.MAX_LENGTH and strata * length >= sm.TIME_BUDGET * 5.0 * 0.9
        assert sm.STRATA < strata <= sm.MAX_STRATA

    def test_a_cobertura_nunca_passa_do_orcamento(self) -> None:
        for speed in (0.3, 1.0, 3.0, 8.0, 40.0):
            strata, length = sm.plan_design(7200.0, speed)
            assert strata * length <= max(sm.MIN_CONTENT, sm.TIME_BUDGET * speed) * 1.25 or strata == sm.MAX_STRATA


class TestProjectBytes:
    def test_nada_medido_nao_projeta(self) -> None:
        assert sm.project_bytes(100.0, [], None) is None
        assert sm.project_bytes(0.0, [sm.Window(0, 4, 100)], None) is None

    def test_arquivo_inteiro_medido_e_exato(self) -> None:
        assert sm.project_bytes(10.0, [sm.Window(0.0, 10.0, 12_345)], _curve(lambda s: 99, 10)) == 12_345

    def test_sem_curva_extrapola_a_taxa_de_cada_estrato(self) -> None:
        windows = [sm.Window(0, 4, 4000), sm.Window(30, 4, 8000)]
        # Estratos de 30 s: 1000 B/s e 2000 B/s.
        assert sm.project_bytes(60.0, windows, None) == pytest.approx(1000 * 30 + 2000 * 30)

    def test_a_razao_pela_fonte_corrige_o_trecho_que_nao_representa(self) -> None:
        # A saída é metade da fonte em todo ponto. A fonte pesa 5× mais na segunda metade de cada estrato de 30 s, e os
        # dois trechos medidos caíram justamente na metade leve.
        curve = _curve(lambda s: 1000 if s % 30 < 15 else 5000, 60)
        windows = [sm.Window(start, 4, 0.5 * curve.between(start, start + 4)) for start in (2, 32)]
        exact = 0.5 * curve.total
        assert sm.project_bytes(60.0, windows, curve) == pytest.approx(exact)
        # Sem a curva, a conta toma a metade leve pelo estrato todo e erra por dois terços.
        assert sm.project_bytes(60.0, windows, None) < 0.5 * exact

    def test_trecho_quase_sem_bytes_na_fonte_nao_amplifica_ruido(self) -> None:
        curve = _curve(lambda s: 0 if s < 10 else 1000, 60)
        quiet = sm.Window(2, 4, 400)  # a fonte não pesa nada ali: a razão seria 400/0
        total = sm.project_bytes(60.0, [quiet, sm.Window(40, 4, 400)], curve)
        assert total is not None and total == pytest.approx(100 * 30 + 100 * 30, rel=0.01)

    def test_curva_inteira_vazia_cai_na_extrapolacao_direta(self) -> None:
        empty = sm.SourceCurve.from_packets([], 60)
        assert sm.project_bytes(60.0, [sm.Window(0, 4, 400), sm.Window(30, 4, 400)], empty) == pytest.approx(6000)


class TestOverhead:
    def test_container_cresce_com_as_amostras_e_nao_com_o_tamanho(self) -> None:
        assert sm.container_overhead_bytes("mp4", 10_000) > sm.container_overhead_bytes("mp4", 1_000)
        assert sm.container_overhead_bytes("mp4", 5_000) > sm.container_overhead_bytes("mkv", 5_000)

    def test_um_1080p_de_um_minuto_paga_menos_de_meio_por_cento(self) -> None:
        samples = 60 * (30 + 47)
        assert sm.container_overhead_bytes("mp4", samples) < 0.005 * 60 * 5_000_000 / 8

    def test_codecs_de_audio_conhecidos(self) -> None:
        assert sm.audio_overhead("m4a") == pytest.approx(0.012)
        assert sm.audio_overhead("opus") < sm.audio_overhead("vorbis")
        assert sm.audio_overhead("flac") == 0.0


class TestNeedsSample:
    @staticmethod
    def _media(*streams, duration=60.0, name="a.mp4", fmt="mov,mp4"):
        from pathlib import Path

        from videomanager.domain.media import LocalMedia
        return LocalMedia(Path(name), duration, fmt, 1_000_000, tuple(streams))

    def _v(self):
        from videomanager.domain.media import LocalStream
        return LocalStream(0, "video", "h264", width=1920, height=1080, fps=30.0)

    def _a(self, codec="aac"):
        from videomanager.domain.media import LocalStream
        return LocalStream(1, "audio", codec, bitrate=192.0)

    def test_copiar_o_video_nao_pede_medida(self) -> None:
        from videomanager.domain.media import VideoTarget
        assert not sm.needs_sample(self._media(self._v(), self._a()), VideoTarget(video_codec="copy"))

    def test_recodificar_o_video_pede(self) -> None:
        from videomanager.domain.media import VideoTarget
        assert sm.needs_sample(self._media(self._v(), self._a()), VideoTarget(video_codec="h264"))

    def test_copiar_que_recodifica_de_fato_tambem_pede_medida(self) -> None:
        """O codec pedido é "Cópia", mas redimensionar, mudar a taxa ou trocar para um container que não aceita o codec
        recodifica: o tamanho depende do conteúdo do mesmo jeito (a conta por pixels errou −39% a +609% nesses casos)."""
        from videomanager.domain.media import LocalStream, VideoTarget
        h264 = self._media(self._v(), self._a())
        assert sm.needs_sample(h264, VideoTarget(container="mp4", video_codec="copy", height=720))
        assert sm.needs_sample(h264, VideoTarget(container="mp4", video_codec="copy", fps=24.0))
        assert sm.needs_sample(h264, VideoTarget(container="webm", video_codec="copy"))
        vp9 = self._media(LocalStream(0, "video", "vp9", width=1920, height=1080, fps=30.0), self._a("opus"))
        assert sm.needs_sample(vp9, VideoTarget(container="mp4", video_codec="copy"))
        # e a cópia que de fato copia continua sem medida
        assert not sm.needs_sample(h264, VideoTarget(container="mp4", video_codec="copy"))
        assert not sm.needs_sample(h264, VideoTarget(container="mkv", video_codec="copy"))

    def test_sem_duracao_nao_ha_o_que_medir(self) -> None:
        from videomanager.domain.media import VideoTarget
        assert not sm.needs_sample(self._media(self._v(), duration=None), VideoTarget(video_codec="h264"))

    def test_mp3_e_wav_se_acertam_pela_conta_e_o_resto_do_audio_pede_medida(self) -> None:
        from videomanager.domain.media import AudioTarget
        media = self._media(self._v(), self._a())
        assert not sm.needs_sample(media, AudioTarget(codec="mp3", bitrate="192"))
        assert not sm.needs_sample(media, AudioTarget(codec="wav", bitrate="0"))
        for codec in ("opus", "vorbis", "flac", "alac", "m4a"):
            assert sm.needs_sample(media, AudioTarget(codec=codec, bitrate="128", reencode=True))

    def test_audio_copiado_nao_pede_medida(self) -> None:
        from videomanager.domain.media import AudioTarget
        assert not sm.needs_sample(self._media(self._v(), self._a("aac")), AudioTarget(codec="m4a", bitrate="128"))
        assert sm.needs_sample(self._media(self._v(), self._a("aac")), AudioTarget(codec="m4a", bitrate="128", reencode=True))

    def test_arquivo_sem_audio_nao_mede_audio(self) -> None:
        from videomanager.domain.media import AudioTarget
        assert not sm.needs_sample(self._media(self._v()), AudioTarget(codec="opus", bitrate="128"))
