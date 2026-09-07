"""Entrega e cancelamento da exportação medidos com arquivos de mídia reais."""

from dataclasses import replace
import subprocess

import pytest

from videomanager.core.binaries import find_tools, subprocess_kwargs
from videomanager.core.composer import Composition
from videomanager.core.converter import Converter, probe_file
from videomanager.core.errors import JobCancelled
from videomanager.core.project import media_ref, new_project
from videomanager.core.thumbnail import embed_thumbnail

pytestmark = pytest.mark.ffmpeg


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
    destination = tmp_path / "out.mp4"
    converter = Converter(media, target, destination, tools)
    monkeypatch.setattr("videomanager.core.converter.plan_segments", lambda _: segments)
    def cancel(*args, **kwargs):
        converter.cancel()
    monkeypatch.setattr("videomanager.core.converter.embed_thumbnail", cancel)
    monkeypatch.setattr("videomanager.core.parallel_export.embed_thumbnail", cancel)
    with pytest.raises(JobCancelled):
        converter.run()
    assert not destination.exists()
    assert not list(tmp_path.glob(".tmp_*"))
    assert not list(tmp_path.glob(".videomanager-*"))


def test_exportacao_paralela_incorpora_uma_unica_capa(source, tmp_path, monkeypatch):
    media, tools = source
    target = Composition(replace(new_project(media_ref(media)), fps=30), container="mkv", interpolate=True)
    monkeypatch.setattr("videomanager.core.converter.plan_segments", lambda _: 2)
    calls = []
    def cover(path, tools, **kwargs):
        calls.append(path)
        embed_thumbnail(path, tools, **kwargs)
    monkeypatch.setattr("videomanager.core.converter.embed_thumbnail", cover)
    monkeypatch.setattr("videomanager.core.parallel_export.embed_thumbnail", cover)
    output = Converter(media, target, tmp_path / "out.mkv", tools).run()
    result = probe_file(output, tools)
    assert result.has_video
    assert result.duration == pytest.approx(2, abs=0.15)
    assert len(calls) == 1
    assert not list(tmp_path.glob(".videomanager-*"))
