"""Entrada e saída de projetos de edição (salvar e carregar).

Salva o projeto em formato JSON (.vmp), guardando a estrutura de trilhas,
blocos e metadados de mídia. Preserva caminhos relativos para permitir mover a
pasta do projeto junto com as mídias.
"""

from __future__ import annotations

import json
import math
import tempfile
import os
from pathlib import Path

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.errors import ProjectError
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.domain.project import next_clip_id
from videomanager.domain.project import reserve_project_ids

# 3: imagens vivem na trilha de vídeo e se ajustam à tela. Ao abrir 1 ou 2, as
# imagens das trilhas de Adicionais migram com a escala convertida.
PROJECT_VERSION = 3


def _media_to_dict(media: MediaRef, base_dir: Path | None) -> dict[str, object]:
    path_str = str(media.path)
    is_pseudo = path_str.startswith(("Texto_", "Filtro_", "Transição_"))
    data: dict[str, object] = {
        "path": path_str if is_pseudo else str(media.path.resolve() if media.path.is_absolute() else media.path),
        "kind": media.kind.name,
        "duration": media.duration,
        "width": media.width,
        "height": media.height,
        "fps": media.fps,
        "has_audio": media.has_audio,
        "channels": media.channels,
    }
    if base_dir is not None and not is_pseudo and media.path.is_absolute():
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
    is_pseudo = str(raw_path).startswith(("Texto_", "Filtro_", "Transição_"))
    if not is_pseudo and not raw_path.is_absolute() and base_dir is not None:
        resolved_path = (base_dir / raw_path).resolve()

    if not is_pseudo and not resolved_path.exists():
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
                    "scale_x": clip.scale_x,
                    "scale_y": clip.scale_y,
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
                    "transition_name": clip.transition_name,
                    "transition_left_id": clip.transition_left_id,
                    "transition_right_id": clip.transition_right_id,
                    "transition_affects_additionals": clip.transition_affects_additionals,
                    "chromakey_enabled": clip.chromakey_enabled,
                    "chromakey_color": clip.chromakey_color,
                    "chromakey_similarity": clip.chromakey_similarity,
                    "chromakey_blend": clip.chromakey_blend,
                    "opacity": clip.opacity,
                    "keyframes": [
                        {
                            "time_offset": kf.time_offset,
                            "x": kf.x,
                            "y": kf.y,
                            "scale_x": kf.scale_x,
                            "scale_y": kf.scale_y,
                            "rotation": kf.rotation,
                            "opacity": kf.opacity,
                            "easing": kf.easing,
                        }
                        for kf in clip.keyframes
                    ],
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
        "text_reference_width": project.text_reference_width,
        "text_reference_height": project.text_reference_height,
        "tracks": tracks_data,
    }


def _validate_project(data: dict[str, object]) -> None:
    """Valida o documento inteiro antes de construir ou substituir a edição."""
    def fail(field: str) -> None:
        raise ProjectError(f"Estrutura do arquivo de projeto inválida: {field}.")

    def number(obj, name, *, minimum=None, positive=False, integer=False):
        if name not in obj:
            return
        value = obj[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail(name)
        if integer and not isinstance(value, int):
            fail(name)
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite or (positive and value <= 0) or (minimum is not None and value < minimum):
            fail(name)

    def booleans(obj, names):
        for name in names:
            if name in obj and not isinstance(obj[name], bool):
                fail(name)

    def strings(obj, names):
        for name in names:
            if name in obj and not isinstance(obj[name], str):
                fail(name)

    if not isinstance(data, dict):
        fail("documento")
    version = data.get("version", 1)
    if type(version) is not int or not 1 <= version <= PROJECT_VERSION:
        raise ProjectError(f"Versão de projeto {version} não é suportada por esta versão do aplicativo.")
    for name in ("width", "height", "fps", "text_reference_width", "text_reference_height"):
        number(data, name, positive=True, integer=name != "fps")
    tracks = data.get("tracks", [])
    if not isinstance(tracks, list):
        fail("trilhas")
    clip_ids, track_ids = set(), set()
    for track in tracks:
        if not isinstance(track, dict):
            fail("trilha")
        number(track, "track_id", positive=True, integer=True)
        if "track_id" in track:
            if track["track_id"] in track_ids:
                fail("ID de trilha duplicado")
            track_ids.add(track["track_id"])
        if track.get("kind", "VIDEO") not in TrackKind.__members__:
            fail("tipo de trilha")
        booleans(track, ("muted", "visible"))
        strings(track, ("name",))
        clips = track.get("clips", [])
        if not isinstance(clips, list):
            fail("clipes")
        for clip in clips:
            if not isinstance(clip, dict):
                fail("clipe")
            number(clip, "clip_id", positive=True, integer=True)
            if "clip_id" in clip:
                if clip["clip_id"] in clip_ids:
                    fail("ID de clipe duplicado")
                clip_ids.add(clip["clip_id"])
            if "duration" not in clip:
                fail("duração do clipe")
            for name in ("duration", "speed", "scale", "scale_x", "scale_y"):
                number(clip, name, positive=True)
            for name in ("start", "stroke_width", "chromakey_similarity", "chromakey_blend"):
                number(clip, name, minimum=0, integer=name == "stroke_width")
            media_data = clip.get("media")
            static = (isinstance(media_data, dict) and media_data.get("kind") == "IMAGE") or clip.get("overlay_type") in ("text", "filter")
            # Versões anteriores geravam entrada negativa ao estender um
            # adicional. Recuperar só fontes estáticas, sem aceitar NaN/inf.
            number(clip, "in_point", minimum=None if static else 0)
            number(clip, "font_size", positive=True, integer=True)
            for name in ("gain_db", "x", "y", "rotation"):
                number(clip, name)
            if "opacity" in clip:
                number(clip, "opacity", minimum=0)
                if clip["opacity"] > 1:
                    fail("opacity")
            for name in ("chromakey_similarity", "chromakey_blend"):
                if clip.get(name, 0) > 1 or clip.get(name, 0) < 0:
                    fail(name)
            if "keyframes" in clip:
                if not isinstance(clip["keyframes"], list):
                    fail("quadros-chave")
                for kf in clip["keyframes"]:
                    if not isinstance(kf, dict):
                        fail("quadro-chave")
                    number(kf, "time_offset", minimum=0 if data.get("version", 1) == 1 else None)
                    for kf_num in ("x", "y", "rotation"):
                        number(kf, kf_num)
                    for kf_pos in ("scale_x", "scale_y"):
                        number(kf, kf_pos, positive=True)
                    if "opacity" in kf:
                        number(kf, "opacity", minimum=0)
                        if kf["opacity"] > 1:
                            fail("opacidade do quadro-chave")
                    strings(kf, ("easing",))
            booleans(
                clip,
                (
                    "muted",
                    "detached",
                    "audio_only",
                    "font_bold",
                    "font_italic",
                    "chromakey_enabled",
                    "transition_affects_additionals",
                ),
            )
            strings(clip, ("overlay_type", "text_content", "font_family", "text_color", "stroke_color", "filter_name", "transition_name", "chromakey_color"))
            if clip.get("overlay_type", "none") not in ("none", "image", "text", "filter", "transition"):
                fail("tipo de sobreposição")
            media = clip.get("media")
            if not isinstance(media, dict) or not isinstance(media.get("path"), str) or not media["path"]:
                fail("caminho da mídia")
            if media.get("kind", "VIDEO") not in MediaKind.__members__:
                fail("tipo de mídia")
            strings(media, ("rel_path",))
            booleans(media, ("has_audio",))
            for name in ("duration", "width", "height", "fps", "channels"):
                if media.get(name) is not None:
                    number(media, name, positive=True, integer=name in ("width", "height", "channels"))


def project_from_dict(data: dict[str, object], base_dir: Path | None = None,
                      tools: FFmpegTools | None = None) -> tuple[Project, list[Path]]:
    """Carrega apenas projetos válidos e apresenta falhas como erros de domínio."""
    try:
        _validate_project(data)
        # Reserva todos os IDs antes de gerar os ausentes em documentos antigos.
        tracks = data.get("tracks", [])
        reserve_project_ids(
            (clip.get("clip_id", 0) for track in tracks for clip in track.get("clips", [])),
            (track.get("track_id", 0) for track in tracks),
        )
        return _project_from_dict(data, base_dir, tools)
    except (ValueError, TypeError, KeyError, OverflowError, OSError) as exc:
        raise ProjectError(f"Estrutura do arquivo de projeto inválida: {exc}") from exc


def _project_from_dict(
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
        track_identity = {"track_id": t_data["track_id"]} if "track_id" in t_data else {}

        clips: list[Clip] = []
        for c_data in t_data.get("clips", []):
            if not isinstance(c_data, dict):
                continue
            media_data = c_data.get("media")
            if not isinstance(media_data, dict):
                continue
            overlay_type = str(c_data.get("overlay_type", "none"))
            media, missing = _dict_to_media(media_data, base_dir)
            if overlay_type not in ("text", "filter", "transition") and missing is not None and missing not in missing_files:
                missing_files.append(missing)

            keyframes_raw = c_data.get("keyframes", [])
            clip_kfs: list[Keyframe] = []
            if isinstance(keyframes_raw, list):
                for kf_d in keyframes_raw:
                    if isinstance(kf_d, dict):
                        clip_kfs.append(
                            Keyframe(
                                time_offset=float(kf_d.get("time_offset", 0.0)),
                                x=float(kf_d.get("x", 0.5)),
                                y=float(kf_d.get("y", 0.5)),
                                scale_x=float(kf_d.get("scale_x", 1.0)),
                                scale_y=float(kf_d.get("scale_y", 1.0)),
                                rotation=float(kf_d.get("rotation", 0.0)),
                                opacity=float(kf_d.get("opacity", 1.0)),
                                easing=str(kf_d.get("easing", "linear")),
                            )
                        )

            clip = Clip(
                media=media,
                start=float(c_data.get("start", 0.0)),
                duration=float(c_data.get("duration", 0.0)),
                in_point=(0.0 if media.kind is MediaKind.IMAGE or overlay_type in ("text", "filter")
                          else float(c_data.get("in_point", 0.0))),
                gain_db=float(c_data.get("gain_db", 0.0)),
                muted=bool(c_data.get("muted", False)),
                detached=bool(c_data.get("detached", False)),
                audio_only=bool(c_data.get("audio_only", False)),
                speed=float(c_data.get("speed", 1.0)),
                x=float(c_data.get("x", 0.5)),
                y=float(c_data.get("y", 0.5)),
                scale=float(c_data.get("scale", 1.0)),
                scale_x=float(c_data.get("scale_x", c_data.get("scale", 1.0))),
                scale_y=float(c_data.get("scale_y", c_data.get("scale", 1.0))),
                rotation=float(c_data.get("rotation", 0.0)),
                opacity=float(c_data.get("opacity", 1.0)),
                keyframes=tuple(clip_kfs),
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
                transition_name=str(c_data.get("transition_name", "")),
                transition_left_id=(int(c_data["transition_left_id"]) if c_data.get("transition_left_id") is not None else None),
                transition_right_id=(int(c_data["transition_right_id"]) if c_data.get("transition_right_id") is not None else None),
                transition_affects_additionals=bool(
                    c_data.get("transition_affects_additionals", False)
                ),
                chromakey_enabled=bool(c_data.get("chromakey_enabled", False)),
                chromakey_color=str(c_data.get("chromakey_color", "#00FF00")),
                chromakey_similarity=float(c_data.get("chromakey_similarity", 0.25)),
                chromakey_blend=float(c_data.get("chromakey_blend", 0.10)),
                clip_id=c_data["clip_id"] if "clip_id" in c_data else next_clip_id(),
            )
            clips.append(clip)

        tracks.append(
            Track(
                kind=kind,
                name=name,
                muted=muted,
                visible=visible,
                clips=tuple(sorted(clips, key=lambda c: c.start)),
                **track_identity,
            )
        )

    project = Project(
        tracks=tuple(tracks),
        width=width,
        height=height,
        fps=fps,
        text_reference_width=int(data.get("text_reference_width", width)),
        text_reference_height=int(data.get("text_reference_height", height)),
    ).with_normalized_transitions()
    if version < 3:
        # Só arquivos anteriores ao formato 3: um v3 gravado pelo aplicativo
        # nunca tem imagem em Adicionais, e reabri-lo precisa devolver
        # exatamente a mesma montagem.
        project = project.with_images_in_video_tracks(legacy_scale=True)
    return project, missing_files


def save_project(project: Project, path: Path) -> None:
    """Grava o projeto em disco no formato JSON."""
    tmp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = project_to_dict(project, base_dir=path.parent)
        text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
        _backup_previous_version(path)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}-", suffix=".tmp", delete=False) as handle:
            tmp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    except (OSError, ValueError) as exc:
        raise ProjectError(f"Não foi possível salvar o projeto em {path}: {exc}") from exc
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                # Uma falha de limpeza não pode esconder o erro de gravação.
                pass


def _backup_previous_version(path: Path) -> None:
    """Preserva o original antes de gravá-lo num formato mais novo.

    Binários antigos não abrem o formato novo; a cópia ``.vN.bak`` é o caminho
    de volta. Nunca sobrescreve uma cópia existente.
    """
    if not path.is_file():
        return
    original = path.read_bytes()
    try:
        old = json.loads(original)
    except (ValueError, UnicodeDecodeError):
        return
    if not isinstance(old, dict):
        return
    version = old.get('version', 1)
    if type(version) is not int or version >= PROJECT_VERSION:
        return
    number = 0
    while True:
        suffix = '' if number == 0 else f'.{number}'
        backup = path.with_name(path.name + f'.v{version}.bak' + suffix)
        try:
            handle = backup.open('xb')
        except FileExistsError:
            number += 1
            continue
        try:
            with handle:
                handle.write(original)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            backup.unlink(missing_ok=True)
            raise
        return


def load_project(path: Path, tools: FFmpegTools | None = None) -> tuple[Project, list[Path]]:
    """Abre o arquivo de projeto e retorna (projeto, arquivos_ausentes)."""
    if not path.is_file():
        raise ProjectError(f"Arquivo de projeto não encontrado: {path}")

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProjectError(f"Arquivo de projeto corrompido ou inválido: {exc}") from exc
    except OSError as exc:
        raise ProjectError(f"Erro ao ler arquivo de projeto: {exc}") from exc

    if not isinstance(data, dict):
        raise ProjectError("Formato de projeto inválido.")

    return project_from_dict(data, base_dir=path.parent, tools=tools)

__all__ = [
    'FFmpegTools',
    'ProjectError',
    'Clip',
    'MediaKind',
    'MediaRef',
    'Project',
    'Track',
    'TrackKind',
    'next_clip_id',
    'reserve_project_ids',
]
