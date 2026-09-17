"""Fim de bloco sem quadros pretos — o que aparecia na emenda do loop.

Muito MP4 tem o container um pouco mais longo que a trilha de vídeo (áudio AAC
com sobra, arquivos baixados a 23,976 fps). O bloco durava o container, e os
últimos quadros dele saíam pretos: um lampejo entre dois blocos e, no loop da
prévia, uma tela preta antes de recomeçar.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from videomanager.domain.media import LocalMedia, LocalStream
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, media_ref


def _local(container: float, video: float | None) -> LocalMedia:
    return LocalMedia(Path("/m/v.mp4"), container, "mov,mp4,m4a,3gp,3g2,mj2", 1000, (
        LocalStream(0, "video", "h264", height=90, width=160, fps=30, duration=video),
        LocalStream(1, "audio", "aac", sample_rate=48000, channels=2, duration=container),
    ))


class TestDuracaoDoVideo:
    def test_bloco_novo_dura_a_trilha_de_video(self) -> None:
        assert media_ref(_local(3.4, 3.0)).duration == pytest.approx(3.0)

    def test_sem_duracao_da_trilha_vale_o_container(self) -> None:
        assert media_ref(_local(3.4, None)).duration == pytest.approx(3.4)

    def test_audio_puro_nao_muda(self) -> None:
        local = LocalMedia(Path("/m/s.mp3"), 5.0, "mp3", 10, (LocalStream(0, "audio", "mp3", duration=4.9),))
        assert media_ref(local).duration == pytest.approx(5.0)


def test_bloco_de_video_segura_o_ultimo_quadro_e_imagem_nao() -> None:
    from videomanager.infrastructure.ffmpeg.composer import build_graph

    video = Clip(MediaRef(Path("/m/v.mp4"), MediaKind.VIDEO, duration=3, width=160, height=90, fps=30), 0, 3)
    photo = Clip(MediaRef(Path("/m/f.png"), MediaKind.IMAGE, width=160, height=90), 3, 2)
    graph = build_graph(Project(tracks=(Track(TrackKind.VIDEO, clips=(video, photo)),), width=160, height=90, fps=30))
    chains = [f for f in graph.filters if f.startswith("[0:v]") or f.startswith("[1:v]")]
    video_chain = next(f for f in chains if f.startswith("[0:v]"))
    photo_chain = next(f for f in chains if f.startswith("[1:v]"))
    assert "tpad=stop_mode=clone" in video_chain
    assert "tpad" not in photo_chain


@pytest.fixture
def ffmpeg(tmp_path):
    from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs
    tools = find_tools()
    if tools is None:
        pytest.skip("ffmpeg/ffprobe indisponíveis")

    def run(*args):
        subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", *map(str, args)],
                       check=True, timeout=60, **subprocess_kwargs())
    return tools, run


@pytest.mark.ffmpeg
def test_sondagem_le_a_duracao_da_trilha_de_video(ffmpeg, tmp_path) -> None:
    from videomanager.infrastructure.ffmpeg.converter import probe_file

    tools, run = ffmpeg
    source = tmp_path / "audio_maior.mp4"
    run("-f", "lavfi", "-i", "color=c=white:s=160x90:r=30:d=3", "-f", "lavfi", "-i", "sine=d=3.4",
        "-c:v", "libx264", "-c:a", "aac", source)
    local = probe_file(source, tools)
    assert local.duration == pytest.approx(3.4, abs=0.05)
    assert local.video.duration == pytest.approx(3.0, abs=0.02)
    assert media_ref(local).duration == pytest.approx(3.0, abs=0.02)


@pytest.mark.ffmpeg
def test_bloco_antigo_mais_longo_que_o_video_nao_termina_preto(ffmpeg, tmp_path) -> None:
    """Projetos já gravados guardam a duração do container: a reprodução segura
    o último quadro em vez de mostrar preto até o fim do bloco."""
    from videomanager.infrastructure.ffmpeg.composer import playback_command
    from videomanager.infrastructure.system.binaries import subprocess_kwargs

    tools, run = ffmpeg
    source = tmp_path / "curto.mp4"
    run("-f", "lavfi", "-i", "color=c=white:s=160x90:r=30:d=3", "-c:v", "libx264", source)
    legacy = MediaRef(source, MediaKind.VIDEO, duration=3.4, width=160, height=90, fps=30)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(legacy, 0, 3.4),)),), width=160, height=90, fps=30)
    command = playback_command(project, 2.5, (160, 90), tools, fps=30)
    process = subprocess.Popen(command, **subprocess_kwargs())
    try:
        frames = [process.stdout.read(160 * 90 * 3) for _ in range(26)]
    finally:
        process.kill()
        process.wait()
    # Quadro 21 a partir de 2,5 s = 3,2 s: além do vídeo, dentro do bloco.
    tail = frames[21]
    assert len(tail) == 160 * 90 * 3
    assert tail[(45 * 160 + 80) * 3] > 200
