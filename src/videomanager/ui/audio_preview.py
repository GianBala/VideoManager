"""Som da prévia: a mixagem do projeto, tocada enquanto se edita.

**O que sai pelos alto-falantes é a mesma mixagem que o arquivo exportado vai
ter** — todas as trilhas somadas, com o volume em decibéis de cada bloco e os
mudos aplicados. Isso é possível porque quem mistura é o ffmpeg, com o mesmo
grafo da exportação (ver ``core/composer.py``), e aqui só se toca o PCM que sai
dele. Um player de arquivo não daria conta: ele abre **um** arquivo, e uma
edição com duas trilhas de áudio não é um arquivo.

**O caminho é um cano com pressão de volta.** Uma thread lê o ffmpeg em pedaços
e enfileira; um temporizador na interface despeja no ``QAudioSink`` só o que
couber na fila dele. A thread nunca escreve na placa e a interface nunca lê do
cano — que é o que impede um ffmpeg lento de congelar a janela. A fila é curta
de propósito: cheia, ela segura o ffmpeg, em vez de deixar a memória crescer com
áudio que só vai tocar daqui a dez minutos.

**O relógio da reprodução é este módulo.** ``QAudioSink.processedUSecs()`` conta
o que a placa realmente consumiu, e é a única medida honesta de "onde a
reprodução está": o relógio de parede adianta quando o computador não dá conta,
e o resultado seria imagem à frente do som.

**Parar não espera ninguém.** Encerrar o ffmpeg é trabalho de uma thread
descartável (:func:`_dispose`), porque esperá-lo na interface custava dois
segundos de janela congelada por pausa — ver o comentário lá.

Nada aqui pode derrubar a aba: sem o módulo de multimídia no pacote, sem
dispositivo de som ou sem trilha audível no projeto, :attr:`available` é falso e
a prévia toca muda, como nasceu.
"""

from __future__ import annotations

import queue
import subprocess
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.binaries import subprocess_kwargs
from ..core.composer import CHANNELS, SAMPLE_RATE

try:  # pragma: no cover - depende do que foi empacotado
    from PySide6.QtCore import QLoggingCategory
    from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

    # O backend de multimídia do Qt despeja a estrutura do arquivo no stderr a
    # cada abertura — o mesmo ruído que o resto do aplicativo silencia.
    QLoggingCategory.setFilterRules("qt.multimedia.ffmpeg*=false")
    MULTIMEDIA_AVAILABLE = True
except ImportError:  # pragma: no cover
    QAudioFormat = QAudioSink = QMediaDevices = None  # type: ignore[assignment]
    MULTIMEDIA_AVAILABLE = False

# Tamanho do pedaço lido do ffmpeg. 8 KB são ~42 ms de áudio: pequeno o
# bastante para a fila reagir depressa a um cancelamento, grande o bastante para
# não transformar a leitura numa sucessão de chamadas de sistema.
_CHUNK = 8192
# Fila curta: cerca de meio segundo de áudio adiantado. Além disso o ffmpeg fica
# bloqueado escrevendo, que é exatamente o que se quer.
_QUEUE_CHUNKS = 24
# De quanto em quanto tempo a interface abastece a placa.
_FEED_MS = 20

_BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * 2  # s16le

# Quanto a thread de encerramento dá ao ffmpeg antes de matá-lo. Ver
# :func:`_reap`: com o cano cheio o prazo quase sempre se esgota, então ele é
# curto — o que se ganha esperando mais é um processo decodificando à toa
# enquanto o próximo já está tocando.
_TERMINATE_GRACE = 0.2


def _reap(process: subprocess.Popen) -> None:
    """Encerra o ffmpeg da mixagem, com prazo e depois à força.

    **Um ffmpeg bloqueado escrevendo num cano que ninguém lê não atende ao
    SIGTERM.** Ele só nota o pedido entre pacotes, e não chega lá: o ``write``
    fica preso até haver espaço, e espaço não vai haver — a leitura parou junto
    com a reprodução. Medido nesta máquina, três vezes seguidas: o
    ``wait(timeout=2)`` da parada ia até o fim, **2,00 s** em cheio.

    Isso rodava na interface. Eram dois segundos de janela congelada em cada
    pausa e em cada toque na linha do tempo durante a reprodução — exatamente o
    lugar em que se espera resposta imediata.
    """
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=_TERMINATE_GRACE)
    except subprocess.SubprocessError:
        process.kill()
        process.wait()


def _dispose(process: subprocess.Popen) -> threading.Thread:
    """Manda encerrar ``process`` fora da interface, e devolve na hora.

    A thread **não** é daemon: fechar a janela é o último momento em que alguém
    pode mandar o ffmpeg parar, e uma thread daemon seria abandonada no meio
    disso se o interpretador terminasse antes dela. O preço é uma fração de
    segundo no fechamento, e só quando havia som tocando.
    """
    thread = threading.Thread(target=_reap, args=(process,), daemon=False)
    thread.start()
    return thread


class AudioPreview(QObject):
    """Toca a mixagem do projeto a partir de um instante."""

    # A reprodução terminou sozinha (o áudio acabou) ou falhou.
    stopped = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sink = None
        self._device = None
        self._process: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._chunks: queue.Queue[bytes | None] = queue.Queue(_QUEUE_CHUNKS)
        # Sobra do pedaço que não coube na placa no tique anterior.
        self._pending: bytes | None = None
        self._stopping = threading.Event()
        self._origin = 0.0
        self._finished = False
        # Cada início e cada parada abrem uma geração nova. Avisos agendados
        # numa geração anterior são descartados (ver :meth:`_emit_stopped`).
        self._generation = 0
        self._volume = 0.7
        self._muted = False

        self._feed = QTimer(self)
        self._feed.setInterval(_FEED_MS)
        self._feed.timeout.connect(self._pump)

    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Se há como tocar som nesta máquina e neste pacote."""
        if not MULTIMEDIA_AVAILABLE:
            return False
        return not QMediaDevices.defaultAudioOutput().isNull()

    @property
    def playing(self) -> bool:
        return self._sink is not None and not self._finished

    @property
    def position(self) -> float:
        """Instante da edição que está saindo pela placa, em segundos."""
        if self._sink is None:
            return self._origin
        return self._origin + self._sink.processedUSecs() / 1_000_000

    # ------------------------------------------------------------------

    def start(self, command: list[str], at: float) -> bool:
        """Começa a tocar a mixagem produzida por ``command``, situada em ``at``."""
        self.stop()
        if not self.available:
            return False

        try:
            kwargs = subprocess_kwargs()
            kwargs["stderr"] = subprocess.DEVNULL
            process = subprocess.Popen(command, **kwargs)
        except OSError:
            return False

        fmt = QAudioFormat()
        fmt.setSampleRate(SAMPLE_RATE)
        fmt.setChannelCount(CHANNELS)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        device = QMediaDevices.defaultAudioOutput()
        if not device.isFormatSupported(fmt):
            process.terminate()
            return False

        self._origin = at
        self._finished = False
        # Fila e sinal de parada **novos**, e entregues ao leitor como
        # argumentos: a reprodução anterior é encerrada sem espera, então o
        # leitor dela ainda pode estar de pé por alguns instantes. Enquanto os
        # dois compartilhavam os atributos do objeto, esse leitor atrasado
        # despejava o som antigo na fila da reprodução nova — e via o sinal de
        # parada ser limpo aqui, o que o fazia continuar lendo sem fim.
        chunks: queue.Queue[bytes | None] = queue.Queue(_QUEUE_CHUNKS)
        stopping = threading.Event()
        self._chunks = chunks
        self._stopping = stopping
        self._pending = None
        self._process = process
        self._reader = threading.Thread(
            target=self._read, args=(process, chunks, stopping), daemon=True
        )
        self._reader.start()

        self._sink = QAudioSink(device, fmt, self)
        self._apply_volume()
        self._device = self._sink.start()
        self._feed.start()
        return True

    def _read(
        self,
        process: subprocess.Popen,
        chunks: queue.Queue[bytes | None],
        stopping: threading.Event,
    ) -> None:
        """Lê o ffmpeg em pedaços, na thread — a interface nunca toca no cano.

        Só mexe no que recebeu: a fila e o sinal de parada são os da reprodução
        que o criou, e não os do objeto. É o que impede um leitor atrasado de
        alimentar a reprodução seguinte (ver :meth:`start`).
        """
        try:
            assert process.stdout is not None
            while not stopping.is_set():
                data = process.stdout.read(_CHUNK)
                if not data:
                    break
                # Com prazo: sem ele, um cancelamento com a fila cheia deixaria
                # esta thread pendurada até alguém consumir.
                while not stopping.is_set():
                    try:
                        chunks.put(data, timeout=0.2)
                        break
                    except queue.Full:
                        continue
        except (OSError, ValueError):
            pass
        finally:
            try:
                chunks.put_nowait(None)  # marca o fim do fluxo
            except queue.Full:
                pass

    def _pump(self) -> None:
        """Abastece a placa com o que já chegou, sem nunca esperar por dados.

        **O que a placa não aceita fica guardado para o próximo tique.** O
        ``write`` de um ``QAudioSink`` grava no máximo ``bytesFree()`` e
        descarta o excedente em silêncio — e áudio descartado não soa como
        falha, soa como som acelerado: o conteúdo corre à frente do relógio.
        Medido antes desta correção: 48% do PCM perdido, som ao dobro da
        velocidade.
        """
        if self._sink is None or self._device is None:
            return
        while True:
            free = self._sink.bytesFree()
            if free <= 0:
                return
            if self._pending is None:
                try:
                    chunk = self._chunks.get_nowait()
                except queue.Empty:
                    return
                if chunk is None:
                    self._finish()
                    return
                self._pending = chunk
            written = self._device.write(self._pending[:free])
            if written <= 0:
                return
            self._pending = self._pending[written:] or None

    def _finish(self) -> None:
        """O áudio acabou: avisa quem ouve e desmonta o que sobrou.

        A placa ainda tem o fim do som na fila dela, então o desligamento espera
        esse resto ser consumido — cortar aqui truncaria a última palavra.
        """
        self._finished = True
        self._feed.stop()
        remaining = 0
        if self._sink is not None:
            remaining = max(0, self._sink.bufferSize() - self._sink.bytesFree())
        # A espera carrega a geração em que foi agendada: sem isso, quem parasse
        # e voltasse a tocar nesse intervalo veria a reprodução nova ser
        # encerrada pelo aviso da anterior.
        generation = self._generation
        QTimer.singleShot(
            int(remaining / _BYTES_PER_SECOND * 1000) + 60,
            lambda: self._emit_stopped(generation),
        )

    def _emit_stopped(self, generation: int) -> None:
        if generation != self._generation:
            return
        self.stop()
        self.stopped.emit()

    def stop(self) -> None:
        """Encerra a reprodução e **devolve na hora**.

        Nada aqui espera processo: quem espera é a thread de :func:`_dispose`.
        A interface chama isto a cada pausa e a cada toque na linha do tempo
        durante a reprodução, e é o caminho que precisa responder no quadro
        seguinte.
        """
        self._generation += 1
        self._feed.stop()
        self._stopping.set()
        if self._sink is not None:
            self._sink.stop()
            self._sink.deleteLater()
            self._sink = None
        self._device = None
        if self._process is not None:
            _dispose(self._process)
        self._process = None
        self._reader = None
        self._pending = None
        self._finished = False

    # ------------------------------------------------------------------

    def set_volume(self, percent: int) -> None:
        self._volume = min(max(0, percent), 100) / 100
        self._apply_volume()

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self._apply_volume()

    def _apply_volume(self) -> None:
        if self._sink is not None:
            self._sink.setVolume(0.0 if self._muted else self._volume)
