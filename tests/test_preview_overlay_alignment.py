"""Consistência geométrica entre a edição pausada e a reprodução."""

import subprocess
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage, QPixmap

from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import (
    Clip,
    MediaKind,
    MediaRef,
    Project,
    Track,
    TrackKind,
)
from videomanager.infrastructure.ffmpeg.composer import playback_command
from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs
from videomanager.presentation.qt.panels.edit_widgets import _Preview


pytestmark = pytest.mark.usefixtures("desktop_app")


@pytest.mark.ffmpeg
@pytest.mark.parametrize('scale', [.5, .02])
def test_animacao_sutil_de_escala_alinha_alcas_com_pixels_renderizados(tmp_path, scale):
    from videomanager.infrastructure.ffmpeg.composer import frame_command
    from videomanager.infrastructure.ffmpeg.preview import frame_from_command

    tools = find_tools()
    if tools is None:
        pytest.skip('ffmpeg indisponível')
    path = tmp_path / 'branco.png'
    image = QImage(320, 180, QImage.Format.Format_RGB32)
    image.fill(QColor('white'))
    assert image.save(str(path))
    clip = Clip(MediaRef(path, MediaKind.IMAGE, width=320, height=180), 0, 2,
                scale_x=scale, scale_y=scale, keyframes=(
                    Keyframe(0, scale_x=scale, scale_y=scale),
                    Keyframe(2, scale_x=scale+.009, scale_y=scale+.009)))
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(clip,)),), width=320, height=180)
    frame = frame_from_command(frame_command(project, 1, (320, 180), tools), (320, 180))
    assert frame and frame.is_complete
    points = [(x, y) for y in range(180) for x in range(320)
              if frame.data[(y*320+x)*3] > 200]
    left, top = min(x for x, _ in points), min(y for _, y in points)
    width = max(x for x, _ in points) - left + 1
    height = max(y for _, y in points) - top + 1
    preview = _Preview()
    preview.resize(320, 180)
    preview.set_frame_pixmap(QPixmap(320, 180))
    preview.set_active_clip(clip, 320, 180)
    preview.set_position(1)
    cx, cy, w, h = preview._clip_geometry(clip)
    assert (cx-w/2, cy-h/2, w, h) == pytest.approx((left, top, width, height))


def _migrado(clip: Clip, width: int = 1920, height: int = 1080) -> Clip:
    """Clipe de projeto antigo, convertido pela migração do formato 3.

    Os valores destes testes foram escolhidos para cair em casos-limite do
    arredondamento com a imagem no tamanho natural. Migrá-los precisa manter
    os mesmos pixels — e é isso que os testes passam a garantir também.
    """
    legacy = Project(width=width, height=height, tracks=(Track(kind=TrackKind.ADDITIONAL, clips=(clip,)),))
    return legacy.with_images_in_video_tracks(legacy_scale=True).tracks[0].clips[0]


def test_imagem_pausada_respeita_grade_de_pixels_do_ffmpeg() -> None:
    """A imagem não pode saltar ao trocar o desenho do Qt pelo do FFmpeg.

    O filtro overlay do FFmpeg trunca as coordenadas via (int)(x*W - w/2).
    A geometria calculada no preview pausado deve coincidir exatamente com
    a coordenada inteira gerada pelo FFmpeg durante a reprodução.
    """
    x = 0.7665137855377699
    y = 0.16295659828296777
    scale = 0.5776978502158273
    still = Keyframe(
        time_offset=5.0,
        x=x,
        y=y,
        scale_x=scale,
        scale_y=scale,
    )
    clip = Clip(
        media=MediaRef(
            Path("imagem.webp"),
            MediaKind.IMAGE,
            width=1552,
            height=608,
        ),
        start=10.0,
        duration=20.0,
        x=x,
        y=y,
        scale_x=scale,
        scale_y=scale,
        keyframes=(still,),
    )
    clip = _migrado(clip)
    preview = _Preview()
    preview.resize(960, 540)
    preview.set_frame_pixmap(QPixmap(960, 540))
    preview.set_active_clip(clip, 1920, 1080)
    preview.set_position(15.0)

    # Imagem 448x176. No FFmpeg: round(0.766514 * 960 - 224) = round(511.853) = 512.
    # Topo: round(0.162957 * 540 - 88) = round(0.0) = 0.
    # Centro visual: (512 + 224, 0 + 88) = (736, 88).
    transform = clip.transform_at(5.0)
    geometry = preview._image_overlay_geometry(
        clip, transform, preview._video_rect()
    )
    assert geometry == pytest.approx((736, 88, 448, 176))


def test_imagem_pausada_coincide_com_frame_real_do_ffmpeg(tmp_path: Path) -> None:
    """Valida contra os pixels reais emitidos pelo binário do FFmpeg."""
    tools = find_tools()
    if tools is None:
        pytest.skip("ffmpeg indisponível")

    x = 0.7665137855377699
    y = 0.16295659828296777
    scale = 0.5776978502158273

    img_path = tmp_path / "test_img.png"
    img = QImage(1552, 608, QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 255, 255, 255))
    img.save(str(img_path))

    still = Keyframe(
        time_offset=5.0,
        x=x,
        y=y,
        scale_x=scale,
        scale_y=scale,
    )
    clip = Clip(
        media=MediaRef(img_path, MediaKind.IMAGE, width=1552, height=608),
        start=10.0,
        duration=20.0,
        x=x,
        y=y,
        scale_x=scale,
        scale_y=scale,
        keyframes=(still,),
    )
    clip = _migrado(clip)
    proj = Project(
        width=1920,
        height=1080,
        tracks=(Track(kind=TrackKind.VIDEO, clips=(clip,)),),
    )

    preview = _Preview()
    preview.resize(960, 540)
    preview.set_frame_pixmap(QPixmap(960, 540))
    preview.set_active_clip(clip, 1920, 1080)
    preview.set_position(15.0)

    transform = clip.transform_at(5.0)
    vrect = preview._video_rect()
    geom = preview._image_overlay_geometry(clip, transform, vrect)
    geom_left = round(geom[0] - geom[2] / 2.0)
    geom_top = round(geom[1] - geom[3] / 2.0)
    geom_w = round(geom[2])
    geom_h = round(geom[3])

    cmd = playback_command(proj, at=15.0, size=(960, 540), tools=tools, fps=30)
    proc = subprocess.Popen(cmd, **subprocess_kwargs())
    try:
        raw_frame = proc.stdout.read(960 * 540 * 3)
    finally:
        proc.kill()

    assert len(raw_frame) == 960 * 540 * 3
    ff_img = QImage(raw_frame, 960, 540, 960 * 3, QImage.Format.Format_RGB888)
    xs = [px for py in range(540) for px in range(960) if ff_img.pixelColor(px, py).red() > 200]
    ys = [py for py in range(540) for px in range(960) if ff_img.pixelColor(px, py).red() > 200]

    ff_left = min(xs)
    ff_top = min(ys)
    ff_w = max(xs) - min(xs) + 1
    ff_h = max(ys) - min(ys) + 1

    assert (ff_left, ff_top, ff_w, ff_h) == (geom_left, geom_top, geom_w, geom_h)


def test_animacao_quadros_chave_coincide_com_ffmpeg(tmp_path: Path) -> None:
    """Valida que animações com interpolação de quadros-chave coincidem pixel a pixel."""
    tools = find_tools()
    if tools is None:
        pytest.skip("ffmpeg indisponível")

    img_path = tmp_path / "anim_img.png"
    img = QImage(400, 300, QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 0, 0, 255))
    img.save(str(img_path))

    kf0 = Keyframe(time_offset=0.0, x=0.2, y=0.2, scale_x=1.0, scale_y=1.0)
    kf1 = Keyframe(time_offset=4.0, x=0.8, y=0.8, scale_x=1.0, scale_y=1.0)
    clip = Clip(
        media=MediaRef(img_path, MediaKind.IMAGE, width=400, height=300),
        start=0.0,
        duration=10.0,
        x=0.2,
        y=0.2,
        scale_x=1.0,
        scale_y=1.0,
        keyframes=(kf0, kf1),
    )
    clip = _migrado(clip)
    proj = Project(
        width=1920,
        height=1080,
        tracks=(Track(kind=TrackKind.VIDEO, clips=(clip,)),),
    )

    pw, ph = 960, 540
    # Testar pontos com frações arbitrárias e transições (ex: 0.0, 1.5, 3.0, 3.5)
    for at in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0):
        preview = _Preview()
        preview.resize(pw, ph)
        preview.set_frame_pixmap(QPixmap(pw, ph))
        preview.set_active_clip(clip, 1920, 1080)
        preview.set_position(at)

        transform = clip.transform_at(at)
        vrect = preview._video_rect()
        geom = preview._image_overlay_geometry(clip, transform, vrect)
        geom_left = round(geom[0] - geom[2] / 2.0)
        geom_top = round(geom[1] - geom[3] / 2.0)
        geom_w = round(geom[2])
        geom_h = round(geom[3])

        cmd = playback_command(proj, at=at, size=(pw, ph), tools=tools, fps=30)
        proc = subprocess.Popen(cmd, **subprocess_kwargs())
        try:
            raw_frame = proc.stdout.read(pw * ph * 3)
        finally:
            proc.kill()

        assert len(raw_frame) == pw * ph * 3
        ff_img = QImage(raw_frame, pw, ph, pw * 3, QImage.Format.Format_RGB888)
        xs = [px for py in range(ph) for px in range(pw) if ff_img.pixelColor(px, py).red() > 200 and ff_img.pixelColor(px, py).blue() < 50]
        ys = [py for py in range(ph) for px in range(pw) if ff_img.pixelColor(px, py).red() > 200 and ff_img.pixelColor(px, py).blue() < 50]

        ff_left = min(xs)
        ff_top = min(ys)
        ff_w = max(xs) - min(xs) + 1
        ff_h = max(ys) - min(ys) + 1

        assert (ff_left, ff_top, ff_w, ff_h) == (geom_left, geom_top, geom_w, geom_h), f"Mismatch at at={at}"


def test_texto_pequeno_nao_recebe_minimo_de_tamanho_visual():
    text = Clip(MediaRef(Path('Texto'), MediaKind.IMAGE), 0, 5, overlay_type='text',
                text_content='a', font_size=10)
    preview = _Preview()
    preview.resize(320, 180)
    pixmap = QPixmap(320, 180)
    pixmap.fill(QColor('black'))
    preview.set_frame_pixmap(pixmap)
    preview.set_active_clip(text, 1920, 1080)
    geometry = preview._clip_geometry(text)
    assert geometry and geometry[2] < 20 and geometry[3] < 20
