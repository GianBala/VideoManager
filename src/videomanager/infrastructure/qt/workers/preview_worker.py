"""Workers da aba de edição: quadro, tira de miniaturas, onda, keyframes e prévia.

Todos chamam o ffmpeg, e todos são cancelados com frequência: navegar pela linha
do tempo pede um quadro novo a cada movimento do cursor, e a maioria desses
pedidos deixa de interessar antes de terminar. Daí cada worker carregar um
``token``, que a tela usa para descartar o que chegou tarde demais (ver
:class:`PreviewSignals`), e daí a reprodução ser interrompível a qualquer quadro.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from PySide6.QtCore import QRunnable, Slot

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.errors import VideoManagerError
from videomanager.application.media.preview import PreviewFrameInbox
from dataclasses import replace

from videomanager.infrastructure.ffmpeg.preview import FramePump
from videomanager.infrastructure.ffmpeg.preview import jpeg_frames
from videomanager.infrastructure.system.binaries import lower_priority
from videomanager.infrastructure.system.binaries import subprocess_kwargs
from videomanager.infrastructure.ffmpeg.preview import filmstrip_frames
from videomanager.infrastructure.ffmpeg.preview import frame_from_command
from videomanager.infrastructure.ffmpeg.preview import render_waveform
from videomanager.infrastructure.ffmpeg.trimmer import keyframe_times
from videomanager.infrastructure.qt.workers.signals import PreviewSignals
from videomanager.infrastructure.qt.workers.signals import emit_safely


class _Interruption:
    """Trava de cancelamento dos workers que abrem um ffmpeg e esperam por ele.

    Composição, e não herança: um ``QRunnable`` do PySide6 misturado com outra
    classe base cobra atenção de MRO que este punhado de linhas não justifica.

    O que ela resolve é o fechamento da janela. O destrutor do ``QThreadPool``
    espera as threads dele, e estes processos têm prazos longos — 120 s a onda,
    180 s os keyframes: sem poder matá-los, fechar a aba de edição no meio de
    um trabalho de fundo segurava a saída do aplicativo até o prazo acabar.
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._cancelled = False
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def register(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._process = process
        if self._cancelled:
            # A desistência chegou entre abrir e registrar: sem esta
            # conferência o processo seguiria decodificando sozinho.
            process.terminate()

    def cancel(self) -> None:
        self._cancelled = True
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()

    def release(self) -> None:
        """Libera também os buffers que Popen.communicate guarda internamente."""
        with self._lock:
            self._process = None


class FrameWorker(QRunnable):
    """Um quadro da composição, para a tela de prévia.

    Recebe o comando pronto — montado pelo compositor a partir do projeto — em
    vez de um arquivo: é isso que faz a prévia mostrar as trilhas sobrepostas, e
    não só a mídia de baixo.
    """

    def __init__(
        self,
        command: list[str] | Callable[[], list[str]],
        size: tuple[int, int],
        seconds: float,
        token: int,
    ) -> None:
        super().__init__()
        # Pode vir pronto ou como receita, montada já na thread do worker.
        self._command = command
        self._size = size
        self._seconds = seconds
        self._token = token
        self._guard = _Interruption()
        self.signals = PreviewSignals()

    def cancel(self) -> None:
        self._guard.cancel()

    @Slot()
    def run(self) -> None:
        try:
            command = self._command() if callable(self._command) else self._command
            frame = frame_from_command(
                command, self._size, register=self._guard.register, strict=True
            )
            if frame is not None and not self._guard.cancelled:
                emit_safely(
                    self.signals.frame, self._token, replace(frame, seconds=self._seconds)
                )
        except (VideoManagerError, OSError, subprocess.SubprocessError) as exc:
            if not self._guard.cancelled:
                message = str(exc) if isinstance(exc, VideoManagerError) else "Não foi possível atualizar a prévia."
                emit_safely(self.signals.failed, self._token, message)
        finally:
            self._guard.release()
            if self._guard.cancelled:
                emit_safely(self.signals.cancelled, self._token)
            emit_safely(self.signals.done)


class FilmstripWorker(QRunnable):
    """A tira de miniaturas do trecho visível da linha do tempo.

    Emite cada miniatura assim que ela sai, em vez de esperar a tira inteira: a
    tira aparece preenchendo da esquerda para a direita, e o usuário já pode
    navegar pelas primeiras enquanto as últimas ainda estão sendo geradas.
    """

    def __init__(
        self,
        path: Path,
        start: float,
        end: float,
        count: int,
        size: tuple[int, int],
        tools: FFmpegTools,
        token: int,
    ) -> None:
        super().__init__()
        self._path = path
        self._start = start
        self._end = end
        self._count = count
        self._size = size
        self._tools = tools
        self._token = token
        self._guard = _Interruption()
        self.signals = PreviewSignals()

    def cancel(self) -> None:
        self._guard.cancel()

    @Slot()
    def run(self) -> None:
        # ``closing`` não é zelo: desistir no meio da tira precisa **fechar** o
        # gerador, e é o fechamento que encerra o ffmpeg do passe único. Sair do
        # laço sem isso deixaria o processo decodificando o resto de um trecho
        # que ninguém vai ver — de novo o caso que enchia a máquina de ffmpeg.
        #
        # A trava vai junto porque o fechamento do gerador só acontece **entre**
        # dois quadros: quem estivesse parado esperando a leitura de um deles
        # ficaria ali até o quadro chegar.
        quadros = filmstrip_frames(
            self._path, self._start, self._end, self._count, self._size, self._tools,
            register=self._guard.register,
        )
        try:
            with closing(quadros):
                for index, frame in quadros:
                    if self._guard.cancelled:
                        return
                    emit_safely(self.signals.strip, self._token, index, frame)
        finally:
            self._guard.release()
            emit_safely(self.signals.done)


class WaveformWorker(QRunnable):
    """A forma de onda do trecho visível."""

    def __init__(
        self,
        path: Path,
        start: float,
        duration: float,
        size: tuple[int, int],
        color: str,
        tools: FFmpegTools,
        token: int,
    ) -> None:
        super().__init__()
        self._path = path
        self._start = start
        self._duration = duration
        self._size = size
        self._color = color
        self._tools = tools
        self._token = token
        self._guard = _Interruption()
        self.signals = PreviewSignals()

    def cancel(self) -> None:
        self._guard.cancel()

    @Slot()
    def run(self) -> None:
        try:
            width, height = self._size
            png = render_waveform(
                self._path,
                self._tools,
                width=width,
                height=height,
                color=self._color,
                start=self._start,
                duration=self._duration,
                register=self._guard.register,
            )
            if png:
                emit_safely(self.signals.waveform, self._token, png)
        finally:
            self._guard.release()
            emit_safely(self.signals.done)


class KeyframeWorker(QRunnable):
    """Mapeia os keyframes do arquivo, uma vez, ao abri-lo.

    Sem eles a aba funciona; com eles a tela sabe dizer onde o corte sem
    recodificar vai realmente cair — que é a informação que decide entre esperar
    uma recodificação e mover a marca alguns quadros.
    """

    def __init__(self, path: Path, tools: FFmpegTools) -> None:
        super().__init__()
        self._path = path
        self._tools = tools
        self._guard = _Interruption()
        self.signals = PreviewSignals()

    def cancel(self) -> None:
        self._guard.cancel()

    @Slot()
    def run(self) -> None:
        try:
            emit_safely(
                self.signals.keyframes,
                keyframe_times(self._path, self._tools, register=self._guard.register),
            )
        except VideoManagerError:
            # Um arquivo cujos keyframes não podem ser mapeados ainda pode ser
            # recortado: o modo exato não depende deles, e o modo rápido volta a
            # deixar a escolha do ponto com o próprio ffmpeg.
            emit_safely(self.signals.keyframes, ())
        finally:
            self._guard.release()
            emit_safely(self.signals.done)


class ScrubCacheWorker(QRunnable):
    """Compõe um trecho em JPEG pequeno para o cache da agulha, sem pressa.

    Roda com prioridade baixa e entrega os quadros em lotes, para a interface
    guardar sem ser acordada a cada um.
    """

    _BATCH = 12

    def __init__(self, command: list[str], first_index: int, token: int) -> None:
        super().__init__()
        self._command = command
        self._first_index = first_index
        self._token = token
        self._guard = _Interruption()
        self.signals = PreviewSignals()

    def cancel(self) -> None:
        self._guard.cancel()

    @Slot()
    def run(self) -> None:
        process = None
        try:
            if self._guard.cancelled:
                return
            kwargs = subprocess_kwargs()
            kwargs["stderr"] = subprocess.DEVNULL
            process = subprocess.Popen(self._command, **kwargs)
            self._guard.register(process)
            lower_priority(process)
            batch: list[bytes] = []
            index = self._first_index
            assert process.stdout is not None
            for image in jpeg_frames(process.stdout.read):
                if self._guard.cancelled:
                    return
                batch.append(image)
                if len(batch) >= self._BATCH:
                    emit_safely(self.signals.scrub_frames, self._token, index, batch)
                    index += len(batch)
                    batch = []
            if batch and not self._guard.cancelled:
                emit_safely(self.signals.scrub_frames, self._token, index, batch)
        except (VideoManagerError, OSError, subprocess.SubprocessError):
            pass  # o cache é um atalho: sem ele, a agulha pede o quadro exato
        finally:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.SubprocessError:
                    process.kill()
                if process.stdout is not None:
                    process.stdout.close()
            self._guard.release()
            emit_safely(self.signals.done)


class PlaybackWorker(QRunnable):
    """Reprodução da prévia: um quadro por sinal, no ritmo do relógio.

    O fluxo é o da composição inteira a partir do instante pedido, então ele
    acaba junto com o projeto — os vãos entre blocos vêm pretos, como no arquivo
    exportado, em vez de serem pulados.
    """

    def __init__(
        self,
        command: list[str],
        start: float,
        size: tuple[int, int],
        token: int,
        *,
        fps: float,
        autostart: bool = True,
    ) -> None:
        super().__init__()
        # A taxa vem de fora e é obrigatória: é a **mesma** com que o comando
        # foi montado. Se as duas se separarem, o fluxo é gerado num ritmo e
        # entregue noutro — e a reprodução sai em velocidade errada sem nada
        # falhar. Por isso não há valor padrão aqui.
        self._pump = FramePump(command, start, size, fps=fps)
        self._inbox = PreviewFrameInbox()
        self._cancelled = False
        self._token = token
        self._gate = threading.Event()
        if autostart:
            self._gate.set()
        self.signals = PreviewSignals()

    def start_playback(self, at: float | None = None) -> None:
        """Libera um fluxo previamente carregado sem abrir outro processo.

        ``at`` marca o instante de ``playback_clock`` do primeiro quadro: a
        emenda do loop, que entra quando o fluxo atual termina, e a espera pelo
        som no play, que solta a imagem no instante em que o som começou.
        """
        if at is not None:
            self._pump.start_at(at)
        self._gate.set()

    def hold_start(self) -> None:
        """Segura o primeiro quadro até ``start_playback(at=...)``."""
        self._pump.hold_start()

    def clock_position(self, now: float | None = None) -> float | None:
        return self._pump.clock_position(now)

    def set_clock_offset(self, seconds: float) -> None:
        self._pump.set_clock_offset(seconds)

    def cancel(self) -> None:
        self._cancelled = True
        self._gate.set()
        self._pump.stop()

    @Slot()
    def run(self) -> None:
        try:
            for frame in self._pump.frames(
                gate=self._gate,
                on_primed=lambda: emit_safely(self.signals.primed, self._token),
            ):
                if not self._cancelled and self._inbox.publish(frame):
                    emit_safely(self.signals.frame, self._token, self._inbox)
        except (VideoManagerError, OSError, subprocess.SubprocessError) as exc:
            if not self._cancelled:
                message = str(exc) if isinstance(exc, VideoManagerError) else "A reprodução da prévia foi interrompida por uma falha."
                emit_safely(self.signals.failed, self._token, message)
        finally:
            if self._cancelled:
                emit_safely(self.signals.cancelled, self._token)
            emit_safely(self.signals.done)

__all__ = [
    'FFmpegTools',
    'VideoManagerError',
]


class InteractionWorker(QRunnable):
    """Prepara três imagens uma vez; os movimentos seguintes não abrem processos."""
    def __init__(self, commands, token):
        super().__init__()
        self._commands, self._token = commands, token
        self._guard = _Interruption()
        self.signals = PreviewSignals()

    def cancel(self):
        self._guard.cancel()

    @Slot()
    def run(self):
        from videomanager.infrastructure.ffmpeg.preview import _run
        try:
            commands = self._commands() if callable(self._commands) else self._commands
            images = []
            for command in commands:
                if self._guard.cancelled:
                    return
                images.append(_run(command, 30, self._guard.register, strict=True))
                self._guard.release()
            if not self._guard.cancelled:
                emit_safely(self.signals.frame, self._token, tuple(images))
        except (VideoManagerError, OSError, subprocess.SubprocessError):
            # A composição normal continua disponível se a preparação falhar.
            pass
        finally:
            self._guard.release()
            emit_safely(self.signals.done)
