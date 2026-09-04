"""Testes de interface para trilha de adicionais, painel de extras, popups e preview."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from videomanager.core.binaries import FFmpegTools
from videomanager.core.project import (
    IMAGE_DURATION,
    Clip,
    MediaKind,
    MediaRef,
    TrackKind,
)
from videomanager.core.settings import Settings
from videomanager.ui.panels.edit_panel import EditPanel, _Preview, _SpeedPopup, _VolumePopup


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def dummy_tools() -> FFmpegTools:
    return FFmpegTools(
        ffmpeg=Path("/bin/ffmpeg"),
        ffprobe=Path("/bin/ffprobe"),
        source="system",
    )


def test_extras_box_text_and_filter_insertion(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        # Insere clipe de texto
        panel._text_input.setText("Olá Mundo")
        panel._font_size_spin.setValue(40)
        panel._bold_btn.setChecked(True)
        panel._set_text_color("#ff0000")
        panel._insert_text_clip()

        assert len(panel._project.additional_tracks) == 1
        add_track = panel._project.additional_tracks[0]
        assert len(add_track.clips) == 1
        clip = add_track.clips[0]
        assert clip.overlay_type == "text"
        assert clip.text_content == "Olá Mundo"
        assert clip.font_size == 40
        assert clip.font_bold is True
        assert clip.text_color == "#ff0000"
        assert clip.is_additional is True

        # Insere filtro
        panel._select_filter("sepia")
        panel._filter_dur.setValue(7.5)
        panel._insert_filter_clip("sepia")

        # Verifica se o filtro foi colocado na trilha de adicionais
        total_clips = sum(len(t.clips) for t in panel._project.additional_tracks)
        assert total_clips == 2
        filter_clip = [c for t in panel._project.additional_tracks for c in t.clips if c.overlay_type == "filter"][0]
        assert filter_clip.filter_name == "sepia"
        assert filter_clip.duration == 7.5
    finally:
        panel.shutdown()


def test_image_inserted_into_additional_track(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        img_ref = MediaRef(
            path=Path("/tmp/foto.png"),
            kind=MediaKind.IMAGE,
            width=800,
            height=600,
        )
        panel._pool.append(img_ref)
        panel._insert_media_ref(img_ref)

        assert len(panel._project.additional_tracks) >= 1
        add_clip = panel._project.additional_tracks[0].clips[0]
        assert add_clip.media.kind is MediaKind.IMAGE
        assert add_clip.is_additional is True
    finally:
        panel.shutdown()


def test_speed_adjustment_and_popups(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        vid_ref = MediaRef(
            path=Path("/tmp/video.mp4"),
            kind=MediaKind.VIDEO,
            duration=10.0,
            width=1920,
            height=1080,
            fps=30.0,
        )
        panel._pool.append(vid_ref)
        panel._insert_media_ref(vid_ref)

        clip = panel._project.clips[0]
        panel._timeline.select(clip.clip_id)

        # Testa ajuste de velocidade para 2.0x
        panel._on_speed(2.0)
        updated = panel._project.find(clip.clip_id)[1]
        assert updated.speed == 2.0
        assert updated.duration == pytest.approx(5.0, abs=0.01)

        # Testa ajuste de velocidade para 0.5x
        panel._on_speed(0.5)
        updated_half = panel._project.find(clip.clip_id)[1]
        assert updated_half.speed == 0.5
        assert updated_half.duration == pytest.approx(20.0, abs=0.01)

        # Testa popups
        vol_popup = _VolumePopup(0.0)
        assert vol_popup._spin.value() == 0.0
        vol_popup._spin.setValue(3.5)

        spd_popup = _SpeedPopup(1.0)
        assert spd_popup._spin.value() == 1.0
        spd_popup._spin.setValue(1.5)
    finally:
        panel.shutdown()


def test_preview_interactive_transform(qapp: QApplication) -> None:
    preview = _Preview()
    preview.resize(800, 600)
    ref = MediaRef(
        path=Path("/tmp/overlay.png"),
        kind=MediaKind.IMAGE,
        width=400,
        height=300,
    )
    clip = Clip(
        media=ref,
        start=0.0,
        duration=5.0,
        overlay_type="image",
        x=0.5,
        y=0.5,
        scale=1.0,
        rotation=0.0,
    )
    preview.set_active_clip(clip, 1920, 1080)
    preview.set_position(1.0)

    # Hit test no centro (mover)
    geom = preview._clip_geometry(clip)
    assert geom is not None
    cx, cy, w, h = geom
    mode, _ = preview._hit_test(QPoint(int(cx), int(cy)))
    assert mode == "move"

    # Hit test na alça de rotação (haste no topo)
    mode_rot, _ = preview._hit_test(QPoint(int(cx), int(cy - h / 2 - 24)))
    assert mode_rot == "rotate"

    # Hit test na alça de canto (redimensionar)
    mode_scale, _ = preview._hit_test(QPoint(int(cx - w / 2), int(cy - h / 2)))
    assert mode_scale == "scale"

    # Simula arraste para mover
    press_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(cx, cy),
        QPointF(cx, cy),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mousePressEvent(press_ev)
    assert preview._drag_mode == "move"

    # Move 50px para a direita
    move_ev = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(cx + 50, cy),
        QPointF(cx + 50, cy),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_ev)
    assert preview._active_clip.x > 0.5

    release_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(cx + 50, cy),
        QPointF(cx + 50, cy),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseReleaseEvent(release_ev)
    assert preview._drag_mode is None
