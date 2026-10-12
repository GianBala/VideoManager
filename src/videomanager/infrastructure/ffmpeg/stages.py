"""Vários comandos em sequência que, para quem lê, são um cano só.

O bloco invertido da prévia é lido em janelas (ver ``domain.reversal``): cada
janela é um ffmpeg, e a reprodução e o som precisam enxergá-los como **um fluxo
contínuo** — quem lê quadros ou PCM não quer saber de onde uma janela acaba e a
outra começa. :class:`StagedProcess` tem a cara de um ``subprocess.Popen`` (os
leitores só usam ``stdout.read``, ``poll``, ``terminate``, ``kill``, ``wait`` e o
``stderr``) e passa de um comando ao seguinte na hora em que o anterior acaba.

**A janela seguinte abre antes de a atual acabar.** Ela só começa a produzir
depois de ler e virar o trecho dela inteiro, e esperar o fim da anterior para
abri-la deixaria um silêncio ou um quadro parado a cada emenda. Abrir cedo demais
também custa: uma prévia pausada, com o primeiro quadro já pré-carregado, não
pode estar com duas janelas na memória. Por isso a abertura acontece quando a
atual passa da metade do que vai produzir (``Stages.sizes``) — e as janelas da
prévia usam metade do orçamento de memória, porque duas vivem juntas.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Stages:
    """Comandos a rodar um depois do outro, no lugar de um comando só.

    ``sizes`` diz quantos bytes cada comando vai produzir, quando se sabe (quadros
    cru e PCM sabem): é com ele que a janela seguinte é aberta na metade da atual.
    Sem o tamanho, abre assim que a atual produz o primeiro byte.
    """

    commands: tuple[tuple[str, ...], ...]
    sizes: tuple[int | None, ...] = ()

    def __post_init__(self) -> None:
        if not self.commands:
            raise ValueError("Stages precisa de ao menos um comando")

    def size_of(self, index: int) -> int | None:
        return self.sizes[index] if index < len(self.sizes) else None

    def map(self, function) -> Stages:
        """Os mesmos comandos depois de ``function(comando)`` — para preparar cada um."""
        return Stages(tuple(tuple(function(list(command))) for command in self.commands), self.sizes)


class _Out:
    """O ``stdout`` do fluxo: lê do estágio atual e atravessa as emendas."""

    def __init__(self, owner: StagedProcess) -> None:
        self._owner = owner

    def read(self, size: int = -1) -> bytes:
        return self._owner._read(size)

    def close(self) -> None:
        self._owner._close_pipes()


class _Err:
    """O ``stderr`` do fluxo: o fim do que os estágios disseram, quando acabam."""

    def __init__(self, owner: StagedProcess) -> None:
        self._owner = owner
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        self._owner._finished.wait()
        with self._owner._lock:
            data = bytes(self._owner._tail)
        chunk = data[self._offset:] if size is None or size < 0 else data[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        return None


class StagedProcess:
    """Um fluxo só, feito de um processo por estágio, com a cara de um ``Popen``."""

    # O que se guarda do stderr: o suficiente para a mensagem de erro, que é só
    # a cauda (ver ``preview._DiagnosticTail``).
    _TAIL = 8192

    def __init__(self, stages: Stages, **kwargs) -> None:
        self._stages = stages
        self._kwargs = kwargs
        self._lock = threading.RLock()
        self._procs: list[subprocess.Popen] = []
        # Quem drena o stderr de cada estágio: o fim do fluxo espera pela do
        # estágio que falhou, ou a causa do erro chegava vazia a quem a mostra.
        self._drains: list[threading.Thread | None] = []
        self._index = 0
        self._read_in_stage = 0
        self._stopped = False
        self._failure: int | None = None
        self._finished = threading.Event()
        self._tail = bytearray()
        self.returncode: int | None = None
        self.stdout = _Out(self)
        self.stderr = _Err(self) if kwargs.get("stderr") == subprocess.PIPE else None
        try:
            self._open(0)
        except OSError:
            self._finish(-1)
            raise

    # -- abrir e acompanhar os estágios ---------------------------------------

    def _open(self, index: int) -> None:
        with self._lock:
            if self._stopped or index >= len(self._stages.commands) or len(self._procs) > index:
                return
            process = subprocess.Popen(list(self._stages.commands[index]), **self._kwargs)
            self._procs.append(process)
            drain = None
            if self.stderr is not None and process.stderr is not None:
                drain = threading.Thread(target=self._drain, args=(process.stderr,), daemon=True)
                drain.start()
            self._drains.append(drain)

    def _drain(self, stream) -> None:
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                with self._lock:
                    self._tail += chunk
                    del self._tail[:-self._TAIL]
        except (OSError, ValueError):
            pass

    def _prefetch(self) -> None:
        """Abre o estágio seguinte quando o atual já passou da metade."""
        size = self._stages.size_of(self._index)
        if size is not None and self._read_in_stage < size // 2:
            return
        try:
            self._open(self._index + 1)
        except OSError:
            # A falha de abrir aparece quando a leitura chegar lá, com o
            # estágio que não abriu; aqui só se desiste da pré-abertura.
            pass

    # -- leitura ----------------------------------------------------------------

    def _read(self, size: int) -> bytes:
        out = bytearray()
        while size < 0 or len(out) < size:
            with self._lock:
                if self._stopped or self._finished.is_set() or self._index >= len(self._procs):
                    break
                process = self._procs[self._index]
            want = 65536 if size < 0 else size - len(out)
            chunk = process.stdout.read(want) if process.stdout is not None else b""
            if chunk:
                out += chunk
                self._read_in_stage += len(chunk)
                self._prefetch()
                continue
            # Fim do estágio: confere como terminou e passa ao seguinte.
            code = process.wait()
            drain = self._drains[self._index] if self._index < len(self._drains) else None
            if drain is not None:
                drain.join(timeout=2)
            with self._lock:
                if self._stopped:
                    break
                if code != 0:
                    self._finish(code)
                    break
                self._index += 1
                self._read_in_stage = 0
                if self._index >= len(self._stages.commands):
                    self._finish(0)
                    break
            try:
                self._open(self._index)
            except OSError:
                self._finish(-1)
                break
        return bytes(out)

    def _finish(self, code: int) -> None:
        with self._lock:
            if self.returncode is None:
                self.returncode = code
        self._finished.set()

    def _close_pipes(self) -> None:
        with self._lock:
            procs = list(self._procs)
        for process in procs:
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError:
                    pass

    # -- a cara do Popen --------------------------------------------------------

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self._end(subprocess.Popen.terminate)

    def kill(self) -> None:
        self._end(subprocess.Popen.kill)

    def _end(self, action) -> None:
        with self._lock:
            self._stopped = True
            procs = list(self._procs)
        for process in procs:
            if process.poll() is None:
                try:
                    action(process)
                except OSError:
                    pass
        self._finish(-15)

    def wait(self, timeout: float | None = None) -> int:
        """Espera todos os estágios abertos acabarem; ``TimeoutExpired`` no prazo."""
        with self._lock:
            procs = list(self._procs)
        for process in procs:
            process.wait(timeout=timeout)
        self._finish(0)
        return self.returncode if self.returncode is not None else 0


def open_process(command, **kwargs):
    """O processo de um comando só, ou o fluxo único de vários em sequência."""
    if isinstance(command, Stages):
        return StagedProcess(command, **kwargs)
    return subprocess.Popen(command, **kwargs)
