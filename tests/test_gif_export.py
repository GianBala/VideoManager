"""Exportação da edição como GIF animado, com ffmpeg de verdade.

GIF não tem trilha de áudio e só admite 256 cores por quadro, então a
exportação monta uma paleta a partir da própria edição e grava em loop.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, media_ref
from videomanager.infrastructure.ffmpeg.composer import export_args
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs

pytestmark = pytest.mark.ffmpeg


@pytest.fixture
def tools():
    found = find_tools()
    if found is None:
        pytest.skip("FFmpeg não disponível")
    return found


def _probe(tools, path: Path) -> str:
    return subprocess.run(
        [tools.ffprobe_str, "-v", "error", "-count_frames", "-show_entries",
         "format=format_name:stream=codec_type,codec_name,width,height,nb_read_frames",
         "-of", "compact", str(path)],
        capture_output=True, text=True, timeout=120, check=True,
    ).stdout


def test_exporta_gif_animado_em_loop_e_sem_som(tools, tmp_path) -> None:
    fonte = tmp_path / "fonte.mp4"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=320x180:r=30:d=2", "-f", "lavfi", "-i", "sine=d=2",
                    "-c:v", "libx264", "-c:a", "aac", str(fonte)],
                   check=True, timeout=120, **subprocess_kwargs())
    media = media_ref(probe_file(fonte, tools))
    project = Project(
        tracks=(
            Track(TrackKind.VIDEO, clips=(Clip(media, 0, 2.0),)),
            Track(TrackKind.AUDIO, clips=(Clip(
                MediaRef(fonte, MediaKind.AUDIO, duration=2.0, has_audio=True, channels=2), 0, 2.0),)),
        ),
        width=160, height=90, fps=10.0,
    )
    destino = tmp_path / "saida.gif"
    subprocess.run(export_args(project, destino, tools, container="gif"), check=True, timeout=300,
                   **subprocess_kwargs())

    info = _probe(tools, destino)
    assert "format_name=gif" in info
    assert "codec_name=gif" in info and "width=160|height=90" in info
    assert "codec_type=audio" not in info, "GIF não tem trilha de áudio"
    quadros = int(info.split("nb_read_frames=")[1].split("|")[0].split("\n")[0])
    assert quadros == pytest.approx(20, abs=2), f"esperados ~20 quadros a 10 q/s, vieram {quadros}"
    assert destino.stat().st_size > 1024

    # Em loop infinito: o GIF traz a extensão NETSCAPE, e nela a contagem de
    # repetições zero, que o formato define como "para sempre".
    dados = destino.read_bytes()
    marca = dados.find(b"NETSCAPE2.0")
    assert marca > 0, "sem a marca de loop"
    repeticoes = int.from_bytes(dados[marca + 13:marca + 15], "little")
    assert repeticoes == 0, f"o loop para depois de {repeticoes} voltas"


def test_imagem_parada_tambem_vira_gif(tools, tmp_path) -> None:
    foto = tmp_path / "foto.png"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=64x64", "-frames:v", "1", str(foto)],
                   check=True, timeout=60, **subprocess_kwargs())
    imagem = MediaRef(foto, MediaKind.IMAGE, width=64, height=64)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(imagem, 0, 1.0),)),),
                      width=64, height=64, fps=10.0)
    destino = tmp_path / "foto.gif"
    subprocess.run(export_args(project, destino, tools, container="gif"), check=True, timeout=120,
                   **subprocess_kwargs())
    assert "format_name=gif" in _probe(tools, destino)


def test_gif_termina_na_ultima_imagem_mesmo_com_musica_mais_longa(tools, tmp_path) -> None:
    """O GIF não tem som, então a música não pode alongá-lo.

    Um vídeo de 2 s com uma música de 5 s saía como um GIF de 5 s: três
    segundos de tela preta no fim da animação, que ainda voltava a eles a cada
    repetição do loop.
    """
    from videomanager.application.media.export_description import describe_export
    from videomanager.domain.composition import Composition

    fonte, musica = tmp_path / "fonte.mp4", tmp_path / "musica.m4a"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=160x90:r=10:d=2", "-c:v", "libx264", str(fonte)],
                   check=True, timeout=120, **subprocess_kwargs())
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=5",
                    str(musica)], check=True, timeout=120, **subprocess_kwargs())
    project = Project(
        tracks=(
            Track(TrackKind.VIDEO, clips=(Clip(media_ref(probe_file(fonte, tools)), 0, 2.0),)),
            Track(TrackKind.AUDIO, clips=(Clip(MediaRef(musica, MediaKind.AUDIO, duration=5.0, has_audio=True,
                                                        channels=1), 0, 5.0),)),
        ),
        width=160, height=90, fps=10.0,
    )
    destino = tmp_path / "saida.gif"
    subprocess.run(export_args(project, destino, tools, container="gif"), check=True, timeout=300,
                   **subprocess_kwargs())

    quadros = int(_probe(tools, destino).split("nb_read_frames=")[1].split("|")[0].split("\n")[0])
    assert quadros == pytest.approx(20, abs=2), f"esperados ~20 quadros (2 s a 10 q/s), vieram {quadros}"
    # A barra de progresso e o texto da janela contam a mesma duração.
    assert Composition(project, container="gif").output_duration == pytest.approx(2.0)
    assert "2,00 s de duração" in describe_export(project, "gif")
