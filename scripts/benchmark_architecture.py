"""Compara a migração com um checkout anterior, usando a mesma mídia local.

Uso: python scripts/benchmark_architecture.py --baseline /tmp/base/src --repeat 5
Não mede rede, GPU ou percepção de fluidez. Resultados saem como JSON no stdout.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time


def sample(args):
    sys.path.insert(0, str(args.source))
    before = time.perf_counter()
    if args.sample == 'startup':
        legacy = (args.source / 'videomanager' / 'core' / 'converter.py').exists()
        audio = importlib.import_module('videomanager.' + (
            'ui.audio_preview' if legacy else 'infrastructure.qt.audio'))
        audio.AudioPreview.available = property(lambda self: False)
        from videomanager.app import build_app
        app, window = build_app([])
        window.show()
        app.processEvents()
        elapsed = time.perf_counter() - before
        window.close()
    else:
        legacy = (args.source / 'videomanager' / 'core' / 'converter.py').exists()
        def module(old, new):
            return importlib.import_module('videomanager.' + (old if legacy else new))
        converter = module('core.converter', 'infrastructure.ffmpeg.converter')
        composer = module('core.composer', 'infrastructure.ffmpeg.composer')
        project_module = module('core.project', 'domain.project')
        binaries = module('core.binaries', 'infrastructure.system.binaries')
        preview = module('core.preview', 'infrastructure.ffmpeg.preview')
        composition = module('core.composer', 'domain.composition').Composition
        tools = binaries.find_tools()
        assert tools is not None
        media = converter.probe_file(args.fixture, tools)
        project = project_module.new_project(project_module.media_ref(media))
        before = time.perf_counter()
        if args.sample in ('preview', 'seek'):
            seconds = 0 if args.sample == 'preview' else 1.5
            command = composer.frame_command(project, seconds, (320, 180), tools)
            frame = preview.frame_from_command(command, (320, 180))
            assert frame is not None and frame.is_complete
        else:
            converter.Converter(media, composition(project), args.destination, tools).run()
        elapsed = time.perf_counter() - before
    result = {'seconds': elapsed}
    if sys.platform == 'linux':
        import resource
        # São picos separados; somá-los não mede o pico simultâneo do conjunto.
        result['python_peak_mib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        result['child_peak_mib'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    print(json.dumps(result))


def compare(args):
    sys.path.insert(0, str(args.source))
    from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs
    tools = find_tools()
    if tools is None:
        raise RuntimeError('Instale ou provisione ffmpeg/ffprobe antes de medir.')
    results = {'python': platform.python_version(), 'platform': platform.platform(),
               'repeat': args.repeat, 'fixture': 'testsrc2+sine, 640x360, 24fps, 3s', 'runs': {}}
    with tempfile.TemporaryDirectory(prefix='vm-benchmark-') as directory:
        temp = Path(directory)
        fixture = temp / 'source.mp4'
        subprocess.run([tools.ffmpeg_str, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=s=640x360:r=24:d=3', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=3', '-c:v', 'libx264', '-c:a', 'aac',
                        '-shortest', str(fixture)], check=True, **subprocess_kwargs())
        sources = [('baseline', args.baseline), ('current', args.source)] if args.baseline else [('current', args.source)]
        for scenario in ('startup', 'preview', 'seek', 'export'):
            for label, _ in sources:
                results['runs'][label + '_' + scenario] = {'samples': []}
            # Intercala versões para reduzir o efeito da ordem/cache da máquina.
            for iteration in range(args.repeat):
                for label, source in sources:
                    env = dict(os.environ, QT_QPA_PLATFORM='offscreen',
                               PATH=str(tools.ffmpeg.parent) + os.pathsep + os.environ.get('PATH', ''),
                               XDG_CONFIG_HOME=str(temp / 'config'), XDG_DATA_HOME=str(temp / 'data'),
                               XDG_CACHE_HOME=str(temp / 'cache'))
                    command = [sys.executable, str(Path(__file__).resolve()), '--source', str(source.resolve()),
                               '--sample', scenario, '--fixture', str(fixture), '--destination',
                               str(temp / f'{label}-{iteration}.mp4')]
                    completed = subprocess.run(command, env=env, text=True, capture_output=True, check=True, timeout=90)
                    results['runs'][label + '_' + scenario]['samples'].append(json.loads(completed.stdout))
        for data in results['runs'].values():
            times = [s['seconds'] for s in data['samples']]
            data.update(median_seconds=statistics.median(times), min_seconds=min(times), max_seconds=max(times),
                        p95_seconds=sorted(times)[math.ceil(len(times) * .95) - 1])
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] / 'src')
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--sample', choices=('startup', 'preview', 'seek', 'export'))
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--destination', type=Path)
    options = parser.parse_args()
    if options.repeat < 1:
        parser.error('--repeat precisa ser positivo')
    sample(options) if options.sample else compare(options)
