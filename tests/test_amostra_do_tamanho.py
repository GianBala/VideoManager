"""A amostra que mede o tamanho do que a conversão grava (``infrastructure/ffmpeg/sample.py``), contra a codificação inteira.

Tudo aqui codifica de verdade e mede os bytes que o encoder gravou: um estimador que só não explode não prova nada. O
caso que o desenho antigo (3 trechos de 8 s em 25%, 50% e 75%) errava em −99,9% — o trecho pesado nos primeiros 20% do
arquivo, que nenhum dos três alcançava — é o que prende a escolha dos trechos.
"""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.domain import size_model
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import VideoTarget
from videomanager.infrastructure.ffmpeg import sample
from videomanager.infrastructure.ffmpeg.converter import build_audio_args
from videomanager.infrastructure.ffmpeg.converter import build_video_args
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.system.binaries import subprocess_kwargs
from videomanager.infrastructure.system.process import ProcessControl

pytestmark = pytest.mark.ffmpeg


@pytest.fixture
def ffmpeg_tools():
    from videomanager.infrastructure.system.binaries import find_tools
    tools = find_tools()
    if tools is None:
        pytest.skip("ffmpeg/ffprobe indisponíveis")
    return tools


def _run(tools, *args: str) -> None:
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", *args], check=True, timeout=120,
                   **subprocess_kwargs())


def _heavy_then_still(tools, folder: Path, heavy: int, still: int) -> Path:
    """Ruído de imagem nos primeiros ``heavy`` s e uma tela cinza parada nos ``still`` seguintes."""
    path = folder / "origem.mp4"
    _run(tools, "-f", "lavfi", "-i", f"testsrc2=s=640x360:r=30:d={heavy},noise=alls=40:allf=t",
         "-f", "lavfi", "-i", f"color=c=gray:s=640x360:r=30:d={still}",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-c:v", "libx264", "-crf", "20",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path))
    return path


def _full_video_kbps(tools, media, target: VideoTarget, folder: Path) -> float:
    silent = replace(media, streams=tuple(s for s in media.streams if s.kind == "video"))
    output = folder / f"completo.{target.extension}"
    ProcessControl().run(build_video_args(silent, target, output, tools), timeout=180)
    return sample.payload_bytes(output, "v:0", tools, ProcessControl()) * 8 / 1000 / media.duration


H264 = VideoTarget(container="mp4", video_codec="h264")


def test_arquivo_curto_e_medido_inteiro_e_o_resultado_e_exato(ffmpeg_tools, tmp_path) -> None:
    media = probe_file(_heavy_then_still(ffmpeg_tools, tmp_path, 8, 8), ffmpeg_tools)
    medido = sample.sample_video_kbps(media, H264, ffmpeg_tools, ProcessControl())
    assert medido == pytest.approx(_full_video_kbps(ffmpeg_tools, media, H264, tmp_path), rel=0.002)


def test_trecho_pesado_no_comeco_nao_escapa_da_amostra(ffmpeg_tools, tmp_path, monkeypatch) -> None:
    media = probe_file(_heavy_then_still(ffmpeg_tools, tmp_path, 20, 80), ffmpeg_tools)
    # Sem orçamento de tempo a cobertura é a mínima (6 trechos de 4 s): o caso difícil, de amostrar 24 s de 100.
    monkeypatch.setattr(size_model, "TIME_BUDGET", 0.0001)
    medido = sample.sample_video_kbps(media, H264, ffmpeg_tools, ProcessControl())
    real = _full_video_kbps(ffmpeg_tools, media, H264, tmp_path)
    assert real > 1000  # a origem é mesmo pesada onde se diz que é
    assert medido == pytest.approx(real, rel=0.08)


def test_encoder_rapido_mede_o_arquivo_inteiro(ffmpeg_tools, tmp_path, monkeypatch) -> None:
    media = probe_file(_heavy_then_still(ffmpeg_tools, tmp_path, 30, 90), ffmpeg_tools)
    monkeypatch.setattr(size_model, "TIME_BUDGET", 10_000.0)  # cabe tudo
    windows = []
    original = size_model.project_bytes

    def espiar(duration, janelas, curve):
        windows.extend(janelas)
        return original(duration, janelas, curve)

    monkeypatch.setattr(size_model, "project_bytes", espiar)
    medido = sample.sample_video_kbps(media, H264, ffmpeg_tools, ProcessControl())
    assert [(w.start, round(w.length)) for w in windows] == [(0.0, 120)]
    assert medido == pytest.approx(_full_video_kbps(ffmpeg_tools, media, H264, tmp_path), rel=0.002)


def test_curva_da_fonte_conta_a_partir_do_inicio_do_arquivo(ffmpeg_tools, tmp_path) -> None:
    """TS e gravações de câmera não começam em zero: sem descontar o início, o primeiro trecho da curva ficava vazio."""
    origem = _heavy_then_still(ffmpeg_tools, tmp_path, 10, 10)
    transporte = tmp_path / "origem.ts"
    _run(ffmpeg_tools, "-i", str(origem), "-c", "copy", str(transporte))
    em_ts = sample.source_curve(probe_file(transporte, ffmpeg_tools), ffmpeg_tools, ProcessControl())
    em_mp4 = sample.source_curve(probe_file(origem, ffmpeg_tools), ffmpeg_tools, ProcessControl())
    assert em_ts is not None and em_mp4 is not None
    # O mpegts começa em 1,4 s: a parte do arquivo que cai nos 2 primeiros segundos é a mesma nos dois formatos.
    assert em_ts.between(0, 2) / em_ts.total == pytest.approx(em_mp4.between(0, 2) / em_mp4.total, rel=0.1)


def test_amostra_de_audio_acompanha_a_codificacao_inteira(ffmpeg_tools, tmp_path) -> None:
    """Rajadas de ruído a cada 30 s: o Opus gasta ordens de grandeza a mais nelas do que no silêncio entre elas."""
    origem = tmp_path / "audio.mka"
    _run(ffmpeg_tools, "-f", "lavfi", "-i", "anoisesrc=d=150:a=0.3:r=48000,volume='if(lt(mod(t,30),8),1,0.02)':eval=frame",
         "-c:a", "pcm_s16le", str(origem))
    media = probe_file(origem, ffmpeg_tools)
    alvo = AudioTarget(codec="opus", bitrate="128", reencode=True)
    medido = sample.sample_audio_kbps(media, alvo, ffmpeg_tools, ProcessControl())
    completo = tmp_path / "completo.opus"
    ProcessControl().run(build_audio_args(media, alvo, completo, ffmpeg_tools), timeout=120)
    real = sample.payload_bytes(completo, "a:0", ffmpeg_tools, ProcessControl()) * 8 / 1000 / media.duration
    assert medido == pytest.approx(real, rel=0.12)
    assert abs(medido - 128) > 5  # o nominal não é o que o Opus grava aqui: a medida tem o que mostrar
