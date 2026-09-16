"""Ensaio opt-in de gestos e recursos com Qt/FFmpeg reais, sem áudio físico.

Execute com PYTHONPATH=src e QT_QPA_PLATFORM=offscreen. Usa somente mídia e
preferências temporárias. Os handlers reais recebem gestos a 60 Hz; isto mede
atualização canônica e escoamento de workers, não percepção em monitor físico.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time


def distribution(values):
    ordered = sorted(values)
    return {'count': len(ordered), 'median_ms': statistics.median(ordered) * 1000,
            'p95_ms': ordered[math.ceil(len(ordered) * .95) - 1] * 1000,
            'max_ms': max(ordered) * 1000} if ordered else {'count': 0}


def run(gestures):
    with tempfile.TemporaryDirectory(prefix='vm-editor-responsiveness-') as directory:
        folder = Path(directory)
        for variable, name in (('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                               ('XDG_CACHE_HOME', 'cache')):
            os.environ[variable] = str(folder / name)
        from videomanager.app import build_app
        from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, media_ref
        from videomanager.infrastructure.ffmpeg.converter import probe_file
        from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs
        tools = find_tools()
        if tools is None:
            raise RuntimeError('O ensaio requer FFmpeg e ffprobe.')
        source = folder / 'scene.mp4'
        subprocess.run([tools.ffmpeg_str, '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=s=640x360:r=30:d=6', '-c:v', 'libx264', str(source)],
                       check=True, timeout=30, **subprocess_kwargs())
        app, window = build_app([], audio_enabled=False)
        panel = window._edit
        window._tabs.setCurrentIndex(2)
        window.show()
        app.processEvents()
        video = Clip(media_ref(probe_file(source, tools)), 0, 6)
        title = Clip(MediaRef(folder / 'Texto', MediaKind.IMAGE), 0, 6, overlay_type='text',
                     text_content='Ensaio de atualização', font_size=30, opacity=.7)
        effect = Clip(MediaRef(folder / 'Filtro', MediaKind.IMAGE), 0, 6,
                      overlay_type='filter', filter_name='contraste')
        project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(title, effect)),
                                  Track(TrackKind.VIDEO, clips=(video,))), width=640, height=360)
        requested = {}
        accepted_delays, final_delays, heartbeat, rss = [], [], [], []
        counters = {'requests': 0, 'started': 0, 'emitted': 0, 'presented': 0,
                    'max_frame_workers': 0, 'max_runner_workers': 0, 'max_children': 0}
        active = set()
        original_worker, original_show = panel._runtime.frame_worker, panel._show_frame
        def make_worker(*args, **kwargs):
            worker = original_worker(*args, **kwargs)
            counters['started'] += 1
            active.add(id(worker))
            counters['max_frame_workers'] = max(counters['max_frame_workers'], len(active))
            worker.signals.done.connect(lambda: active.discard(id(worker)))
            worker.signals.frame.connect(lambda *_: counters.__setitem__('emitted', counters['emitted'] + 1))
            return worker
        def show(frame):
            counters['presented'] += 1
            key = panel._presented_key
            if key is not None and key.revision in requested:
                accepted_delays.append(time.monotonic() - requested[key.revision])
            original_show(frame)
        panel._runtime.frame_worker, panel._show_frame = make_worker, show
        last_event = [time.monotonic()]
        def tick():
            app.processEvents()
            now = time.monotonic()
            heartbeat.append(now - last_event[0])
            last_event[0] = now
            counters['max_runner_workers'] = max(counters['max_runner_workers'], panel._runner.active + panel._background.active)
            children = set()
            for path in Path('/proc/self/task').glob('*/children'):
                try:
                    children.update(path.read_text().split())
                except FileNotFoundError:
                    pass
            counters['max_children'] = max(counters['max_children'], len(children))
            time.sleep(.002)
        def wait(predicate, timeout=15):
            deadline = time.monotonic() + timeout
            while not predicate():
                if time.monotonic() >= deadline:
                    raise RuntimeError('Prazo excedido ao aguardar a revisão ou o encerramento.')
                tick()
        def current():
            key = panel._presented_key
            return key is not None and key.revision == panel._frame_revision and not panel._frame_busy
        try:
            panel.install_project(project, folder / 'project.vmp', [video.media], {})
            panel._timeline.select(title.clip_id)
            wait(current)
            for gesture in range(gestures):
                for step in range(8):
                    before = time.monotonic()
                    x = .3 + .4 * ((gesture * 8 + step) % 23) / 22
                    panel._on_overlay_transformed(title.clip_id, x, .5, 1, 0)
                    requested[panel._frame_revision] = before
                    counters['requests'] += 1
                    until = before + 1 / 60
                    while time.monotonic() < until:
                        tick()
                before = time.monotonic()
                panel._on_overlay_transform_finished(title.clip_id)
                requested[panel._frame_revision] = before
                counters['requests'] += 1
                wait(current)
                final_delays.append(time.monotonic() - before)
                status = Path('/proc/self/status')
                if status.exists():
                    rss.append(next(int(line.split()[1]) / 1024 for line in status.read_text().splitlines()
                                    if line.startswith('VmRSS:')))
            panel._session.mark_saved()
        finally:
            before = time.monotonic()
            panel.shutdown()
            wait(lambda: panel._runner.active == 0 and panel._background.active == 0)
            shutdown_seconds = time.monotonic() - before
            panel._session.mark_saved()
            window.close()
            app.processEvents()
        result = {'gestures': gestures, 'steps_per_gesture': 8, 'requested_hz': 60,
                  'scene': 'vídeo testsrc2 640x360 + texto semitransparente + contraste',
                  'preview_size': panel._preview_size(), 'counters': counters,
                  'snapshot_latency': distribution(accepted_delays),
                  'final_latency': distribution(final_delays), 'event_loop': distribution(heartbeat),
                  'shutdown_ms': shutdown_seconds * 1000, 'workers_after_shutdown': panel._runner.active + panel._background.active}
        result['rss_mib_after_each_gesture'] = rss
        if os.name == 'posix':
            import resource
            result['python_peak_mib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            result['children_cpu_seconds'] = sum(resource.getrusage(resource.RUSAGE_CHILDREN)[:2])
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gestures', type=int, default=30)
    args = parser.parse_args()
    if args.gestures < 1:
        parser.error('--gestures precisa ser positivo')
    run(args.gestures)
