"""Mede a resposta da agulha arrastada, com e sem o cache de quadros.

    PYTHONPATH=src python scripts/validate_scrub.py [--seconds 30] [--size 1920x1080]

Gera um vídeo sintético, compõe o cache de um trecho como a prévia faz e compara
o custo por movimento da agulha: quadro guardado (assinatura + JPEG + QPixmap)
contra o quadro exato (um ffmpeg por quadro). Os números servem para comparar
máquinas e versões; não substituem arrastar a agulha no aplicativo.
"""

from __future__ import annotations

import argparse
import io
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from videomanager.application.media.scrub import ScrubFrameCache  # noqa: E402
from videomanager.domain.preview import fit_size  # noqa: E402
from videomanager.domain.project import media_ref, new_project  # noqa: E402
from videomanager.domain.scrub import render_signature, signature_at, signature_segments  # noqa: E402
from videomanager.infrastructure.ffmpeg.composer import frame_command, scrub_command  # noqa: E402
from videomanager.infrastructure.ffmpeg.converter import probe_file  # noqa: E402
from videomanager.infrastructure.ffmpeg.preview import frame_from_command, jpeg_frames  # noqa: E402
from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--size", default="1920x1080")
    options = parser.parse_args()
    width, height = (int(v) for v in options.size.split("x"))
    app = QApplication.instance() or QApplication([])
    tools = find_tools()
    if tools is None:
        print("ffmpeg/ffprobe indisponíveis", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="videomanager-scrub-") as folder:
        source = Path(folder) / "fonte.mp4"
        subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"testsrc2=s={width}x{height}:r=30:d={options.seconds}", "-c:v", "libx264",
                        "-preset", "veryfast", "-g", "60", str(source)], check=True, **subprocess_kwargs())
        project = new_project(media_ref(probe_file(source, tools)))
        fps = 30.0
        size = fit_size(project.width, project.height, 640, 360)
        span = min(20.0, float(options.seconds))

        began = time.perf_counter()
        result = subprocess.run(scrub_command(project, 0.0, span, size, tools, fps=fps), check=True,
                                **subprocess_kwargs())
        images = list(jpeg_frames(io.BytesIO(result.stdout).read))
        fill_seconds = time.perf_counter() - began
        cache = ScrubFrameCache(fps, size, 1 << 30)
        segments = signature_segments(project, 0.0, span)
        for index, data in enumerate(images):
            cache.put(index, signature_at(segments, index / fps), data, focus_index=0)

        hits = []
        positions = [i * span / 400 for i in range(400)]
        for seconds in positions:
            start = time.perf_counter()
            index = cache.index_of(seconds)
            data = cache.get(index, render_signature(project, cache.seconds_of(index)))
            pixmap = QPixmap.fromImage(QImage.fromData(data, "JPG"))
            assert not pixmap.isNull()
            hits.append(time.perf_counter() - start)

        exact = []
        preview = fit_size(project.width, project.height, 1280, 720)
        for seconds in positions[::40]:
            start = time.perf_counter()
            frame = frame_from_command(frame_command(project, seconds, preview, tools), preview)
            assert frame is not None and frame.is_complete
            exact.append(time.perf_counter() - start)

    average_bytes = sum(len(i) for i in images) / max(1, len(images))
    print(f"fonte: {width}x{height}, cache {size[0]}x{size[1]} a {fps:g} q/s")
    print(f"preenchimento: {len(images)} quadros em {fill_seconds:.2f} s "
          f"({len(images) / fill_seconds:.0f} q/s, {span / fill_seconds:.1f}x tempo real), "
          f"{average_bytes / 1024:.1f} KB por quadro")
    print(f"agulha com cache: mediana {statistics.median(hits) * 1000:.2f} ms, "
          f"p95 {sorted(hits)[int(len(hits) * .95)] * 1000:.2f} ms por movimento")
    print(f"agulha sem cache: mediana {statistics.median(exact) * 1000:.0f} ms por quadro "
          f"({1 / statistics.median(exact):.1f} q/s)")
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
