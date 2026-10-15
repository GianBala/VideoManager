"""Bitrate de vídeo no download: recodificar só quando foi pedido, no codec certo e sem aumentar (``infrastructure/ffmpeg/recode.py``).

O download nunca recodifica por conta própria; pedir um bitrate é o consentimento. O que isso pode errar sem exceção: o vídeo
que sai maior que a fonte (recodificado a um bitrate acima do dela), o codec que troca junto, o áudio que é recodificado sem
ninguém pedir, o arquivo que fica pela metade quando o ffmpeg falha, a capa embutida que se perde.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from videomanager.application.errors import DownloadFailedError, JobCancelled
from videomanager.domain.selection import VideoRequest
from videomanager.infrastructure.ffmpeg import recode
from videomanager.infrastructure.ffmpeg.recode import SourceVideo
from videomanager.infrastructure.yt_dlp.downloader import Downloader, RecodePlan


def _fonte(family="h264", container="mp4", kbps=4000.0, duration=10.0) -> SourceVideo:
    return SourceVideo(family=family, container=container, kbps=kbps, duration=duration)


# -- a decisão ------------------------------------------------------------------------------------------------

def test_o_pedido_de_video_sem_bitrate_e_igual_a_fonte():
    assert VideoRequest().video_kbps is None


@pytest.mark.parametrize("fonte, pedido, recodifica", [
    (4000.0, 2500, True),
    (2500.0, 2500, False),   # já está no bitrate pedido
    (2540.0, 2500, False),   # dentro da folga do ffprobe
    (900.0, 2500, False),    # abaixo: recodificar só aumentaria o arquivo
    (None, 2500, True),      # sem bitrate conhecido, vale o pedido
])
def test_nao_recodifica_para_um_bitrate_igual_ou_maior_que_o_da_fonte(fonte, pedido, recodifica):
    assert recode.needs_recode(_fonte(kbps=fonte), pedido) is recodifica


@pytest.mark.parametrize("familia, container, esperado", [
    ("h264", "mp4", "h264"), ("hevc", "mp4", "hevc"), ("hevc", "mkv", "hevc"), ("vp9", "webm", "vp9"),
    ("vp9", "mp4", "h264"),    # o container não aceita: cai no padrão dele
    ("vp9", "mkv", "vp9"), ("av1", "webm", "av1"), ("h264", "webm", "vp9"), (None, "mp4", "h264"),
])
def test_o_codec_da_saida_e_o_da_fonte_quando_o_container_o_aceita(familia, container, esperado):
    assert recode.target_family(_fonte(family=familia, container=container)) == esperado


def test_o_comando_recodifica_so_o_primeiro_video_e_copia_o_resto(tmp_path):
    tools = type("T", (), {"ffmpeg_str": "ffmpeg", "ffprobe_str": "ffprobe"})()
    [args] = recode.build_args(tmp_path / "a.mp4", tmp_path / "b.mp4", "hevc", 2500, "mp4", tools)
    assert args[args.index("-map") + 1] == "0" and args[args.index("-c") + 1] == "copy"
    assert args[args.index("-c:v:0") + 1] == "libx265" and args[args.index("-b:v") + 1] == "2500k"
    assert "hvc1" in args and "+faststart" in args  # etiqueta que o QuickTime exige e índice no começo do MP4
    assert recode.seconds_done("out_time_us=1500000\n") == 1.5 and recode.seconds_done("bitrate=  1.0kbits/s") is None


def test_x264_x265_e_vp9_recodificam_em_duas_passadas_e_o_av1_em_uma(tmp_path):
    tools = type("T", (), {"ffmpeg_str": "ffmpeg", "ffprobe_str": "ffprobe"})()
    log = tmp_path / ".passada"
    for familia in ("h264", "hevc", "vp9"):
        primeira, segunda = recode.build_args(tmp_path / "a.mp4", tmp_path / "b.mp4", familia, 2500, "mp4", tools, passlog=log)
        assert primeira[primeira.index("-pass") + 1] == "1" and "-an" in primeira and "null" in primeira
        assert segunda[segunda.index("-pass") + 1] == "2" and segunda[-1] == str(tmp_path / "b.mp4")
        assert primeira[primeira.index("-passlogfile") + 1] == segunda[segunda.index("-passlogfile") + 1] == str(log)
        assert recode.passes_for(familia) == 2
    assert len(recode.build_args(tmp_path / "a.mp4", tmp_path / "b.mp4", "av1", 2500, "mp4", tools, passlog=log)) == 1
    assert recode.passes_for("av1") == 1


# -- o ffmpeg de verdade --------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tools():
    from videomanager.infrastructure.system import binaries
    achadas = binaries.find_tools()
    if achadas is None:
        pytest.skip("ffmpeg não disponível; rode a aplicação uma vez para provisioná-lo")
    return achadas


def _sintetico(tools, pasta: Path, kbps: int = 3000, segundos: int = 8) -> Path:
    saida = pasta / "fonte.mp4"
    comando = [tools.ffmpeg_str, "-nostdin", "-v", "error", "-y",
               "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={segundos}",
               "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}",
               "-c:v", "libx264", "-b:v", f"{kbps}k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(saida)]
    subprocess.run(comando, check=True)
    return saida


def _sondar(tools, path: Path) -> dict:
    saida = subprocess.run([tools.ffprobe_str, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams",
                            str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(saida)


def _baixado(tools, pasta: Path, kbps: int, **kwargs) -> tuple[Downloader, Path, list]:
    fonte = _sintetico(tools, pasta, **kwargs)
    eventos: list = []
    baixador = Downloader({}, on_progress=eventos.append, recode_plan=RecodePlan(kbps=kbps, tools=tools))
    baixador._final_path = fonte
    return baixador, fonte, eventos


@pytest.mark.ffmpeg
def test_recodifica_ao_bitrate_pedido_sem_tocar_no_audio_e_troca_o_arquivo_no_lugar(tools, tmp_path):
    baixador, fonte, eventos = _baixado(tools, tmp_path, kbps=800)
    antes = _sondar(tools, fonte)
    audio_antes = next(s for s in antes["streams"] if s["codec_type"] == "audio")
    baixador._recode_video()
    depois = _sondar(tools, fonte)
    video = next(s for s in depois["streams"] if s["codec_type"] == "video")
    audio = next(s for s in depois["streams"] if s["codec_type"] == "audio")
    kbps = float(depois["format"]["size"]) * 8 / float(depois["format"]["duration"]) / 1000
    assert video["codec_name"] == "h264"
    assert 650 < kbps - 128 < 950, f"o arquivo saiu com {kbps:.0f} kbps no total (áudio de 128) para um pedido de 800 de vídeo"
    assert audio["codec_name"] == "aac" and audio["nb_frames"] == audio_antes["nb_frames"]  # copiado, não recodificado
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".recodificando")] == []  # nem os arquivos da passada dupla
    assert any(getattr(e, "percent", None) is not None for e in eventos)


@pytest.mark.ffmpeg
def test_um_bitrate_acima_do_da_fonte_deixa_o_arquivo_como_esta(tools, tmp_path):
    baixador, fonte, _ = _baixado(tools, tmp_path, kbps=20000)
    antes = fonte.read_bytes()
    baixador._recode_video()
    assert fonte.read_bytes() == antes
    assert any("kbps" in linha for linha in baixador.log)


@pytest.mark.ffmpeg
def test_cancelar_a_recodificacao_deixa_a_fonte_intacta_e_nao_sobra_arquivo(tools, tmp_path, monkeypatch):
    baixador, fonte, _ = _baixado(tools, tmp_path, kbps=800)
    antes = fonte.read_bytes()

    def cancelar_no_meio(args, duration, index=0, total=1):
        baixador._cancelled = True
        raise JobCancelled("cancelado")

    monkeypatch.setattr(baixador, "_run_recode", cancelar_no_meio)
    with pytest.raises(JobCancelled):
        baixador._recode_video()
    assert fonte.read_bytes() == antes
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fonte.mp4"]


@pytest.mark.ffmpeg
def test_o_ffmpeg_que_falha_levanta_erro_claro_e_deixa_a_fonte(tools, tmp_path, monkeypatch):
    baixador, fonte, _ = _baixado(tools, tmp_path, kbps=800)
    antes = fonte.read_bytes()
    monkeypatch.setattr(recode, "build_args", lambda *a, **k: [[tools.ffmpeg_str, "-nostdin", "-i", "/nao/existe.mp4", "x.mp4"]])
    with pytest.raises(DownloadFailedError):
        baixador._recode_video()
    assert fonte.read_bytes() == antes
