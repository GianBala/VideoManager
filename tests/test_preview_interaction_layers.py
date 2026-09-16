"""Resposta imediata e integridade visual das camadas de interação."""
from dataclasses import replace
from pathlib import Path
import subprocess

import pytest
from PySide6.QtGui import QImage, QPixmap

from videomanager.application.media.interaction import interaction_plan
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.infrastructure.ffmpeg.composer import frame_command, interaction_commands
from videomanager.infrastructure.ffmpeg.preview import _run
from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs
from videomanager.presentation.qt.panels.edit_widgets import _Preview

pytestmark = pytest.mark.usefixtures('desktop_app')


def picture(path, color, w=160, h=90):
    image = QImage(w, h, QImage.Format.Format_RGBA8888)
    image.fill(color)
    assert image.save(str(path))
    return MediaRef(path, MediaKind.IMAGE, width=w, height=h)


def scene(tmp_path):
    from PySide6.QtGui import QColor
    green = Clip(picture(tmp_path / 'green.png', QColor('lime')), 0, 5)
    red = Clip(picture(tmp_path / 'red.png', QColor('red')), 0, 5,
               scale_x=.5, scale_y=.5, opacity=.5)
    blue = Clip(picture(tmp_path / 'blue.png', QColor('blue')), 0, 5,
                scale_x=.2, scale_y=.2)
    project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(blue,)),
                              Track(TrackKind.ADDITIONAL, clips=(red,)),
                              Track(TrackKind.VIDEO, clips=(green,))), width=320, height=180)
    return project, red


def test_plano_estavel_durante_pose_mas_invalidado_por_contexto(tmp_path):
    project, clip = scene(tmp_path)
    plan = interaction_plan(project, clip.clip_id, 1)
    assert plan == interaction_plan(project.with_updated_clip(clip.clip_id, x=.2, rotation=35, opacity=.4), clip.clip_id, 1)
    assert plan != interaction_plan(project, clip.clip_id, 2)
    other = project.tracks[0].clips[0]
    assert plan != interaction_plan(project.with_updated_clip(other.clip_id, x=.1), clip.clip_id, 1)
    effect = Clip(None, 0, 5, overlay_type='filter', filter_name='inverter')
    assert interaction_plan(replace(project, tracks=(Track(TrackKind.ADDITIONAL, clips=(effect,)), *project.tracks)), clip.clip_id, 1) is None
    below = replace(project, tracks=(*project.tracks, Track(TrackKind.ADDITIONAL, clips=(effect,))))
    assert interaction_plan(below, clip.clip_id, 1) is not None


@pytest.mark.ffmpeg
@pytest.mark.parametrize('video', [False, True])
def test_gesto_preserva_fundo_alfa_e_objeto_superior(tmp_path, video):
    tools = find_tools()
    if tools is None:
        pytest.skip('FFmpeg indisponível')
    project, clip = scene(tmp_path)
    if video:
        source = tmp_path / 'red.mp4'
        subprocess.run([tools.ffmpeg_str, '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=red:s=160x90:r=30:d=5', '-c:v', 'libx264', str(source)],
                       check=True, timeout=30, **subprocess_kwargs())
        clip = replace(clip, media=MediaRef(source, MediaKind.VIDEO, width=160, height=90, duration=5))
        project = replace(project, tracks=(project.tracks[0], replace(project.tracks[1], clips=(clip,)), project.tracks[2]))
    size = (640, 360)
    plan = interaction_plan(project, clip.clip_id, 1)
    images = [QPixmap.fromImage(QImage.fromData(_run(c, 30, strict=True)))
              for c in interaction_commands(plan, size, tools)]
    assert all(not p.isNull() for p in images)
    assert images[2].toImage().pixelColor(0, 0).alpha() == 0
    preview = _Preview()
    preview.resize(*size)
    initial = QPixmap.fromImage(QImage.fromData(_run(frame_command(project, 1, size, tools, png=True), 30, strict=True)))
    preview.set_frame_pixmap(initial)
    preview.set_active_clip(clip, project.width, project.height)
    preview.set_position(1)
    preview.set_interaction_layers(tuple(images))
    moved = replace(clip, x=.7)
    preview.set_active_clip(moved, project.width, project.height)
    assert preview.begin_interaction()
    actual = preview.grab().toImage()
    updated = project.with_updated_clip(clip.clip_id, x=.7)
    expected = QImage.fromData(_run(frame_command(updated, 1, size, tools, png=True), 30, strict=True))
    # Interior do canvas, fora das alças: fundo descoberto, frente e alfa móvel.
    for x, y in [(280, 180), (320, 180), (460, 185), (380, 200), (70, 80)]:
        a, b = actual.pixelColor(x, y), expected.pixelColor(x, y)
        assert max(abs(a.red()-b.red()), abs(a.green()-b.green()), abs(a.blue()-b.blue())) <= 4, (video, x, y, a.getRgb(), b.getRgb())
    # Um resultado definitivo substitui o feedback; não há cópia antiga sobreposta.
    preview.set_frame_pixmap(QPixmap.fromImage(expected))
    assert not preview._interaction_visible


def mouse(preview, kind, x, y):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y),
                        Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    if kind == QEvent.Type.MouseButtonPress:
        preview.mousePressEvent(event)
    else:
        preview.mouseMoveEvent(event)


def test_rotacao_interativa_preserva_voltas_e_cruzamento_de_180_graus():
    from PySide6.QtCore import QEvent
    from videomanager.domain.keyframe import Keyframe
    import math
    preview = _Preview(); preview.resize(640, 360); preview.set_frame_pixmap(QPixmap(640, 360))
    clip = Clip(MediaRef(Path('video.mp4'), MediaKind.VIDEO, width=640, height=360), 0, 5,
                scale_x=.3, scale_y=.3, rotation=720,
                keyframes=(Keyframe(0, rotation=720, scale_x=.3, scale_y=.3), Keyframe(4, rotation=1080)))
    preview.set_active_clip(clip, 640, 360); preview.set_snap_enabled(False)
    cx, cy, w, h = preview._clip_geometry(clip)
    radius = h/2+24
    mouse(preview, QEvent.Type.MouseButtonPress, cx, cy-radius)
    assert preview._drag_mode == 'rotate'
    for angle in (-30, 30, 90, 150, 179, -179, -150):
        mouse(preview, QEvent.Type.MouseMove, cx+radius*math.cos(math.radians(angle)),
              cy+radius*math.sin(math.radians(angle)))
    assert preview._active_clip.transform_at(0).rotation == pytest.approx(1020, abs=2)
    assert preview._active_clip.keyframes[-1].rotation == 1080


@pytest.mark.parametrize('large', [False, True])
def test_alca_proporcional_nao_deforma_ao_atingir_limite(large):
    from PySide6.QtCore import QEvent
    preview = _Preview(); preview.resize(640, 360); preview.set_frame_pixmap(QPixmap(640, 360))
    clip = Clip(MediaRef(Path('video.mp4'), MediaKind.VIDEO, width=640, height=360), 0, 5,
                scale_x=.4, scale_y=.2)
    preview.set_active_clip(clip, 640, 360); preview.set_snap_enabled(False)
    cx, cy, w, h = preview._clip_geometry(clip)
    mouse(preview, QEvent.Type.MouseButtonPress, cx+w/2, cy+h/2)
    assert preview._drag_mode == 'scale_br'
    opposite = (cx-w/2, cy-h/2)
    factor = 100 if large else .001
    mouse(preview, QEvent.Type.MouseMove, opposite[0]+w*factor, opposite[1]+h*factor)
    transformed = preview._active_clip
    assert transformed.scale_x / transformed.scale_y == pytest.approx(2)
    assert transformed.scale_x == pytest.approx(10 if large else .1)
    assert transformed.scale_y == pytest.approx(5 if large else .05)


@pytest.mark.ffmpeg
@pytest.mark.parametrize('kind', ['text', 'chroma'])
def test_textura_isolada_preserva_texto_e_chroma(tmp_path, kind):
    from PySide6.QtGui import QColor
    from videomanager.bootstrap import build_editor_service
    tools = find_tools()
    if tools is None:
        pytest.skip('FFmpeg indisponível')
    project, clip = scene(tmp_path)
    if kind == 'text':
        clip = replace(clip, overlay_type='text', text_content='Movimento', font_size=22,
                       scale_x=1, scale_y=1, stroke_width=2)
    else:
        # Chroma aplicado à mídia isolada mantém a transparência ao mover.
        clip = replace(clip, chromakey_enabled=True, chromakey_color='#ff0000')
    project = replace(project, tracks=(project.tracks[0], replace(project.tracks[1], clips=(clip,)), project.tracks[2]))
    service = build_editor_service()
    assets = service.text_assets(project)
    plan = interaction_plan(project, clip.clip_id, 1)
    images = [QImage.fromData(_run(c, 30, strict=True))
              for c in interaction_commands(plan, (640, 360), tools, text_assets=assets)]
    assert all(not im.isNull() for im in images)
    texture = images[1]
    if kind == 'chroma':
        assert texture.pixelColor(texture.width()//2, texture.height()//2).alpha() < 5
    else:
        assert texture.pixelColor(0, 0).alpha() == 0
        assert any(texture.pixelColor(x, y).alpha() > 200
                   for y in range(texture.height()) for x in range(texture.width()))
    # Frente não passa a ter fundo preto opaco quando contém outra camada.
    assert images[2].pixelColor(0, 0) == QColor(0, 0, 0, 0)
