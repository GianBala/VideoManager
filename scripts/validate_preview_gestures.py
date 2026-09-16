"""Mede conteúdo e eventos reais de arrasto na prévia, sem áudio físico.

Execute com PYTHONPATH=src e QT_QPA_PLATFORM=offscreen. O ensaio guarda apenas
mídia e preferências temporárias; o JSON sai em stdout.
"""
import json
import argparse
import math
import os
from pathlib import Path
import statistics
import tempfile
import time


def main(canonical_only=False):
    with tempfile.TemporaryDirectory(prefix='vm-pointer-') as folder:
        for key in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            os.environ[key] = str(Path(folder) / key)
        from PySide6.QtCore import Qt, QPoint, QEvent, QObject
        from PySide6.QtGui import QColor, QImage
        from PySide6.QtTest import QTest
        from videomanager.app import build_app
        from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
        app, window = build_app([], audio_enabled=False)
        panel, preview = window._edit, window._edit._preview
        if canonical_only:
            panel._prepare_interaction = lambda: None
        window.resize(1920, 1080)
        window._tabs.setCurrentIndex(2)
        window.show()
        preview.setFixedSize(640, 360)
        def wait(test):
            until = time.monotonic() + 15
            while not test() and time.monotonic() < until:
                app.processEvents(); time.sleep(.001)
            assert test(), 'Prazo de preparação da prévia excedido'
        def media(name, color):
            path = Path(folder) / (name + '.png')
            im = QImage(320, 180, QImage.Format.Format_RGBA8888)
            im.fill(QColor(color)); im.save(str(path))
            return MediaRef(path, MediaKind.IMAGE, width=320, height=180)
        background = Clip(media('background', 'lime'), 0, 5)
        moving = Clip(media('moving', 'red'), 0, 5, scale_x=.25, scale_y=.25, x=.3)
        project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(moving,)),
                                  Track(TrackKind.VIDEO, clips=(background,))), width=640, height=360)
        requests = []
        original = panel._runtime.frame_worker
        def frame_worker(*args, **kwargs):
            requests.append(time.monotonic())
            return original(*args, **kwargs)
        panel._runtime.frame_worker = frame_worker
        panel._apply(project)
        panel._timeline.select(moving.clip_id)
        wait(lambda: preview.has_frame and not panel._frame_busy)
        if not canonical_only and hasattr(preview, '_interaction_layers'):
            wait(lambda: preview._interaction_layers is not None)
        preview.set_snap_enabled(False)
        pending = [None]
        paints = []
        class PaintMonitor(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Paint and pending[0] is not None:
                    paints.append((time.perf_counter() - pending[0]) * 1000)
                    pending[0] = None
                return False
        monitor = PaintMonitor(preview)
        preview.installEventFilter(monitor)
        content_matches = 0
        start_requests = len(requests)
        for gesture in range(12):
            x, y, _, _ = preview._clip_geometry(preview._active_clip)
            start = QPoint(round(x), round(y))
            QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=start)
            direction = 1 if gesture % 2 == 0 else -1
            for step in range(1, 13):
                target = start + QPoint(direction * step * 6, 0)
                pending[0] = time.perf_counter()
                QTest.mouseMove(preview, target)
                app.processEvents()
                # A borda de pixels vermelhos deve acompanhar a pose inteira;
                # mover só a caixa de alças não satisfaz essa medição.
                cx, cy, w, h = preview._clip_geometry(preview._active_clip)
                image = preview.grab().toImage()
                row = [x for x in range(image.width())
                       if (p := image.pixelColor(x, round(cy + h * .25))).red() > 200 and p.green() < 30]
                content_matches += bool(row and abs(min(row) - (cx - w / 2)) <= 2
                                        and abs(max(row) + 1 - (cx + w / 2)) <= 2)
                time.sleep(.016)
            QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=target)
            wait(lambda: not panel._frame_busy)
        result = {'canonical_only': canonical_only, 'gestures': 12, 'moves': 144, 'content_followed_immediately': content_matches,
                  'full_renders': len(requests) - start_requests,
                  'paint_ms': {'median': statistics.median(paints),
                               'p95': sorted(paints)[math.ceil(.95*len(paints))-1], 'max': max(paints)}}
        panel.shutdown()
        wait(lambda: panel._runner.active == 0 and panel._background.active == 0)
        result['workers_after_shutdown'] = panel._runner.active + panel._background.active
        panel._session.mark_saved(); window.close()
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canonical-only', action='store_true')
    main(parser.parse_args().canonical_only)
