"""Fluidez da reprodução da prévia: ritmo dos quadros, som e emendas.

A imagem andava aos trancos o tempo todo, mais visível nos cortes e na volta do
loop. Medido no painel real (30 q/s, Windows): intervalos de 25 a 48 ms entre
quadros, imagem 77 ms à frente do som e 147 ms de imagem parada na volta do
loop. As causas, cada uma fixada aqui:

- o ritmo era medido com ``time.monotonic``, que no Windows até o Python 3.12
  anda em degraus de 15,6 ms;
- a imagem saía antes do som começar (abrir a mixagem leva uns 120 ms) e nunca
  mais se acertava com ele;
- o fluxo do começo do loop só era solto no tique que percebia a volta, e o
  primeiro quadro dele era descartado.
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from videomanager.application.errors import VideoManagerError
from videomanager.application.media.preview import playback_clock
from videomanager.domain.preview import RawFrame
from videomanager.infrastructure.ffmpeg.preview import FramePump


class _Stream:
    """Saída de um ffmpeg falso: ``frames`` quadros, com uma demora opcional."""

    def __init__(self, frames: int, *, stall_at: int = 0, stall: float = 0.0, tail: bytes = b"") -> None:
        self.frames, self.stall_at, self.stall, self.tail = frames, stall_at, stall, tail
        self.reads = 0
        self.closed = False

    def read(self, size: int) -> bytes:
        if self.closed:
            raise ValueError("fechado")
        self.reads += 1
        if self.reads == self.stall_at:
            time.sleep(self.stall)
        if self.reads <= self.frames:
            return b"x" * size
        tail, self.tail = self.tail, b""
        return tail

    def close(self) -> None:
        self.closed = True


class _Process:
    def __init__(self, stream: _Stream, returncode: int = 0) -> None:
        self.stdout, self.stderr = stream, None
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True

    def wait(self, timeout=None) -> int:
        return self.returncode


def _launch(monkeypatch, process: _Process) -> None:
    monkeypatch.setattr(
        "videomanager.infrastructure.ffmpeg.preview.subprocess.Popen", lambda *args, **kwargs: process
    )


class TestRitmoDosQuadros:
    def test_relogio_da_reproducao_tem_resolucao_fina(self) -> None:
        # Com ``monotonic`` no Windows o menor passo era 15,6 ms: a espera de
        # cada quadro errava até um passo, em dente de serra.
        steps: list[float] = []
        last = playback_clock()
        deadline = time.perf_counter() + 0.5
        while len(steps) < 20 and time.perf_counter() < deadline:
            now = playback_clock()
            if now != last:
                steps.append(now - last)
                last = now
        assert steps and min(steps) < 0.001

    def test_fila_adiantada_absorve_demora_da_producao(self, monkeypatch) -> None:
        # O 8º quadro demora 300 ms para sair do ffmpeg — como abrir o
        # decodificador do bloco seguinte num corte. Lendo só na hora de
        # mostrar, a tela parava esse tempo todo.
        _launch(monkeypatch, _Process(_Stream(12, stall_at=8, stall=0.3)))
        pump = FramePump(["ffmpeg"], 0.0, (1, 1), fps=20)
        moments = [playback_clock() for _frame in pump.frames()]
        assert len(moments) == 12
        gaps = [after - before for before, after in zip(moments, moments[1:])]
        assert max(gaps) < 0.15

    def test_hora_marcada_segura_o_primeiro_quadro(self, monkeypatch) -> None:
        _launch(monkeypatch, _Process(_Stream(3)))
        pump = FramePump(["ffmpeg"], 5.0, (1, 1), fps=20)
        assert pump.clock_position() is None
        at = playback_clock() + 0.15
        pump.start_at(at)
        frames = pump.frames()
        first = next(frames)
        assert playback_clock() >= at - 0.002
        assert first.seconds == 5.0
        assert pump.clock_position(at + 0.5) == pytest.approx(5.5)
        frames.close()

    def test_imagem_segurada_sai_ancorada_no_instante_do_som(self, monkeypatch) -> None:
        _launch(monkeypatch, _Process(_Stream(4)))
        pump = FramePump(["ffmpeg"], 2.0, (1, 1), fps=20)
        pump.hold_start()
        got: list[tuple[float, float]] = []

        def consume() -> None:
            for frame in pump.frames():
                got.append((playback_clock(), frame.seconds))

        thread = threading.Thread(target=consume)
        thread.start()
        time.sleep(0.2)
        assert not got, "segurada, a imagem não sai sozinha"
        # O som começou 40 ms antes de o painel perceber.
        anchor = playback_clock() - 0.04
        pump.start_at(anchor)
        thread.join(2)
        assert not thread.is_alive()
        assert got[0][1] == 2.0 and got[0][0] - anchor < 0.1
        assert pump.clock_position(anchor + 1.0) == pytest.approx(3.0)

    def test_acerto_do_relogio_e_inteiro_no_comeco_e_suave_depois(self, monkeypatch) -> None:
        _launch(monkeypatch, _Process(_Stream(40)))
        pump = FramePump(["ffmpeg"], 0.0, (1, 1), fps=20)
        frames = pump.frames()
        next(frames)
        before = playback_clock()
        pump.set_clock_offset(0.1)  # imagem 100 ms à frente do som
        next(frames)
        assert playback_clock() - before >= 0.13, "no começo a imagem espera o som de uma vez"
        for _ in range(9):
            next(frames)
        before = playback_clock()
        pump.set_clock_offset(0.1)
        next(frames)
        assert playback_clock() - before < 0.09, "no meio, só alguns milissegundos por quadro"
        assert pump._offset == pytest.approx(0.097)
        frames.close()

    def test_parar_com_a_imagem_segurada_encerra_sem_quadro(self, monkeypatch) -> None:
        process = _Process(_Stream(5))
        _launch(monkeypatch, process)
        pump = FramePump(["ffmpeg"], 0.0, (1, 1), fps=20)
        pump.hold_start()
        got: list[RawFrame] = []
        thread = threading.Thread(target=lambda: got.extend(pump.frames()))
        thread.start()
        time.sleep(0.05)
        pump.stop()
        thread.join(1)
        assert not thread.is_alive() and not got
        assert process.stdout.closed

    @pytest.mark.parametrize(("tail", "returncode"), [(b"xy", 0), (b"", 1)])
    def test_fim_com_quadro_incompleto_ou_erro_continua_sendo_falha(self, monkeypatch, tail, returncode) -> None:
        _launch(monkeypatch, _Process(_Stream(3, tail=tail), returncode))
        pump = FramePump(["ffmpeg"], 0.0, (1, 1), fps=100)
        with pytest.raises(VideoManagerError):
            list(pump.frames())


# ---------------------------------------------------------------------------
# Painel
# ---------------------------------------------------------------------------


class _Worker:
    def __init__(self, seconds: float, token: int, autostart: bool) -> None:
        from videomanager.infrastructure.qt.workers.signals import PreviewSignals

        self.seconds, self.token, self.autostart = seconds, token, autostart
        self.signals = PreviewSignals()
        self.held = False
        self.started: list[float | None] = []
        self.offsets: list[float] = []
        self.cancelled = False
        self.began: float | None = None

    def hold_start(self) -> None:
        self.held = True

    def start_playback(self, at: float | None = None) -> None:
        self.started.append(at)

    def cancel(self) -> None:
        self.cancelled = True

    def clock_position(self, now: float | None = None) -> float | None:
        return None if self.began is None else self.seconds + now - self.began

    def set_clock_offset(self, seconds: float) -> None:
        self.offsets.append(seconds)


class _Audio:
    def __init__(self) -> None:
        self.available = True
        self.audible = True
        self.playing = False
        self.position = 0.0

    def stop(self) -> None:
        self.playing = False

    def cancel_next(self) -> None:
        pass

    def set_volume(self, _value) -> None:
        pass

    def set_muted(self, _value) -> None:
        pass


@pytest.fixture
def harness(desktop_app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from videomanager.application.capabilities import FFmpegTools
    from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
    from videomanager.domain.project import Clip, MediaKind, MediaRef, Track, TrackKind
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.panels import edit_panel as module

    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    tools = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")
    runtime = build_desktop_runtime(audio_enabled=False)
    workers: list[_Worker] = []

    def playback_worker(project, seconds, size, tools, token, *, fps, text_assets=None, autostart=True):
        workers.append(_Worker(seconds, token, autostart))
        return workers[-1]

    def play_audio(output, project, seconds, tools, *, text_assets=None, until=None):
        if output.available and output.audible:
            output.playing, output.position = True, seconds

    monkeypatch.setattr(runtime, "playback_worker", playback_worker)
    monkeypatch.setattr(runtime, "play_audio", play_audio)
    panel = module.EditPanel(Settings(), ensure_tools=lambda: tools, editor=build_editor_service(),
                             processing=build_processing_service(), runtime=runtime)
    monkeypatch.setattr(panel._runner, "start", lambda *args: None)
    now = [100.0]
    monkeypatch.setattr(module, "playback_clock", lambda: now[0])

    def install(duration: float) -> None:
        video = MediaRef(Path("/m/v.mp4"), MediaKind.VIDEO, duration=duration, width=320, height=180, fps=30)
        project = replace(panel._project, tracks=(Track(TrackKind.VIDEO, clips=(Clip(video, 0, duration),)),))
        panel.install_project(project, None, [], {})

    install(10)
    audio = _Audio()
    monkeypatch.setattr(panel, "_audio", audio)
    monkeypatch.setattr(panel, "_show_frame", lambda frame: None)
    monkeypatch.setattr(panel, "_prepare_interaction", lambda: None)
    try:
        yield SimpleNamespace(panel=panel, workers=workers, audio=audio, now=now, install=install)
    finally:
        panel.shutdown()


def _frame(seconds: float) -> RawFrame:
    return RawFrame(b"\0\0\0", 1, 1, seconds)


class TestEsperaPeloSom:
    def test_play_com_som_segura_a_imagem_ate_o_som_sair(self, harness) -> None:
        panel, audio, now = harness.panel, harness.audio, harness.now
        panel._start_playback(2.0)
        worker = harness.workers[-1]
        assert worker.held and worker.started == []
        panel._on_playback_primed(worker.token)  # primeiro quadro pronto: o som abre
        assert audio.playing
        now[0] += 0.04
        panel._on_tick()
        assert worker.started == [], "a placa ainda não tocou nada"
        audio.position = 2.03
        now[0] += 0.04
        panel._on_tick()
        # Solta ancorada em quando o som começou, não em quando o tique viu.
        assert worker.started == [pytest.approx(now[0] - 0.03)]
        assert not panel._video_held

    def test_play_pre_carregado_tambem_espera_o_som(self, harness) -> None:
        panel, audio, now = harness.panel, harness.audio, harness.now
        panel._timeline.set_position(2.0)
        panel._prime_playback()
        primed = harness.workers[-1]
        panel._on_playback_primed(primed.token)
        panel._start_playback(2.0)
        assert primed.held and primed.started == [None]
        assert audio.playing
        audio.position = 2.02
        now[0] += 0.04
        panel._on_tick()
        assert primed.started == [None, pytest.approx(now[0] - 0.02)]

    def test_placa_que_nao_anda_nao_prende_a_imagem(self, harness) -> None:
        panel, now = harness.panel, harness.now
        panel._start_playback(2.0)
        worker = harness.workers[-1]
        panel._on_playback_primed(worker.token)
        now[0] += 0.3
        panel._on_tick()
        assert worker.started == []
        now[0] += 0.3
        panel._on_tick()
        assert worker.started == [now[0]]

    def test_sem_trilha_audivel_a_imagem_sai_no_primeiro_quadro(self, harness) -> None:
        panel, audio, now = harness.panel, harness.audio, harness.now
        audio.audible = False
        panel._start_playback(2.0)
        worker = harness.workers[-1]
        now[0] += 0.01
        panel._on_tick()
        assert worker.started == [], "o som pendente só abre com o primeiro quadro"
        panel._on_playback_primed(worker.token)
        assert worker.started == [now[0]]

    def test_sem_som_disponivel_a_imagem_nao_e_segurada(self, harness) -> None:
        harness.audio.available = False
        harness.panel._start_playback(2.0)
        worker = harness.workers[-1]
        assert not worker.held and worker.autostart
        assert not harness.panel._video_held


class TestAcertoComOSom:
    def test_acerto_ignora_o_degrau_da_placa(self, harness) -> None:
        panel = harness.panel
        worker = _Worker(2.0, 7, True)
        worker.began = 100.0
        panel._playback = worker
        panel._sync_video_clock(2.49, 100.5)  # imagem 10 ms à frente: degrau
        panel._sync_video_clock(2.44, 100.5)  # 60 ms à frente
        panel._sync_video_clock(2.53, 100.5)  # 30 ms atrás
        assert worker.offsets == [0.0, pytest.approx(0.06), pytest.approx(-0.03)]

    def test_desvio_so_reabre_o_fluxo_depois_do_primeiro_quadro_dele(self, harness, monkeypatch) -> None:
        # Um clique longe seguido de play: a tela ainda mostra o ponto antigo
        # até o primeiro quadro do fluxo novo chegar. Isso não é desvio.
        panel, audio, now = harness.panel, harness.audio, harness.now
        panel._start_playback(2.0)
        worker = harness.workers[-1]
        panel._on_playback_primed(worker.token)
        audio.position = 5.0
        reopened: list[float] = []
        monkeypatch.setattr(panel, "_start_frames", lambda seconds: reopened.append(seconds))
        now[0] += 0.04
        panel._on_tick()
        assert reopened == []
        panel._on_frame(worker.token, _frame(2.0))
        now[0] += 0.04
        panel._on_tick()
        assert reopened == [5.0]


class TestVoltaDoLoop:
    def test_quadros_do_comeco_entram_antes_da_troca(self, harness, monkeypatch) -> None:
        panel = harness.panel
        shown: list[float] = []
        monkeypatch.setattr(panel, "_show_frame", lambda frame: shown.append(frame.seconds))
        panel._playing = True
        panel._play_token = 50
        loop_worker = _Worker(0.0, 51, False)
        panel._loop_worker, panel._loop_token = loop_worker, 51
        panel._on_frame(51, _frame(0.0))
        panel._on_frame(50, _frame(9.97))  # quadro atrasado do fim
        assert shown == [0.0] and panel._loop_video_live
        panel._swap_loop_video()
        assert panel._play_token == 51 and not panel._loop_video_live
        panel._on_frame(51, _frame(1 / 30))
        assert shown == [0.0, 1 / 30]

    def test_volta_e_agendada_pelo_relogio_da_imagem(self, harness) -> None:
        panel, now = harness.panel, harness.now
        harness.audio.available = False
        harness.install(4)
        panel._loop.setChecked(True)
        panel._start_playback(2.0)
        main = harness.workers[-1]
        panel._on_playback_primed(main.token)
        main.began = now[0]
        now[0] += 1.2  # 3,2 s: faltam menos de 1,5 s
        panel._on_tick()
        loop_worker = harness.workers[-1]
        assert loop_worker is not main and loop_worker.seconds == 0.0
        # Solto já, com hora marcada para quando a imagem atual chegar ao fim.
        assert loop_worker.started == [pytest.approx(now[0] + 0.8)]
        assert main.offsets == [0.0]
        now[0] += 0.9
        panel._on_tick()
        assert panel._play_token == loop_worker.token and main.cancelled
