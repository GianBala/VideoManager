"""Pasta dos temporários de download de cada sessão do aplicativo.

Antes era uma pasta só, comum a todas as tarefas e a todas as janelas abertas.
Como o yt-dlp retoma um ``.part`` que encontra com o nome esperado, o resto de
uma tarefa cancelada era continuado por outra — mesmo título e id, outro
formato — e o resultado saía corrompido e marcado "Concluído"; e nada apagava
os ``.part`` de quem cancelava, que ficavam para sempre numa pasta que o
usuário não vê.

Hoje cada sessão tem a própria pasta, com uma trava (``QLockFile``) que só é
retomável quando o processo dono morreu, e cada tarefa uma subpasta dentro dela
(:func:`videomanager.infrastructure.qt.workers.download_worker.task_dir`). O
aplicativo não é de instância única: a varredura que abre uma sessão nova
apaga só as sessões cuja trava ficou para trás, nunca a de outra janela aberta.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QLockFile

_PREFIX = "sessao-"
_LOCK = ".trava"
# Versões anteriores baixavam direto na raiz. Um dia de idade separa o que
# sobrou delas de um download em curso de uma versão antiga ainda aberta.
_LEGACY_AGE = 24 * 3600


class DownloadSession:
    """A pasta desta sessão, criada e travada no primeiro uso."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._path: Path | None = None
        self._lock: QLockFile | None = None

    @property
    def path(self) -> Path:
        if self._path is None:
            sweep(self._root)
            path = self._root / f"{_PREFIX}{os.getpid()}-{uuid.uuid4().hex[:8]}"
            path.mkdir(parents=True, exist_ok=True)
            lock = QLockFile(str(path / _LOCK))
            lock.setStaleLockTime(0)
            lock.tryLock(0)
            self._path, self._lock = path, lock
        return self._path

    def close(self) -> None:
        """Solta a trava e apaga a pasta: sem a fila, nenhum ``.part`` é retomável."""
        if self._path is None:
            return
        self._lock.unlock()
        shutil.rmtree(self._path, ignore_errors=True)
        self._path = self._lock = None


def sweep(root: Path) -> None:
    """Apaga as sessões cujo processo morreu e os restos das versões antigas."""
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.is_dir() and entry.name.startswith(_PREFIX):
            lock = QLockFile(str(entry / _LOCK))
            # Sem isto, uma trava com mais de 30 s contaria como velha pela
            # idade, e a sessão de outra janela aberta seria apagada.
            lock.setStaleLockTime(0)
            if lock.tryLock(0):
                lock.unlock()
                shutil.rmtree(entry, ignore_errors=True)
        elif entry.is_file():
            try:
                old = time.time() - entry.stat().st_mtime > _LEGACY_AGE
            except OSError:
                continue
            if old:
                entry.unlink(missing_ok=True)
