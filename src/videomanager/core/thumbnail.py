"""Capa opcional da exportação, com cancelamento e arquivos temporários próprios."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from .binaries import FFmpegTools
from .process import ProcessControl

_LOG = logging.getLogger(__name__)


def embed_thumbnail(destination: Path, tools: FFmpegTools,
                    *, control: ProcessControl | None = None) -> None:
    """Acrescenta uma capa; falhas cosméticas preservam a exportação original."""
    control = control or ProcessControl()
    control.check()
    container = destination.suffix.lower()
    if container not in (".mp4", ".mov", ".m4v", ".mkv", ".matroska"):
        return
    try:
        with tempfile.TemporaryDirectory(prefix=".videomanager-cover-", dir=destination.parent) as temp:
            thumbnail = Path(temp) / "cover.jpg"
            probe = control.run([
                tools.ffprobe_str, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(destination),
            ])
            try:
                seek = max(0.0, float(probe.stdout.strip()) / 2) if probe.returncode == 0 else 0.0
            except ValueError:
                seek = 0.0
            for position in (seek, 0.0):
                result = control.run([
                    tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error", "-y",
                    "-ss", f"{position:.3f}", "-i", str(destination),
                    "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "2", str(thumbnail),
                ])
                if result.returncode == 0 and thumbnail.is_file() and thumbnail.stat().st_size:
                    break
            else:
                _LOG.warning("Não foi possível gerar a capa de %s", destination)
                return
            control.check()
            if container in (".mp4", ".mov", ".m4v"):
                try:
                    from mutagen.mp4 import MP4, MP4Cover
                    media = MP4(destination)
                    media["covr"] = [MP4Cover(thumbnail.read_bytes(), imageformat=MP4Cover.FORMAT_JPEG)]
                    media.save()
                except Exception as exc:
                    # mutagen é opcional; seu erro dá lugar ao remux padrão.
                    _LOG.debug("Capa nativa indisponível: %s", exc)
                else:
                    control.check()
                    return
            output = Path(temp) / f"covered{container}"
            command = [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(destination)]
            if container in (".mkv", ".matroska"):
                command += ["-attach", str(thumbnail), "-map", "0", "-c", "copy",
                            "-metadata:s:t:0", "mimetype=image/jpeg", "-metadata:s:t:0", "filename=cover.jpg"]
            else:
                command += ["-i", str(thumbnail), "-map", "0", "-map", "1", "-c", "copy",
                            "-c:v:1", "mjpeg", "-disposition:v:1", "attached_pic", "-movflags", "+faststart"]
            command += ["-map_metadata", "-1", "-map_chapters", "-1", str(output)]
            result = control.run(command, timeout=1800)
            control.check()
            if result.returncode == 0 and output.is_file() and output.stat().st_size:
                output.replace(destination)
            else:
                _LOG.warning("Não foi possível incorporar a capa de %s", destination)
    except (OSError, subprocess.SubprocessError) as exc:
        _LOG.warning("Falha ao preparar a capa de %s: %s", destination, exc)
