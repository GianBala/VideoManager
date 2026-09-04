"""Testes de persistência de projetos (salvar e carregar .vmp)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from videomanager.core.errors import ProjectError
from videomanager.core.project import (
    Clip,
    MediaKind,
    MediaRef,
    Project,
    Track,
    TrackKind,
)
from videomanager.core.project_io import (
    load_project,
    project_from_dict,
    project_to_dict,
    save_project,
)


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
