"""Workers da aba de edição: quadro, tira de miniaturas, onda, keyframes e prévia.

Todos chamam o ffmpeg, e todos são cancelados com frequência: navegar pela linha
do tempo pede um quadro novo a cada movimento do cursor, e a maioria desses
pedidos deixa de interessar antes de terminar. Daí cada worker carregar um
``token``, que a tela usa para descartar o que chegou tarde demais (ver
:class:`PreviewSignals`), e daí a reprodução ser interrompível a qualquer quadro.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRunnable, Slot

from ..core.binaries import FFmpegTools
from ..core.errors import VideoManagerError
from ..core.preview import FramePump, filmstrip_times, render_frame, render_waveform
from ..core.trimmer import keyframe_times
from .signals import PreviewSignals, emit_safely


class FrameWorker(QRunnable):
    """Um quadro exato, para a tela de prévia."""

    def __init__(
        self,
        path: Path,
        seconds: float,
        size: tuple[int, int],
        tools: FFmpegTools,
        token: int,
    ) -> None:
        super().__init__()
        self._path = path
        self._seconds = seconds
        self._size = size
        self._tools = tools
        self._token = token
        self.signals = PreviewSignals()

    @Slot()
    def run(self) -> None:
        try:
            frame = render_frame(self._path, self._seconds, self._size, self._tools)
            if frame is not None:
                emit_safely(self.signals.frame, self._token, frame)
        finally:
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
        self._times = filmstrip_times(start, end, count)
        self._size = size
        self._tools = tools
        self._token = token
        self._cancelled = False
        self.signals = PreviewSignals()

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            for index, moment in enumerate(self._times):
                if self._cancelled:
                    return
                frame = render_frame(self._path, moment, self._size, self._tools)
                if frame is not None:
                    emit_safely(self.signals.strip, self._token, index, frame)
        finally:
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
        self.signals = PreviewSignals()

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
            )
            if png:
                emit_safely(self.signals.waveform, self._token, png)
        finally:
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
        self.signals = PreviewSignals()

    @Slot()
    def run(self) -> None:
        try:
            emit_safely(self.signals.keyframes, keyframe_times(self._path, self._tools))
        except VideoManagerError:
            # Um arquivo cujos keyframes não podem ser mapeados ainda pode ser
            # recortado: o modo exato não depende deles, e o modo rápido volta a
            # deixar a escolha do ponto com o próprio ffmpeg.
            emit_safely(self.signals.keyframes, ())
        finally:
            emit_safely(self.signals.done)


class PlaybackWorker(QRunnable):
    """Reprodução da prévia: um quadro por sinal, no ritmo do relógio."""

    def __init__(
        self,
        path: Path,
        start: float,
        size: tuple[int, int],
        tools: FFmpegTools,
        token: int,
        *,
        stop_at: float | None = None,
    ) -> None:
        super().__init__()
        self._pump = FramePump(path, start, size, tools)
        self._token = token
        self._stop_at = stop_at
        self.signals = PreviewSignals()

    def cancel(self) -> None:
        self._pump.stop()

    @Slot()
    def run(self) -> None:
        try:
            for frame in self._pump.frames():
                emit_safely(self.signals.frame, self._token, frame)
                # Parar no fim do trecho é o que faz o botão de reprodução
                # servir para conferir o corte, e não só o arquivo.
                if self._stop_at is not None and frame.seconds >= self._stop_at:
                    break
        finally:
            emit_safely(self.signals.done)
