"""Entrada e saída de projetos de edição (salvar e carregar).

Salva o projeto em formato JSON (.vmp), guardando a estrutura de trilhas,
blocos e metadados de mídia. Preserva caminhos relativos para permitir mover a
pasta do projeto junto com as mídias.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .binaries import FFmpegTools
from .errors import ProjectError
from .project import (
    Clip,
    MediaKind,
    MediaRef,
    Project,
    Track,
    TrackKind,
)

PROJECT_VERSION = 1


def _media_to_dict(media: MediaRef, base_dir: Path | None) -> dict[str, object]:
    data: dict[str, object] = {
        "path": str(media.path.resolve() if media.path.is_absolute() else media.path),
        "kind": media.kind.name,
        "duration": media.duration,
        "width": media.width,
        "height": media.height,
        "fps": media.fps,
        "has_audio": media.has_audio,
        "channels": media.channels,
    }
    if base_dir is not None:
        try:
            rel = os.path.relpath(media.path, base_dir)
            data["rel_path"] = rel
        except ValueError:
            # Em sistemas como Windows com unidades diferentes (C: e D:),
            # relpath pode falhar.
            pass
    return data


def _dict_to_media(data: dict[str, object], base_dir: Path | None) -> tuple[MediaRef, Path | None]:
    raw_path = Path(str(data["path"]))
    resolved_path = raw_path
    missing: Path | None = None

    if not resolved_path.exists():
        # Tenta pelo caminho relativo se disponível
        rel_path = data.get("rel_path")
        if rel_path and base_dir is not None:
            candidate = (base_dir / str(rel_path)).resolve()
            if candidate.exists():
                resolved_path = candidate

        # Tenta buscar diretamente pelo nome do arquivo na mesma pasta do projeto
        if not resolved_path.exists() and base_dir is not None:
            candidate = (base_dir / raw_path.name).resolve()
            if candidate.exists():
                resolved_path = candidate

        if not resolved_path.exists():
            missing = raw_path

    kind_str = str(data.get("kind", "VIDEO"))
    try:
        kind = MediaKind[kind_str]
    except KeyError:
        kind = MediaKind.VIDEO

    duration = float(data["duration"]) if data.get("duration") is not None else None
    width = int(data["width"]) if data.get("width") is not None else None
    height = int(data["height"]) if data.get("height") is not None else None
    fps = float(data["fps"]) if data.get("fps") is not None else None
    has_audio = bool(data.get("has_audio", False))
    channels = int(data["channels"]) if data.get("channels") is not None else None

    ref = MediaRef(
        path=resolved_path,
        kind=kind,
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        has_audio=has_audio,
        channels=channels,
    )
    return ref, missing


def project_to_dict(project: Project, base_dir: Path | None = None) -> dict[str, object]:
    """Serializa o projeto para uma estrutura de dicionário."""
    tracks_data: list[dict[str, object]] = []
    for track in project.tracks:
        clips_data: list[dict[str, object]] = []
        for clip in track.clips:
            clips_data.append(
                {
                    "clip_id": clip.clip_id,
                    "start": clip.start,
                    "duration": clip.duration,
                    "in_point": clip.in_point,
                    "gain_db": clip.gain_db,
                    "muted": clip.muted,
                    "detached": clip.detached,
                    "audio_only": clip.audio_only,
                    "speed": clip.speed,
                    "x": clip.x,
                    "y": clip.y,
                    "scale": clip.scale,
                    "rotation": clip.rotation,
                    "overlay_type": clip.overlay_type,
                    "text_content": clip.text_content,
                    "font_family": clip.font_family,
                    "font_size": clip.font_size,
                    "font_bold": clip.font_bold,
                    "font_italic": clip.font_italic,
                    "text_color": clip.text_color,
                    "stroke_color": clip.stroke_color,
                    "stroke_width": clip.stroke_width,
                    "filter_name": clip.filter_name,
                    "media": _media_to_dict(clip.media, base_dir),
                }
            )
        tracks_data.append(
            {
                "track_id": track.track_id,
                "name": track.name,
                "kind": track.kind.name,
                "muted": track.muted,
                "visible": track.visible,
                "clips": clips_data,
            }
        )

    return {
        "version": PROJECT_VERSION,
        "width": project.width,
        "height": project.height,
        "fps": project.fps,
        "tracks": tracks_data,
    }


def project_from_dict(
    data: dict[str, object],
    base_dir: Path | None = None,
    tools: FFmpegTools | None = None,
) -> tuple[Project, list[Path]]:
    """Reconstrói um projeto a partir do dicionário serializado."""
    missing_files: list[Path] = []
    version = data.get("version", 1)
    if not isinstance(version, int) or version > PROJECT_VERSION:
        raise ProjectError(
            f"Versão de projeto {version} não é suportada por esta versão do aplicativo."
        )

    width = int(data.get("width", 1920))
    height = int(data.get("height", 1080))
    fps = float(data.get("fps", 30.0))

    tracks_raw = data.get("tracks", [])
    if not isinstance(tracks_raw, list):
        raise ProjectError("Estrutura do arquivo de projeto corrompida: trilhas inválidas.")

    tracks: list[Track] = []
    for t_data in tracks_raw:
        if not isinstance(t_data, dict):
            continue
        kind_str = str(t_data.get("kind", "VIDEO"))
        try:
            kind = TrackKind[kind_str]
        except KeyError:
            kind = TrackKind.VIDEO

        name = str(t_data.get("name", ""))
        muted = bool(t_data.get("muted", False))
        visible = bool(t_data.get("visible", True))
        track_id = int(t_data.get("track_id", 0))

        clips: list[Clip] = []
        for c_data in t_data.get("clips", []):
            if not isinstance(c_data, dict):
                continue
            media_data = c_data.get("media")
            if not isinstance(media_data, dict):
                continue
            media, missing = _dict_to_media(media_data, base_dir)
            if missing is not None and missing not in missing_files:
                missing_files.append(missing)

            clip = Clip(
                media=media,
                start=float(c_data.get("start", 0.0)),
                duration=float(c_data.get("duration", 0.0)),
                in_point=float(c_data.get("in_point", 0.0)),
                gain_db=float(c_data.get("gain_db", 0.0)),
                muted=bool(c_data.get("muted", False)),
                detached=bool(c_data.get("detached", False)),
                audio_only=bool(c_data.get("audio_only", False)),
                speed=float(c_data.get("speed", 1.0)),
                x=float(c_data.get("x", 0.5)),
                y=float(c_data.get("y", 0.5)),
                scale=float(c_data.get("scale", 1.0)),
                rotation=float(c_data.get("rotation", 0.0)),
                overlay_type=str(c_data.get("overlay_type", "none")),
                text_content=str(c_data.get("text_content", "")),
                font_family=str(c_data.get("font_family", "Sans Serif")),
                font_size=int(c_data.get("font_size", 36)),
                font_bold=bool(c_data.get("font_bold", False)),
                font_italic=bool(c_data.get("font_italic", False)),
                text_color=str(c_data.get("text_color", "#ffffff")),
                stroke_color=str(c_data.get("stroke_color", "#000000")),
                stroke_width=int(c_data.get("stroke_width", 0)),
                filter_name=str(c_data.get("filter_name", "")),
                clip_id=int(c_data.get("clip_id", 0)),
            )
            clips.append(clip)

        tracks.append(
            Track(
                kind=kind,
                name=name,
                muted=muted,
                visible=visible,
                clips=tuple(sorted(clips, key=lambda c: c.start)),
                track_id=track_id,
            )
        )

    project = Project(
        tracks=tuple(tracks),
        width=width,
        height=height,
        fps=fps,
    )
    return project, missing_files


def save_project(project: Project, path: Path) -> None:
    """Grava o projeto em disco no formato JSON."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = project_to_dict(project, base_dir=path.parent)
        text = json.dumps(data, indent=2, ensure_ascii=False)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:
        raise ProjectError(f"Não foi possível salvar o projeto em {path}: {exc}") from exc


def load_project(path: Path, tools: FFmpegTools | None = None) -> tuple[Project, list[Path]]:
    """Abre o arquivo de projeto e retorna (projeto, arquivos_ausentes)."""
    if not path.is_file():
        raise ProjectError(f"Arquivo de projeto não encontrado: {path}")

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ProjectError(f"Arquivo de projeto corrompido ou inválido: {exc}") from exc
    except OSError as exc:
        raise ProjectError(f"Erro ao ler arquivo de projeto: {exc}") from exc

    if not isinstance(data, dict):
        raise ProjectError("Formato de projeto inválido.")

    return project_from_dict(data, base_dir=path.parent, tools=tools)
