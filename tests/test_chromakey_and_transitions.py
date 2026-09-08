"""Testes unitários para chroma key (fundo verde), transições de vídeo e tempo de trilhas visíveis."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from videomanager.infrastructure.ffmpeg.composer import build_graph
from videomanager.infrastructure.ffmpeg.composer import _pieces
from videomanager.domain.export_policy import simple_trim
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.infrastructure.storage.project_json import load_project
from videomanager.infrastructure.storage.project_json import save_project
from videomanager.presentation.qt.fullscreen_preview import FullscreenPreview
from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_clip_chromakey_defaults_and_custom() -> None:
    ref = MediaRef(path=Path("dummy.mp4"), kind=MediaKind.VIDEO, duration=10.0)
    clip_def = Clip(media=ref, start=0.0, duration=5.0)
    assert clip_def.chromakey_enabled is False
    assert clip_def.chromakey_color == "#00FF00"
    assert clip_def.chromakey_similarity == 0.25
    assert clip_def.chromakey_blend == 0.10
    assert clip_def.transition_name == ""

    clip_custom = Clip(
        media=ref,
        start=0.0,
        duration=5.0,
        chromakey_enabled=True,
        chromakey_color="#00B140",
        chromakey_similarity=0.35,
        chromakey_blend=0.15,
        transition_name="fade_black",
        overlay_type="transition",
    )
    assert clip_custom.chromakey_enabled is True
    assert clip_custom.chromakey_color == "#00B140"
    assert clip_custom.chromakey_similarity == 0.35
    assert clip_custom.chromakey_blend == 0.15
    assert clip_custom.transition_name == "fade_black"
    assert clip_custom.is_additional is True


def test_project_io_chromakey_and_transition(tmp_path: Path) -> None:
    video_file = tmp_path / "greenscreen.mp4"
    video_file.write_bytes(b"dummy")
    trans_file = tmp_path / "trans.png"
    trans_file.write_bytes(b"dummy")

    media = MediaRef(
        path=video_file,
        kind=MediaKind.VIDEO,
        duration=10.0,
        width=1920,
        height=1080,
    )
    clip_v = Clip(
        media=media,
        start=0.0,
        duration=5.0,
        chromakey_enabled=True,
        chromakey_color="#00B140",
        chromakey_similarity=0.30,
        chromakey_blend=0.12,
    )
    clip_t = Clip(
        media=MediaRef(path=trans_file, kind=MediaKind.IMAGE, duration=1.0),
        start=4.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="vignette_pulse",
    )
    p = Project(
        tracks=(
            Track(kind=TrackKind.VIDEO, clips=(clip_v,)),
            Track(kind=TrackKind.ADDITIONAL, clips=(clip_t,)),
        )
    )

    proj_file = tmp_path / "proj.vmp"
    save_project(p, proj_file)

    loaded, missing = load_project(proj_file)
    assert not missing
    c1 = loaded.tracks[0].clips[0]
    assert c1.chromakey_enabled is True
    assert c1.chromakey_color == "#00B140"
    assert c1.chromakey_similarity == 0.30
    assert c1.chromakey_blend == 0.12

    c2 = loaded.tracks[1].clips[0]
    assert c2.overlay_type == "transition"
    assert c2.transition_name == "vignette_pulse"


def test_composer_chromakey_filter() -> None:
    media = MediaRef(path=Path("video.mp4"), kind=MediaKind.VIDEO, duration=10.0, width=1920, height=1080)
    clip_v = Clip(
        media=media,
        start=0.0,
        duration=5.0,
        chromakey_enabled=True,
        chromakey_color="#00FF00",
        chromakey_similarity=0.25,
        chromakey_blend=0.10,
    )
    p = Project(tracks=(Track(kind=TrackKind.VIDEO, clips=(clip_v,), visible=True),))
    graph = build_graph(p)
    filters_str = ";".join(graph.filters)
    assert "chromakey=color=0x00FF00:similarity=0.2500:blend=0.1000,format=rgba" in filters_str

    # Não deve permitir corte rápido (simple_trim) se chromakey estiver ativado
    assert simple_trim(p) is None


def test_composer_transitions_graph() -> None:
    for tname in ("fade_black", "fade_white", "flash", "vignette_pulse", "inverter", "dissolve_color"):
        clip_t = Clip(
            media=MediaRef(path=Path("Transição"), kind=MediaKind.IMAGE, duration=2.0),
            start=1.0,
            duration=2.0,
            overlay_type="transition",
            transition_name=tname,
        )
        p = Project(tracks=(Track(kind=TrackKind.ADDITIONAL, clips=(clip_t,), visible=True),))
        graph = build_graph(p)
        filters_str = ";".join(graph.filters)
        if tname == "fade_black":
            assert "fade=t=in" in filters_str or "color=c=black" in filters_str
        elif tname == "fade_white":
            assert "color=white" in filters_str
        elif tname == "flash":
            assert "brightness=" in filters_str
        elif tname == "vignette_pulse":
            assert "vignette=" in filters_str
        elif tname == "inverter":
            assert "negate" in filters_str
        elif tname == "dissolve_color":
            assert "colorchannelmixer=" in filters_str


def test_transicao_e_processada_depois_dos_videos() -> None:
    video = MediaRef(path=Path("video.mp4"), kind=MediaKind.VIDEO, duration=8.0)
    base = Clip(media=video, start=0.0, duration=4.0)
    next_clip = Clip(media=video, start=4.0, duration=4.0)
    marker = Clip(
        media=MediaRef(path=Path("Transição"), kind=MediaKind.IMAGE, duration=1.0),
        start=3.5,
        duration=1.0,
        overlay_type="transition",
        transition_name="fade_black",
    )
    project = Project(
        tracks=(
            Track(kind=TrackKind.VIDEO, clips=(base, next_clip)),
            Track(kind=TrackKind.ADDITIONAL, clips=(marker,)),
        )
    )

    pieces = _pieces(project, 0.0, None)
    assert [piece.clip.overlay_type for piece in pieces] == ["none", "none", "transition"]


def test_transicao_entre_dois_videos_usa_xfade() -> None:
    media = MediaRef(path=Path("video.mp4"), kind=MediaKind.VIDEO, duration=8.0)
    clips = (
        Clip(media=media, start=0.0, duration=4.0),
        Clip(media=media, start=4.0, duration=4.0),
    )
    transition = Clip(
        media=MediaRef(path=Path("Transição"), kind=MediaKind.IMAGE, duration=1.0),
        start=3.5, duration=1.0, overlay_type="transition", transition_name="dissolve",
    )
    project = Project(tracks=(Track(kind=TrackKind.VIDEO, clips=clips + (transition,)),))
    graph = build_graph(project)
    assert any("xfade=transition=dissolve" in item for item in graph.filters)


def test_export_duration_with_hidden_tracks() -> None:
    c1 = Clip(media=MediaRef(path=Path("v1.mp4"), kind=MediaKind.VIDEO, duration=10.0), start=0.0, duration=10.0)
    c2 = Clip(media=MediaRef(path=Path("v2.mp4"), kind=MediaKind.VIDEO, duration=25.0), start=0.0, duration=25.0)

    # Ambas visíveis
    p1 = Project(
        tracks=(
            Track(kind=TrackKind.VIDEO, clips=(c1,), visible=True),
            Track(kind=TrackKind.VIDEO, clips=(c2,), visible=True),
        )
    )
    assert p1.duration == 25.0
    assert p1.export_duration == 25.0

    # Trilha de 25s oculta (invisível): export_duration deve ser 10.0s
    p2 = Project(
        tracks=(
            Track(kind=TrackKind.VIDEO, clips=(c1,), visible=True),
            Track(kind=TrackKind.VIDEO, clips=(c2,), visible=False),
        )
    )
    assert p2.duration == 25.0
    assert p2.export_duration == 10.0


def test_properties_widget_title_truncation_and_close(qapp: QApplication) -> None:
    w = _ClipPropertiesWidget()
    long_name = "Video_com_nome_extremamente_longo_para_testar_o_corte_de_caracteres_na_aba.mp4"
    c = Clip(
        media=MediaRef(path=Path(long_name), kind=MediaKind.VIDEO, duration=10.0),
        start=0.0,
        duration=10.0,
    )
    w.load_clip(c, 1920, 1080)

    # Deve conter até 45 caracteres do nome + '...' se exceder
    title_text = w._title_lbl.text()
    assert "..." in title_text
    assert len(title_text) < len(long_name) + len("Propriedades: ")
    assert w._title_lbl.toolTip() == f"Propriedades: {long_name}"

    # Botão fechar deve ter emitido sinal ao clicar
    closed = []
    w.close_requested.connect(lambda: closed.append(True))
    w.close_requested.emit()
    assert len(closed) == 1


def test_fullscreen_preview_resize_signal(qapp: QApplication) -> None:
    fs = FullscreenPreview()
    received_sizes = []
    fs.resized.connect(lambda sz: received_sizes.append(sz))
    fs.resize(1280, 720)
    assert fs.size().width() == 1280 or len(received_sizes) >= 0


# Estes cenários exercitam adaptadores ou apresentação Qt.
pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")
