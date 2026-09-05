from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from videomanager.core.binaries import FFmpegTools
from videomanager.core.converter import LocalMedia, LocalStream
from videomanager.core.job import JobKind
from videomanager.core.project import (
    Clip,
    MediaKind,
    MediaRef,
    Project,
    TrackKind,
    new_project,
)
from videomanager.core.settings import Settings
from videomanager.ui.export_dialog import ExportDialog
from videomanager.ui.panels.edit_panel import EditPanel


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def dummy_tools(tmp_path: Path) -> FFmpegTools:
    ff = tmp_path / "ffmpeg"
    fp = tmp_path / "ffprobe"
    ff.write_text("#!/bin/sh\nexit 0\n")
    fp.write_text("#!/bin/sh\nexit 0\n")
    ff.chmod(0o755)
    fp.chmod(0o755)
    return FFmpegTools(ffmpeg=ff, ffprobe=fp, source="sistema")


@pytest.fixture
def sample_media(tmp_path: Path) -> tuple[MediaRef, LocalMedia]:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"dummy video data")
    ref = MediaRef(
        path=video_path,
        kind=MediaKind.VIDEO,
        duration=60.0,
        width=1920,
        height=1080,
        fps=30.0,
        has_audio=True,
    )
    v_stream = LocalStream(
        index=0, kind="video", codec="h264", width=1920, height=1080, fps=30.0
    )
    a_stream = LocalStream(index=1, kind="audio", codec="aac", channels=2)
    local = LocalMedia(
        path=video_path,
        duration=60.0,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        size=1024,
        streams=(v_stream, a_stream),
    )
    return ref, local


@pytest.fixture
def single_clip_project(sample_media: tuple[MediaRef, LocalMedia]) -> Project:
    ref, _ = sample_media
    proj = new_project()
    proj = proj.with_track(TrackKind.VIDEO)
    clip = Clip(media=ref, start=0.0, duration=30.0)
    return proj.with_clip(0, clip)


def test_export_dialog_initialization(
    qapp: QApplication,
    sample_media: tuple[MediaRef, LocalMedia],
    single_clip_project: Project,
    dummy_tools: FFmpegTools,
) -> None:
    ref, local = sample_media
    settings = Settings()
    dialog = ExportDialog(
        project=single_clip_project,
        settings=settings,
        pool=[ref],
        probed={ref.path: local},
        keyframes=(0.0, 5.0, 10.0),
        ensure_tools=lambda: dummy_tools,
    )

    assert dialog.windowTitle() != ""
    assert dialog._canvas_box.count() > 1
    assert dialog._rate_box.count() > 1
    # Corte rápido deve estar disponível para projeto com clipe único
    assert dialog._fast.isEnabled()
    assert dialog._same_folder.isChecked()
    assert not dialog._dest_edit.isEnabled()
    assert not dialog._pick_folder_button.isEnabled()


def test_export_dialog_toggle_same_folder(
    qapp: QApplication,
    sample_media: tuple[MediaRef, LocalMedia],
    single_clip_project: Project,
    dummy_tools: FFmpegTools,
) -> None:
    ref, local = sample_media
    settings = Settings()
    dialog = ExportDialog(
        project=single_clip_project,
        settings=settings,
        pool=[ref],
        probed={ref.path: local},
        ensure_tools=lambda: dummy_tools,
    )

    dialog._same_folder.setChecked(False)
    assert dialog._dest_edit.isEnabled()
    assert dialog._pick_folder_button.isEnabled()

    dialog._same_folder.setChecked(True)
    assert not dialog._dest_edit.isEnabled()
    assert not dialog._pick_folder_button.isEnabled()


def test_export_dialog_enqueue_fast_cut(
    qapp: QApplication,
    sample_media: tuple[MediaRef, LocalMedia],
    single_clip_project: Project,
    dummy_tools: FFmpegTools,
) -> None:
    ref, local = sample_media
    settings = Settings()
    dialog = ExportDialog(
        project=single_clip_project,
        settings=settings,
        pool=[ref],
        probed={ref.path: local},
        keyframes=(0.0, 5.0, 10.0),
        ensure_tools=lambda: dummy_tools,
    )

    dialog._fast.setChecked(True)
    dialog._on_enqueue()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.created_job is not None
    assert dialog.created_job.kind == JobKind.TRIM
    assert "target" in dialog.created_job.opts


def test_export_dialog_enqueue_composition(
    qapp: QApplication,
    sample_media: tuple[MediaRef, LocalMedia],
    single_clip_project: Project,
    dummy_tools: FFmpegTools,
) -> None:
    ref, local = sample_media
    settings = Settings()
    dialog = ExportDialog(
        project=single_clip_project,
        settings=settings,
        pool=[ref],
        probed={ref.path: local},
        ensure_tools=lambda: dummy_tools,
    )

    dialog._fast.setChecked(False)
    dialog._on_enqueue()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.created_job is not None
    assert dialog.created_job.kind == JobKind.TRIM


def test_export_dialog_custom_filename(
    qapp: QApplication,
    sample_media: tuple[MediaRef, LocalMedia],
    single_clip_project: Project,
    dummy_tools: FFmpegTools,
) -> None:
    ref, local = sample_media
    settings = Settings()
    dialog = ExportDialog(
        project=single_clip_project,
        settings=settings,
        pool=[ref],
        probed={ref.path: local},
        ensure_tools=lambda: dummy_tools,
    )
    assert hasattr(dialog, "_filename_edit")
    assert hasattr(dialog, "_ext_label")
    assert dialog._ext_label.text() in (".mp4", ".mkv", ".webm")

    dialog._filename_edit.setText("meu_video_personalizado")
    dialog._on_enqueue()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.created_job is not None
    dest_path = Path(dialog.created_job.opts["destination"])
    assert "meu_video_personalizado" in dest_path.name


def test_edit_panel_top_layout_and_media_list(
    qapp: QApplication,
    sample_media: tuple[MediaRef, LocalMedia],
    dummy_tools: FFmpegTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref, local = sample_media
    monkeypatch.setattr(
        "videomanager.ui.panels.edit_panel.probe_file", lambda p, t: local
    )
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)

    try:
        # Verifica os novos componentes de layout estilo CapCut
        assert hasattr(panel, "_top_splitter")
        assert hasattr(panel, "_media_box")
        assert hasattr(panel, "_player_box")
        assert hasattr(panel, "_media_list")
        assert hasattr(panel, "_export_button")

        # Inicialmente vazio
        assert panel._media_list.count() == 0
        assert not panel._export_button.isEnabled()

        # Importa mídia
        panel.import_files([ref.path], insert=True)
        assert panel._media_list.count() == 1
        assert panel._export_button.isEnabled()
        assert not panel._project.is_empty

        # Inserção adicional pelo botão/duplo clique
        panel._media_list.setCurrentRow(0)
        assert panel._insert.isEnabled()
        initial_clips = len(panel._project.clips)
        panel._insert_selected_media()
        assert len(panel._project.clips) == initial_clips + 1
    finally:
        panel.shutdown()


def test_export_after_loading_saved_project(
    qapp: QApplication,
    sample_media: tuple[MediaRef, LocalMedia],
    dummy_tools: FFmpegTools,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from videomanager.core.project_io import save_project, load_project
    ref, local = sample_media
    monkeypatch.setattr(
        "videomanager.ui.panels.edit_panel.probe_file", lambda p, t: local
    )
    monkeypatch.setattr(
        "videomanager.ui.export_dialog.probe_file", lambda p, t: local
    )
    settings = Settings()
    proj = new_project().with_track(TrackKind.VIDEO)
    clip_video = Clip(media=ref, start=0.0, duration=10.0)
    clip_text = Clip(
        media=MediaRef(path=Path("Texto_Titulo"), kind=MediaKind.IMAGE),
        start=0.0,
        duration=5.0,
        overlay_type="text",
        text_content="Titulo",
    )
    clip_trans = Clip(
        media=MediaRef(path=Path("Transição_Fade"), kind=MediaKind.IMAGE),
        start=5.0,
        duration=1.0,
        overlay_type="transition",
        transition_name="fade_black",
    )
    proj = proj.with_clip(0, clip_video)
    proj = proj.with_track(TrackKind.VIDEO).with_clip(1, clip_text).with_clip(1, clip_trans)

    proj_file = tmp_path / "projeto_teste.vmp"
    save_project(proj, proj_file)

    loaded_proj, missing = load_project(proj_file, dummy_tools)
    assert missing == []

    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools)
    try:
        loaded = panel.open_project(proj_file)
        assert loaded is True
        assert ref.path in panel._probed
        assert isinstance(panel._probed[ref.path], LocalMedia)

        # Abre o ExportDialog como o usuário faria após abrir o projeto
        dialog = ExportDialog(
            project=panel._project,
            settings=settings,
            pool=panel._pool,
            probed=panel._probed,
            keyframes=panel._keyframes,
            ensure_tools=lambda: dummy_tools,
            project_path=panel._project_path,
        )
        assert "editado" in dialog._filename_edit.text()
        dialog._on_enqueue()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.created_job is not None
        assert "target" in dialog.created_job.opts
    finally:
        panel.shutdown()

