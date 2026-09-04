"""Testes de interface para trilha de adicionais, painel de extras, popups e preview."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from videomanager.core.binaries import FFmpegTools
from videomanager.core.project import (
    IMAGE_DURATION,
    Clip,
    MediaKind,
    MediaRef,
    TrackKind,
)
from videomanager.core.settings import Settings
from videomanager.ui import strings
from videomanager.ui.panels.edit_panel import EditPanel, _Preview, _SpeedPopup, _VolumePopup


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)


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


def test_font_selector_widget(qapp: QApplication) -> None:
    from videomanager.ui.panels.edit_panel import _FontSelectorWidget

    selector = _FontSelectorWidget("Sans Serif")
    assert selector.current_family() == "Sans Serif"
    assert not selector._expanded

    selector._toggle_list()
    assert selector._expanded
    assert not selector._list_container.isHidden()

    changed_fonts: list[str] = []
    selector.font_changed.connect(changed_fonts.append)

    # Simula escolha de fonte
    if selector._font_list.count() > 1:
        target_item = selector._font_list.item(1)
        target_name = target_item.text()
        selector._on_item_clicked(target_item)
        assert selector.current_family() == target_name
        assert not selector._expanded
        assert changed_fonts == [target_name]


def test_bidirectional_text_and_filter_editing(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        # 1. Inserção de texto inicial
        panel._text_input.setText("Legenda Original")
        panel._font_size_spin.setValue(32)
        panel._bold_btn.setChecked(False)
        panel._insert_text_clip()

        track = panel._project.additional_tracks[0]
        text_clip = track.clips[0]
        assert text_clip.text_content == "Legenda Original"

        # 2. Seleciona o clipe na timeline e verifica se a interface sincroniza
        panel._timeline.select(text_clip.clip_id)
        panel._refresh_clip_fields()

        assert panel._text_input.text() == "Legenda Original"
        assert panel._font_size_spin.value() == 32
        assert panel._insert_text_btn.text() == strings.EDIT_UPDATE_TEXT
        assert not panel._insert_new_text_btn.isHidden()

        # 3. Edita o texto selecionado
        panel._text_input.setText("Legenda Modificada")
        panel._font_size_spin.setValue(48)
        panel._bold_btn.setChecked(True)
        panel._handle_insert_or_update_text()

        updated_clip = panel._project.find(text_clip.clip_id)[1]
        assert updated_clip.text_content == "Legenda Modificada"
        assert updated_clip.font_size == 48
        assert updated_clip.font_bold is True

        # 4. Inserção de Filtro e edição bidirecional
        panel._select_filter("pb")
        panel._filter_dur.setValue(4.0)
        panel._insert_filter_clip("pb")

        filter_clip = [c for t in panel._project.additional_tracks for c in t.clips if c.overlay_type == "filter"][0]
        assert filter_clip.filter_name == "pb"

        # Seleciona filtro na timeline
        panel._timeline.select(filter_clip.clip_id)
        panel._refresh_clip_fields()

        assert panel._selected_filter_name == "pb"
        assert panel._filter_dur.value() == 4.0
        assert panel._apply_filter_btn.text() == strings.EDIT_UPDATE_FILTER
        assert not panel._insert_new_filter_btn.isHidden()

        # Altera para sépia e atualiza
        panel._select_filter("sepia")
        panel._filter_dur.setValue(6.0)
        panel._handle_apply_or_update_filter()

        updated_filter = panel._project.find(filter_clip.clip_id)[1]
        assert updated_filter.filter_name == "sepia"
        assert updated_filter.duration == 6.0
    finally:
        panel.shutdown()


def test_media_cleanup_restriction_and_clear_unused(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        ref_used = MediaRef(path=Path("/tmp/used.mp4"), kind=MediaKind.VIDEO, duration=10.0)
        ref_unused = MediaRef(path=Path("/tmp/unused.mp4"), kind=MediaKind.VIDEO, duration=5.0)

        panel._pool.append(ref_used)
        panel._pool.append(ref_unused)
        panel._refresh_pool()
        assert len(panel._pool) == 2

        # Insere apenas ref_used na timeline
        panel._insert_media_ref(ref_used)
        assert len(panel._project.clips) == 1

        # Tenta remover ref_used: deve ser bloqueado porque está em uso
        panel._remove_media_ref(ref_used)
        assert ref_used in panel._pool

        # Limpar mídias não usadas deve remover ref_unused e manter ref_used
        panel._clear_unused_media()
        assert len(panel._pool) == 1
        assert panel._pool[0] == ref_used

        # Ao remover da timeline o clipe, agora pode ser removido da biblioteca
        panel._project = panel._project.without_clip(panel._project.clips[0].clip_id)
        panel._remove_media_ref(ref_used)
        assert len(panel._pool) == 0
    finally:
        panel.shutdown()


def test_project_lifecycle_media_management(qapp: QApplication, dummy_tools: FFmpegTools, tmp_path: Path) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        sample_file = tmp_path / "sample.mp4"
        sample_file.write_bytes(b"dummy")
        ref = MediaRef(path=sample_file, kind=MediaKind.VIDEO, duration=8.0)
        panel._pool.append(ref)
        panel._insert_media_ref(ref)
        assert len(panel._pool) == 1

        # Salva o projeto
        proj_file = tmp_path / "teste_projeto.vmp"
        panel._project_path = proj_file
        panel.save_project()

        # Iniciar novo projeto deve limpar o acervo de mídias
        panel._is_dirty = False
        panel.new_project()
        assert len(panel._pool) == 0
        assert panel._media_list.count() == 0

        # Abrir projeto existente deve resgatar as mídias para a aba "Mídia do projeto"
        panel.open_project(proj_file)
        assert len(panel._pool) == 1
        assert panel._pool[0].path == sample_file
        assert panel._media_list.count() == 1
    finally:
        panel.shutdown()


def test_loop_playback_logic(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        ref = MediaRef(path=Path("/tmp/loop_test.mp4"), kind=MediaKind.VIDEO, duration=4.0)
        panel._pool.append(ref)
        panel._insert_media_ref(ref)

        clip = panel._project.clips[0]
        # Acelera clipe para 2.0x (duração efetiva = 2.0s)
        panel._timeline.select(clip.clip_id)
        panel._on_speed(2.0)

        panel._loop.setChecked(True)
        # Mock de reprodução ativa
        panel._playing = True
        panel._play_token = 42

        # Perto do fim da timeline (ex: 1.95s com threshold de fim)
        panel._timeline.set_position(1.98)
        looped = False

        def mock_loop():
            nonlocal looped
            looped = True

        panel._loop_playback = mock_loop
        panel._on_tick()
        assert looped is True
    finally:
        panel.shutdown()

