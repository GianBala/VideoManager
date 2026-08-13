"""Workers da aba de edição: quadro, tira de miniaturas, onda, keyframes e prévia.

Todos chamam o ffmpeg, e todos são cancelados com frequência: navegar pela linha
do tempo pede um quadro novo a cada movimento do cursor, e a maioria desses
pedidos deixa de interessar antes de terminar. Daí cada worker carregar um
``token``, que a tela usa para descartar o que chegou tarde demais (ver
:class:`PreviewSignals`), e daí a reprodução ser interrompível a qualquer quadro.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

from PySide6.QtCore import QRunnable, Slot

from ..core.binaries import FFmpegTools
from ..core.errors import VideoManagerError
from dataclasses import replace

from ..core.preview import (
    FramePump,
    filmstrip_frames,
    frame_from_command,
    render_waveform,
)
from ..core.trimmer import keyframe_times
from .signals import PreviewSignals, emit_safely


class FrameWorker(QRunnable):
    """Um quadro da composição, para a tela de prévia.

    Recebe o comando pronto — montado pelo compositor a partir do projeto — em
    vez de um arquivo: é isso que faz a prévia mostrar as trilhas sobrepostas, e
    não só a mídia de baixo.
    """

    def __init__(
        self,
        command: list[str],
        size: tuple[int, int],
        seconds: float,
        token: int,
    ) -> None:
        super().__init__()
        self._command = command
        self._size = size
        self._seconds = seconds
        self._token = token
        self.signals = PreviewSignals()

    @Slot()
    def run(self) -> None:
        try:
            frame = frame_from_command(self._command, self._size)
            if frame is not None:
                emit_safely(
                    self.signals.frame, self._token, replace(frame, seconds=self._seconds)
                )
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
        self._start = start
        self._end = end
        self._count = count
        self._size = size
        self._tools = tools
        self._token = token
        self._cancelled = False
        self.signals = PreviewSignals()

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        # ``closing`` não é zelo: desistir no meio da tira precisa **fechar** o
        # gerador, e é o fechamento que encerra o ffmpeg do passe único. Sair do
        # laço sem isso deixaria o processo decodificando o resto de um trecho
        # que ninguém vai ver — de novo o caso que enchia a máquina de ffmpeg.
        quadros = filmstrip_frames(
            self._path, self._start, self._end, self._count, self._size, self._tools
        )
        try:
            with closing(quadros):
                for index, frame in quadros:
                    if self._cancelled:
                        return
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
        fps: int,
    ) -> None:
        super().__init__()
        # A taxa vem de fora e é obrigatória: é a **mesma** com que o comando
        # foi montado. Se as duas se separarem, o fluxo é gerado num ritmo e
        # entregue noutro — e a reprodução sai em velocidade errada sem nada
        # falhar. Por isso não há valor padrão aqui.
        self._pump = FramePump(command, start, size, fps=fps)
        self._token = token
        self.signals = PreviewSignals()

    def cancel(self) -> None:
        self._pump.stop()

    @Slot()
    def run(self) -> None:
        try:
            for frame in self._pump.frames():
                emit_safely(self.signals.frame, self._token, frame)
        finally:
            emit_safely(self.signals.done)
