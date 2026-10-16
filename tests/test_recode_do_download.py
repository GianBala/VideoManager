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

from videomanager.application.errors import JobCancelled
from videomanager.domain.selection import VideoRequest
from videomanager.infrastructure.ffmpeg import recode
from videomanager.infrastructure.ffmpeg.recode import SourceVideo
from videomanager.infrastructure.yt_dlp.downloader import Downloader, RecodePlan


def _e_o_aviso_de_fallback(aviso) -> bool:
    """O ``Text`` guarda a chave por dentro; o que se vê é o texto do catálogo, no idioma do momento."""
    from videomanager.domain.i18n import t
    return str(aviso).startswith(t("RECODE_FALLBACK", error="\0").split("\0")[0])


def _fonte(family="h264", container="mp4", kbps=4000.0, duration=10.0) -> SourceVideo:
    return SourceVideo(family=family, container=container, kbps=kbps, duration=duration)


# -- a decisão ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("fonte", [4000.0, 2500.0, 2550.0, 2551.0, 900.0, None])
def test_o_ffmpeg_decide_pela_mesma_regra_do_painel_e_da_estimativa(fonte):
    from videomanager.domain.selection import keeps_source
    assert recode.needs_recode(_fonte(kbps=fonte), 2500) is (not keeps_source(fonte, 2500))


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
def test_o_ffmpeg_que_falha_entrega_o_original_com_aviso(tools, tmp_path, monkeypatch):
    """Decisão Q2 da revisão de efeed31 a 087f775: o download já está completo; a recodificação é um acabamento, e a
    falha dela não pode descartá-lo. (Antes: ``DownloadFailedError``, e o arquivo ficava preso na pasta temporária.)"""
    baixador, fonte, _ = _baixado(tools, tmp_path, kbps=800)
    antes = fonte.read_bytes()
    monkeypatch.setattr(recode, "build_args", lambda *a, **k: [[tools.ffmpeg_str, "-nostdin", "-i", "/nao/existe.mp4", "x.mp4"]])
    baixador._recode_video()  # não levanta
    assert fonte.read_bytes() == antes
    assert len(baixador.warnings) == 1 and _e_o_aviso_de_fallback(baixador.warnings[0])
    assert any("entregue" in linha or "delivered" in linha for linha in baixador.log)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fonte.mp4"]  # nenhuma sobra da recodificação


@pytest.mark.ffmpeg
def test_run_entrega_o_arquivo_e_o_aviso_quando_a_recodificacao_falha(tools, tmp_path, monkeypatch):
    fonte = _sintetico(tools, tmp_path)
    _com_yt_dlp_falso(monkeypatch, fonte)
    monkeypatch.setattr(recode, "build_args", lambda *a, **k: [[tools.ffmpeg_str, "-nostdin", "-i", "/nao/existe.mp4", "x.mp4"]])
    resultado = Downloader({}, recode_plan=RecodePlan(kbps=800, tools=tools)).run("https://exemplo.invalido/v")
    assert resultado.path == fonte and len(resultado.warnings) == 1 and _e_o_aviso_de_fallback(resultado.warnings[0])


@pytest.mark.ffmpeg
def test_arquivo_sem_video_nao_e_recodificado_nem_falha(tools, tmp_path):
    """Num lote em "Vídeo com áudio", um item só de áudio chegava ao ffmpeg com ``-map 0:v:0`` e a tarefa falhava."""
    audio = tmp_path / "so_audio.m4a"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=3", "-c:a", "aac",
                    str(audio)], check=True)
    antes = audio.read_bytes()
    baixador = Downloader({}, recode_plan=RecodePlan(kbps=800, tools=tools))
    baixador._final_path = audio
    baixador._recode_video()
    assert audio.read_bytes() == antes and baixador.warnings == ()
    assert any("vídeo" in linha or "video" in linha for linha in baixador.log)
    assert [p.name for p in tmp_path.iterdir()] == ["so_audio.m4a"]


@pytest.mark.ffmpeg
def test_a_sondagem_distingue_o_arquivo_sem_video_do_com_video(tools, tmp_path):
    audio = tmp_path / "so_audio.m4a"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=3", "-c:a", "aac",
                    str(audio)], check=True)
    assert not recode.probe_video(audio, tools).has_video
    assert recode.probe_video(_sintetico(tools, tmp_path), tools).has_video
    assert SourceVideo("h264", "mp4", 4000.0, 10.0).has_video  # o padrão: quem monta à mão não muda


# -- a ligação com o download e o cancelamento de verdade ------------------------------------------------------

class _YtDlpFalso:
    """O ``YoutubeDL`` que só entrega o arquivo já "baixado": o que importa aqui é o que ``run`` faz depois."""

    arquivo: Path

    def __init__(self, opts):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def add_post_processor(self, *args, **kwargs):
        pass

    def extract_info(self, url, download=True):
        return {"title": "titulo", "requested_downloads": [{"filepath": str(self.arquivo)}]}


def _com_yt_dlp_falso(monkeypatch, arquivo: Path) -> None:
    from videomanager.infrastructure.yt_dlp import downloader

    _YtDlpFalso.arquivo = arquivo
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", _YtDlpFalso)


@pytest.mark.ffmpeg
def test_run_recodifica_o_que_o_yt_dlp_baixou_quando_o_pedido_traz_o_bitrate(tools, tmp_path, monkeypatch):
    """Os outros testes chamam ``_recode_video`` direto; este garante que o download passa por ele (tirar a chamada de
    ``run`` desligava o recurso inteiro sem a suíte notar)."""
    fonte = _sintetico(tools, tmp_path)
    _com_yt_dlp_falso(monkeypatch, fonte)
    antes = _sondar(tools, fonte)
    resultado = Downloader({}, recode_plan=RecodePlan(kbps=800, tools=tools)).run("https://exemplo.invalido/v")
    depois = _sondar(tools, fonte)
    assert resultado.path == fonte and resultado.title == "titulo"
    kbps = float(depois["format"]["size"]) * 8 / float(depois["format"]["duration"]) / 1000
    assert 650 < kbps - 128 < 950, f"saiu com {kbps:.0f} kbps no total para um pedido de 800 de vídeo"
    assert float(antes["format"]["size"]) > 2 * float(depois["format"]["size"])


@pytest.mark.ffmpeg
def test_run_sem_plano_deixa_o_arquivo_baixado_como_esta(tools, tmp_path, monkeypatch):
    fonte = _sintetico(tools, tmp_path)
    _com_yt_dlp_falso(monkeypatch, fonte)
    antes = fonte.read_bytes()
    Downloader({}).run("https://exemplo.invalido/v")
    assert fonte.read_bytes() == antes


@pytest.mark.ffmpeg
def test_cancelar_mata_o_ffmpeg_da_recodificacao_de_verdade(tools, tmp_path, monkeypatch):
    """O teste de cancelamento acima troca ``_run_recode`` por uma função que levanta e nunca abre um processo. Aqui o
    ffmpeg corre de verdade, aberto pela ``Popen`` registrada do yt-dlp, e ``cancel()`` precisa alcançá-lo."""
    import threading
    import time

    fonte = tmp_path / "fonte.mp4"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=1920x1080:rate=60:duration=40", "-c:v", "libx264", "-preset", "ultrafast",
                    "-b:v", "20000k", "-pix_fmt", "yuv420p", str(fonte)], check=True)
    antes = fonte.read_bytes()
    _com_yt_dlp_falso(monkeypatch, fonte)
    baixador = Downloader({}, recode_plan=RecodePlan(kbps=1500, tools=tools))
    desfecho: dict = {}

    def baixar():
        try:
            baixador.run("https://exemplo.invalido/v")
            desfecho["fim"] = "terminou"
        except JobCancelled:
            desfecho["fim"] = "cancelado"

    fio = threading.Thread(target=baixar)
    fio.start()
    prazo = time.monotonic() + 20
    while not baixador._processes and time.monotonic() < prazo:
        time.sleep(0.02)
    assert baixador._processes, "o ffmpeg da recodificação não foi registrado para o cancelamento"
    processo = baixador._processes[-1]
    baixador.cancel()
    fio.join(15)
    assert not fio.is_alive() and desfecho == {"fim": "cancelado"}
    assert processo.poll() is not None  # o ffmpeg morreu, e não só a thread esperou por ele
    assert fonte.read_bytes() == antes
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fonte.mp4"]


@pytest.mark.ffmpeg
def test_a_capa_e_a_legenda_embutidas_sobrevivem_a_recodificacao(tools, tmp_path):
    """O docstring do arquivo promete "a capa embutida que se perde": o ``-map 0`` e a cópia do resto a guardam."""
    capa, legenda = tmp_path / "capa.jpg", tmp_path / "l.srt"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=1",
                    "-frames:v", "1", str(capa)], check=True)
    legenda.write_text("1\n00:00:01,000 --> 00:00:03,000\nola\n")
    base = _sintetico(tools, tmp_path)
    fonte = tmp_path / "com_capa.mp4"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-i", str(base), "-i", str(legenda), "-i", str(capa),
                    "-map", "0", "-map", "1", "-map", "2", "-c", "copy", "-c:s", "mov_text", "-disposition:v:1",
                    "attached_pic", str(fonte)], check=True)
    baixador = Downloader({}, recode_plan=RecodePlan(kbps=800, tools=tools))
    baixador._final_path = fonte
    baixador._recode_video()
    streams = _sondar(tools, fonte)["streams"]
    tipos = [(s["codec_type"], s["codec_name"], bool((s.get("disposition") or {}).get("attached_pic"))) for s in streams]
    assert tipos == [("video", "h264", False), ("audio", "aac", False), ("subtitle", "mov_text", False), ("video", "mjpeg", True)]
