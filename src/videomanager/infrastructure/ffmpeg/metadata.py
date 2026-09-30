"""Leitura e gravação de metadados por remux: a cópia leva os mesmos pacotes.

``-map 0 -c copy`` com os metadados da origem copiados e só as diferenças
aplicadas por ``-metadata``: o que o usuário não mexeu sai como estava, e nada é
recodificado. Duas coisas não saem de graça, e as duas foram medidas:

- **A capa do MKV.** O ffmpeg expõe a capa JPEG/PNG anexada como uma trilha de
  imagem; num remux simples ela voltava como **trilha de vídeo de um quadro**,
  e o player passava a ver dois vídeos. No MKV a capa sai da cópia e volta por
  ``-attach``, extraída byte a byte.
- **O que o formato não guarda.** Gravado sem erro não quer dizer guardado: o
  MP4 descarta campo livre em silêncio. A cópia é lida de volta antes de
  publicar, e o que ficou de fora vai para a tela.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.errors import ConversionError
from videomanager.domain.i18n import Text, t
from videomanager.domain.metadata import CoverInfo
from videomanager.domain.metadata import FileMetadata
from videomanager.domain.metadata import MetadataEdit
from videomanager.domain.metadata import SavedCopy
from videomanager.domain.metadata import TrackInfo
from videomanager.domain.metadata import editable_tags
from videomanager.infrastructure.ffmpeg.catalog import FFmpegCatalog
from videomanager.infrastructure.storage.outputs import FileOutputStore
from videomanager.infrastructure.system.process import ProcessControl

_IMAGE_TYPES = {"mjpeg": ("image/jpeg", "jpg"), "png": ("image/png", "png"), "webp": ("image/webp", "webp")}
_MIMETYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
# Remux copia: a demora é a do disco, e um arquivo de dezenas de GB precisa caber.
_SAVE_TIMEOUT = 3600


def _run(control: ProcessControl, command: list[str], timeout: float = 60) -> subprocess.CompletedProcess:
    try:
        return control.run(command, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConversionError(Text("META_FFMPEG_FAILED", detail=str(exc))) from exc


def read_metadata(path: Path, tools: FFmpegTools, control: ProcessControl | None = None) -> FileMetadata:
    control = control or ProcessControl()
    result = _run(control, [tools.ffprobe_str, "-v", "quiet", "-print_format", "json",
                            "-show_format", "-show_streams", str(path)])
    if result.returncode != 0:
        raise ConversionError(Text("CONVERT_NOT_MEDIA", name=path.name))
    try:
        data = json.loads(result.stdout or b"{}")
    except json.JSONDecodeError as exc:
        raise ConversionError(Text("CONVERT_PROBE_UNREADABLE")) from exc
    container = data.get("format") or {}
    format_name = str(container.get("format_name") or "")
    raw_streams = [s for s in data.get("streams") or [] if isinstance(s, dict)]

    meta = FileMetadata(path, format_name, None, (), ())
    title_key = meta.track_title_key
    tracks: list[TrackInfo] = []
    streams: list[tuple[str, str]] = []
    cover: CoverInfo | None = None
    for position, raw in enumerate(raw_streams):
        kind = str(raw.get("codec_type") or "")
        codec = str(raw.get("codec_name") or "")
        tags = _lower(raw.get("tags"))
        streams.append((kind, codec))
        picture = bool((raw.get("disposition") or {}).get("attached_pic"))
        image_attachment = kind == "attachment" and tags.get("mimetype", "").startswith("image/")
        if picture or image_attachment:
            if cover is None:
                mimetype = tags.get("mimetype") or _IMAGE_TYPES.get(codec, ("", ""))[0]
                cover = CoverInfo(position, "picture" if picture else "attachment", mimetype,
                                  tags.get("filename", ""))
            continue
        if kind == "attachment":
            continue
        tracks.append(TrackInfo(position, kind, codec, tags.get(title_key, ""), tags.get("language", "")))

    file_tags = container.get("tags") or {}
    if meta.tags_on_stream:
        audio = next((s for s in raw_streams if s.get("codec_type") == "audio"), {})
        file_tags = audio.get("tags") or {}
    try:
        duration = float(container.get("duration"))
    except (TypeError, ValueError):
        duration = None
    return FileMetadata(path, format_name, duration, tuple((str(k), str(v)) for k, v in file_tags.items()),
                        tuple(tracks), cover, tuple(streams))


def _lower(tags: object) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in (tags or {}).items()} if isinstance(tags, dict) else {}


def cover_bytes(meta: FileMetadata, tools: FFmpegTools, control: ProcessControl | None = None) -> bytes | None:
    """A imagem da capa como está no arquivo, sem recodificar."""
    cover = meta.cover
    if cover is None:
        return None
    control = control or ProcessControl()
    if cover.stream == "picture":
        result = _run(control, [tools.ffmpeg_str, "-nostdin", "-v", "error", "-i", str(meta.path),
                                "-map", f"0:{cover.index}", "-c", "copy", "-frames:v", "1",
                                "-f", "image2pipe", "-"])
        return result.stdout if result.returncode == 0 and result.stdout else None
    with tempfile.TemporaryDirectory(prefix="videomanager-capa-") as folder:
        target = Path(folder) / "capa"
        # O ffmpeg grava o anexo e sai com erro por não haver saída: quem diz se
        # deu certo é o arquivo, não o código de retorno.
        _run(control, [tools.ffmpeg_str, "-nostdin", "-v", "error", "-y",
                       f"-dump_attachment:{cover.index}", str(target), "-i", str(meta.path)])
        return target.read_bytes() if target.is_file() and target.stat().st_size else None


def metadata_args(meta: FileMetadata, edit: MetadataEdit, output: Path, tools: FFmpegTools,
                  *, attach: Path | None = None) -> list[str]:
    """O remux que aplica ``edit``; ``attach`` é a imagem que entra como anexo (MKV)."""
    picture = edit.cover_image if edit.cover_image and not meta.cover_as_attachment else None
    args = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-y", "-i", str(meta.path)]
    if picture:
        args += ["-i", str(picture)]
    drop: set[int] = set()
    if meta.cover and (edit.remove_cover or edit.cover_image
                       or (meta.cover_as_attachment and meta.cover.stream == "picture")):
        drop.add(meta.cover.index)
    args += ["-map", "0", *[arg for index in sorted(drop) for arg in ("-map", f"-0:{index}")]]
    kept = [index for index in range(len(meta.streams)) if index not in drop]
    if picture:
        args += ["-map", "1"]
    args += ["-c", "copy", "-map_metadata", "0", "-map_chapters", "0"]

    scope = "-metadata:s:a:0" if meta.tags_on_stream else "-metadata"
    args += [arg for key, value in _tag_changes(meta, edit) for arg in (scope, f"{key}={value}")]
    if not meta.tags_on_stream:
        originals = {track.index: track for track in meta.tracks}
        for index, title, language in edit.tracks:
            track = originals.get(index)
            if track is None or index not in kept:
                continue
            out = f"-metadata:s:{kept.index(index)}"
            if title != track.title:
                args += [out, f"{meta.track_title_key}={title}"]
            if language != track.language:
                args += [out, f"language={language}"]

    if picture:
        position = len(kept)
        args += [f"-disposition:{position}", "attached_pic"]
        if meta.path.suffix.lower() == ".mp3":
            # Sem estes dois, o ID3 marca a imagem como "outra", e o Windows e
            # os players de música não a mostram como capa.
            args += [f"-metadata:s:{position}", "title=Album cover",
                     f"-metadata:s:{position}", "comment=Cover (front)"]
    if attach is not None:
        attachments = sum(1 for index in kept if meta.streams[index][0] == "attachment")
        mimetype = _MIMETYPES.get(attach.suffix.lower(), "image/jpeg")
        args += ["-attach", str(attach), f"-metadata:s:t:{attachments}", f"mimetype={mimetype}",
                 f"-metadata:s:t:{attachments}", f"filename=cover{attach.suffix.lower() or '.jpg'}"]
    suffix = meta.path.suffix.lower()
    if suffix == ".mp3":
        args += ["-id3v2_version", "3"]  # o Windows Explorer não lê o ID3v2.4
    elif suffix in (".mp4", ".m4a", ".m4v", ".mov"):
        args += ["-movflags", "+faststart"]
    return [*args, str(output)]


def _tag_changes(meta: FileMetadata, edit: MetadataEdit) -> list[tuple[str, str]]:
    """Só as diferenças; valor vazio apaga. A caixa segue a da origem.

    O ffmpeg compara as chaves sem caixa, e o MKV guarda ``ARTIST`` onde o MP4
    guarda ``artist``: gravar na caixa da origem troca o campo, em vez de criar
    um segundo com o mesmo nome.
    """
    before = {key.lower(): (key, value) for key, value in editable_tags(meta)}
    after = {key.strip().lower(): (key.strip(), value) for key, value in edit.tags if key.strip()}
    changes = [(before[lower][0], "") for lower in before if lower not in after]
    for lower, (key, value) in after.items():
        if not value and lower not in before:
            continue
        if before.get(lower, (key, None))[1] != value:
            changes.append((before.get(lower, (key,))[0], value))
    return changes


def verify_copy(meta: FileMetadata, edit: MetadataEdit, copy: FileMetadata) -> tuple[str | Text, ...]:
    """O que a cópia não guardou; levanta se ela não tem as mesmas trilhas."""
    def body(info: FileMetadata) -> list[tuple[str, str]]:
        cover = info.cover.index if info.cover else None
        return [stream for index, stream in enumerate(info.streams) if index != cover]

    if body(copy) != body(meta):
        raise ConversionError(Text("META_COPY_DIFFERS"))
    missing: list[str | Text] = []
    written = {key.lower(): value for key, value in copy.tags}
    for key, value in edit.tags:
        key = key.strip()
        if key and value and written.get(key.lower()) != value:
            missing.append(key)
    wanted = {key.strip().lower() for key, value in edit.tags if key.strip() and value}
    missing += [key for key, _ in editable_tags(meta) if key.lower() not in wanted and key.lower() in written]
    if not meta.tags_on_stream:
        # A conferência acima garante as mesmas faixas, na mesma ordem.
        positions = {track.index: position for position, track in enumerate(meta.tracks)}
        for index, title, language in edit.tracks:
            position = positions.get(index)
            if position is None:
                continue
            original, saved = meta.tracks[position], copy.tracks[position]
            if title != original.title and saved.title != title:
                missing.append(Text("META_NOT_SAVED_TRACK_TITLE", number=position + 1))
            if language != original.language and _language(saved.language) != _language(language):
                missing.append(Text("META_NOT_SAVED_TRACK_LANGUAGE", number=position + 1))
    wants_cover = bool(edit.cover_image or (meta.cover and not edit.remove_cover))
    if wants_cover != (copy.cover is not None):
        missing.append(Text("META_NOT_SAVED_COVER"))
    return tuple(missing)


def _packet_counts(path: Path, info: FileMetadata, tools: FFmpegTools, control: ProcessControl) -> list[str]:
    """Pacotes de cada trilha, fora a capa: só demultiplexa, não decodifica."""
    result = _run(control, [tools.ffprobe_str, "-v", "error", "-count_packets", "-show_entries",
                            "stream=index,nb_read_packets", "-of", "csv=p=0", str(path)], _SAVE_TIMEOUT)
    cover = str(info.cover.index) if info.cover else None
    lines = (line.split(",") for line in (result.stdout or b"").decode().splitlines() if "," in line)
    return [count for index, count in lines if index != cover]


def _same_content(meta: FileMetadata, copy: FileMetadata, render: Path, tools: FFmpegTools,
                  control: ProcessControl) -> bool:
    """A mesma duração, ou, quando ela discorda, os mesmos pacotes.

    Duração não prova nada sozinha: sem o cabeçalho Xing, a do MP3 VBR é
    estimada pelo bitrate do começo (medido num rip real: 18,80 s contra
    20,04 s), e a cópia ganha o cabeçalho e diz a real — a cópia correta era
    recusada. Contar pacotes lê o arquivo inteiro, então só entra quando a
    duração discorda.
    """
    if not (meta.duration and copy.duration) or abs(meta.duration - copy.duration) <= 0.2:
        return True
    return _packet_counts(meta.path, meta, tools, control) == _packet_counts(render, copy, tools, control)


def _language(code: str) -> str:
    # Sem idioma, o MP4 grava "und": para quem apagou o campo, é o mesmo.
    return "" if code in ("", "und") else code


def save_metadata(meta: FileMetadata, edit: MetadataEdit, tools: FFmpegTools, control: ProcessControl,
                  fallback: Path) -> SavedCopy:
    """Grava a cópia com ``edit``, confere e só então a publica. O original não muda."""
    directory = meta.path.parent
    fallback_used = not FFmpegCatalog().writable(directory)
    if fallback_used:
        directory = fallback
    store = FileOutputStore()
    lease = store.reserve(meta.path, meta, directory, t("OUTPUT_METADATA_SUFFIX"))
    destination = lease.path
    descriptor, name = tempfile.mkstemp(prefix=".videomanager-", suffix=destination.suffix,
                                        dir=destination.parent)
    os.close(descriptor)
    render = Path(name)
    try:
        with tempfile.TemporaryDirectory(prefix=".videomanager-meta-", dir=destination.parent) as folder:
            attach = None
            if meta.cover_as_attachment and edit.cover_image:
                attach = edit.cover_image
            elif meta.cover_as_attachment and meta.cover and meta.cover.stream == "picture" and not edit.remove_cover:
                image = cover_bytes(meta, tools, control)
                if image is None:
                    raise ConversionError(Text("META_COVER_UNREADABLE"))
                extension = next((ext for ext, mime in _MIMETYPES.items() if mime == meta.cover.mimetype), ".jpg")
                attach = Path(folder) / f"cover{extension}"
                attach.write_bytes(image)
            result = _run(control, metadata_args(meta, edit, render, tools, attach=attach), _SAVE_TIMEOUT)
            control.check()
            if result.returncode != 0 or not render.stat().st_size:
                lines = (result.stderr or b"").decode("utf-8", "replace").strip().splitlines()
                raise ConversionError(Text("META_FFMPEG_FAILED", detail=lines[-1] if lines else "?"))
        copy = read_metadata(render, tools, control)
        not_saved = verify_copy(meta, edit, copy)
        if not _same_content(meta, copy, render, tools, control):
            raise ConversionError(Text("META_COPY_DIFFERS"))
        control.check()
        store.commit(render, destination, lease=lease)
    except BaseException:
        store.abort(destination, lease=lease)
        raise
    finally:
        render.unlink(missing_ok=True)
    return SavedCopy(destination, not_saved, fallback_used)
