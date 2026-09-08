"""Entrega e cancelamento da exportação medidos com arquivos de mídia reais."""

from dataclasses import replace
import subprocess

import pytest

from videomanager.infrastructure.system.binaries import find_tools
from videomanager.infrastructure.system.binaries import subprocess_kwargs
from videomanager.domain.composition import Composition
from videomanager.infrastructure.ffmpeg.converter import Converter
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.application.errors import JobCancelled
from videomanager.domain.project import media_ref
from videomanager.domain.project import new_project
from videomanager.infrastructure.ffmpeg.thumbnail import embed_thumbnail
from videomanager.infrastructure.storage.outputs import FileOutputStore

pytestmark = pytest.mark.ffmpeg


@pytest.mark.parametrize("segments", [1, 2])
def test_cancelar_antes_de_iniciar_libera_reserva(source, tmp_path, monkeypatch, segments):
    media, tools = source
    target = Composition(new_project(media_ref(media)))
    lease = FileOutputStore().reserve(media.path, target, tmp_path, custom_stem="out")
    converter = Converter(media, target, lease.path, tools, lease=lease)
    monkeypatch.setattr("videomanager.infrastructure.ffmpeg.converter.plan_segments", lambda _: segments)
    def unexpected(*args, **kwargs):
        pytest.fail("cancelamento anterior ao início não deve abrir processo")
    monkeypatch.setattr(subprocess, "Popen", unexpected)
    converter.cancel()
    with pytest.raises(JobCancelled):
        converter.run()
    assert not lease.path.exists()


def test_temporario_nao_sobrescreve_arquivo_de_outra_operacao(source, tmp_path):
    media, tools = source
    sentinel = tmp_path / ".tmp_out.mp4"
    sentinel.write_bytes(b"arquivo de outra operacao")
    output = Converter(media, Composition(new_project(media_ref(media))), tmp_path / "out.mp4", tools).run()
    assert output.stat().st_size > 0
    assert sentinel.read_bytes() == b"arquivo de outra operacao"


@pytest.mark.parametrize("segments", [1, 2])
def test_falha_inesperada_na_capa_limpa_reserva_e_temporarios(source, tmp_path, monkeypatch, segments):
    media, tools = source
    target = Composition(new_project(media_ref(media)))
    lease = FileOutputStore().reserve(media.path, target, tmp_path, custom_stem="out")
    monkeypatch.setattr("videomanager.infrastructure.ffmpeg.converter.plan_segments", lambda _: segments)
    def fail(*args, **kwargs):
        raise OSError("falha simulada na capa")
    monkeypatch.setattr("videomanager.infrastructure.ffmpeg.converter.embed_thumbnail", fail)
    monkeypatch.setattr("videomanager.infrastructure.ffmpeg.parallel.embed_thumbnail", fail)
    with pytest.raises(OSError, match="falha simulada"):
        Converter(media, target, lease.path, tools, lease=lease).run()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.mp4"]


@pytest.fixture
def source(tmp_path):
    tools = find_tools()
    if tools is None:
        pytest.skip("ffmpeg/ffprobe indisponíveis")
    path = tmp_path / "source.mp4"
    subprocess.run([
        tools.ffmpeg_str, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
        "testsrc2=s=160x90:r=24:d=2", "-c:v", "libx264", str(path),
    ], check=True, timeout=20, **subprocess_kwargs())
    return probe_file(path, tools), tools


@pytest.mark.parametrize("segments", [1, 2])
def test_cancelar_na_capa_nao_entrega_sucesso(source, tmp_path, monkeypatch, segments):
    media, tools = source
    target = Composition(replace(new_project(media_ref(media)), fps=30), interpolate=True)
    lease = FileOutputStore().reserve(media.path, target, tmp_path, custom_stem='out')
    destination = lease.path
    converter = Converter(media, target, destination, tools, lease=lease)
    monkeypatch.setattr("videomanager.infrastructure.ffmpeg.converter.plan_segments", lambda _: segments)
    def cancel(*args, **kwargs):
        converter.cancel()
    monkeypatch.setattr("videomanager.infrastructure.ffmpeg.converter.embed_thumbnail", cancel)
    monkeypatch.setattr("videomanager.infrastructure.ffmpeg.parallel.embed_thumbnail", cancel)
    with pytest.raises(JobCancelled):
        converter.run()
    assert not destination.exists()
    assert not list(tmp_path.glob(".tmp_*"))
    assert not list(tmp_path.glob(".videomanager-*"))


def test_exportacao_paralela_incorpora_uma_unica_capa(source, tmp_path, monkeypatch):
    media, tools = source
    target = Composition(replace(new_project(media_ref(media)), fps=30), container="mkv", interpolate=True)
    monkeypatch.setattr("videomanager.infrastructure.ffmpeg.converter.plan_segments", lambda _: 2)
    calls = []
    def cover(path, tools, **kwargs):
        calls.append(path)
        embed_thumbnail(path, tools, **kwargs)
    monkeypatch.setattr("videomanager.infrastructure.ffmpeg.converter.embed_thumbnail", cover)
    monkeypatch.setattr("videomanager.infrastructure.ffmpeg.parallel.embed_thumbnail", cover)
    output = Converter(media, target, tmp_path / "out.mkv", tools).run()
    result = probe_file(output, tools)
    assert result.has_video
    assert result.duration == pytest.approx(2, abs=0.15)
    assert len(calls) == 1
    assert not list(tmp_path.glob(".videomanager-*"))


@pytest.mark.parametrize('segments', [1, 2])
def test_callback_com_falha_nao_deixa_processos_nem_arquivos(source, tmp_path, monkeypatch, segments):
    from videomanager.application.errors import ConversionError
    media, tools = source
    target = Composition(new_project(media_ref(media)))
    lease = FileOutputStore().reserve(media.path, target, tmp_path, custom_stem='out')
    children = []
    original = subprocess.Popen
    def popen(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    def fail(progress):
        raise RuntimeError('progresso indisponível')
    monkeypatch.setattr(subprocess, 'Popen', popen)
    monkeypatch.setattr('videomanager.infrastructure.ffmpeg.converter.plan_segments', lambda _: segments)
    with pytest.raises((RuntimeError, ConversionError), match='progresso indisponível'):
        Converter(media, target, lease.path, tools, lease=lease, on_progress=fail).run()
    assert children and all(child.poll() is not None for child in children)
    assert sorted(p.name for p in tmp_path.iterdir()) == ['source.mp4']


@pytest.mark.parametrize('segments', [1, 2])
def test_cancelamento_derruba_filho_que_ignora_terminate(source, tmp_path, monkeypatch, segments):
    import os
    import sys
    import threading
    import time
    if os.name == 'nt':
        pytest.skip('Windows TerminateProcess já encerra o filho à força; SIGTERM é POSIX')
    media, tools = source
    target = Composition(new_project(media_ref(media)))
    lease = FileOutputStore().reserve(media.path, target, tmp_path, custom_stem='out')
    marker = tmp_path / 'started'
    command = [sys.executable, '-c',
               'import signal,time,pathlib,sys; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
               'pathlib.Path(sys.argv[1]).touch(); time.sleep(60)', str(marker)]
    monkeypatch.setattr('videomanager.infrastructure.ffmpeg.converter.plan_segments', lambda _: segments)
    monkeypatch.setattr('videomanager.infrastructure.ffmpeg.converter.build_args', lambda *a, **k: command)
    monkeypatch.setattr('videomanager.infrastructure.ffmpeg.parallel.segment_video_args', lambda *a, **k: command)
    converter = Converter(media, target, lease.path, tools, lease=lease)
    errors, children = [], []
    original = subprocess.Popen
    def popen(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(subprocess, 'Popen', popen)
    def run():
        try:
            converter.run()
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        start = time.monotonic()
        converter.cancel()
        assert time.monotonic() - start < 0.5, 'a interface não deve aguardar o filho'
        thread.join(3)
        assert not thread.is_alive()
        assert errors and isinstance(errors[0], JobCancelled)
        assert all(child.poll() is not None for child in children)
        assert not lease.path.exists()
        assert not list(tmp_path.glob('.videomanager-*'))
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
        thread.join(5)


def test_juntar_audio_ligeiramente_mais_curto_preserva_todos_os_quadros(source, tmp_path):
    import json
    from videomanager.infrastructure.ffmpeg.composer import mux_args
    media, tools = source
    audio = tmp_path / 'audio.m4a'
    subprocess.run([
        tools.ffmpeg_str, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
        'sine=duration=1.9', '-c:a', 'aac', str(audio),
    ], check=True, timeout=10, **subprocess_kwargs())
    output = tmp_path / 'mux.mp4'
    subprocess.run(mux_args(media.path, audio, output, tools),
                   check=True, timeout=10, **subprocess_kwargs())
    result = subprocess.run([
        tools.ffprobe_str, '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=nb_frames,duration', '-of', 'json', str(output),
    ], check=True, timeout=10, **subprocess_kwargs())
    video = json.loads(result.stdout)['streams'][0]
    assert int(video['nb_frames']) == 48
    assert float(video['duration']) == pytest.approx(2, abs=0.01)
