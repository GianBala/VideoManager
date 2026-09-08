"""Validação opt-in do dispositivo real: toca um tom baixo por poucos segundos.

Execute com PYTHONPATH=src python scripts/validate_audio.py. Não altera as
preferências do usuário nem o volume do sistema; mede o consumo pelo QAudioSink.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import time

from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaDevices

from videomanager.domain.project import media_ref, new_project
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.qt.runtime import DesktopRuntime
from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs


def main() -> None:
    app = QApplication([])
    tools = find_tools()
    if tools is None:
        raise RuntimeError('FFmpeg/ffprobe indisponíveis')
    runtime = DesktopRuntime()
    output = runtime.audio_output()
    if not output.available:
        raise RuntimeError('Nenhum dispositivo de saída de áudio disponível')
    device = QMediaDevices.defaultAudioOutput()
    output.set_volume(10)
    stopped = []
    output.stopped.connect(lambda: stopped.append(time.monotonic()))
    with tempfile.TemporaryDirectory(prefix='vm-audio-') as directory:
        source = Path(directory) / 'tone.wav'
        subprocess.run([
            tools.ffmpeg_str, '-nostdin', '-v', 'error', '-f', 'lavfi',
            '-i', 'sine=frequency=440:duration=2:sample_rate=44100',
            '-af', 'volume=0.1', str(source),
        ], check=True, timeout=10, **subprocess_kwargs())
        project = new_project(media_ref(probe_file(source, tools)))
        try:
            # Pausa e reinício em outro ponto não podem reutilizar PCM antigo.
            runtime.play_audio(output, project, 0, tools)
            if not output.playing:
                raise RuntimeError('A placa recusou o formato ou a abertura do fluxo')
            initial = time.monotonic()
            while time.monotonic() - initial < 0.3:
                app.processEvents()
                time.sleep(0.005)
            old_process = output._process
            pause = time.monotonic()
            output.stop()
            pause_ms = (time.monotonic() - pause) * 1000
            runtime.play_audio(output, project, 0.5, tools)
            if not output.playing:
                raise RuntimeError('Falha ao reiniciar o áudio')
            sink = output._sink
            current_process = output._process
            started = time.monotonic()
            positions, errors = [], set()
            while not stopped and time.monotonic() - started < 8:
                positions.append(output.position)
                errors.add(str(sink.error()))
                app.processEvents()
                time.sleep(0.005)
            if not stopped or max(positions, default=0) < 1.8:
                raise RuntimeError('Áudio não consumido integralmente pela placa')
            if positions != sorted(positions):
                raise RuntimeError('Relógio de reprodução retrocedeu')
            if errors != {'Error.NoError'}:
                raise RuntimeError(f'Falha reportada pelo sink: {errors}')
            for process in (old_process, current_process):
                if process is not None:
                    process.wait(timeout=2)
            print(json.dumps({
                'device': device.description(), 'pcm': output.target_format,
                'pause_ms': round(pause_ms, 2),
                'last_position': round(max(positions), 3),
                'playback_seconds': round(stopped[0] - started, 3),
                'stopped_events': len(stopped), 'errors': sorted(errors),
                'result': 'VM_AUDIO_OK',
            }, ensure_ascii=False, indent=2))
        finally:
            output.stop()


if __name__ == '__main__':
    main()
