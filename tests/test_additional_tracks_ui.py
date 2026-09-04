"""Testes de interface para trilha de adicionais, painel de extras, popups e preview."""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QMessageBox

from videomanager.core.binaries import FFmpegTools
from videomanager.core.project import (
    Clip,
    MediaKind,
    MediaRef,
)
from videomanager.core.settings import Settings
from videomanager.ui import strings
from videomanager.ui.panels.edit_panel import (
    EditPanel,
    _FontSelectorWidget,
    _Preview,
    _SpeedPopup,
    _VolumePopup,
)


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

    # Hit test nas alças de canto (redimensionar com cantos identificados)
    mode_tl, _ = preview._hit_test(QPoint(int(cx - w / 2), int(cy - h / 2)))
    assert mode_tl == "scale_tl"
    mode_tr, _ = preview._hit_test(QPoint(int(cx + w / 2), int(cy - h / 2)))
    assert mode_tr == "scale_tr"
    mode_br, _ = preview._hit_test(QPoint(int(cx + w / 2), int(cy + h / 2)))
    assert mode_br == "scale_br"
    mode_bl, _ = preview._hit_test(QPoint(int(cx - w / 2), int(cy + h / 2)))
    assert mode_bl == "scale_bl"

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


def test_media_list_delete_shortcut_and_context_menu(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        ref1 = MediaRef(path=Path("/tmp/media1.mp4"), kind=MediaKind.VIDEO, duration=5.0)
        ref2 = MediaRef(path=Path("/tmp/media2.mp4"), kind=MediaKind.VIDEO, duration=5.0)
        panel._pool.extend([ref1, ref2])
        panel._refresh_pool()
        assert len(panel._pool) == 2
        assert panel._media_list.count() == 2

        # 1. Test context menu text is "Deletar  (Del)"
        assert strings.EDIT_MEDIA_REMOVE == "Deletar  (Del)"

        # 2. Test deleting selected item with focus on _media_list
        panel._media_list.setCurrentRow(0)
        panel._media_list.setFocus()
        panel._delete_selected()

        assert len(panel._pool) == 1
        assert panel._pool[0].path == Path("/tmp/media2.mp4")
        assert panel._media_list.count() == 1
    finally:
        panel.shutdown()


def test_font_selector_popular_fonts_and_search(qapp: QApplication) -> None:
    selector = _FontSelectorWidget("Sans Serif")
    # Verify popular fonts exist
    items = [selector._font_list.item(i).text() for i in range(selector._font_list.count())]
    assert "Arial" in items
    assert "Comic Sans MS" in items
    assert "Times New Roman" in items

    # Test filtering
    selector._filter_fonts("Comic")
    visible = [
        selector._font_list.item(i).text()
        for i in range(selector._font_list.count())
        if not selector._font_list.item(i).isHidden()
    ]
    assert "Comic Sans MS" in visible
    assert "Arial" not in visible

    # Test clear filter
    selector._filter_fonts("")
    visible_all = [
        selector._font_list.item(i).text()
        for i in range(selector._font_list.count())
        if not selector._font_list.item(i).isHidden()
    ]
    assert len(visible_all) == len(items)


def test_font_size_controls_and_presets(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        text_tab = panel._extras_tabs.widget(0)
        button_texts = {b.text() for b in text_tab.findChildren(type(panel._bold_btn))}

        # Presets 18, 24, 36, 48, 64, 72 must be present
        presets = {"18", "24", "36", "48", "64", "72"}
        assert presets.issubset(button_texts)

        # Spinbox must have no built-in stacked arrows
        assert panel._font_size_spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons

        # Check increment and decrement buttons
        dec_btns = [b for b in text_tab.findChildren(type(panel._bold_btn)) if b.text() == "-"]
        inc_btns = [b for b in text_tab.findChildren(type(panel._bold_btn)) if b.text() == "+"]
        assert len(dec_btns) == 1
        assert len(inc_btns) == 1
        assert "color: #ffffff" in dec_btns[0].styleSheet()
        assert "color: #ffffff" in inc_btns[0].styleSheet()

        # Step is 1 pt
        initial_val = panel._font_size_spin.value()
        inc_btns[0].click()
        assert panel._font_size_spin.value() == initial_val + 1
        dec_btns[0].click()
        assert panel._font_size_spin.value() == initial_val

        # Clicking a preset sets the spinbox value directly
        btn_36 = [b for b in text_tab.findChildren(type(panel._bold_btn)) if b.text() == "36"][0]
        btn_36.click()
        assert panel._font_size_spin.value() == 36
    finally:
        panel.shutdown()


def test_preview_ghost_avoidance_and_playback_state(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        # Insere clipe de texto na trilha de adicionais
        panel._text_input.setText("Overlay Text")
        panel._insert_text_clip()
        track = panel._project.additional_tracks[0]
        text_clip = track.clips[0]

        # Com o clipe selecionado, o projeto a ser renderizado no fundo exclui o clipe ativo
        panel._timeline.select(text_clip.clip_id)
        active = panel._timeline.selected_clip
        assert active is not None
        assert active.clip_id == text_clip.clip_id

        # Verifica se without_clip exclui o clipe selecionado
        proj_without = panel._project.without_clip(active.clip_id)
        assert proj_without.find(active.clip_id) is None

        # Deseleciona
        panel._timeline.select(-1)
        assert panel._timeline.selected_clip is None

        # Testa estado de playback no preview
        assert not panel._preview._is_playing
        panel._preview.set_playing(True)
        assert panel._preview._is_playing
        panel._preview.set_playing(False)
        assert not panel._preview._is_playing
    finally:
        panel.shutdown()


def test_filter_selection_highlight_style(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        # Check stylesheet of filter buttons
        for btn in panel._filter_buttons:
            style = btn.styleSheet()
            # Must have light blue border on checked
            assert "border: 2px solid #38bdf8" in style
            # Must NOT paint entire background purple
            assert "#7b1fa2" not in style
            assert "#9c27b0" not in style
    finally:
        panel.shutdown()


def test_text_stroke_controls_and_bidirectional_sync(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        # 1. Configura texto com contorno ativo
        panel._text_input.setText("Texto com Borda")
        panel._stroke_checkbox.setChecked(True)
        panel._stroke_spin.setValue(5)
        panel._set_stroke_color("#e11d48")
        panel._insert_text_clip()

        track = panel._project.additional_tracks[0]
        clip = track.clips[0]
        assert clip.stroke_width == 5
        assert clip.stroke_color == "#e11d48"

        # 2. Deseleciona e seleciona novamente para testar sincronização na UI
        panel._timeline.select(-1)
        panel._timeline.select(clip.clip_id)
        panel._refresh_clip_fields()

        assert panel._stroke_checkbox.isChecked() is True
        assert panel._stroke_spin.isEnabled() is True
        assert panel._stroke_spin.value() == 5
        assert panel._stroke_color == "#e11d48"

        # 3. Edita espessura e cor do contorno
        panel._stroke_spin.setValue(8)
        panel._set_stroke_color("#000000")

        updated = panel._project.find(clip.clip_id)[1]
        assert updated.stroke_width == 8
        assert updated.stroke_color == "#000000"

        # 4. Desmarca o checkbox de contorno (stroke_width deve ir a 0)
        panel._stroke_checkbox.setChecked(False)
        assert panel._stroke_spin.isEnabled() is False
        assert panel._stroke_color_indicator.isEnabled() is False

        updated_no_stroke = panel._project.find(clip.clip_id)[1]
        assert updated_no_stroke.stroke_width == 0
    finally:
        panel.shutdown()


def test_timeline_track_visibility_toggle_and_menu(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        # Insere um vídeo fictício na timeline
        from videomanager.core.project import new_project, TrackKind, MediaRef, Clip, MediaKind
        ref = MediaRef(Path("/m/teste.mp4"), MediaKind.VIDEO, duration=10.0, width=1280, height=720, has_audio=True)
        clip_v = Clip(media=ref, start=0.0, duration=10.0)
        proj = new_project().with_clip(0, clip_v)
        panel._apply(proj)

        # Trilha 0 (Vídeo) visível inicialmente
        assert panel._project.tracks[0].visible is True

        # Menu no cabeçalho deve oferecer "Ocultar a trilha"
        menu = panel.build_menu("cabecalho", 0, -1)
        action_texts = [a.text() for a in menu.actions()]
        assert strings.EDIT_TRACK_HIDE in action_texts

        # Oculta a trilha
        panel._toggle_track_visibility(0)
        assert panel._project.tracks[0].visible is False

        # Menu no cabeçalho agora deve oferecer "Mostrar a trilha"
        menu2 = panel.build_menu("cabecalho", 0, -1)
        action_texts2 = [a.text() for a in menu2.actions()]
        assert strings.EDIT_TRACK_SHOW in action_texts2

        # Clica no botão de olho da timeline via simulação de mouse
        eye_rect = panel._timeline._eye_rect(0)
        hit_kind, hit_idx, _ = panel._timeline._hit(eye_rect.center().x(), eye_rect.center().y())
        assert hit_kind == "olho"
        assert hit_idx == 0

        # Mostra a trilha novamente
        panel._toggle_track_visibility(0)
        assert panel._project.tracks[0].visible is True
    finally:
        panel.shutdown()


def test_video_track_button_positions_and_version(qapp: QApplication) -> None:
    import videomanager
    from videomanager.ui.panels.timeline import Timeline
    from videomanager.ui.theme import DARK
    from videomanager.core.project import Project, Track, TrackKind

    assert videomanager.__version__ == "1.0"

    tl = Timeline(DARK)
    proj = Project(
        tracks=(
            Track(kind=TrackKind.VIDEO, name="Vídeo"),
            Track(kind=TrackKind.ADDITIONAL, name="Adicionais"),
            Track(kind=TrackKind.AUDIO, name="Áudio"),
        )
    )
    tl.set_project(proj)

    # Na trilha de vídeo (índice 0): Mute fica à esquerda do Olho (visibilidade)
    mute_rect_0 = tl._mute_rect(0)
    eye_rect_0 = tl._eye_rect(0)
    assert mute_rect_0.right() < eye_rect_0.left()
    assert eye_rect_0.right() > mute_rect_0.right()

    # Na trilha de áudio (índice 2): apenas mute na extrema direita
    mute_rect_2 = tl._mute_rect(2)
    assert mute_rect_2.right() == eye_rect_0.right()

    # Verifica que os recursos de ícone existem e são válidos
    res_dir = Path(__file__).resolve().parent.parent / "src" / "videomanager" / "resources"
    svg_icon = res_dir / "videomanager.svg"
    png_icon = res_dir / "videomanager.png"
    assert svg_icon.is_file() and svg_icon.stat().st_size > 0
    assert res_dir.exists()


def test_opposite_corner_anchored_resizing(qapp: QApplication) -> None:
    from videomanager.ui.panels.edit_panel import _Preview
    preview = _Preview()
    preview.resize(800, 600)
    ref = MediaRef(path=Path("/tmp/box.png"), kind=MediaKind.IMAGE, width=400, height=200)
    clip = Clip(media=ref, start=0.0, duration=5.0, overlay_type="image", x=0.5, y=0.5, scale=1.0, rotation=0.0)
    preview.set_active_clip(clip, 1920, 1080)
    preview.set_position(1.0)

    geom = preview._clip_geometry(clip)
    assert geom is not None
    cx0, cy0, w0, h0 = geom

    # Ponto Top-Left inicial
    init_tl = (cx0 - w0 / 2.0, cy0 - h0 / 2.0)
    # Ponto Bottom-Right inicial
    init_br = (cx0 + w0 / 2.0, cy0 + h0 / 2.0)

    # 1. Clica no canto BR (Bottom-Right) e arrasta para expandir
    br_pos = QPointF(cx0 + w0 / 2.0, cy0 + h0 / 2.0)
    press_ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, br_pos, br_pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    preview.mousePressEvent(press_ev)
    assert preview._drag_mode == "scale_br"

    # Arrasta aumentando a largura e altura em 40px
    move_ev = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(br_pos.x() + 40, br_pos.y() + 20), QPointF(br_pos.x() + 40, br_pos.y() + 20), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    preview.mouseMoveEvent(move_ev)

    # A nova geometria deve manter o canto TL rigorosamente idêntico!
    new_geom = preview._clip_geometry(preview._active_clip)
    assert new_geom is not None
    ncx, ncy, nw, nh = new_geom
    new_tl = (ncx - nw / 2.0, ncy - nh / 2.0)
    assert abs(new_tl[0] - init_tl[0]) < 0.05
    assert abs(new_tl[1] - init_tl[1]) < 0.05
    assert nw > w0
    assert nh > h0

    release_ev = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(br_pos.x() + 40, br_pos.y() + 20), QPointF(br_pos.x() + 40, br_pos.y() + 20), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    preview.mouseReleaseEvent(release_ev)

    # 2. Agora clica no canto TL e arrasta encolhendo: o canto BR deve permanecer fixo!
    tl_pos = QPointF(ncx - nw / 2.0, ncy - nh / 2.0)
    press_tl = QMouseEvent(QMouseEvent.Type.MouseButtonPress, tl_pos, tl_pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    preview.mousePressEvent(press_tl)
    assert preview._drag_mode == "scale_tl"

    current_br = (ncx + nw / 2.0, ncy + nh / 2.0)
    move_tl = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(tl_pos.x() + 20, tl_pos.y() + 10), QPointF(tl_pos.x() + 20, tl_pos.y() + 10), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    preview.mouseMoveEvent(move_tl)

    geom_after_tl = preview._clip_geometry(preview._active_clip)
    assert geom_after_tl is not None
    ncx2, ncy2, nw2, nh2 = geom_after_tl
    new_br2 = (ncx2 + nw2 / 2.0, ncy2 + nh2 / 2.0)
    assert abs(new_br2[0] - current_br[0]) < 0.05
    assert abs(new_br2[1] - current_br[1]) < 0.05


def test_video_clip_manipulation_in_preview(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    from videomanager.ui.panels.edit_panel import _Preview
    preview = _Preview()
    preview.resize(800, 600)

    # Clipe de vídeo em trilha de vídeo
    ref = MediaRef(path=Path("/tmp/filme.mp4"), kind=MediaKind.VIDEO, duration=10.0, width=1920, height=1080)
    clip_vid = Clip(media=ref, start=0.0, duration=5.0, x=0.5, y=0.5, scale=1.0, rotation=0.0)

    preview.set_active_clip(clip_vid, 1920, 1080)
    preview.set_position(2.0)

    # Deve calcular geometria corretamente através de fit_size
    geom = preview._clip_geometry(clip_vid)
    assert geom is not None
    cx, cy, w, h = geom
    assert w > 0 and h > 0

    # Deve permitir hit_test no corpo (move), rotação e cantos
    mode_body, _ = preview._hit_test(QPoint(int(cx), int(cy)))
    assert mode_body == "move"

    mode_rot, _ = preview._hit_test(QPoint(int(cx), int(cy - h / 2 - 24)))
    assert mode_rot == "rotate"

    mode_br, _ = preview._hit_test(QPoint(int(cx + w / 2), int(cy + h / 2)))
    assert mode_br == "scale_br"


def test_deselection_when_clicking_outside(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    from videomanager.ui.panels.edit_panel import EditPanel
    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools)
    try:
        # Adiciona um clipe de texto na trilha de adicionais
        panel._text_input.setText("Texto Selecionado")
        panel._insert_text_clip()
        clip = panel._project.additional_tracks[0].clips[0]
        panel._timeline.select(clip.clip_id)
        assert panel._timeline.selected_clip is not None

        # 1. Clique na prévia fora do objeto emite clicked_outside e desseleciona
        press_outside = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(5, 5),
            QPointF(5, 5),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        panel._preview.mousePressEvent(press_outside)
        assert panel._timeline.selected_clip is None

        # 2. Seleciona novamente e clica em área vazia fora das trilhas (ex.: no _preview_frame)
        panel._timeline.select(clip.clip_id)
        assert panel._timeline.selected_clip is not None

        dummy_click = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        # O eventFilter do painel intercepta e desseleciona
        panel.eventFilter(panel._preview_frame, dummy_click)
        assert panel._timeline.selected_clip is None
    finally:
        panel.shutdown()


def test_snap_magnetic_border_and_escape(qapp: QApplication) -> None:
    preview = _Preview()
    preview.resize(800, 600)
    clip = Clip(
        media=None,
        start=0.0,
        duration=5.0,
        overlay_type="text",
        text_content="Teste Snap",
        x=0.5,
        y=0.5,
        scale=1.0,
        rotation=0.0,
    )
    preview.set_active_clip(clip, 1920, 1080)
    vrect = preview._video_rect()
    geom = preview._clip_geometry(clip)
    assert geom is not None
    cx, cy, w, h = geom

    # 1. Simula início de arraste a partir do centro
    preview._drag_mode = "move"
    preview._drag_clip_id = clip.clip_id
    preview._drag_start_pos = QPoint(int(cx), int(cy))
    preview._drag_init_x = clip.x
    preview._drag_init_y = clip.y

    # Arrasta para perto da borda esquerda interna do vídeo (dentro do limiar de 14px)
    # Posição onde a borda esquerda do objeto fica a 5px de vrect.left()
    target_mouse_x = vrect.left() + (w / 2.0) + 5.0
    move_event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(target_mouse_x, cy),
        QPointF(target_mouse_x, cy),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_event)

    # Deve ter ativado o snap na borda esquerda:
    assert preview._snap_guide_x == float(vrect.left())
    # O clipe ativo deve estar com a borda esquerda perfeitamente alinhada em vrect.left():
    active_cx = vrect.left() + preview._active_clip.x * vrect.width()
    assert abs((active_cx - w / 2.0) - vrect.left()) < 0.001

    # 2. Força o movimento para além do limiar de 14px (ex: 25px para fora)
    target_forced_x = vrect.left() + (w / 2.0) - 25.0
    move_forced = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(target_forced_x, cy),
        QPointF(target_forced_x, cy),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_forced)

    # O snap deve desengatar e seguir livremente a posição do cursor
    assert preview._snap_guide_x is None
    forced_cx = vrect.left() + preview._active_clip.x * vrect.width()
    assert forced_cx < vrect.left() + (w / 2.0)  # Moveu-se para além da borda

    # 3. mouseReleaseEvent limpa as guias
    release_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(target_forced_x, cy),
        QPointF(target_forced_x, cy),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseReleaseEvent(release_event)
    assert preview._snap_guide_x is None
    assert preview._snap_guide_y is None
    assert preview._drag_mode is None


def test_snap_magnetic_rotation_and_escape(qapp: QApplication) -> None:
    preview = _Preview()
    preview.resize(800, 600)
    clip = Clip(
        media=None,
        start=0.0,
        duration=5.0,
        overlay_type="text",
        text_content="Teste Rot",
        x=0.5,
        y=0.5,
        scale=1.0,
        rotation=0.0,
    )
    preview.set_active_clip(clip, 1920, 1080)
    geom = preview._clip_geometry(clip)
    assert geom is not None
    cx, cy, w, h = geom

    preview._drag_mode = "rotate"
    preview._drag_clip_id = clip.clip_id
    preview._drag_init_angle = 0.0
    preview._drag_init_rot = 0.0

    # 1. Ângulo próximo a 90° (ex: 91.5° -> diferença de 1.5° <= 4.0°)
    rad_near_90 = math.radians(91.5)
    r = 100.0
    pos_x = cx + r * math.cos(rad_near_90)
    pos_y = cy + r * math.sin(rad_near_90)

    move_event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(pos_x, pos_y),
        QPointF(pos_x, pos_y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_event)

    # Deve travar exatamente em 90.0°
    assert preview._snap_guide_rot == 90.0
    assert preview._active_clip.rotation == 90.0

    # 2. Ângulo forçado além do limiar (ex: 98.0° -> diferença de 8.0° > 4.0°)
    rad_forced = math.radians(98.0)
    pos_fx = cx + r * math.cos(rad_forced)
    pos_fy = cy + r * math.sin(rad_forced)

    move_forced = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(pos_fx, pos_fy),
        QPointF(pos_fx, pos_fy),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_forced)

    # Deve soltar o snap e permitir rotação livre
    assert preview._snap_guide_rot is None
    assert abs(preview._active_clip.rotation - 98.0) < 0.5

    # 3. Ângulo próximo a 0° / 360° (ex: 358.5° -> trava em 0.0°)
    rad_near_360 = math.radians(358.5)
    pos_zx = cx + r * math.cos(rad_near_360)
    pos_zy = cy + r * math.sin(rad_near_360)

    move_zero = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(pos_zx, pos_zy),
        QPointF(pos_zx, pos_zy),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_zero)
    assert preview._snap_guide_rot == 0.0
    assert preview._active_clip.rotation == 0.0


def test_snap_toggle_button_and_persistence(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        assert panel._snap_btn.isChecked() is True
        assert panel._preview._snap_enabled is True

        # Desativa o botão
        panel._snap_btn.setChecked(False)
        assert panel._preview._snap_enabled is False
        assert panel._settings.preview_snap is False

        # Reativa o botão
        panel._snap_btn.setChecked(True)
        assert panel._preview._snap_enabled is True
        assert panel._settings.preview_snap is True
    finally:
        panel.shutdown()


def test_properties_tab_opening_editing_and_closing(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools)
    try:
        panel._text_input.setText("Texto Propriedades")
        panel._insert_text_clip()
        clip = panel._project.additional_tracks[0].clips[0]

        # 1. Abre a aba de propriedades pelo método chamado pelo menu
        panel._open_properties_tab(clip.clip_id)

        # Aba de propriedades deve estar visível e ativa
        assert panel._extras_tabs.indexOf(panel._properties_widget) >= 0
        assert panel._extras_tabs.currentWidget() is panel._properties_widget

        # 2. Verifica se valores iniciais estão corretos
        assert panel._properties_widget._clip_id == clip.clip_id
        assert panel._properties_widget._spin_scale.value() == clip.scale
        assert panel._properties_widget._spin_rot.value() == clip.rotation

        # 3. Edita rotação usando preset 90°
        panel._properties_widget._set_preset_rotation(90.0)
        updated_clip = panel._project.find(clip.clip_id)[1]
        assert updated_clip.rotation == 90.0

        # 4. Edita posição X na aba
        panel._properties_widget._spin_x.setValue(500)
        updated_clip = panel._project.find(clip.clip_id)[1]
        expected_x = 500 / panel._project.width
        assert abs(updated_clip.x - expected_x) < 0.001

        # 5. Edita escala na aba
        panel._properties_widget._spin_scale.setValue(2.0)
        updated_clip = panel._project.find(clip.clip_id)[1]
        assert updated_clip.scale == 2.0

        # 6. Fecha a aba de propriedades
        panel._close_properties_tab()
        assert panel._extras_tabs.indexOf(panel._properties_widget) == -1
    finally:
        panel.shutdown()






