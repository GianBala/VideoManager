"""Processos curtos com prazo, cancelamento e coleta garantida do processo filho."""

from __future__ import annotations

import subprocess
import threading
import time

from .binaries import subprocess_kwargs
from .errors import JobCancelled


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
