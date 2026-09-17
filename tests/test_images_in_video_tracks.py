"""Imagens como parte da trilha de vídeo, como nos editores atuais.

Antes uma foto só podia viver em trilha de Adicionais e aparecia no tamanho
natural (reduzida se passasse da tela, nunca ampliada). Agora ela entra na
trilha de vídeo e se ajusta à tela como um vídeo. Projetos antigos são migrados
convertendo a escala, para a foto continuar no mesmo lugar e do mesmo tamanho.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.domain.geometry import image_base_size, natural_image_size
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import (
    Clip, MediaKind, MediaRef, Project, Track, TrackKind, accepts, auto_canvas, new_project,
)

FOTO = MediaRef(Path("/m/foto.png"), MediaKind.IMAGE, width=400, height=300)
VIDEO = MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=10, width=1280, height=720, fps=30)
SOM = MediaRef(Path("/m/som.mp3"), MediaKind.AUDIO, duration=10, has_audio=True, channels=2)
TEXTO = MediaRef(Path("Texto"), MediaKind.IMAGE)


class TestOndeCadaBlocoVive:
    def test_imagem_vai_para_trilha_de_video(self) -> None:
        foto = Clip(FOTO, 0, 5)
        assert accepts(TrackKind.VIDEO, foto)
        assert not accepts(TrackKind.ADDITIONAL, foto)

    @pytest.mark.parametrize("kind", ["text", "filter"])
    def test_texto_e_filtro_continuam_nos_adicionais(self, kind) -> None:
        item = Clip(TEXTO, 0, 5, overlay_type=kind, text_content="Oi", filter_name="pb")
        assert accepts(TrackKind.ADDITIONAL, item)
        assert not accepts(TrackKind.VIDEO, item)
        assert item.is_overlay

    def test_transicao_video_e_audio_nao_mudam(self) -> None:
        marker = Clip(TEXTO, 0, 1, overlay_type="transition")
        assert accepts(TrackKind.VIDEO, marker) and not accepts(TrackKind.ADDITIONAL, marker)
        assert accepts(TrackKind.VIDEO, Clip(VIDEO, 0, 5))
        assert accepts(TrackKind.AUDIO, Clip(SOM, 0, 5)) and not accepts(TrackKind.VIDEO, Clip(SOM, 0, 5))
        assert not Clip(FOTO, 0, 5).is_overlay

    def test_projeto_novo_com_foto_usa_a_trilha_de_video(self) -> None:
        project = new_project(FOTO)
        assert [t.kind for t in project.tracks] == [TrackKind.VIDEO, TrackKind.AUDIO]
        assert project.tracks[0].clips[0].media is FOTO

    def test_foto_na_trilha_de_video_nao_define_a_tela(self) -> None:
        project = auto_canvas(Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(FOTO, 0, 5),)),)))
        assert (project.width, project.height) == (1920, 1080)
        mixed = auto_canvas(Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(FOTO, 0, 5), Clip(VIDEO, 5, 5))),)))
        assert (mixed.width, mixed.height) == (1280, 720)


class TestTamanho:
    def test_imagem_pequena_amplia_ate_a_tela(self) -> None:
        assert image_base_size(400, 300, 1920, 1080) == (1440, 1080)

    def test_imagem_grande_reduz_como_antes(self) -> None:
        assert image_base_size(4000, 3000, 1920, 1080) == natural_image_size(4000, 3000, 1920, 1080)

    def test_tamanho_natural_nunca_amplia(self) -> None:
        assert natural_image_size(400, 300, 1920, 1080) == (400, 300)


def _legado(*clips: Clip, width: int = 1920, height: int = 1080) -> Project:
    return Project(tracks=(Track(TrackKind.ADDITIONAL, clips=clips, name="Adicionais 1"),
                           Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 0, 10),), name="Vídeo 1")),
                   width=width, height=height)


class TestMigracao:
    def test_trilha_so_de_imagens_vira_trilha_de_video_com_a_mesma_aparencia(self) -> None:
        foto = Clip(FOTO, 1, 4, x=.3, y=.4, scale=.5, scale_x=.5, scale_y=.5,
                    keyframes=(Keyframe(0, scale_x=.5, scale_y=.5), Keyframe(2, scale_x=1, scale_y=1)))
        project = _legado(foto)
        track_id = project.tracks[0].track_id
        migrated = project.with_images_in_video_tracks(legacy_scale=True)
        track = migrated.tracks[0]
        assert track.kind is TrackKind.VIDEO and track.track_id == track_id
        moved = track.clips[0]
        assert moved.clip_id == foto.clip_id and (moved.x, moved.y) == (.3, .4)
        base_w, base_h = image_base_size(400, 300, 1920, 1080)
        old_w, old_h = natural_image_size(400, 300, 1920, 1080)
        assert round(base_w * moved.scale_x) == round(old_w * .5)
        assert round(base_h * moved.scale_y) == round(old_h * .5)
        assert round(base_w * moved.keyframes[1].scale_x) == old_w
        assert migrated.tracks[0].name == "Vídeo 2"

    def test_trilha_mista_ganha_trilha_de_video_acima(self) -> None:
        foto = Clip(FOTO, 0, 2)
        texto = Clip(TEXTO, 3, 2, overlay_type="text", text_content="Oi")
        migrated = _legado(foto, texto).with_images_in_video_tracks(legacy_scale=True)
        kinds = [t.kind for t in migrated.tracks]
        assert kinds == [TrackKind.VIDEO, TrackKind.ADDITIONAL, TrackKind.VIDEO]
        assert [c.clip_id for c in migrated.tracks[0].clips] == [foto.clip_id]
        assert [c.clip_id for c in migrated.tracks[1].clips] == [texto.clip_id]

    def test_sem_escala_legada_so_muda_de_trilha(self) -> None:
        foto = Clip(FOTO, 0, 2, scale_x=.7, scale_y=.7, scale=.7)
        migrated = _legado(foto).with_images_in_video_tracks(legacy_scale=False)
        assert migrated.tracks[0].clips[0].scale_x == .7

    def test_projeto_sem_imagem_em_adicionais_e_o_mesmo(self) -> None:
        project = _legado(Clip(TEXTO, 0, 2, overlay_type="text", text_content="Oi"))
        assert project.with_images_in_video_tracks(legacy_scale=True) is project

    def test_imagem_maior_que_a_tela_nao_muda_escala(self) -> None:
        grande = replace(FOTO, width=4000, height=3000)
        foto = Clip(grande, 0, 2, scale_x=.8, scale_y=.8, scale=.8)
        migrated = _legado(foto).with_images_in_video_tracks(legacy_scale=True)
        assert migrated.tracks[0].clips[0].scale_x == pytest.approx(.8)


class TestArquivo:
    def _documento_v2(self, tmp_path: Path) -> Path:
        from videomanager.infrastructure.storage.project_json import project_to_dict
        data = project_to_dict(_legado(Clip(FOTO, 0, 2, scale_x=1, scale_y=1)), base_dir=tmp_path)
        data["version"] = 2
        path = tmp_path / "antigo.vmp"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_abrir_v2_migra_e_salvar_grava_v3_com_copia(self, tmp_path) -> None:
        from videomanager.infrastructure.storage.project_json import load_project, save_project
        path = self._documento_v2(tmp_path)
        original = path.read_bytes()
        project, _ = load_project(path)
        assert project.tracks[0].kind is TrackKind.VIDEO
        assert project.tracks[0].clips[0].scale_x == pytest.approx(400 / 1440)
        save_project(project, path)
        assert json.loads(path.read_text(encoding="utf-8"))["version"] == 3
        assert (tmp_path / "antigo.vmp.v2.bak").read_bytes() == original
        again, _ = load_project(path)
        assert again.tracks[0].clips[0].scale_x == pytest.approx(400 / 1440)


def test_painel_insere_foto_na_trilha_de_video_e_sem_velocidade(desktop_app, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.panels.edit_panel import EditPanel

    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    panel = EditPanel(Settings(), ensure_tools=lambda: None, editor=build_editor_service(),
                      processing=build_processing_service(), runtime=build_desktop_runtime(audio_enabled=False))
    try:
        panel._place(FOTO, at=0)
        found = panel._project.find(panel._timeline.selected)
        assert found is not None and panel._project.tracks[found[0]].kind is TrackKind.VIDEO
        panel._refresh_controls()
        assert not panel._speed_btn.isEnabled()
    finally:
        panel.shutdown()


# --- integração com ffmpeg ---------------------------------------------------

@pytest.fixture
def ffmpeg(tmp_path):
    from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs
    tools = find_tools()
    if tools is None:
        pytest.skip("ffmpeg/ffprobe indisponíveis")

    def run(*args):
        subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", *map(str, args)],
                       check=True, timeout=30, **subprocess_kwargs())
    return tools, run


def _red_box(frame, width: int, height: int) -> tuple[int, int]:
    """Largura e altura da região vermelha no quadro rgb24."""
    data = frame.data
    xs, ys = [], []
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            r, g, b = data[(y * width + x) * 3:(y * width + x) * 3 + 3]
            if r > 180 and g < 80 and b < 80:
                xs.append(x)
                ys.append(y)
    return (max(xs) - min(xs) + 2, max(ys) - min(ys) + 2) if xs else (0, 0)


@pytest.mark.ffmpeg
def test_foto_nova_preenche_a_altura_da_tela(ffmpeg, tmp_path) -> None:
    from videomanager.infrastructure.ffmpeg.composer import frame_command
    from videomanager.infrastructure.ffmpeg.preview import frame_from_command

    tools, run = ffmpeg
    png = tmp_path / "vermelho.png"
    run("-f", "lavfi", "-i", "color=c=red:s=80x60", "-frames:v", "1", png)
    foto = MediaRef(png, MediaKind.IMAGE, width=80, height=60)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(foto, 0, 2),)),), width=320, height=180, fps=25)
    frame = frame_from_command(frame_command(project, .5, (320, 180), tools), (320, 180))
    assert frame is not None and frame.is_complete
    w, h = _red_box(frame, 320, 180)
    assert h >= 176 and 236 <= w <= 244


@pytest.mark.ffmpeg
def test_projeto_antigo_com_foto_pequena_mantem_o_tamanho(ffmpeg, tmp_path) -> None:
    from videomanager.infrastructure.ffmpeg.composer import frame_command
    from videomanager.infrastructure.ffmpeg.preview import frame_from_command
    from videomanager.infrastructure.storage.project_json import load_project, project_to_dict

    tools, run = ffmpeg
    png = tmp_path / "vermelho.png"
    run("-f", "lavfi", "-i", "color=c=red:s=80x60", "-frames:v", "1", png)
    foto = MediaRef(png, MediaKind.IMAGE, width=80, height=60)
    legacy = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(Clip(foto, 0, 2, x=.3, y=.5),)),),
                     width=320, height=180, fps=25)
    data = project_to_dict(legacy, base_dir=tmp_path)
    data["version"] = 2
    path = tmp_path / "antigo.vmp"
    path.write_text(json.dumps(data), encoding="utf-8")
    project, _ = load_project(path)
    frame = frame_from_command(frame_command(project, .5, (320, 180), tools), (320, 180))
    assert frame is not None and frame.is_complete
    w, h = _red_box(frame, 320, 180)
    assert 76 <= w <= 84 and 56 <= h <= 64


@pytest.mark.ffmpeg
def test_transicao_entre_foto_e_video_na_mesma_trilha(ffmpeg, tmp_path) -> None:
    from videomanager.infrastructure.ffmpeg.composer import frame_command
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.ffmpeg.preview import frame_from_command
    from videomanager.domain.project import media_ref

    tools, run = ffmpeg
    png, blue = tmp_path / "vermelho.png", tmp_path / "azul.mp4"
    run("-f", "lavfi", "-i", "color=c=red:s=160x90", "-frames:v", "1", png)
    run("-f", "lavfi", "-i", "color=c=blue:s=160x90:r=25:d=4", "-c:v", "libx264", blue)
    left = Clip(MediaRef(png, MediaKind.IMAGE, width=160, height=90), 0, 2)
    right = Clip(media_ref(probe_file(blue, tools)), 2, 2)
    marker = Clip(MediaRef(Path("Transição_x"), MediaKind.IMAGE), 1.5, 1, overlay_type="transition",
                  transition_name="fade", transition_left_id=left.clip_id, transition_right_id=right.clip_id)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(left, right, marker)),), width=160, height=90, fps=25)
    assert project.transition_contexts(), "foto e vídeo encostados formam um corte"
    frame = frame_from_command(frame_command(project, 2.0, (160, 90), tools), (160, 90))
    assert frame is not None and frame.is_complete
    r, g, b = frame.data[(45 * 160 + 80) * 3:(45 * 160 + 80) * 3 + 3]
    assert r > 60 and b > 60, "no meio da transição as duas imagens se misturam"
