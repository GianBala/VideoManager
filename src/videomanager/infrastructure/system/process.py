"""Processos curtos com prazo, cancelamento e coleta garantida do processo filho."""

from __future__ import annotations

import subprocess
import threading
import time

from videomanager.infrastructure.system.binaries import subprocess_kwargs
from videomanager.application.errors import JobCancelled


def terminate_and_wait(process: subprocess.Popen, *, grace: float = 0.2) -> None:
    """Coleta um filho mesmo quando ele ignora o pedido inicial de parada."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    _wait_for_exit(process, grace)


def _wait_for_exit(process: subprocess.Popen, grace: float = 0.2) -> None:
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        process.wait()


def terminate_async(process: subprocess.Popen) -> threading.Thread:
    """Cancelamento com prazo sem bloquear a thread da interface."""
    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    thread = threading.Thread(target=_wait_for_exit, args=(process,), daemon=False)
    thread.start()
    return thread


class ProcessControl:
    """Compartilha cancelamento entre etapas sem deixar processos órfãos."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def check(self) -> None:
        if self._cancelled.is_set():
            raise JobCancelled("Operação cancelada.")

    def run(self, command: list[str], *, timeout: float = 60) -> subprocess.CompletedProcess:
        self.check()
        process = subprocess.Popen(command, **subprocess_kwargs())
        deadline = time.monotonic() + timeout
        try:
            while True:
                self.check()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                    self.check()
                    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        raise
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=0.2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()

__all__ = [
    'JobCancelled',
]
