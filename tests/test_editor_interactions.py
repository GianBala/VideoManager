"""Testes de interação, eventos de tela e consistência visual do editor de vídeo."""

from pathlib import Path
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QSpinBox, QTextEdit

from videomanager.domain.project import (
    Clip,
    MediaKind,
    MediaRef,
    Project,
    Track,
    TrackKind,
)
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt.fullscreen_preview import FullscreenPreview
from videomanager.presentation.qt.panels.edit_panel import EditPanel
from videomanager.domain.keyframe import Keyframe
from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget, _Preview
from videomanager.presentation.qt.panels.timeline import Timeline
from videomanager.presentation.qt.theme import DARK
from videomanager.bootstrap import (
    build_desktop_runtime,
    build_editor_service,
    build_processing_service,
)
from videomanager.application.capabilities import FFmpegTools

pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")


@pytest.fixture
def dummy_tools() -> FFmpegTools:
    return FFmpegTools(
        ffmpeg=Path("/bin/ffmpeg"),
        ffprobe=Path("/bin/ffprobe"),
        source="system",
    )


def test_paste_clip_additional_creates_additional_track(
    dummy_tools: FFmpegTools,
) -> None:
    """Verifica que colar clipe adicional cria/usa TrackKind.ADDITIONAL e não VIDEO."""
    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(),
    )
    try:
        panel._text_input.setText("Texto para Copiar")
        panel._insert_text_clip()
        text_clip = panel._project.additional_tracks[0].clips[0]

        # Copia o clipe
        panel._clipboard = text_clip

        # Move o cursor para além do primeiro clipe e preenche a trilha existente
        panel._timeline.set_position(10.0)
        panel._paste_clip()

        # Verifica que o clipe colado está numa trilha ADDITIONAL
        found = panel._project.find(panel._timeline.selected)
        assert found is not None
        track_idx, pasted_clip = found
        assert panel._project.tracks[track_idx].kind is TrackKind.ADDITIONAL
        assert pasted_clip.is_additional
    finally:
        panel.shutdown()


def test_hit_narrow_clip_prefers_closer_handle() -> None:
    """Em clipes estreitos onde ambas as alças cabem no limiar, a mais próxima é escolhida."""
    timeline = Timeline(DARK)
    media = MediaRef(Path("test.mp4"), MediaKind.VIDEO, duration=10.0)
    clip = Clip(media=media, start=1.0, duration=0.05)  # clipe muito curto
    project = Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(clip,)),))
    timeline.set_project(project)
    timeline.set_view(0.0, 10.0)

    rect = timeline._clip_rect(0, clip)
    x_right_edge = rect.right()
    # Ao clicar exatamente na borda direita, deve retornar "fim" e não "inicio"
    kind, _, cid = timeline._hit(x_right_edge, rect.center().y())
    assert kind == "fim"
    assert cid == clip.clip_id

    # Ao clicar na borda esquerda, deve retornar "inicio"
    x_left_edge = rect.left()
    kind, _, cid = timeline._hit(x_left_edge, rect.center().y())
    assert kind == "inicio"
    assert cid == clip.clip_id


def test_timeline_click_empty_space_deselects() -> None:
    """Clicar em área vazia da timeline desmarca o clipe selecionado."""
    timeline = Timeline(DARK)
    media = MediaRef(Path("test.mp4"), MediaKind.VIDEO, duration=10.0)
    clip = Clip(media=media, start=0.0, duration=5.0)
    project = Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(clip,)),))
    timeline.set_project(project)
    timeline.select(clip.clip_id)
    assert timeline.selected == clip.clip_id

    # Simula clique no vazio (ex: tempo 8.0, onde não há clipe)
    x_empty = timeline._x_of(8.0)
    y_empty = timeline._clip_rect(0, clip).center().y()
    pos = QPointF(x_empty, y_empty)
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    timeline.mousePressEvent(event)
    assert timeline.selected == -1


def test_timeline_set_project_deselects_dead_clip() -> None:
    """Se o clipe selecionado for excluído do projeto, a timeline redefine selected para -1."""
    timeline = Timeline(DARK)
    media = MediaRef(Path("test.mp4"), MediaKind.VIDEO, duration=10.0)
    clip = Clip(media=media, start=0.0, duration=5.0)
    project = Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(clip,)),))
    timeline.set_project(project)
    timeline.select(clip.clip_id)
    assert timeline.selected == clip.clip_id

    # Atualiza o projeto sem o clipe
    empty_project = project.without_clip(clip.clip_id)
    timeline.set_project(empty_project)
    assert timeline.selected == -1


def test_timeline_hover_eye_shows_pointing_hand_cursor() -> None:
    """Passar o cursor sobre o botão do olho (visibilidade) mostra PointingHandCursor."""
    timeline = Timeline(DARK)
    track = Track(kind=TrackKind.VIDEO)
    project = Project(tracks=(track,))
    timeline.set_project(project)

    eye_rect = timeline._eye_rect(0)
    pos = eye_rect.center()
    event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        pos,
        pos,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    timeline.mouseMoveEvent(event)
    assert timeline.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_preview_no_drag_mode_and_emits_play_toggle_when_playing() -> None:
    """Quando o preview está reproduzindo, clique alterna reprodução e não inicia arrasto."""
    preview = _Preview()
    media = MediaRef(Path("test.mp4"), MediaKind.VIDEO, duration=10.0, width=1920, height=1080)
    clip = Clip(media=media, start=0.0, duration=5.0)
    preview.set_active_clip(clip, 1920, 1080)
    preview.set_position(1.0)
    preview.resize(800, 600)
    preview.set_playing(True)

    requested = []
    preview.play_toggle_requested.connect(lambda: requested.append(True))

    pos = QPointF(400, 300)
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mousePressEvent(event)

    assert len(requested) == 1
    assert preview._drag_mode is None


def test_audio_only_clip_has_no_visual_geometry_or_handles() -> None:
    """Clipe somente de áudio não possui geometria no canvas visual mesmo se media.has_video for True."""
    preview = _Preview()
    media = MediaRef(Path("video.mp4"), MediaKind.VIDEO, duration=10.0, width=1920, height=1080)
    audio_clip = Clip(media=media, start=0.0, duration=5.0, audio_only=True)

    assert not audio_clip.has_image
    assert audio_clip.audio_only

    geom = preview._clip_geometry(audio_clip)
    assert geom is None

    mode, _ = preview._hit_test_clip(audio_clip, QPoint(400, 300))
    assert mode is None


def test_preview_overlay_clips_z_order_reversed(
    dummy_tools: FFmpegTools,
) -> None:
    """Verifica que a ordem de sobreposições em _update_preview_overlay_clips coincide com FFmpeg (Trilha 0 no topo)."""
    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(),
    )
    try:
        panel._add_track(TrackKind.ADDITIONAL)
        panel._add_track(TrackKind.ADDITIONAL)

        c1 = Clip(
            media=MediaRef(Path("t1"), MediaKind.IMAGE, duration=5.0),
            overlay_type="text",
            text_content="Cima",
            start=0.0,
            duration=5.0,
        )
        c2 = Clip(
            media=MediaRef(Path("t2"), MediaKind.IMAGE, duration=5.0),
            overlay_type="text",
            text_content="Baixo",
            start=0.0,
            duration=5.0,
        )
        panel._project = panel._project.with_clip(0, c1).with_clip(1, c2)
        panel._timeline.set_position(1.0)
        panel._update_preview_overlay_clips()

        # No preview, c2 (trilha inferior) deve vir ANTES de c1 (trilha superior)
        # para que o QPainter desenhe c1 POR CIMA de c2!
        overlays = panel._preview._overlay_clips
        assert len(overlays) == 2
        assert overlays[0].clip_id == c2.clip_id
        assert overlays[1].clip_id == c1.clip_id
    finally:
        panel.shutdown()


def test_fullscreen_preview_scales_when_one_dimension_matches() -> None:
    """Verifica que FullscreenPreview escala imagem mesmo quando uma das dimensões coincide."""
    fs = FullscreenPreview()
    fs.resize(1920, 1080)
    fs._image.resize(1920, 1080)

    pixmap = QPixmap(1920, 800)
    fs.set_frame(pixmap)

    assert fs._image.pixmap() is not None
    assert not fs._image.pixmap().isNull()
    fs.close()


def test_dispatch_ignores_shortcuts_in_spinboxes_and_text_edits(
    dummy_tools: FFmpegTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Atalhos do painel são ignorados quando foco está em QSpinBox ou QTextEdit."""
    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(),
    )
    try:
        from PySide6.QtWidgets import QApplication

        spin = QSpinBox(panel)
        monkeypatch.setattr(QApplication, "focusWidget", lambda: spin)
        called = []
        panel._dispatch(lambda: called.append(True))
        assert len(called) == 0

        text_edit = QTextEdit(panel)
        monkeypatch.setattr(QApplication, "focusWidget", lambda: text_edit)
        called.clear()
        panel._dispatch(lambda: called.append(True))
        assert len(called) == 0

        monkeypatch.setattr(QApplication, "focusWidget", lambda: None)
        called.clear()
        panel._dispatch(lambda: called.append(True))
        assert len(called) == 1
    finally:
        panel.shutdown()


def test_additional_image_overlay_receives_active_filter_in_preview(
    tmp_path: Path,
    dummy_tools: FFmpegTools,
) -> None:
    """Verifica que imagens de trilhas adicionais recebem filtros ativos da timeline no preview."""
    test_img = tmp_path / "red.png"
    img = QPixmap(50, 50)
    img.fill(Qt.GlobalColor.red)
    img.save(str(test_img))

    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(),
    )
    try:
        ref_img = MediaRef(path=test_img, kind=MediaKind.IMAGE, duration=10.0, width=50, height=50)
        c_image = Clip(media=ref_img, start=0.0, duration=10.0, overlay_type="image")
        t_image = Track(kind=TrackKind.ADDITIONAL, clips=(c_image,))

        ref_f = MediaRef(path=Path("Filtro_PB"), kind=MediaKind.IMAGE, duration=5.0)
        c_filter = Clip(
            media=ref_f,
            start=1.0,
            duration=5.0,
            overlay_type="filter",
            filter_name="pb",
        )
        t_filter = Track(kind=TrackKind.ADDITIONAL, clips=(c_filter,))

        ref_v = MediaRef(
            path=Path("video.mp4"),
            kind=MediaKind.VIDEO,
            duration=10.0,
            width=1920,
            height=1080,
        )
        c_video = Clip(media=ref_v, start=0.0, duration=10.0)
        t_video = Track(kind=TrackKind.VIDEO, clips=(c_video,))

        # Track 0: Filtro, Track 1: Imagem, Track 2: Vídeo
        project = Project(tracks=(t_filter, t_image, t_video), width=1920, height=1080, fps=30.0)
        panel._apply(project)

        # Na posição 2.0s, o filtro "pb" está ativo sobre a imagem
        panel._timeline.set_position(2.0)
        panel._update_preview_overlay_clips()

        assert c_image.clip_id in panel._preview._clip_filters
        assert panel._preview._clip_filters[c_image.clip_id] == ("pb",)

        # Obtém o pixmap do preview e verifica se o filtro foi aplicado (escala de cinza: R == G == B)
        pix = panel._preview._get_clip_pixmap(c_image, filters=panel._preview._clip_filters[c_image.clip_id])
        assert pix is not None and not pix.isNull()
        col = pix.toImage().pixelColor(25, 25)
        assert col.red() == col.green() == col.blue()

        # Na posição 7.0s, o filtro acabou: a imagem volta a não ter filtro
        panel._timeline.set_position(7.0)
        panel._update_preview_overlay_clips()
        assert c_image.clip_id not in panel._preview._clip_filters

        pix_raw = panel._preview._get_clip_pixmap(c_image, filters=())
        assert pix_raw is not None
        col_raw = pix_raw.toImage().pixelColor(25, 25)
        assert col_raw.red() > 200 and col_raw.green() == 0 and col_raw.blue() == 0
    finally:
        panel.shutdown()


def test_filter_transformations_in_preview() -> None:
    """Verifica que as funções de filtro do preview geram imagens válidas com os efeitos corretos."""
    preview = _Preview()
    pix = QPixmap(20, 20)
    pix.fill(Qt.GlobalColor.red)

    # Inverter
    inv = preview._apply_filters_to_pixmap(pix, ("inverter",))
    c_inv = inv.toImage().pixelColor(10, 10)
    assert c_inv.red() == 0 and c_inv.green() == 255 and c_inv.blue() == 255

    # PB
    pb = preview._apply_filters_to_pixmap(pix, ("pb",))
    c_pb = pb.toImage().pixelColor(10, 10)
    assert c_pb.red() == c_pb.green() == c_pb.blue()

    # Sepia
    sepia = preview._apply_filters_to_pixmap(pix, ("sepia",))
    c_sepia = sepia.toImage().pixelColor(10, 10)
    assert c_sepia.red() > c_sepia.green() > c_sepia.blue()

    # Contraste e Vinheta não devem quebrar
    contrast = preview._apply_filters_to_pixmap(pix, ("contraste",))
    assert not contrast.isNull()
    vignette = preview._apply_filters_to_pixmap(pix, ("vinheta",))
    assert not vignette.isNull()


def test_preview_drag_with_keyframes_only_modifies_current_keyframe() -> None:
    """Verifica que arrastar um clipe com keyframes altera apenas o keyframe da agulha atual."""
    preview = _Preview()
    preview.resize(800, 600)

    # Cria clipe com 2 keyframes em t=0s e t=5s, ambos inicialmente em (0.2, 0.2)
    kf0 = Keyframe(time_offset=0.0, x=0.2, y=0.2, scale_x=0.5, scale_y=0.5)
    kf1 = Keyframe(time_offset=5.0, x=0.2, y=0.2, scale_x=0.5, scale_y=0.5)
    media = MediaRef(Path("test.png"), MediaKind.IMAGE, duration=10.0, width=100, height=100)
    clip = Clip(media=media, start=0.0, duration=10.0, overlay_type="image", keyframes=(kf0, kf1))

    preview.set_active_clip(clip, 800, 600)
    # Posiciona a agulha exatamente no segundo keyframe (t=5.0s)
    preview.set_position(5.0)

    geom = preview._clip_geometry(clip)
    assert geom is not None
    cx, cy, w, h = geom

    # Inicia arrasto com botão esquerdo sobre o clipe
    p_pt = QPointF(cx, cy)
    press_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        p_pt,
        p_pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mousePressEvent(press_event)
    assert preview._drag_mode == "move"

    # Move o cursor 200px para a direita e 100px para baixo
    m_pt = QPointF(cx + 200, cy + 100)
    move_event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        m_pt,
        m_pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_event)

    # Finaliza arrasto
    release_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        m_pt,
        m_pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseReleaseEvent(release_event)

    updated_clip = preview._active_clip
    assert updated_clip is not None
    assert len(updated_clip.keyframes) == 2

    kfs = updated_clip.keyframes
    # O primeiro keyframe (em t=0s) DEVE PERMANECER INTACTO em (0.2, 0.2)
    assert abs(kfs[0].time_offset - 0.0) < 1e-4
    assert abs(kfs[0].x - 0.2) < 1e-4
    assert abs(kfs[0].y - 0.2) < 1e-4

    # O segundo keyframe (em t=5s) foi atualizado com o novo centro
    assert abs(kfs[1].time_offset - 5.0) < 1e-4
    assert kfs[1].x > 0.3
    assert kfs[1].y > 0.3

    # Interpolação no ponto médio (t=2.5s) calcula a posição suave entre os dois keyframes
    mid_t = updated_clip.transform_at(2.5)
    assert kfs[0].x < mid_t.x < kfs[1].x
    assert kfs[0].y < mid_t.y < kfs[1].y


def test_properties_widget_with_keyframes_only_modifies_current_keyframe() -> None:
    """Verifica que alterar campos no painel de propriedades altera apenas o keyframe da agulha."""
    widget = _ClipPropertiesWidget()
    kf0 = Keyframe(time_offset=0.0, x=0.2, y=0.2, scale_x=0.5, scale_y=0.5)
    kf1 = Keyframe(time_offset=5.0, x=0.2, y=0.2, scale_x=0.5, scale_y=0.5)
    media = MediaRef(Path("test.png"), MediaKind.IMAGE, duration=10.0, width=100, height=100)
    clip = Clip(media=media, start=0.0, duration=10.0, overlay_type="image", keyframes=(kf0, kf1))

    widget.load_clip(clip, 800, 600)
    widget.set_playhead_position(5.0)

    # Altera x para 0.8
    widget._emit_property_change({"x": 0.8})

    updated = widget._clip
    assert updated is not None
    assert len(updated.keyframes) == 2

    # Keyframe em t=0s deve manter x=0.2
    assert abs(updated.keyframes[0].x - 0.2) < 1e-4
    # Keyframe em t=5s deve ter x=0.8
    assert abs(updated.keyframes[1].x - 0.8) < 1e-4

    # Altera escala no keyframe 5s
    widget._emit_property_change({"scale_x": 1.2, "scale_y": 1.2})
    # Keyframe em t=0s deve manter escala 0.5
    assert abs(widget._clip.keyframes[0].scale_x - 0.5) < 1e-4
    # Keyframe em t=5s deve ter escala 1.2
    assert abs(widget._clip.keyframes[1].scale_x - 1.2) < 1e-4


def test_properties_widget_auto_keyframe_at_new_time() -> None:
    """Ao alterar propriedades em um instante sem keyframe, cria um novo keyframe sem afetar os existentes."""
    widget = _ClipPropertiesWidget()
    kf0 = Keyframe(time_offset=0.0, x=0.2, y=0.2, rotation=0.0)
    kf1 = Keyframe(time_offset=5.0, x=0.8, y=0.8, rotation=0.0)
    media = MediaRef(Path("test.png"), MediaKind.IMAGE, duration=10.0, width=100, height=100)
    clip = Clip(media=media, start=0.0, duration=10.0, overlay_type="image", keyframes=(kf0, kf1))

    widget.load_clip(clip, 800, 600)
    # Posiciona a agulha em t=2.5s (onde não há keyframe)
    widget.set_playhead_position(2.5)

    widget._emit_property_change({"rotation": 45.0})

    updated = widget._clip
    assert len(updated.keyframes) == 3
    # Keyframe intermediário criado em t=2.5s
    assert abs(updated.keyframes[1].time_offset - 2.5) < 1e-4
    assert abs(updated.keyframes[1].rotation - 45.0) < 1e-4
    # Posição interpolada herdada em t=2.5s (~0.5)
    assert abs(updated.keyframes[1].x - 0.5) < 1e-2

    # Keyframes de 0s e 5s inalterados
    assert abs(updated.keyframes[0].x - 0.2) < 1e-4
    assert abs(updated.keyframes[2].x - 0.8) < 1e-4


def test_properties_widget_auto_keyframe_position_at_new_time() -> None:
    """Ao alterar X ou Y em um instante sem keyframe, cria um novo keyframe sem afetar os existentes."""
    widget = _ClipPropertiesWidget()
    kf0 = Keyframe(time_offset=0.0, x=0.2, y=0.2)
    kf1 = Keyframe(time_offset=5.0, x=0.2, y=0.2)
    media = MediaRef(Path("test.png"), MediaKind.IMAGE, duration=10.0, width=100, height=100)
    clip = Clip(media=media, start=0.0, duration=10.0, overlay_type="image", keyframes=(kf0, kf1))

    widget.load_clip(clip, 800, 600)
    widget.set_playhead_position(2.5)

    widget._emit_property_change({"x": 0.75})

    updated = widget._clip
    assert updated is not None
    assert len(updated.keyframes) == 3
    assert abs(updated.keyframes[1].time_offset - 2.5) < 1e-4
    assert abs(updated.keyframes[1].x - 0.75) < 1e-4
    assert abs(updated.keyframes[0].x - 0.2) < 1e-4
    assert abs(updated.keyframes[2].x - 0.2) < 1e-4


def test_preview_drag_auto_keyframe_at_new_time() -> None:
    """Ao arrastar a posição no preview em instante sem keyframe, cria novo keyframe mantendo os outros intactos."""
    preview = _Preview()
    preview.resize(800, 600)

    kf0 = Keyframe(time_offset=0.0, x=0.2, y=0.2)
    kf1 = Keyframe(time_offset=5.0, x=0.2, y=0.2)
    media = MediaRef(Path("test.png"), MediaKind.IMAGE, duration=10.0, width=100, height=100)
    clip = Clip(media=media, start=0.0, duration=10.0, overlay_type="image", keyframes=(kf0, kf1))

    preview.set_active_clip(clip, 800, 600)
    preview.set_position(2.5)

    geom = preview._clip_geometry(clip)
    assert geom is not None
    cx, cy, w, h = geom

    p_pt = QPointF(cx, cy)
    press_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        p_pt,
        p_pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mousePressEvent(press_event)
    assert preview._drag_mode == "move"

    m_pt = QPointF(cx + 150, cy + 100)
    move_event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        m_pt,
        m_pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_event)

    release_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        m_pt,
        m_pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseReleaseEvent(release_event)

    updated_clip = preview._active_clip
    assert updated_clip is not None
    assert len(updated_clip.keyframes) == 3

    kfs = updated_clip.keyframes
    assert abs(kfs[0].time_offset - 0.0) < 1e-4
    assert abs(kfs[0].x - 0.2) < 1e-4

    assert abs(kfs[1].time_offset - 2.5) < 1e-4
    assert kfs[1].x > 0.3
    assert kfs[1].y > 0.3

    assert abs(kfs[2].time_offset - 5.0) < 1e-4
    assert abs(kfs[2].x - 0.2) < 1e-4


def test_preview_rotate_auto_keyframe_at_new_time() -> None:
    """Ao rotacionar pela alça no preview em instante sem keyframe, cria novo keyframe mantendo os outros intactos."""
    preview = _Preview()
    preview.resize(800, 600)

    kf0 = Keyframe(time_offset=0.0, x=0.5, y=0.5, rotation=0.0)
    kf1 = Keyframe(time_offset=5.0, x=0.5, y=0.5, rotation=0.0)
    media = MediaRef(Path("test.png"), MediaKind.IMAGE, duration=10.0, width=100, height=100)
    clip = Clip(media=media, start=0.0, duration=10.0, overlay_type="image", keyframes=(kf0, kf1))

    preview.set_active_clip(clip, 800, 600)
    preview.set_position(2.5)

    geom = preview._clip_geometry(clip)
    assert geom is not None
    cx, cy, w, h = geom

    # Alça de rotação fica no topo: cy - h/2 - 24
    rot_pt = QPointF(cx, cy - h / 2.0 - 24.0)
    press_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        rot_pt,
        rot_pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mousePressEvent(press_event)
    assert preview._drag_mode == "rotate"

    # Move para o lado direito para girar em torno de 90 graus
    m_pt = QPointF(cx + 80, cy)
    move_event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        m_pt,
        m_pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_event)

    release_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        m_pt,
        m_pt,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseReleaseEvent(release_event)

    updated_clip = preview._active_clip
    assert updated_clip is not None
    assert len(updated_clip.keyframes) == 3

    kfs = updated_clip.keyframes
    assert abs(kfs[0].time_offset - 0.0) < 1e-4
    assert abs(kfs[0].rotation - 0.0) < 1e-4

    assert abs(kfs[1].time_offset - 2.5) < 1e-4
    assert kfs[1].rotation > 10.0

    assert abs(kfs[2].time_offset - 5.0) < 1e-4
    assert abs(kfs[2].rotation - 0.0) < 1e-4
