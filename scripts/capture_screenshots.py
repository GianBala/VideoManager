"""Gera as imagens do README: capturas das abas e um GIF animado da edição.

    PYTHONPATH=src python scripts/capture_screenshots.py [--saida docs/imagens]

Tudo sai de mídia sintética (ffmpeg) e de um perfil temporário: nada toca as
preferências nem os arquivos de quem roda. A janela usa ``WA_DontShowOnScreen``,
então é desenhada e capturada sem nunca aparecer na tela. O GIF é exportado
pelo mesmo caminho da janela de exportação (``composer.export_args``).

Refaça as imagens quando a interface mudar de forma visível; elas não fazem
parte da suíte de testes.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ICONE = REPO / "src" / "videomanager" / "resources" / "videomanager.png"

# Estas capturas dependem de fontes com símbolos: a plataforma "offscreen" do Qt
# no Windows não as tem e desenha quadrados no lugar dos ícones.
_PLATAFORMA_PADRAO = "windows" if sys.platform == "win32" else "offscreen"


def _argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--saida", type=Path, default=REPO / "docs" / "imagens",
                        help="pasta das imagens (padrão: docs/imagens)")
    parser.add_argument("--plataforma", default=_PLATAFORMA_PADRAO,
                        help=f"plataforma do Qt (padrão: {_PLATAFORMA_PADRAO})")
    return parser.parse_args()


def main() -> int:
    args = _argumentos()
    os.environ["QT_QPA_PLATFORM"] = args.plataforma
    saida: Path = args.saida
    saida.mkdir(parents=True, exist_ok=True)
    trabalho = Path(tempfile.mkdtemp(prefix="vm-capturas-"))

    from videomanager.infrastructure.storage import settings as armazenamento

    perfil = trabalho / "perfil"
    perfil.mkdir()
    armazenamento.config_dir = lambda: perfil

    from PySide6.QtCore import Qt

    from videomanager.app import build_app
    from videomanager.application.events import Progress, ProgressStage
    from videomanager.application.jobs.models import Job, JobKind, JobStatus
    from videomanager.domain.keyframe import ClipTransform, Keyframe, create_preset_keyframes
    from videomanager.domain.project import (
        Clip, MediaKind, MediaRef, Project, Track, TrackKind, media_ref,
    )
    from videomanager.infrastructure.ffmpeg.composer import export_args
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs
    from videomanager.infrastructure.yt_dlp.probe import media_from_info

    ferramentas = find_tools()
    if ferramentas is None:
        print("ffmpeg/ffprobe não encontrados.", file=sys.stderr)
        return 1

    def ffmpeg(*argumentos: str) -> None:
        subprocess.run([ferramentas.ffmpeg_str, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
                        *argumentos], check=True, **subprocess_kwargs())

    app, janela = build_app([], audio_enabled=False)
    janela.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

    # --- mídia sintética -----------------------------------------------------
    ffmpeg("-f", "lavfi", "-i", "gradients=s=1280x720:d=7:speed=0.04:c0=0x0b1026:c1=0x6d28d9:c2=0x0ea5e9"
           ":c3=0xf472b6:nb_colors=4:rate=30", "-f", "lavfi", "-i", "sine=frequency=330:duration=7",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(trabalho / "aurora.mp4"))
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=1280x720:d=7:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:duration=7",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(trabalho / "cidade.mp4"))
    ffmpeg("-f", "lavfi", "-i", "gradients=s=1280x720:d=6:speed=0.06:c0=0x022c22:c1=0x10b981:c2=0xfde047"
           ":nb_colors=3:rate=30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(trabalho / "campo.mp4"))
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=196:duration=15", "-c:a", "libmp3lame", "-b:a", "128k",
           str(trabalho / "trilha.mp3"))
    ffmpeg("-ss", "3", "-i", str(trabalho / "aurora.mp4"), "-frames:v", "1", "-vf", "scale=480:-2",
           str(trabalho / "capa.png"))
    # Fundos lisos e transição por deslize no GIF: gradiente e misturas de cor não cabem
    # nas 256 cores da paleta e saem com ruído (e o arquivo, enorme).
    ffmpeg("-f", "lavfi", "-i", "color=c=0x0f172a:s=1280x720:r=30:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           str(trabalho / "azul.mp4"))
    ffmpeg("-f", "lavfi", "-i", "color=c=0x4c1d95:s=1280x720:r=30:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           str(trabalho / "roxo.mp4"))

    # O ícone oficial do aplicativo faz o papel de imagem sobreposta nas edições.
    shutil.copyfile(ICONE, trabalho / "icone.png")

    nomes = ("aurora.mp4", "cidade.mp4", "campo.mp4", "trilha.mp3", "icone.png", "azul.mp4", "roxo.mp4")
    caminhos = {nome: trabalho / nome for nome in nomes}
    refs = {nome: media_ref(probe_file(caminho, ferramentas)) for nome, caminho in caminhos.items()}

    def processar(segundos: float) -> None:
        fim = time.monotonic() + segundos
        while time.monotonic() < fim:
            app.processEvents()
            time.sleep(0.005)

    def esperar(condicao, prazo: float = 25.0) -> None:
        fim = time.monotonic() + prazo
        while not condicao() and time.monotonic() < fim:
            app.processEvents()
            time.sleep(0.005)

    def salvar(nome: str, largura: int) -> None:
        processar(0.5)
        imagem = janela.grab().toImage()
        if imagem.width() > largura:
            imagem = imagem.scaledToWidth(largura, Qt.TransformationMode.SmoothTransformation)
        imagem.save(str(saida / nome), "PNG")
        print(f"{nome}: {imagem.width()}x{imagem.height()}", flush=True)

    # --- fila com tarefas em andamento ---------------------------------------
    fila = janela._queue
    tarefas = [
        Job(url="https://exemplo.com/video", title="Curta-metragem de demonstração em 4K",
            description="MP4 · 1080p", kind=JobKind.DOWNLOAD, status=JobStatus.RUNNING,
            progress=Progress("Baixando", percent=63.0, speed=8.4e6, eta=41, stage=ProgressStage.DOWNLOAD)),
        Job(url="https://exemplo.com/podcast", title="Podcast — episódio 42", description="MP3 · 320 kbps",
            kind=JobKind.DOWNLOAD, status=JobStatus.RUNNING,
            progress=Progress("Baixando", percent=27.0, speed=3.1e6, eta=88, stage=ProgressStage.DOWNLOAD)),
        Job(url="", title="aurora.mp4", description="H.264 · 720p", kind=JobKind.CONVERT,
            status=JobStatus.PROCESSING, progress=Progress("Convertendo", percent=82.0, eta=6)),
        Job(url="", title="Meu projeto.mp4", description="Exportação · 1080p", kind=JobKind.EXPORT,
            status=JobStatus.DONE, result_size=48_600_000, progress=Progress("Concluído", percent=100.0)),
        Job(url="https://exemplo.com/lista/4", title="Playlist — item 4 de 12", description="MP4 · 1080p",
            kind=JobKind.DOWNLOAD, status=JobStatus.PENDING),
    ]
    for tarefa in tarefas:
        fila.service.add(tarefa)
        fila.job_added.emit(tarefa)
        fila.job_changed.emit(tarefa)
    fila.counts_changed.emit()

    # --- aba Download --------------------------------------------------------
    janela.resize(1280, 900)
    janela.show()
    processar(0.6)
    info = json.loads((REPO / "tests" / "fixtures" / "youtube_dash.json").read_text(encoding="utf-8"))
    midia = dataclasses.replace(
        media_from_info(info), title="Curta-metragem de demonstração em 4K", uploader="Canal de exemplo",
        thumbnail_url="", url="https://exemplo.com/video",
    )
    janela._url.setText("https://exemplo.com/video")
    janela._dest.setText(r"C:\Users\usuario\Downloads")
    janela._on_probed(midia)
    janela._card._pending_thumb_url = "demo"
    janela._card._apply_thumb("demo", (trabalho / "capa.png").read_bytes())
    janela._tabs.setCurrentIndex(0)
    processar(1.0)
    salvar("download.png", 1280)

    # --- aba Convert ---------------------------------------------------------
    janela._tabs.setCurrentIndex(1)
    janela._convert.add_files([caminhos["aurora.mp4"], caminhos["cidade.mp4"], caminhos["campo.mp4"]])
    processar(2.5)
    conversao = janela._convert
    conversao._to_video.setChecked(True)
    conversao._container.setCurrentIndex(max(0, conversao._container.findData("mp4")))
    conversao._video_codec.setCurrentIndex(max(0, conversao._video_codec.findData("h264")))
    conversao._resize.setCurrentIndex(max(0, conversao._resize.findData(720)))
    processar(1.0)
    salvar("convert.png", 1280)

    # --- aba Editar ----------------------------------------------------------
    janela.resize(1920, 1200)
    janela._tabs.setCurrentIndex(2)
    processar(0.6)
    painel = janela._edit

    c1 = Clip(refs["aurora.mp4"], start=0.0, duration=6.0)
    c2 = Clip(refs["cidade.mp4"], start=6.0, duration=6.0)
    c3 = Clip(refs["campo.mp4"], start=12.0, duration=5.0)
    transicao = Clip(MediaRef(Path("Transicao"), MediaKind.IMAGE, duration=1.0), start=5.5, duration=1.0,
                     overlay_type="transition", transition_name="dissolve",
                     transition_left_id=c1.clip_id, transition_right_id=c2.clip_id)
    animado = Clip(
        refs["icone.png"], start=1.0, duration=8.0, scale=0.28, x=0.85, y=0.2,
        keyframes=(
            Keyframe(0.0, x=1.15, y=0.2, scale_x=0.28, scale_y=0.28, opacity=0.0, easing="ease_out"),
            Keyframe(1.0, x=0.85, y=0.2, scale_x=0.28, scale_y=0.28, opacity=1.0, easing="ease_in_out"),
            Keyframe(5.0, x=0.85, y=0.2, scale_x=0.28, scale_y=0.28, opacity=1.0),
            Keyframe(7.0, x=0.85, y=0.8, scale_x=0.4, scale_y=0.4, rotation=360.0, opacity=1.0),
        ),
    )
    titulo = Clip(MediaRef(Path("Texto_Video Manager"), MediaKind.IMAGE, duration=5.0), start=0.5, duration=5.0,
                  overlay_type="text", text_content="Video Manager", font_family="Sans Serif", font_size=110,
                  font_bold=True, text_color="#ffffff", stroke_color="#0f172a", stroke_width=6, x=0.5, y=0.5)
    vinheta = Clip(MediaRef(Path("Filtro_Vinheta"), MediaKind.IMAGE, duration=3.0), start=6.0, duration=6.0,
                   overlay_type="filter", filter_name="vinheta")
    musica = Clip(refs["trilha.mp3"], start=0.0, duration=15.0, gain_db=-6.0)
    projeto = Project(
        tracks=(
            Track(TrackKind.ADDITIONAL, clips=(titulo, vinheta), name="Adicionais 1"),
            Track(TrackKind.VIDEO, clips=(animado,), name="Vídeo 2"),
            Track(TrackKind.VIDEO, clips=(c1, transicao, c2, c3), name="Vídeo 1"),
            Track(TrackKind.AUDIO, clips=(musica,), name="Áudio 1"),
        ),
        width=1280, height=720, fps=30.0,
    )
    assert len(projeto.transition_contexts()) == 1

    painel.import_files([caminhos[n] for n in ("aurora.mp4", "cidade.mp4", "campo.mp4", "trilha.mp3", "icone.png")])
    processar(4.0)
    painel._apply(projeto)
    painel._timeline.select(animado.clip_id)
    painel._seek_to(2.0)
    painel._open_properties_tab(animado.clip_id)
    esperar(lambda: painel._preview.has_frame and not painel._frame_busy)
    processar(4.0)  # miniaturas e forma de onda das trilhas
    painel._timeline.fit()
    processar(1.0)
    divisao = painel._split_view.sizes()
    painel._split_view.setSizes([int(sum(divisao) * 0.61), int(sum(divisao) * 0.39)])
    processar(2.0)
    salvar("editor.png", 1600)

    # --- GIF: a edição exportada pelo próprio aplicativo ---------------------
    azul = Clip(refs["azul.mp4"], start=0.0, duration=3.5)
    roxo = Clip(refs["roxo.mp4"], start=3.5, duration=3.5)
    passagem = Clip(MediaRef(Path("Transicao"), MediaKind.IMAGE, duration=1.0), start=3.0, duration=1.0,
                    overlay_type="transition", transition_name="slideleft",
                    transition_left_id=azul.clip_id, transition_right_id=roxo.clip_id)

    def texto(conteudo: str, inicio: float, duracao: float, y: float, tamanho: int, preset: str) -> Clip:
        return Clip(
            MediaRef(Path(f"Texto_{conteudo[:15]}"), MediaKind.IMAGE, duration=duracao), start=inicio,
            duration=duracao, overlay_type="text", text_content=conteudo, font_family="Sans Serif",
            font_size=tamanho, font_bold=True, text_color="#ffffff", x=0.5, y=y,
            keyframes=create_preset_keyframes(preset, ClipTransform(x=0.5, y=y), duration=0.6),
        )

    icone_gif = Clip(refs["icone.png"], start=0.6, duration=6.4, scale=0.32, x=0.5, y=0.74,
                     keyframes=create_preset_keyframes("spin_in", ClipTransform(x=0.5, y=0.74, scale_x=0.32,
                                                                                  scale_y=0.32), duration=0.8))
    demo = Project(
        tracks=(
            Track(TrackKind.ADDITIONAL, clips=(texto("Video Manager", 0.3, 3.2, 0.4, 110, "zoom_in"),
                                               texto("Baixe · Converta · Edite", 3.7, 3.3, 0.4, 64, "slide_up")),
                  name="Adicionais 1"),
            Track(TrackKind.VIDEO, clips=(icone_gif,), name="Vídeo 2"),
            Track(TrackKind.VIDEO, clips=(azul, passagem, roxo), name="Vídeo 1"),
        ),
        width=1280, height=720, fps=30.0,
    )
    recursos = painel.editor.text_assets(demo)
    para_gif = dataclasses.replace(demo.for_render(640, 360), fps=12.5)
    destino = saida / "demo.gif"
    subprocess.run(export_args(para_gif, destino, ferramentas, container="gif", text_assets=recursos),
                   check=True, timeout=300, **subprocess_kwargs())
    print(f"demo.gif: {destino.stat().st_size / 1024:.0f} KB", flush=True)

    janela.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
