"""Níveis de compressão: que alvo cada arquivo recebe, e o que isso anuncia."""
from pathlib import Path

import pytest

from videomanager.domain.compression import LEVELS
from videomanager.domain.compression import compression_target
from videomanager.domain.estimator import estimate_convert_size
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import LocalStream
from videomanager.domain.media import VideoTarget

LEVE, EQUILIBRADA, FORTE, MAXIMA = LEVELS


def _video(largura=1920, altura=1080, audio="aac", kbps=256.0, nome="video.mp4", rotacao=0.0):
    streams = [LocalStream(0, "video", "h264", width=largura, height=altura, fps=30.0, rotation=rotacao)]
    if audio:
        streams.append(LocalStream(1, "audio", audio, bitrate=kbps))
    return LocalMedia(Path(f"/origem/{nome}"), 60.0, "mov,mp4", 150_000_000, tuple(streams))


def _audio(codec, kbps, nome="musica.mp3", capa=False):
    streams = [LocalStream(0, "audio", codec, bitrate=kbps)]
    if capa:
        streams.append(LocalStream(1, "video", "mjpeg", width=500, height=500, attached_picture=True))
    return LocalMedia(Path(f"/origem/{nome}"), 180.0, "mp3", 7_000_000, tuple(streams))


def test_niveis_vao_da_qualidade_ao_tamanho():
    alvos = [compression_target(_video(), nivel, "h264", "software") for nivel in LEVELS]
    assert [alvo.quality for alvo in alvos] == ["high", "balanced", "economy", "economy"]
    assert [alvo.audio_bitrate for alvo in alvos] == ["192", "128", "96", "64"]
    assert [alvo.height for alvo in alvos] == [None, None, None, 720]


@pytest.mark.parametrize(("largura", "altura", "rotacao", "reduz"), [
    (1920, 1080, 0, 720),   # paisagem acima do teto
    (1080, 1920, 0, 720),   # retrato: o teto é o lado curto
    (1920, 1080, 90, 720),  # gravado de lado, com rotação nos metadados
    (1280, 720, 0, None),   # já no teto
    (854, 480, 0, None),    # abaixo: ampliar só aumentaria o arquivo
])
def test_maxima_nunca_amplia(largura, altura, rotacao, reduz):
    alvo = compression_target(_video(largura, altura, rotacao=rotacao), MAXIMA, "h264", "software")
    assert alvo.height == reduz


def test_audio_do_video_abaixo_do_teto_e_copiado():
    assert compression_target(_video(kbps=96.0), EQUILIBRADA, "h264", "software").audio_codec == "copy"
    alvo = compression_target(_video(kbps=256.0), EQUILIBRADA, "h264", "software")
    assert (alvo.audio_codec, alvo.audio_bitrate) == ("aac", "128")
    # Sem o bitrate de origem não há como saber: recodifica no teto.
    assert compression_target(_video(kbps=None), EQUILIBRADA, "h264", "software").audio_codec == "aac"


def test_mkv_continua_mkv_e_o_resto_vira_mp4():
    # Só o MKV guarda todas as faixas de áudio e as legendas.
    assert compression_target(_video(nome="a.mkv"), EQUILIBRADA, "hevc", "software").container == "mkv"
    assert compression_target(_video(nome="a.mov"), EQUILIBRADA, "hevc", "software").container == "mp4"
    assert compression_target(_video(nome="a.webm"), EQUILIBRADA, "av1", "software").container == "mp4"


def test_codec_e_placa_escolhidos_chegam_ao_alvo():
    alvo = compression_target(_video(), FORTE, "hevc", "nvenc")
    assert isinstance(alvo, VideoTarget)
    assert (alvo.video_codec, alvo.hardware) == ("hevc", "nvenc")


def test_audio_acima_do_teto_e_recodificado_no_mesmo_formato():
    alvo = compression_target(_audio("mp3", 320.0), EQUILIBRADA, "h264", "software")
    assert alvo == AudioTarget(codec="mp3", bitrate="128", reencode=True)


def test_audio_abaixo_do_teto_nao_e_recodificado():
    # Recodificar 96 kbps em 96 kbps só perderia qualidade, sem ganhar espaço.
    alvo = compression_target(_audio("mp3", 96.0), EQUILIBRADA, "h264", "software")
    assert alvo == AudioTarget(codec="mp3", bitrate="96", reencode=False)


@pytest.mark.parametrize(("codec", "saida"), [("aac", "m4a"), ("opus", "opus"), ("vorbis", "vorbis"),
                                              ("flac", "m4a"), ("pcm_s16le", "m4a"), ("wmav2", "m4a")])
def test_formato_do_audio_comprimido(codec, saida):
    assert compression_target(_audio(codec, 900.0), FORTE, "h264", "software").codec == saida


def test_mp3_com_capa_e_audio():
    alvo = compression_target(_audio("mp3", 320.0, capa=True), EQUILIBRADA, "h264", "software")
    assert isinstance(alvo, AudioTarget)


def test_imagem_nao_vira_video():
    foto = LocalMedia(Path("/origem/foto.png"), None, "png_pipe", 3_000_000,
                      (LocalStream(0, "video", "png", width=4000, height=3000),))
    assert isinstance(compression_target(foto, EQUILIBRADA, "h264", "software"), AudioTarget)


def test_estimativa_encolhe_a_cada_nivel():
    for midia in (_video(), _video(1080, 1920), _audio("flac", 900.0, nome="a.flac")):
        tamanhos = [estimate_convert_size(midia, compression_target(midia, nivel, "h264", "software"))
                    for nivel in LEVELS]
        assert tamanhos == sorted(tamanhos, reverse=True) and len(set(tamanhos)) == 4, tamanhos


def test_estimativa_do_audio_recodificado_usa_o_bitrate_pedido():
    midia = _audio("mp3", 320.0)
    alvo = compression_target(midia, EQUILIBRADA, "h264", "software")
    assert estimate_convert_size(midia, alvo) == int(128 * 1000 / 8 * 180.0)


def test_estimativa_do_video_usa_o_audio_do_nivel():
    midia = _video(kbps=320.0)
    alvos = [compression_target(midia, nivel, "h264", "software") for nivel in (FORTE, MAXIMA)]
    forte, maxima = (estimate_convert_size(midia, alvo) for alvo in alvos)
    so_video = [estimate_convert_size(_video(audio=None), alvo) for alvo in alvos]
    assert forte - so_video[0] == pytest.approx(96 * 1000 / 8 * 60 * 1.015, rel=0.01)
    assert maxima - so_video[1] == pytest.approx(64 * 1000 / 8 * 60 * 1.015, rel=0.01)
