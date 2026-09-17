"""Emenda do loop da prévia sem corte.

Antes, ao chegar ao fim com Loop marcado, a prévia parava imagem e som e
reabria tudo do zero: o ffmpeg novo levava de 150 a 500 ms até o primeiro
quadro, com a tela parada no último quadro (muitas vezes preto) e o som mudo.
Agora, perto do fim, a imagem do começo já espera pronta e o som do começo
entra na mesma fila da placa, emendado sem pausa.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from videomanager.infrastructure.qt.audio import AudioPreview


class _Sink:
    def __init__(self) -> None:
        self.processed = 0

    def bytesFree(self) -> int:  # noqa: N802
        return 1 << 20

    def processedUSecs(self) -> int:  # noqa: N802
        return self.processed

    def write(self, data: bytes) -> int:
        return len(data)


class _Finished:
    returncode = 0

    def poll(self):
        return 0


def _audio_with(first: list, second: list) -> AudioPreview:
    audio = AudioPreview(enabled=False)
    sink = _Sink()
    audio._sink, audio._device = sink, sink
    audio._bytes_per_second = 1000
    audio._segments = [(0.0, 3.0)]
    audio._written = 0
    current: queue.Queue = queue.Queue()
    for chunk in first:
        current.put(chunk)
    audio._chunks = current
    nxt: queue.Queue = queue.Queue()
    for chunk in second:
        nxt.put(chunk)
    audio._next = (_Finished(), nxt, 0.0, threading.Event())
    audio._process = _Finished()
    return audio


def test_som_do_comeco_entra_na_mesma_fila_sem_parar() -> None:
    audio = _audio_with([b"a" * 500, None], [b"b" * 300])
    ended = []
    audio._finish = lambda: ended.append(True)
    audio._pump()
    assert not ended, "o fim do primeiro trecho não encerra a reprodução"
    assert audio._next is None and audio._segments == [(0.0, 3.0), (0.5, 0.0)]
    audio._sink.processed = 400_000
    assert audio.position == pytest.approx(3.4)
    audio._sink.processed = 600_000
    assert audio.position == pytest.approx(0.1), "depois da emenda o relógio volta ao começo"


def test_sem_proximo_trecho_o_fim_continua_sendo_anunciado() -> None:
    audio = _audio_with([b"a" * 10, None], [])
    audio._next = None
    ended = []
    audio._finish = lambda: ended.append(True)
    audio._pump()
    assert ended


def test_cancelar_o_proximo_trecho_libera_o_leitor() -> None:
    audio = _audio_with([b"a"], [b"b"])
    event = audio._next[3]
    audio.cancel_next()
    assert audio._next is None and event.is_set()


def test_mixagem_do_loop_tem_exatamente_o_tamanho_ate_o_fim() -> None:
    from videomanager.application.capabilities import FFmpegTools
    from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
    from videomanager.infrastructure.ffmpeg.composer import audio_command

    som = MediaRef(Path("/m/s.mp3"), MediaKind.AUDIO, duration=2, has_audio=True, channels=2)
    project = Project(tracks=(Track(TrackKind.AUDIO, clips=(Clip(som, 0, 2),)),))
    tools = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")
    command = audio_command(project, 1.0, tools, until=5.0)
    graph = command[command.index("-filter_complex") + 1]
    assert "apad" in graph and "atrim=end=4.000000" in graph
    assert "apad" not in " ".join(audio_command(project, 1.0, tools))


@pytest.mark.usefixtures("desktop_app", "isolated_audio")
def test_virada_do_loop_usa_a_imagem_pronta_sem_reabrir(monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from videomanager.application.capabilities import FFmpegTools
    from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
    from videomanager.domain.project import Clip, MediaKind, MediaRef, Track, TrackKind
    from videomanager.infrastructure.qt.workers.signals import PreviewSignals
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.panels import edit_panel as module

    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    tools = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")
    runtime = build_desktop_runtime(audio_enabled=False)
    workers = []

    def playback_worker(project, seconds, size, tools, token, *, fps, text_assets=None, autostart=True):
        worker = SimpleNamespace(seconds=seconds, autostart=autostart, token=token, started=[], cancelled=[],
                                 signals=PreviewSignals())
        worker.start_playback = lambda: worker.started.append(True)
        worker.cancel = lambda: worker.cancelled.append(True)
        workers.append(worker)
        return worker

    monkeypatch.setattr(runtime, "playback_worker", playback_worker)
    panel = module.EditPanel(Settings(), ensure_tools=lambda: tools, editor=build_editor_service(),
                             processing=build_processing_service(), runtime=runtime)
    monkeypatch.setattr(panel._runner, "start", lambda *args: None)
    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    try:
        video = MediaRef(Path("/m/v.mp4"), MediaKind.VIDEO, duration=4, width=320, height=180, fps=30)
        panel.install_project(replace(panel._project, tracks=(Track(TrackKind.VIDEO, clips=(Clip(video, 0, 4),)),)),
                              None, [], {})
        panel._loop.setChecked(True)
        reopened = []
        monkeypatch.setattr(panel, "_loop_playback", lambda: reopened.append(True))

        panel._start_playback(2.0)
        main = workers[-1]
        opened_before = len(workers)
        assert main.seconds == pytest.approx(2.0)
        panel._on_playback_primed(main.token)  # primeiro quadro pronto: o relógio anda

        now[0] += 1.2  # 3,2 s: faltam menos de 1,5 s
        panel._on_tick()
        loop_worker = workers[-1]
        assert loop_worker is not main and loop_worker.seconds == 0.0 and loop_worker.autostart is False

        now[0] += 0.9  # 4,1 s: passou do fim
        panel._on_tick()
        assert loop_worker.started, "a imagem do começo é liberada, não reaberta"
        assert main.cancelled
        assert panel._play_token == loop_worker.token
        # Só o fluxo do começo foi aberto depois do play; nada na virada.
        assert len(workers) == opened_before + 1 and not reopened
        assert panel._position == pytest.approx(0.1, abs=0.05)
        assert panel._playing
    finally:
        panel.shutdown()


@pytest.mark.ffmpeg
def test_mixagem_real_sai_com_o_tamanho_exato_do_loop(tmp_path) -> None:
    import subprocess

    from videomanager.domain.project import Clip, Project, Track, TrackKind, media_ref
    from videomanager.infrastructure.ffmpeg.composer import CHANNELS, SAMPLE_RATE, audio_command
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs

    tools = find_tools()
    if tools is None:
        pytest.skip("ffmpeg/ffprobe indisponíveis")
    source = tmp_path / "som.wav"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=2",
                    str(source)], check=True, timeout=30, **subprocess_kwargs())
    som = media_ref(probe_file(source, tools))
    project = Project(tracks=(Track(TrackKind.AUDIO, clips=(Clip(som, 0, 2),)),))
    command = audio_command(project, 1.0, tools, until=5.0)
    result = subprocess.run(command, timeout=60, **subprocess_kwargs())
    # O som acaba em 2 s, mas o trecho vai até o fim do loop, em 5 s: 4 s de PCM.
    assert len(result.stdout) == 4 * SAMPLE_RATE * CHANNELS * 2
