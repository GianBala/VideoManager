"""Testes de interface para trilha de adicionais, painel de extras, popups e preview."""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QMessageBox

from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.project import (
    Clip,
    MediaKind,
    MediaRef,
    Project,
    Track,
    TrackKind,
)
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.panels.edit_panel import EditPanel
from videomanager.presentation.qt.panels.edit_widgets import _FontSelectorWidget
from videomanager.presentation.qt.panels.edit_widgets import _Preview
from videomanager.presentation.qt.panels.edit_widgets import _SpeedPopup
from videomanager.presentation.qt.panels.edit_widgets import _VolumePopup
from videomanager.bootstrap import build_editor_service
from videomanager.bootstrap import build_processing_service
from videomanager.bootstrap import build_desktop_runtime


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
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
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


def test_image_inserted_into_video_track(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        img_ref = MediaRef(
            path=Path("/tmp/foto.png"),
            kind=MediaKind.IMAGE,
            width=800,
            height=600,
        )
        panel._pool.append(img_ref)
        panel._insert_media_ref(img_ref)

        # Imagem é parte da trilha de vídeo; nenhuma trilha de Adicionais nasce.
        assert not panel._project.additional_tracks
        add_clip = panel._project.video_tracks[0].clips[0]
        assert add_clip.media.kind is MediaKind.IMAGE
        assert add_clip.is_additional is True and add_clip.is_overlay is False
    finally:
        panel.shutdown()


def test_speed_adjustment_and_popups(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
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
    from videomanager.presentation.qt.panels.edit_widgets import _FontSelectorWidget

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
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
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
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
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


def test_project_lifecycle_media_management(qapp: QApplication, dummy_tools: FFmpegTools, tmp_path: Path, wait_until) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
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
        panel._session.mark_saved()
        panel.new_project()
        assert len(panel._pool) == 0
        assert panel._media_list.count() == 0

        # Abrir projeto existente deve resgatar as mídias para a aba "Mídia do projeto"
        panel.open_project(proj_file)
        wait_until(lambda: not panel._project_actions.busy)
        assert len(panel._pool) == 1
        assert panel._pool[0].path == sample_file
        assert panel._media_list.count() == 1
    finally:
        panel.shutdown()


def test_loop_playback_logic(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
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

        # O loop começa ao concluir a duração, preservando o último frame.
        panel._timeline.set_position(2.0)
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
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        ref1 = MediaRef(path=Path("/tmp/media1.mp4"), kind=MediaKind.VIDEO, duration=5.0)
        ref2 = MediaRef(path=Path("/tmp/media2.mp4"), kind=MediaKind.VIDEO, duration=5.0)
        panel._pool.extend([ref1, ref2])
        panel._refresh_pool()
        assert len(panel._pool) == 2
        assert panel._media_list.count() == 2

        # 1. O menu do botão direito é montado de verdade sobre uma mídia —
        # conferir só a constante deixou passar um texto inexistente, que
        # levantava AttributeError e impedia o menu de aparecer.
        menu = panel.build_media_menu(panel._media_list.visualItemRect(panel._media_list.item(0)).center())
        assert [a.text() for a in menu.actions()] == [
            strings.EDIT_INSERT, strings.EDIT_MEDIA_REMOVE, "", strings.EDIT_CLEAR_UNUSED]

        # 2. Test deleting selected item with focus on _media_list
        panel._media_list.setCurrentRow(0)
        panel._media_list.setFocus()
        panel._delete_selected()

        assert len(panel._pool) == 1
        assert panel._pool[0].path == Path("/tmp/media2.mp4")
        assert panel._media_list.count() == 1
    finally:
        panel.shutdown()


def test_lista_de_fontes_tem_linhas_com_folga(qapp: QApplication) -> None:
    # Sem o padding de item a lista espremia oito nomes no espaço de cinco,
    # e o estilo fixo que o dava saiu junto com as cores escuras.
    from videomanager.presentation.qt.theme import stylesheet
    for tema in ("dark", "light"):
        selector = _FontSelectorWidget("Sans Serif")
        selector.setStyleSheet(stylesheet(tema))
        selector._toggle_list()
        qapp.processEvents()
        lista = selector._font_list
        assert lista.visualItemRect(lista.item(0)).height() >= lista.fontMetrics().height() + 8
        selector.deleteLater()


def test_botao_de_quadro_chave_tem_a_mesma_letra_marcado_e_desmarcado(qapp: QApplication) -> None:
    # O estado marcado tem letra própria; tirando só as cores do desmarcado, a
    # letra saiu junto e o símbolo mudava de tamanho e de peso ao alternar.
    from videomanager.domain.keyframe import Keyframe
    from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget
    video = MediaRef(Path("/tmp/v.mp4"), MediaKind.VIDEO, duration=5.0, width=640, height=360, fps=30.0)
    widget = _ClipPropertiesWidget()
    widget.load_clip(Clip(video, 0.0, 5.0, keyframes=(Keyframe(1.0, opacity=0.5),)), 640, 360)
    fontes = []
    for instante in (1.0, 3.0):
        widget.set_playhead_position(instante)
        botao = widget._btn_kf_toggle
        botao.ensurePolished()
        fontes.append((botao.text(), botao.font().bold(), botao.font().pixelSize()))
    assert fontes == [("◆", True, 14), ("◇", True, 14)]
    widget.deleteLater()


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
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
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
        # Estilo do tema (legível no claro e no escuro), e não cores fixas.
        for botao in (dec_btns[0], inc_btns[0]):
            assert botao.property("role") == "spin-tool"
            assert botao.styleSheet() == ""

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
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
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
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        # A opção marcada ganha a borda de destaque do tema, sem pintar o
        # fundo inteiro — e sem cores fixas, que no tema claro deixavam os
        # botões pretos.
        from videomanager.presentation.qt.theme import DARK, LIGHT, stylesheet
        for btn in panel._filter_buttons:
            assert btn.property("role") == "option"
            assert btn.styleSheet() == ""
        for tema, cores in (("dark", DARK), ("light", LIGHT)):
            regra = next(linha for linha in stylesheet(tema).splitlines()
                         if linha.startswith('QPushButton[role="option"]:checked'))
            assert f"border: 2px solid {cores['accent']}" in regra
            assert "background" not in regra
    finally:
        panel.shutdown()


def test_text_stroke_controls_and_bidirectional_sync(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
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
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        # Insere um vídeo fictício na timeline
        from videomanager.domain.project import new_project
        from videomanager.domain.project import MediaRef
        from videomanager.domain.project import Clip
        from videomanager.domain.project import MediaKind
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


def test_transicao_nao_dispara_miniatura_de_referencia_sintetica(
    qapp: QApplication,
    dummy_tools: FFmpegTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from videomanager.domain.project import Project
    from videomanager.domain.project import Track
    from videomanager.domain.project import TrackKind

    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(),
    )
    try:
        media = MediaRef(
            Path("/m/video.mp4"),
            MediaKind.VIDEO,
            duration=8.0,
            width=1280,
            height=720,
        )
        left = Clip(media=media, start=0.0, duration=4.0)
        right = Clip(media=media, start=4.0, duration=4.0, in_point=4.0)
        marker = Clip(
            media=MediaRef(Path("Transição_Dissolve"), MediaKind.IMAGE, duration=1.0),
            start=3.5,
            duration=1.0,
            overlay_type="transition",
            transition_name="dissolve",
            transition_left_id=left.clip_id,
            transition_right_id=right.clip_id,
        )
        project = Project(
            tracks=(Track(kind=TrackKind.VIDEO, clips=(left, right, marker)),)
        )
        panel._project = project
        panel._timeline.set_project(project)
        requested: list[int] = []
        monkeypatch.setattr(
            panel,
            "_request_thumbs",
            lambda clip, tools: requested.append(clip.clip_id),
        )

        panel._refresh_backdrop()

        assert set(requested) == {left.clip_id, right.clip_id}
        assert marker.clip_id not in requested
    finally:
        panel.shutdown()


def test_redimensionar_transicao_invalida_quadro_da_revisao_anterior(
    qapp: QApplication,
    dummy_tools: FFmpegTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O mesmo instante não torna válidas duas composições diferentes."""
    from videomanager.domain.project import Project
    from videomanager.domain.project import Track
    from videomanager.domain.project import TrackKind

    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(),
    )
    try:
        media = MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=8.0)
        left = Clip(media=media, start=0.0, duration=4.0)
        right = Clip(media=media, start=4.0, duration=4.0, in_point=4.0)
        marker = Clip(
            media=MediaRef(Path("Transição_Dissolve"), MediaKind.IMAGE, duration=0.2),
            start=3.9,
            duration=0.2,
            overlay_type="transition",
            transition_name="dissolve",
            transition_left_id=left.clip_id,
            transition_right_id=right.clip_id,
        )
        project = Project(
            tracks=(Track(kind=TrackKind.VIDEO, clips=(left, right, marker)),)
        )
        panel._project = project
        panel._timeline.set_project(project)
        panel._timeline.set_position(4.0)

        # Simula a prévia da duração maior ainda em processamento quando a
        # transição volta ao tamanho original.
        panel._frame_busy = True
        panel._frame_revision = 7
        panel._frame_token = 41
        panel._wanted = 4.0
        panel._rendered = 4.0
        panel._project = project.resized(marker.clip_id, "fim", 4.5)
        panel._project = panel._project.resized(marker.clip_id, "fim", 4.1)
        panel._request_frame(force=True)

        assert panel._frame_revision == 8
        assert panel._frame_token != 41
        assert panel._rendered is None

        started: list[tuple[float | None, int]] = []
        monkeypatch.setattr(
            panel,
            "_start_frame",
            lambda: started.append((panel._wanted, panel._frame_revision)),
        )
        panel._on_frame_done(7)
        assert started == [(4.0, 8)]
    finally:
        panel.shutdown()


def test_play_reaproveita_transicao_preparada_sem_abrir_outro_ffmpeg(
    qapp: QApplication,
    dummy_tools: FFmpegTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from videomanager.domain.project import Project
    from videomanager.domain.project import Track
    from videomanager.domain.project import TrackKind
    from videomanager.infrastructure.qt.workers.signals import PreviewSignals

    runtime = build_desktop_runtime()
    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=runtime,
    )

    class Worker:
        def __init__(self) -> None:
            self.signals = PreviewSignals()
            self.started = False
            self.cancelled = False

        def start_playback(self) -> None:
            self.started = True

        def cancel(self) -> None:
            self.cancelled = True

    try:
        media = MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=8.0)
        left = Clip(media=media, start=0.0, duration=4.0)
        right = Clip(media=media, start=4.0, duration=4.0, in_point=4.0)
        transition = Clip(
            media=MediaRef(Path("Transição_Dissolve"), MediaKind.IMAGE, duration=1.0),
            start=3.5,
            duration=1.0,
            overlay_type="transition",
            transition_name="dissolve",
            transition_left_id=left.clip_id,
            transition_right_id=right.clip_id,
        )
        project = Project(
            tracks=(Track(kind=TrackKind.VIDEO, clips=(left, right, transition)),)
        )
        panel._project = project
        panel._timeline.set_project(project)
        panel._timeline.set_position(4.0)

        workers: list[Worker] = []

        def make_worker(*args, **kwargs):
            assert kwargs["autostart"] is False
            worker = Worker()
            workers.append(worker)
            return worker

        monkeypatch.setattr(runtime, "playback_worker", make_worker)
        monkeypatch.setattr(panel._runner, "start", lambda *args: None)

        panel._prime_playback()
        assert len(workers) == 1
        token = panel._primed_token
        workers[0].signals.primed.emit(token)
        assert panel._primed_ready

        panel._playing = True
        started = panel._start_frames(4.0)

        assert started == (token, True)
        assert workers[0].started
        assert not workers[0].cancelled
        assert len(workers) == 1, "o play não deve abrir um segundo processo"
    finally:
        panel._playing = False
        panel.shutdown()


def test_insercao_persiste_opcao_de_afetar_adicionais(
    qapp: QApplication,
    dummy_tools: FFmpegTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from videomanager.domain.project import Project
    from videomanager.domain.project import Track
    from videomanager.domain.project import TrackKind

    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(audio_enabled=False),
    )
    try:
        media = MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=8.0)
        left = Clip(media, start=0.0, duration=4.0)
        right = Clip(media, start=4.0, duration=4.0, in_point=4.0)
        project = Project(
            tracks=(Track(TrackKind.VIDEO, clips=(left, right)),)
        )
        panel._project = project
        panel._timeline.set_project(project)
        panel._timeline.select(left.clip_id)
        panel._timeline.set_position(4.0)
        panel._trans_affect_additionals.setChecked(True)
        monkeypatch.setattr(panel, "_request_frame", lambda **kwargs: None)

        panel._insert_transition_clip("dissolve")

        marker = next(clip for clip in panel._project.clips if clip.is_transition)
        assert marker.transition_affects_additionals is True
    finally:
        panel.shutdown()


def test_tesoura_cria_corte_que_aceita_transicao(
    qapp: QApplication,
    dummy_tools: FFmpegTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from videomanager.domain.project import Project
    from videomanager.domain.project import Track
    from videomanager.domain.project import TrackKind

    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(audio_enabled=False),
    )
    try:
        media = MediaRef(Path("/m/continuo.mp4"), MediaKind.VIDEO, duration=8.0)
        original = Clip(media, start=0.0, duration=8.0)
        project = Project(
            tracks=(Track(TrackKind.VIDEO, clips=(original,)),)
        )
        panel._project = project
        panel._timeline.set_project(project)
        panel._timeline.select(original.clip_id)
        panel._timeline.set_position(4.0)
        monkeypatch.setattr(
            panel,
            "_after_edit",
            lambda **_kwargs: panel._timeline.set_project(panel._project),
        )

        panel._split_here()
        left, right = panel._project.tracks[0].sorted_clips()
        panel._insert_transition_clip("dissolve")

        markers = [clip for clip in panel._project.clips if clip.is_transition]
        assert len(markers) == 1
        assert (
            markers[0].transition_left_id,
            markers[0].transition_right_id,
        ) == (left.clip_id, right.clip_id)
    finally:
        panel.shutdown()


def test_pause_congela_quadro_sem_disparar_renderizacao_redundante(
    qapp: QApplication,
    dummy_tools: FFmpegTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from videomanager.domain.project import Project
    from videomanager.domain.project import Track
    from videomanager.domain.project import TrackKind

    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(audio_enabled=False),
    )

    class Playback:
        cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    try:
        media = MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=10.0)
        project = Project(
            tracks=(
                Track(
                    kind=TrackKind.VIDEO,
                    clips=(Clip(media=media, start=0.0, duration=10.0),),
                ),
            )
        )
        panel._project = project
        panel._timeline.set_project(project)
        # Simula o intervalo entre sinais: a tela já mostrou 4,24 s, mas o
        # relógio do áudio atualizou o cursor pela última vez em 4,00 s.
        panel._timeline.set_position(4.0)
        panel._shown_frame = 4.24
        playback = Playback()
        panel._playing = True
        panel._playback = playback
        old_revision = panel._frame_revision
        old_token = panel._frame_token
        requested: list[bool] = []
        primed: list[bool] = []
        monkeypatch.setattr(
            panel, "_request_frame", lambda **kwargs: requested.append(True)
        )
        monkeypatch.setattr(panel, "_prime_playback", lambda: primed.append(True))

        panel._stop_playback()

        assert playback.cancelled
        assert not panel._playing
        assert panel._playback is None
        assert not requested, "o quadro que já está na tela deve permanecer congelado"
        assert primed == [True]
        assert panel._frame_revision == old_revision + 1
        assert panel._frame_token != old_token
        assert panel._position == pytest.approx(4.24)
        assert panel._rendered == pytest.approx(4.24)
    finally:
        panel.shutdown()


def test_clipe_selecionado_escolhe_corte_da_trilha_exata(
    qapp: QApplication,
    dummy_tools: FFmpegTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from videomanager.domain.project import Project
    from videomanager.domain.project import Track
    from videomanager.domain.project import TrackKind

    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(),
    )
    try:
        media = MediaRef(Path("/m/igual.mp4"), MediaKind.VIDEO, duration=8.0)
        upper_left = Clip(media, start=0.0, duration=4.0)
        upper_right = Clip(media, start=4.0, duration=4.0, in_point=4.0)
        lower_left = Clip(media, start=0.0, duration=4.0)
        lower_right = Clip(media, start=4.0, duration=4.0, in_point=4.0)
        project = Project(
            tracks=(
                Track(TrackKind.VIDEO, name="Vídeo superior", clips=(upper_left, upper_right)),
                Track(TrackKind.VIDEO, name="Vídeo inferior", clips=(lower_left, lower_right)),
            )
        )
        panel._project = project
        panel._timeline.set_project(project)
        panel._timeline.select(lower_right.clip_id)

        edit = panel._find_nearest_video_cut(4.0)
        assert edit is not None
        track_index, left, right, cut = edit
        assert track_index == 1
        assert (left.clip_id, right.clip_id) == (
            lower_left.clip_id,
            lower_right.clip_id,
        )
        assert cut == pytest.approx(4.0)

        # Confirma o fluxo completo de inserção sem iniciar workers de mídia.
        monkeypatch.setattr(
            panel,
            "_after_edit",
            lambda **_: panel._timeline.set_project(panel._project),
        )
        panel._insert_transition_clip("dissolve")
        upper_transitions = [clip for clip in panel._project.tracks[0].clips if clip.is_transition]
        lower_transitions = [clip for clip in panel._project.tracks[1].clips if clip.is_transition]
        assert not upper_transitions
        assert len(lower_transitions) == 1
        assert (
            lower_transitions[0].transition_left_id,
            lower_transitions[0].transition_right_id,
        ) == (lower_left.clip_id, lower_right.clip_id)
    finally:
        panel.shutdown()


def test_clipe_selecionado_sem_corte_nao_escolhe_outra_trilha(
    qapp: QApplication,
    dummy_tools: FFmpegTools,
) -> None:
    from videomanager.domain.project import Project
    from videomanager.domain.project import Track
    from videomanager.domain.project import TrackKind

    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(),
    )
    try:
        media = MediaRef(Path("/m/igual.mp4"), MediaKind.VIDEO, duration=8.0)
        valid_left = Clip(media, start=0.0, duration=4.0)
        valid_right = Clip(media, start=4.0, duration=4.0, in_point=4.0)
        isolated = Clip(media, start=0.0, duration=2.0)
        project = Project(
            tracks=(
                Track(TrackKind.VIDEO, clips=(valid_left, valid_right)),
                Track(TrackKind.VIDEO, clips=(isolated,)),
            )
        )
        panel._project = project
        panel._timeline.set_project(project)
        panel._timeline.select(isolated.clip_id)

        assert panel._find_nearest_video_cut(4.0) is None
    finally:
        panel.shutdown()


def test_sem_clipe_selecionado_mantem_corte_global_mais_proximo(
    qapp: QApplication,
    dummy_tools: FFmpegTools,
) -> None:
    from videomanager.domain.project import Project
    from videomanager.domain.project import Track
    from videomanager.domain.project import TrackKind

    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(),
    )
    try:
        media = MediaRef(Path("/m/igual.mp4"), MediaKind.VIDEO, duration=12.0)
        early_left = Clip(media, start=0.0, duration=3.0)
        early_right = Clip(media, start=3.0, duration=3.0, in_point=3.0)
        late_left = Clip(media, start=0.0, duration=7.0)
        late_right = Clip(media, start=7.0, duration=3.0, in_point=7.0)
        project = Project(
            tracks=(
                Track(TrackKind.VIDEO, clips=(early_left, early_right)),
                Track(TrackKind.VIDEO, clips=(late_left, late_right)),
            )
        )
        panel._project = project
        panel._timeline.set_project(project)
        panel._timeline.select(-1)

        edit = panel._find_nearest_video_cut(6.8)
        assert edit is not None
        track_index, left, right, cut = edit
        assert track_index == 1
        assert (left.clip_id, right.clip_id) == (
            late_left.clip_id,
            late_right.clip_id,
        )
        assert cut == pytest.approx(7.0)
    finally:
        panel.shutdown()


def test_video_track_button_positions_and_version(qapp: QApplication) -> None:
    import videomanager
    from videomanager.presentation.qt.panels.timeline import Timeline
    from videomanager.presentation.qt.theme import DARK
    from videomanager.domain.project import Project
    from videomanager.domain.project import Track
    from videomanager.domain.project import TrackKind

    assert videomanager.__version__ == "2.1"

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
    assert svg_icon.is_file() and svg_icon.stat().st_size > 0
    assert res_dir.exists()


def test_opposite_corner_anchored_resizing(qapp: QApplication) -> None:
    from videomanager.presentation.qt.panels.edit_widgets import _Preview
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
    from videomanager.presentation.qt.panels.edit_widgets import _Preview
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
    from videomanager.presentation.qt.panels.edit_panel import EditPanel
    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
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
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
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
    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
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


def test_properties_lock_ratio_independent_scaling(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        panel._text_input.setText("Texto Proporção")
        panel._insert_text_clip()
        clip = panel._project.additional_tracks[0].clips[0]
        panel._open_properties_tab(clip.clip_id)
        pw = panel._properties_widget

        # Proporção travada por padrão
        assert pw._chk_lock_ratio.isChecked()
        init_w = pw._spin_w.value()
        init_h = pw._spin_h.value()
        _ = init_w / init_h

        # Altera largura: altura deve mudar proporcionalmente
        pw._spin_w.setValue(init_w * 2)
        assert abs(pw._spin_h.value() - (init_h * 2)) <= 1
        updated = panel._project.find(clip.clip_id)[1]
        assert abs(updated.scale_x - updated.scale_y) < 0.01

        # Agora desmarca a trava de proporção
        pw._chk_lock_ratio.setChecked(False)
        assert not pw._chk_lock_ratio.isChecked()

        # Altera largura sem mudar altura
        cur_h = pw._spin_h.value()
        pw._spin_w.setValue(init_w * 3)
        assert pw._spin_h.value() == cur_h
        updated = panel._project.find(clip.clip_id)[1]
        assert updated.scale_x > updated.scale_y

        # Altera altura sem mudar largura
        cur_w = pw._spin_w.value()
        pw._spin_h.setValue(init_h * 4)
        assert pw._spin_w.value() == cur_w
        updated = panel._project.find(clip.clip_id)[1]
        assert updated.scale_y > updated.scale_x
    finally:
        panel.shutdown()


def test_properties_edit_when_deselected_reselects_and_updates_preview(
    qapp: QApplication, dummy_tools: FFmpegTools
) -> None:
    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        panel._text_input.setText("Item Desselecionado")
        panel._insert_text_clip()
        clip = panel._project.additional_tracks[0].clips[0]
        panel._open_properties_tab(clip.clip_id)

        # Desseleciona o item na timeline
        panel._timeline.select(-1)
        assert panel._timeline.selected == -1
        assert panel._timeline.selected_clip is None

        # Edita posição na aba de propriedades
        panel._properties_widget._spin_x.setValue(400)

        # O clipe deve ter sido re-selecionado automaticamente
        assert panel._timeline.selected == clip.clip_id
        assert panel._preview._active_clip is not None
        assert panel._preview._active_clip.clip_id == clip.clip_id
        assert abs(panel._preview._active_clip.x - (400 / panel._project.width)) < 0.001
    finally:
        panel.shutdown()


def test_event_filter_extras_panel_no_deselection(
    qapp: QApplication, dummy_tools: FFmpegTools
) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        panel._text_input.setText("Item EventFilter")
        panel._insert_text_clip()
        clip = panel._project.additional_tracks[0].clips[0]
        panel._open_properties_tab(clip.clip_id)
        assert panel._timeline.selected == clip.clip_id

        # Simula clique no fundo do QGroupBox de transformação da aba de propriedades
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        panel.eventFilter(panel._properties_widget._transform_group, event)

        # Item deve continuar selecionado!
        assert panel._timeline.selected == clip.clip_id
    finally:
        panel.shutdown()


def test_snap_magnetic_resize_and_escape(qapp: QApplication) -> None:
    preview = _Preview()
    preview.resize(800, 600)
    clip = Clip(
        media=None,
        start=0.0,
        duration=5.0,
        overlay_type="text",
        text_content="Teste Snap Resize",
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

    # 1. Simula início de arraste pela alça inferior direita (scale_br)
    preview._drag_mode = "scale_br"
    preview._drag_clip_id = clip.clip_id
    preview._drag_sx = 1.0
    preview._drag_sy = 1.0
    preview._drag_w0 = w
    preview._drag_h0 = h
    preview._drag_opp_x = cx - w / 2.0
    preview._drag_opp_y = cy - h / 2.0
    preview._drag_init_scale = 1.0
    preview._drag_init_rot = 0.0

    # Posição onde a borda direita ficaria a 4px de vrect_right (dentro do limiar de 14px)
    vrect_right = float(vrect.x() + vrect.width())
    target_x = vrect_right - 4.0
    # Como a proporção w:h é mantida na projeção raw_factor, calculamos dy correspondente
    scale_factor = (target_x - preview._drag_opp_x) / w
    target_y = preview._drag_opp_y + scale_factor * h

    move_event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(target_x, target_y),
        QPointF(target_x, target_y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_event)

    # Deve acionar o snap magnético com guia em vrect_right
    assert preview._snap_guide_x == vrect_right
    geom_snapped = preview._clip_geometry(preview._active_clip)
    assert geom_snapped is not None
    scx, scy, sw, sh = geom_snapped
    assert abs((scx + sw / 2.0) - vrect_right) < 0.01

    # 2. Força o redimensionamento para fora da margem de snap (> 14px)
    forced_target_x = vrect_right + 35.0
    forced_scale = (forced_target_x - preview._drag_opp_x) / w
    forced_target_y = preview._drag_opp_y + forced_scale * h

    move_forced = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(forced_target_x, forced_target_y),
        QPointF(forced_target_x, forced_target_y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_forced)

    # O snap deve desarmar (escape livre)
    assert preview._snap_guide_x is None
    geom_forced = preview._clip_geometry(preview._active_clip)
    assert geom_forced is not None
    fcx, fcy, fw, fh = geom_forced
    assert (fcx + fw / 2.0) > vrect_right + 10.0

    # 3. mouseReleaseEvent limpa as guias
    release_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(forced_target_x, forced_target_y),
        QPointF(forced_target_x, forced_target_y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseReleaseEvent(release_event)
    assert preview._snap_guide_x is None
    assert preview._snap_guide_y is None
    assert preview._drag_mode is None


def test_properties_resize_anchored_bottom_left_right_and_up(
    qapp: QApplication, dummy_tools: FFmpegTools
) -> None:
    """Verifica que alterar largura/altura na aba de propriedades expande apenas

    para a direita e para cima, mantendo o canto inferior esquerdo estático.
    """
    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        panel._text_input.setText("Âncora BL")
        panel._insert_text_clip()
        clip = panel._project.additional_tracks[0].clips[0]
        panel._open_properties_tab(clip.clip_id)
        pw = panel._properties_widget

        pw._chk_lock_ratio.setChecked(False)

        init_w = pw._spin_w.value()
        init_h = pw._spin_h.value()
        init_px = pw._spin_x.value()
        init_py = pw._spin_y.value()

        # Bordas iniciais
        init_left = init_px - init_w / 2.0
        init_right = init_px + init_w / 2.0
        init_bottom = init_py + init_h / 2.0
        init_top = init_py - init_h / 2.0

        # 1. Aumenta apenas a largura em 60px
        pw._spin_w.setValue(init_w + 60)
        new_w = pw._spin_w.value()
        new_px = pw._spin_x.value()
        new_py = pw._spin_y.value()

        # Borda esquerda deve continuar IDÊNTICA
        assert abs((new_px - new_w / 2.0) - init_left) < 0.5
        # Borda direita deve ter expandido exatamente para a direita
        assert (new_px + new_w / 2.0) > init_right + 50
        # Eixo Y deve permanecer inalterado
        assert new_py == init_py

        # 2. Aumenta apenas a altura em 40px
        pw._spin_h.setValue(init_h + 40)
        h_new_w = pw._spin_w.value()
        h_new_h = pw._spin_h.value()
        h_new_px = pw._spin_x.value()
        h_new_py = pw._spin_y.value()

        # Borda inferior (bottom) deve continuar IDÊNTICA
        assert abs((h_new_py + h_new_h / 2.0) - init_bottom) < 0.5
        # Borda superior (top) deve ter expandido para cima (menor Y)
        assert (h_new_py - h_new_h / 2.0) < init_top - 30
        # Borda esquerda continua mantida
        assert abs((h_new_px - h_new_w / 2.0) - init_left) < 0.5

        # 3. Trava a proporção e expande via escala
        pw._chk_lock_ratio.setChecked(True)
        cur_left = h_new_px - h_new_w / 2.0
        cur_bottom = h_new_py + h_new_h / 2.0
        pw._spin_scale.setValue(pw._spin_scale.value() * 1.5)

        scale_w = pw._spin_w.value()
        scale_h = pw._spin_h.value()
        scale_px = pw._spin_x.value()
        scale_py = pw._spin_y.value()

        # O canto inferior esquerdo permanece intacto!
        assert abs((scale_px - scale_w / 2.0) - cur_left) < 1.0
        assert abs((scale_py + scale_h / 2.0) - cur_bottom) < 1.0
        # E expandiu para a direita e para cima
        assert (scale_px + scale_w / 2.0) > (h_new_px + h_new_w / 2.0)
        assert (scale_py - scale_h / 2.0) < (h_new_py - h_new_h / 2.0)
    finally:
        panel.shutdown()


def test_calibri_and_rapier_zero_fonts_availability(qapp: QApplication) -> None:
    """Verifica que Calibri e Rapier Zero estão disponíveis no seletor e renderizam com sucesso."""
    from videomanager.infrastructure.qt.text import QtTextRasterizer
    render_text_to_image = QtTextRasterizer().render
    from videomanager.domain.project import Clip
    from videomanager.presentation.qt.fonts import ensure_application_fonts
    from videomanager.presentation.qt.panels.edit_widgets import _FontSelectorWidget

    ensure_application_fonts()
    selector = _FontSelectorWidget("Calibri")

    all_fonts = [selector._font_list.item(i).text() for i in range(selector._font_list.count())]
    assert "Calibri" in all_fonts
    assert "Rapier Zero" in all_fonts
    assert "Rapier Zero Hollow" in all_fonts

    # Teste de seleção de Rapier Zero
    for i in range(selector._font_list.count()):
        item = selector._font_list.item(i)
        if item.text() == "Rapier Zero":
            selector._on_item_clicked(item)
            break
    assert selector.current_family() == "Rapier Zero"

    # Teste de renderização gráfica com as duas fontes
    clip_rapier = Clip(
        media=None,
        start=0.0,
        duration=5.0,
        overlay_type="text",
        text_content="Rapier Zero Font Test",
        font_family="Rapier Zero",
        font_size=32,
    )
    img_rapier = render_text_to_image(clip_rapier)
    assert img_rapier.is_file() and img_rapier.stat().st_size > 0

    clip_calibri = Clip(
        media=None,
        start=0.0,
        duration=5.0,
        overlay_type="text",
        text_content="Calibri Font Test",
        font_family="Calibri",
        font_size=32,
    )
    img_calibri = render_text_to_image(clip_calibri)
    assert img_calibri.is_file() and img_calibri.stat().st_size > 0


def test_preview_video_drag_does_not_drag_or_teleport_overlays(
    qapp: QApplication, dummy_tools: FFmpegTools, tmp_path: Path
) -> None:
    """Garante que arrastar um vídeo no preview não arrasta nem teleporta sobreposições."""
    img_path = tmp_path / "overlay.png"
    pix = QPixmap(100, 100)
    pix.fill(Qt.GlobalColor.cyan)
    pix.save(str(img_path))

    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(),
    )
    panel.resize(1280, 720)
    panel.show()

    # Cria projeto com trilha adicional (imagem) e trilha de vídeo
    media_vid = MediaRef(Path("/dummy/video.mp4"), kind=MediaKind.VIDEO, duration=10.0, width=1920, height=1080)
    media_img = MediaRef(img_path, kind=MediaKind.IMAGE, duration=5.0, width=100, height=100)
    clip_vid = Clip(media=media_vid, start=0.0, duration=10.0, clip_id=1, x=0.5, y=0.5)
    clip_img = Clip(media=media_img, start=0.0, duration=5.0, clip_id=2, x=0.2, y=0.2, overlay_type="image")

    track_add = Track(TrackKind.ADDITIONAL, clips=(clip_img,), name="Adicionais")
    track_vid = Track(TrackKind.VIDEO, clips=(clip_vid,), name="Vídeo")
    project = Project(tracks=(track_add, track_vid), width=1920, height=1080, fps=30)
    panel._apply(project)
    panel._seek_to(1.0)

    # Verifica que _update_preview_overlay_clips identificou a imagem da trilha de adicionais
    assert len(panel._preview._overlay_clips) == 1
    assert panel._preview._overlay_clips[0].clip_id == 2

    # Seleciona o clipe de vídeo para arrastar
    panel._timeline.select(1)
    assert panel._preview._active_clip is not None
    assert panel._preview._active_clip.clip_id == 1

    # Simula quadro renderizado no preview
    frame_pix = QPixmap(800, 600)
    frame_pix.fill(Qt.GlobalColor.blue)
    panel._preview.set_frame_pixmap(frame_pix)

    geom_vid = panel._preview._clip_geometry(clip_vid)
    assert geom_vid is not None
    cx_vid, cy_vid, _, _ = geom_vid

    # Inicia arraste do vídeo
    press_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(cx_vid, cy_vid),
        QPointF(cx_vid, cy_vid),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel._preview.mousePressEvent(press_event)
    assert panel._preview._drag_mode == "move"
    assert panel._preview._drag_clip_id == 1

    # Move o vídeo
    move_event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(cx_vid + 50, cy_vid + 30),
        QPointF(cx_vid + 50, cy_vid + 30),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel._preview.mouseMoveEvent(move_event)

    # Durante o arraste, o clipe de overlay permanece com suas coordenadas intactas
    assert len(panel._preview._overlay_clips) == 1
    assert panel._preview._overlay_clips[0].clip_id == 2
    assert panel._preview._overlay_clips[0].x == 0.2
    assert panel._preview._overlay_clips[0].y == 0.2

    # Renderiza para garantir integridade do paintEvent
    panel._preview.repaint()

    # Solta o mouse
    release_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(cx_vid + 50, cy_vid + 30),
        QPointF(cx_vid + 50, cy_vid + 30),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel._preview.mouseReleaseEvent(release_event)
    assert panel._preview._drag_mode is None

    # O clipe de imagem continua em x=0.2, y=0.2 sem ter sido arrastado ou teleportado
    found_img = panel._project.find(2)
    assert found_img is not None
    assert found_img[1].x == 0.2
    assert found_img[1].y == 0.2

    # Clicar sobre o clipe de sobreposição deve selecioná-lo na timeline
    geom_img = panel._preview._clip_geometry(clip_img)
    assert geom_img is not None
    cx_img, cy_img, _, _ = geom_img
    click_img_event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(cx_img, cy_img),
        QPointF(cx_img, cy_img),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel._preview.mousePressEvent(click_img_event)
    assert panel._timeline.selected == 2
    panel.shutdown()



def test_edit_panel_save_as_button(dummy_tools: FFmpegTools) -> None:
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.bootstrap import build_editor_service, build_processing_service, build_desktop_runtime
    from videomanager.presentation.qt.panels.edit_panel import EditPanel
    from videomanager.presentation.qt import strings

    panel = EditPanel(
        settings=Settings(),
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(),
    )
    assert hasattr(panel, "_save_as_btn")
    assert panel._save_as_btn.text() == strings.EDIT_SAVE_AS_BUTTON

    # Testa acionamento do botão chamando save_project_as
    saved_as_called = False

    def mock_save_as() -> bool:
        nonlocal saved_as_called
        saved_as_called = True
        return True

    panel.save_project_as = mock_save_as
    panel._save_as_btn.click()
    assert saved_as_called
    panel.shutdown()


def test_preview_drag_resize_animated_clip() -> None:
    from dataclasses import replace
    from videomanager.domain.keyframe import create_preset_keyframes
    from videomanager.domain.project import Clip, MediaKind, MediaRef
    from videomanager.presentation.qt.panels.edit_widgets import _Preview

    media = MediaRef(
        path=Path("/tmp/fake_anim.webp"),
        kind=MediaKind.IMAGE,
        duration=None,
        width=800,
        height=600,
        fps=25.0,
        has_audio=False,
        channels=None,
    )
    clip = Clip(
        clip_id=10,
        start=0.0,
        duration=5.0,
        media=media,
        x=0.5,
        y=0.5,
        scale=1.0,
        scale_x=1.0,
        scale_y=1.0,
        rotation=0.0,
        opacity=1.0,
        keyframes=(),
    )
    # Adiciona animação preset slide_up
    kfs = create_preset_keyframes("slide_up", clip.base_transform, duration=0.6)
    clip = replace(clip, keyframes=kfs)

    preview = _Preview()
    preview.resize(960, 540)
    preview.set_active_clip(clip, 1920, 1080)
    preview.set_position(0.3)
    preview._whole_animation = True  # D02: escopo global solicitado explicitamente.

    geom_before = preview._clip_geometry(clip)
    assert geom_before is not None
    cx, cy, w, h = geom_before

    br_pos = QPointF(cx + w / 2, cy + h / 2)
    press_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        br_pos,
        br_pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mousePressEvent(press_ev)
    assert preview._drag_mode == "scale_br"

    # Arrasta para ampliar
    move_pos = QPointF(cx + w / 2 + 80, cy + h / 2 + 80)
    move_ev = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        move_pos,
        move_pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_ev)

    # Verifica que a geometria ativa e os keyframes aumentaram juntos
    geom_after = preview._clip_geometry(preview._active_clip)
    assert geom_after is not None
    assert geom_after[2] > w
    assert geom_after[3] > h
    assert len(preview._active_clip.keyframes) == 2
    assert preview._active_clip.keyframes[0].scale_x == preview._active_clip.keyframes[1].scale_x
    assert preview._active_clip.keyframes[0].scale_x > 1.0


def test_clip_properties_widget_animated_clip_sync() -> None:
    from dataclasses import replace
    from videomanager.domain.keyframe import create_preset_keyframes
    from videomanager.domain.project import Clip, MediaKind, MediaRef
    from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget

    media = MediaRef(
        path=Path("/tmp/fake_prop_sync.webp"),
        kind=MediaKind.IMAGE,
        duration=None,
        width=1200,
        height=800,
        fps=25.0,
        has_audio=False,
        channels=None,
    )
    clip = Clip(
        clip_id=11,
        start=0.0,
        duration=5.0,
        media=media,
        x=0.5,
        y=0.5,
        scale=1.0,
        scale_x=1.0,
        scale_y=1.0,
        rotation=0.0,
        opacity=1.0,
        keyframes=(),
    )
    kfs = create_preset_keyframes("slide_up", clip.base_transform, duration=0.6)
    clip = replace(clip, keyframes=kfs)

    widget = _ClipPropertiesWidget()
    widget.load_clip(clip, 1920, 1080)
    # Ajustada à tela: 1200×800 ocupa a altura de 1080.
    assert widget._spin_w.value() == 1620
    assert widget._spin_h.value() == 1080

    # Move o cursor para o meio da animação
    widget.set_playhead_position(0.3)
    widget._whole_animation.setChecked(True)
    assert widget._spin_w.value() == 1620
    assert widget._spin_h.value() == 1080

    # Altera a largura para 810, metade do tamanho base
    changes_emitted: list[dict] = []
    widget.property_changed.connect(lambda cid, ch: changes_emitted.append(ch))
    widget._spin_w.setValue(810)

    assert changes_emitted
    last_ch = changes_emitted[-1]
    assert "keyframes" in last_ch
    new_kfs = last_ch["keyframes"]
    # A escala uniforme deve ter sido aplicada a todos os keyframes
    assert abs(new_kfs[0].scale_x - 0.5) < 0.02
    assert abs(new_kfs[1].scale_x - 0.5) < 0.02


def test_preview_scale_handle_with_rotated_keyframe(qapp: QApplication) -> None:
    from videomanager.domain.keyframe import Keyframe

    # Clip with rotation 0 at base, but keyframe has rotation 180 (like in projeto.vmp)
    kf1 = Keyframe(time_offset=0.0, x=0.5, y=0.5, scale_x=0.7, scale_y=0.7, rotation=0.0)
    kf2 = Keyframe(time_offset=1.0, x=0.5, y=0.5, scale_x=0.7, scale_y=0.7, rotation=180.0)
    kf3 = Keyframe(time_offset=2.0, x=0.5, y=0.5, scale_x=0.9, scale_y=0.9, rotation=180.0)

    clip = Clip(
        clip_id=10,
        start=0.0,
        duration=5.0,
        x=0.5,
        y=0.5,
        scale_x=0.7,
        scale_y=0.7,
        rotation=0.0,
        overlay_type="image",
        media=MediaRef(
            path=Path("/tmp/fake.png"),
            kind=MediaKind.IMAGE,
            duration=None,
            width=800,
            height=600,
            fps=30.0,
            has_audio=False,
        ),
        keyframes=(kf1, kf2, kf3),
    )

    preview = _Preview()
    preview.resize(960, 540)
    preview.set_active_clip(clip, 1920, 1080)
    # Position at 1.5s where rotation is 180 degrees
    preview.set_position(1.5)

    geom = preview._clip_geometry(clip)
    assert geom is not None
    cx, cy, w, h = geom

    # At 180 degrees rotation, the local BR corner (w/2, h/2) is visually at (cx - w/2, cy - h/2)
    # in screen coordinates
    rad = math.radians(180.0)
    screen_br_x = cx + (w / 2.0) * math.cos(rad) - (h / 2.0) * math.sin(rad)
    screen_br_y = cy + (w / 2.0) * math.sin(rad) + (h / 2.0) * math.cos(rad)

    br_pos = QPointF(screen_br_x, screen_br_y)
    press_ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        br_pos,
        br_pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mousePressEvent(press_ev)
    assert preview._drag_mode == "scale_br"

    # Opposite corner should be around (cx + w/2, cy + h/2), distance should be hypot(w, h), NOT ~0
    opp_dist = math.hypot(preview._drag_opp_x - screen_br_x, preview._drag_opp_y - screen_br_y)
    assert opp_dist > math.hypot(w, h) * 0.9

    # Drag outward to expand
    move_pos = QPointF(screen_br_x - 50, screen_br_y - 50)
    move_ev = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        move_pos,
        move_pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    preview.mouseMoveEvent(move_ev)

    # Scale must have increased, not collapsed
    assert preview._active_clip.transform_at(1.5).scale_x > 0.8
    assert preview._active_clip.keyframes[0] == kf1
    assert preview._active_clip.keyframes[1] == kf2
    assert len(preview._active_clip.keyframes) == 4


def test_filter_clip_preserved_in_paused_frame_preview(
    qapp: QApplication, dummy_tools: FFmpegTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings()
    panel = EditPanel(
        settings=settings,
        ensure_tools=lambda: dummy_tools,
        editor=build_editor_service(),
        processing=build_processing_service(),
        runtime=build_desktop_runtime(),
    )
    try:
        ref_v = MediaRef(
            path=Path("/tmp/video.mp4"),
            kind=MediaKind.VIDEO,
            duration=10.0,
            width=1920,
            height=1080,
        )
        c_video = Clip(media=ref_v, start=0.0, duration=10.0)
        t_video = Track(kind=TrackKind.VIDEO, clips=(c_video,))

        ref_f = MediaRef(path=Path("Filtro_PB"), kind=MediaKind.IMAGE, duration=5.0)
        c_filter = Clip(
            media=ref_f,
            start=1.0,
            duration=5.0,
            overlay_type="filter",
            filter_name="pb",
        )
        t_filter = Track(kind=TrackKind.ADDITIONAL, clips=(c_filter,))

        panel._project = Project(tracks=(t_filter, t_video), width=1920, height=1080, fps=30.0)
        panel._sync_canvas()

        captured_project = None
        orig_frame_worker = panel._runtime.frame_worker

        def mock_frame_worker(proj, seconds, size, tools, token, **kwargs):
            nonlocal captured_project
            captured_project = proj
            return orig_frame_worker(proj, seconds, size, tools, token, **kwargs)

        monkeypatch.setattr(panel._runtime, "frame_worker", mock_frame_worker)

        panel._playing = False
        panel._wanted = 2.0
        panel._start_frame()

        assert captured_project is not None
        filter_clips = [
            c for t in captured_project.tracks for c in t.clips if c.overlay_type == "filter"
        ]
        assert len(filter_clips) == 1
        assert filter_clips[0].filter_name == "pb"

        panel._timeline.set_position(2.0)
        panel._update_preview_overlay_clips()
        assert not any(c.overlay_type == "filter" for c in panel._preview._overlay_clips)

        # Mover a agulha/guia da trilha via _on_scrub com vídeo pausado
        panel._frame_busy = False
        captured_project = None
        panel._timeline.set_position(3.5)
        panel._on_scrub(3.5)
        assert captured_project is not None
        filter_clips_scrub = [
            c for t in captured_project.tracks for c in t.clips if c.overlay_type == "filter"
        ]
        assert len(filter_clips_scrub) == 1
        assert filter_clips_scrub[0].filter_name == "pb"
    finally:
        panel.shutdown()


# Estes cenários exercitam adaptadores ou apresentação Qt.
pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")


def test_opcao_escolhida_nas_abas_de_adicionais_tem_a_medida_de_marcada(qapp: QApplication,
                                                                       dummy_tools: FFmpegTools) -> None:
    """O estado marcado muda borda e peso da fonte, e o QPushButton não refaz a
    dica de tamanho ao ser marcado: a opção escolhida ficava com a altura da
    desmarcada, e a anterior com a da marcada."""
    from videomanager.presentation.qt.theme import stylesheet
    anterior = qapp.styleSheet()
    qapp.setStyleSheet(stylesheet("dark"))
    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools, editor=build_editor_service(),
                      processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        panel.show()
        qapp.processEvents()
        panel._select_filter("sepia")
        alturas = dict(zip(panel._filter_specs, (b.sizeHint().height() for b in panel._filter_buttons)))
        assert alturas["sepia"] > alturas["pb"]
        panel._select_transition("wipeleft")
        alturas = dict(zip(panel._trans_specs, (b.sizeHint().height() for b in panel._trans_buttons)))
        assert alturas["wipeleft"] > alturas["fade"]
    finally:
        panel.shutdown()
        qapp.setStyleSheet(anterior)
