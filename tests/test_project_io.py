"""Testes de persistência de projetos (salvar e carregar .vmp)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from videomanager.application.errors import ProjectError
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.infrastructure.storage.project_json import load_project
from videomanager.infrastructure.storage.project_json import project_from_dict
from videomanager.infrastructure.storage.project_json import project_to_dict
from videomanager.infrastructure.storage.project_json import save_project


def _sample_project(media_path: Path) -> Project:
    media = MediaRef(
        path=media_path,
        kind=MediaKind.VIDEO,
        duration=120.0,
        width=1920,
        height=1080,
        fps=30.0,
        has_audio=True,
        channels=2,
    )
    clip = Clip(
        media=media,
        start=5.0,
        duration=15.0,
        in_point=2.0,
        gain_db=-3.0,
        muted=False,
        detached=False,
        audio_only=False,
        clip_id=42,
    )
    track_v = Track(
        kind=TrackKind.VIDEO,
        name="Vídeo 1",
        muted=False,
        clips=(clip,),
        track_id=1,
    )
    track_a = Track(
        kind=TrackKind.AUDIO,
        name="Áudio 1",
        muted=False,
        clips=(),
        track_id=2,
    )
    return Project(
        tracks=(track_v, track_a),
        width=1920,
        height=1080,
        fps=30.0,
    )


def test_roundtrip_dict(tmp_path: Path) -> None:
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"dummy")

    proj = _sample_project(video_file)
    data = project_to_dict(proj, base_dir=tmp_path)
    loaded, missing = project_from_dict(data, base_dir=tmp_path)

    assert not missing
    assert loaded.width == proj.width
    assert loaded.height == proj.height
    assert loaded.fps == proj.fps
    assert len(loaded.tracks) == 2
    assert loaded.tracks[0].name == "Vídeo 1"
    assert loaded.tracks[0].kind == TrackKind.VIDEO
    assert len(loaded.tracks[0].clips) == 1

    c = loaded.tracks[0].clips[0]
    assert c.start == 5.0
    assert c.duration == 15.0
    assert c.in_point == 2.0
    assert c.gain_db == -3.0
    assert c.clip_id == 42
    assert c.media.path.resolve() == video_file.resolve()


def test_save_and_load_file(tmp_path: Path) -> None:
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"dummy")

    proj = _sample_project(video_file)
    proj_path = tmp_path / "meu_projeto.vmp"
    save_project(proj, proj_path)

    assert proj_path.exists()
    loaded, missing = load_project(proj_path)
    assert not missing
    assert len(loaded.tracks) == 2
    assert loaded.tracks[0].clips[0].media.path.resolve() == video_file.resolve()


def test_missing_media_detected(tmp_path: Path) -> None:
    missing_file = tmp_path / "nao_existe.mp4"
    proj = _sample_project(missing_file)
    proj_path = tmp_path / "projeto.vmp"
    save_project(proj, proj_path)

    loaded, missing = load_project(proj_path)
    assert len(missing) == 1
    assert missing[0].name == "nao_existe.mp4"
    assert len(loaded.tracks[0].clips) == 1


def test_relative_path_resolution(tmp_path: Path) -> None:
    # Simula projeto movido junto com a pasta de mídia
    proj_dir = tmp_path / "pasta_projeto"
    proj_dir.mkdir()
    video_file = proj_dir / "video.mp4"
    video_file.write_bytes(b"dummy")

    proj = _sample_project(video_file)
    proj_path = proj_dir / "projeto.vmp"
    save_project(proj, proj_path)

    # Simula que o caminho absoluto original mudou (por exemplo em outro computador),
    # mas o arquivo está na pasta do projeto
    raw_data = json.loads(proj_path.read_text(encoding="utf-8"))
    raw_data["tracks"][0]["clips"][0]["media"]["path"] = "/computador_antigo/video.mp4"
    proj_path.write_text(json.dumps(raw_data), encoding="utf-8")

    loaded, missing = load_project(proj_path)
    assert not missing
    assert loaded.tracks[0].clips[0].media.path.resolve() == video_file.resolve()


def test_load_corrupted_json(tmp_path: Path) -> None:
    bad_file = tmp_path / "corrompido.vmp"
    bad_file.write_text("{esta_incompleto", encoding="utf-8")
    with pytest.raises(ProjectError, match="corrompido"):
        load_project(bad_file)


def test_load_nonexistent_file(tmp_path: Path) -> None:
    missing = tmp_path / "inexistente.vmp"
    with pytest.raises(ProjectError, match="não encontrado"):
        load_project(missing)


def test_unsupported_version(tmp_path: Path) -> None:
    bad_version = tmp_path / "versao_futura.vmp"
    bad_version.write_text(json.dumps({"version": 999}), encoding="utf-8")
    with pytest.raises(ProjectError, match="não é suportada"):
        load_project(bad_version)


def test_save_load_additional_track_and_speed(tmp_path: Path) -> None:
    img_file = tmp_path / "foto.png"
    img_file.write_bytes(b"dummy_img")

    ref = MediaRef(path=img_file, kind=MediaKind.IMAGE, width=800, height=600)
    clip_add = Clip(
        media=ref,
        start=1.0,
        duration=4.0,
        speed=1.5,
        x=0.25,
        y=0.75,
        scale=1.2,
        rotation=45.0,
        overlay_type="text",
        text_content="Legenda",
        font_family="Arial",
        font_size=42,
        font_bold=True,
        font_italic=True,
        text_color="#ffcc00",
        stroke_color="#123456",
        stroke_width=5,
        filter_name="pb",
    )
    track_add = Track(kind=TrackKind.ADDITIONAL, name="Adicionais 1", clips=(clip_add,))
    proj = Project(tracks=(track_add,), width=1920, height=1080, fps=30.0)

    proj_file = tmp_path / "projeto_adicionais.vmp"
    save_project(proj, proj_file)

    loaded, missing = load_project(proj_file)
    assert not missing
    assert len(loaded.additional_tracks) == 1
    loaded_clip = loaded.additional_tracks[0].clips[0]
    assert loaded_clip.speed == 1.5
    assert loaded_clip.x == 0.25
    assert loaded_clip.y == 0.75
    assert loaded_clip.scale == 1.2
    assert loaded_clip.rotation == 45.0
    assert loaded_clip.overlay_type == "text"
    assert loaded_clip.text_content == "Legenda"
    assert loaded_clip.font_family == "Arial"
    assert loaded_clip.font_size == 42
    assert loaded_clip.font_bold is True
    assert loaded_clip.font_italic is True
    assert loaded_clip.text_color == "#ffcc00"
    assert loaded_clip.stroke_color == "#123456"
    assert loaded_clip.stroke_width == 5
    assert loaded_clip.filter_name == "pb"


def test_save_and_load_keyframes(tmp_path: Path) -> None:
    from videomanager.domain.keyframe import Keyframe

    media_file = tmp_path / "video.mp4"
    media_file.write_bytes(b"")
    media = MediaRef(path=media_file, kind=MediaKind.VIDEO, duration=10.0)

    kf1 = Keyframe(
        time_offset=0.0,
        x=0.5,
        y=1.2,
        scale_x=1.0,
        scale_y=1.0,
        rotation=0.0,
        opacity=0.0,
        easing="ease_out",
    )
    kf2 = Keyframe(
        time_offset=1.5,
        x=0.5,
        y=0.5,
        scale_x=1.5,
        scale_y=1.5,
        rotation=360.0,
        opacity=0.8,
        easing="linear",
    )

    clip = Clip(
        media=media,
        start=0.0,
        duration=5.0,
        opacity=0.8,
        keyframes=(kf1, kf2),
    )
    track = Track(kind=TrackKind.VIDEO, clips=(clip,))
    proj = Project(tracks=(track,))

    proj_file = tmp_path / "keyframes.vmp"
    save_project(proj, proj_file)

    loaded, _ = load_project(proj_file)
    loaded_clip = loaded.tracks[0].clips[0]

    assert loaded_clip.opacity == 0.8
    assert len(loaded_clip.keyframes) == 2
    assert loaded_clip.keyframes[0].time_offset == 0.0
    assert loaded_clip.keyframes[0].y == 1.2
    assert loaded_clip.keyframes[0].opacity == 0.0
    assert loaded_clip.keyframes[0].easing == "ease_out"
    assert loaded_clip.keyframes[1].time_offset == 1.5
    assert loaded_clip.keyframes[1].scale_x == 1.5
    assert loaded_clip.keyframes[1].rotation == 360.0
    assert loaded_clip.keyframes[1].opacity == 0.8
