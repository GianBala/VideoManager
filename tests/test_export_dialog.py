from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import LocalStream
from videomanager.application.jobs.models import JobKind
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.domain.project import new_project
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt.export_dialog import ExportDialog
from videomanager.presentation.qt.panels.edit_panel import EditPanel
from videomanager.bootstrap import build_editor_service
from videomanager.bootstrap import build_processing_service
from videomanager.bootstrap import build_desktop_runtime


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
     processing=build_processing_service(), runtime=build_desktop_runtime())

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
     processing=build_processing_service(), runtime=build_desktop_runtime())

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
     processing=build_processing_service(), runtime=build_desktop_runtime())

    dialog._fast.setChecked(True)
    dialog._on_enqueue()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.created_job is not None
    assert dialog.created_job.kind == JobKind.TRIM
    assert dialog.created_job.request.target is not None


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
     processing=build_processing_service(), runtime=build_desktop_runtime())

    dialog._fast.setChecked(False)
    dialog._on_enqueue()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.created_job is not None
    assert dialog.created_job.kind == JobKind.EXPORT


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
     processing=build_processing_service(), runtime=build_desktop_runtime())
    assert hasattr(dialog, "_filename_edit")
    assert hasattr(dialog, "_ext_label")
    assert dialog._ext_label.text() in (".mp4", ".mkv", ".webm")

    dialog._filename_edit.setText("meu_video_personalizado")
    dialog._on_enqueue()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.created_job is not None
    dest_path = Path(dialog.created_job.request.destination)
    assert "meu_video_personalizado" in dest_path.name


def test_edit_panel_top_layout_and_media_list(
    qapp: QApplication,
    sample_media: tuple[MediaRef, LocalMedia],
    dummy_tools: FFmpegTools,
    monkeypatch: pytest.MonkeyPatch,
    wait_until,
) -> None:
    ref, local = sample_media
    monkeypatch.setattr(
        "videomanager.infrastructure.qt.workers.media_worker.probe_file", lambda p, t, **kw: local
    )
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())

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
        wait_until(lambda: not panel._project_actions.busy)
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
    wait_until,
) -> None:
    from videomanager.infrastructure.storage.project_json import save_project
    from videomanager.infrastructure.storage.project_json import load_project
    ref, local = sample_media
    monkeypatch.setattr(
        "videomanager.infrastructure.qt.workers.media_worker.probe_file", lambda p, t, **kw: local
    )
    monkeypatch.setattr(
        "videomanager.infrastructure.ffmpeg.catalog.probe_file", lambda p, t: local
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

    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        loaded = panel.open_project(proj_file)
        wait_until(lambda: not panel._project_actions.busy)
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
         processing=build_processing_service(), runtime=build_desktop_runtime())
        assert "editado" in dialog._filename_edit.text()
        dialog._on_enqueue()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.created_job is not None
        assert dialog.created_job.request.target is not None
    finally:
        panel.shutdown()


def test_export_dialog_with_hidden_tracks_ignores_them(
    qapp: QApplication,
    sample_media: tuple[MediaRef, LocalMedia],
    dummy_tools: FFmpegTools,
    tmp_path: Path,
) -> None:
    ref1, local1 = sample_media  # 1920x1080 @ 30fps

    video4k_path = tmp_path / "video4k.mp4"
    video4k_path.write_bytes(b"dummy 4k data")
    ref4k = MediaRef(
        path=video4k_path,
        kind=MediaKind.VIDEO,
        duration=30.0,
        width=3840,
        height=2160,
        fps=60.0,
        has_audio=True,
    )
    local4k = LocalMedia(
        path=video4k_path,
        duration=30.0,
        format_name="mov,mp4",
        size=4096,
        streams=(
            LocalStream(index=0, kind="video", codec="h264", width=3840, height=2160, fps=60.0),
        ),
    )

    c1 = Clip(media=ref1, start=0.0, duration=10.0)
    c4k = Clip(media=ref4k, start=0.0, duration=30.0)
    c_aud = Clip(media=ref1, start=0.0, duration=40.0)

    # Trilha 0 (1080p visível), Trilha 1 (4K oculta), Trilha 2 (Áudio mudo)
    t0 = Track(kind=TrackKind.VIDEO, clips=(c1,), visible=True)
    t1_4k = Track(kind=TrackKind.VIDEO, clips=(c4k,), visible=False)
    t2_aud = Track(kind=TrackKind.AUDIO, clips=(c_aud,), visible=True, muted=True)
    proj = Project(tracks=(t0, t1_4k, t2_aud))

    settings = Settings()
    dialog = ExportDialog(
        project=proj,
        settings=settings,
        pool=[ref1, ref4k],
        probed={ref1.path: local1, ref4k.path: local4k},
        keyframes=(0.0, 5.0, 10.0),
        ensure_tools=lambda: dummy_tools,
     processing=build_processing_service(), runtime=build_desktop_runtime())

    # ExportDialog deve manter apenas a trilha visível (track 0)
    assert len(dialog._project.tracks) == 1
    assert len(dialog._project.clips) == 1
    effective = dialog._effective_project()
    assert (effective.width, effective.height) == (1920, 1080)
    assert effective.fps == 30.0
    assert effective.export_duration == 10.0

    # Corte rápido deve estar disponível porque as outras trilhas estão ocultas/mudas
    assert dialog._fast.isEnabled()


def test_export_dialog_quality_selector(
    qapp: QApplication,
    sample_media: tuple[MediaRef, LocalMedia],
    single_clip_project: Project,
    dummy_tools: FFmpegTools,
) -> None:
    from videomanager.domain.composition import Composition

    ref, local = sample_media
    settings = Settings()
    dialog = ExportDialog(
        project=single_clip_project,
        settings=settings,
        pool=[ref],
        probed={ref.path: local},
        ensure_tools=lambda: dummy_tools,
     processing=build_processing_service(), runtime=build_desktop_runtime())

    # Verifica presets no combo
    assert dialog._quality_box.count() == 3
    items = [dialog._quality_box.itemData(i) for i in range(dialog._quality_box.count())]
    assert items == ["balanced", "high", "economy"]
    assert dialog._quality_box.currentData() == "balanced"

    # Muda para alta qualidade e enfileira
    dialog._fast.setChecked(False)
    dialog._quality_box.setCurrentIndex(1)  # high
    assert dialog._quality_choice == "high"

    dialog._on_enqueue()
    assert dialog.created_job is not None
    target = dialog.created_job.request.target
    assert isinstance(target, Composition)
    assert target.quality == "high"
    assert settings.default_export_quality == "high"

    # Visibilidade com somente áudio
    dialog.show()
    dialog._audio_only_check.setChecked(True)
    assert not dialog._quality_box.isVisible()
    assert not dialog._quality_label.isVisible()

    dialog._audio_only_check.setChecked(False)
    assert dialog._quality_box.isVisible()
    assert dialog._quality_label.isVisible()

    # Desabilitado no modo corte rápido
    dialog._fast.setChecked(True)
    assert not dialog._quality_box.isEnabled()

    dialog._fast.setChecked(False)
    assert dialog._quality_box.isEnabled()


def test_export_dialog_fast_cut_strips_metadata(
    qapp: QApplication,
    sample_media: tuple[MediaRef, LocalMedia],
    single_clip_project: Project,
    dummy_tools: FFmpegTools,
) -> None:
    from videomanager.domain.timing import TrimTarget

    ref, local = sample_media
    settings = Settings()
    dialog = ExportDialog(
        project=single_clip_project,
        settings=settings,
        pool=[ref],
        probed={ref.path: local},
        keyframes=(0.0, 5.0, 10.0),
        ensure_tools=lambda: dummy_tools,
     processing=build_processing_service(), runtime=build_desktop_runtime())

    dialog._fast.setChecked(True)
    dialog._on_enqueue()
    assert dialog.created_job is not None
    target = dialog.created_job.request.target
    assert isinstance(target, TrimTarget)
    assert target.copy_metadata is False





# Estes cenários exercitam adaptadores ou apresentação Qt.
pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")


def test_corte_rapido_mostra_apenas_configuracao_real(sample_media, single_clip_project, dummy_tools):
    ref, local = sample_media
    dialog = ExportDialog(project=single_clip_project, settings=Settings(), pool=[ref],
                          probed={ref.path: local}, ensure_tools=lambda: dummy_tools,
                          processing=build_processing_service(), runtime=build_desktop_runtime())
    dialog._container_box.setCurrentIndex(dialog._container_box.findData('webm'))
    dialog._fast.setChecked(True)
    assert dialog._ext_label.text() == '.mp4'
    assert not dialog._container_box.isEnabled()
    assert not dialog._video_codec_box.isEnabled()
    assert 'h264' in dialog._video_codec_box.currentText().lower()
    dialog._fast.setChecked(False)
    assert dialog._container_box.isEnabled()
    assert dialog._video_codec_box.isEnabled()
    assert dialog._container_box.currentData() == 'webm'


def test_export_dialog_gif(qapp, sample_media, single_clip_project, dummy_tools):
    """GIF: sem codec nem qualidade para escolher, com taxas próprias e aviso."""
    from videomanager.presentation.qt import strings

    ref, local = sample_media
    dialog = ExportDialog(project=single_clip_project, settings=Settings(), pool=[ref],
                          probed={ref.path: local}, ensure_tools=lambda: dummy_tools,
                          processing=build_processing_service(), runtime=build_desktop_runtime())
    dialog._fast.setChecked(False)
    dialog._container_box.setCurrentIndex(dialog._container_box.findData("gif"))

    assert dialog._ext_label.text() == ".gif"
    assert not dialog._video_codec_box.isVisibleTo(dialog)
    assert not dialog._quality_box.isVisibleTo(dialog)
    assert dialog._canvas_box.isVisibleTo(dialog) and dialog._rate_box.isVisibleTo(dialog)
    taxas = [dialog._rate_box.itemData(i) for i in range(dialog._rate_box.count())]
    assert 10.0 in taxas and 12.5 in taxas, "GIF oferece taxas baixas"
    assert dialog._warning.text() == strings.EXPORT_GIF_NOTE
    assert "sem som" in dialog._plan.text()
    assert not dialog._fast.isEnabled(), "não há como copiar os dados da origem num GIF"

    dialog._on_enqueue()
    target = dialog.created_job.request.target
    assert target.container == "gif" and target.extension == "gif"
    assert target.family is None
    assert dialog.created_job.request.destination.suffix == ".gif"


def test_export_dialog_volta_do_gif_restaura_codec(qapp, sample_media, single_clip_project, dummy_tools):
    ref, local = sample_media
    dialog = ExportDialog(project=single_clip_project, settings=Settings(), pool=[ref],
                          probed={ref.path: local}, ensure_tools=lambda: dummy_tools,
                          processing=build_processing_service(), runtime=build_desktop_runtime())
    dialog._fast.setChecked(False)
    dialog._container_box.setCurrentIndex(dialog._container_box.findData("gif"))
    dialog._container_box.setCurrentIndex(dialog._container_box.findData("mp4"))
    assert dialog._video_codec_box.isVisibleTo(dialog)
    assert dialog._quality_box.isVisibleTo(dialog)
    assert dialog._warning.text() == ""
    assert dialog._fast.isEnabled()


def test_export_dialog_gif_em_automatica_reduz_tela_e_taxa(qapp, sample_media, single_clip_project, dummy_tools):
    """Sair na tela do projeto fazia o GIF explodir (medido: 14,9 MB × 1,1 MB)."""
    ref, local = sample_media
    dialog = ExportDialog(project=single_clip_project, settings=Settings(), pool=[ref],
                          probed={ref.path: local}, ensure_tools=lambda: dummy_tools,
                          processing=build_processing_service(), runtime=build_desktop_runtime())
    dialog._fast.setChecked(False)
    dialog._container_box.setCurrentIndex(dialog._container_box.findData("gif"))

    efetivo = dialog._effective_project()
    assert max(efetivo.width, efetivo.height) == 640, "a tela automática do GIF é menor"
    assert efetivo.width % 2 == 0 and efetivo.height % 2 == 0
    assert efetivo.fps == 15.0

    # Escolha na mão vale mais que o padrão.
    dialog._canvas_choice = (1920, 1080)
    dialog._rate_choice = 30.0
    escolhido = dialog._effective_project()
    assert (escolhido.width, escolhido.height, escolhido.fps) == (1920, 1080, 30.0)

    # E o limite é só do GIF.
    dialog._canvas_choice = dialog._rate_choice = None
    dialog._container_box.setCurrentIndex(dialog._container_box.findData("mp4"))
    normal = dialog._effective_project()
    assert (normal.width, normal.height) == (1920, 1080) and normal.fps == 30.0


def test_tela_escolhida_fora_das_predefinidas_aparece_como_escolhida(qapp: QApplication) -> None:
    """A tela do slideshow (1920×1440) não está no acervo nem nas predefinidas.

    A janela mostrava "Automática" com ela em vigor, e a exportação saía na
    tela escolhida; como "Automática" já estava marcada, voltar ao automático
    de verdade (1920×1080 sem vídeo) não era possível.
    """
    foto = MediaRef(Path("/tmp/foto.jpg"), MediaKind.IMAGE, width=4000, height=3000)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(foto, 0, 5.0),)),))
    dialog = ExportDialog(project=project, settings=Settings(), pool=[foto], probed={},
                          initial_canvas=(1920, 1440), initial_rate=23.976,
                          processing=build_processing_service(), runtime=build_desktop_runtime(audio_enabled=False))
    assert dialog._canvas_box.currentData() == (1920, 1440)
    assert dialog._rate_box.currentData() == 23.976

    dialog._canvas_box.setCurrentIndex(0)

    assert dialog.chosen_canvas is None
    efetivo = dialog._effective_project()
    assert (efetivo.width, efetivo.height) == (1920, 1080)


def test_opcoes_desligadas_dizem_por_que(qapp: QApplication) -> None:
    """Corte rápido e interpolação desligados explicam o motivo na dica.

    As explicações existiam em strings.py sem uso: a caixa ficava cinza sem
    dizer que a edição não é um recorte ou que nenhum bloco está abaixo da taxa.
    """
    from videomanager.presentation.qt import strings

    video = MediaRef(Path("/tmp/v.mp4"), MediaKind.VIDEO, duration=10.0, width=1920, height=1080, fps=30.0)
    montagem = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(video, 0, 2.0), Clip(video, 2.0, 2.0, in_point=5.0))),),
                       width=1920, height=1080, fps=30.0)
    dialog = ExportDialog(project=montagem, settings=Settings(), pool=[video], probed={},
                          processing=build_processing_service(), runtime=build_desktop_runtime(audio_enabled=False))
    assert not dialog._fast.isEnabled() and dialog._fast.toolTip() == strings.EDIT_FAST_UNAVAILABLE
    assert not dialog._interpolate.isEnabled() and dialog._interpolate.toolTip() == strings.EDIT_INTERPOLATE_OFF
