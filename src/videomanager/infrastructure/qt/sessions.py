"""Pasta de cada sessão do aplicativo: temporários de download e diário de saídas.

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

A pasta guarda também o diário das reservas de saída e das pastas em que a
sessão trabalhou (:mod:`videomanager.infrastructure.storage.outputs`): a
varredura desfaz, numa sessão morta, a reserva de 0 byte e os temporários
``.videomanager-<sessão>-*`` que uma queda deixou na pasta do usuário.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QLockFile

from videomanager.infrastructure.storage import outputs

_PREFIX = "sessao-"
_LOCK = ".trava"
_JOURNAL = "saidas.jsonl"
# Versões anteriores baixavam direto na raiz. Um dia de idade separa o que
# sobrou delas de um download em curso de uma versão antiga ainda aberta.
_LEGACY_AGE = 24 * 3600


class Session:
    """A pasta desta sessão, criada e travada no primeiro uso."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._token = uuid.uuid4().hex[:8]
        self._path: Path | None = None
        self._lock: QLockFile | None = None
        # Downloads e o diário pedem a pasta de threads diferentes; criada duas
        # vezes, a segunda trava falharia e a primeira se soltaria ao ser
        # coletada, deixando a sessão viva com cara de morta.
        self._creating = threading.Lock()

    def start(self) -> None:
        """Varre as sessões mortas e liga o diário de saídas desta.

        Só a aplicação chama: quem monta o runtime em teste não deve criar
        pastas no cache do usuário nem renomear temporários.
        """
        sweep(self._root)
        outputs.use_session(self._token, lambda: self.path / _JOURNAL)

    @property
    def path(self) -> Path:
        with self._creating:
            if self._path is None:
                sweep(self._root)
                path = self._root / f"{_PREFIX}{os.getpid()}-{self._token}"
                path.mkdir(parents=True, exist_ok=True)
                lock = QLockFile(str(path / _LOCK))
                lock.setStaleLockTime(0)
                lock.tryLock(0)
                self._path, self._lock = path, lock
            return self._path

    def close(self) -> None:
        """Solta a trava e apaga a pasta: sem a fila, nenhum ``.part`` é retomável."""
        with self._creating:
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
                outputs.recover(entry / _JOURNAL, entry.name.rsplit("-", 1)[-1])
                shutil.rmtree(entry, ignore_errors=True)
        elif entry.is_file():
            try:
                old = time.time() - entry.stat().st_mtime > _LEGACY_AGE
            except OSError:
                continue
            if old:
                entry.unlink(missing_ok=True)
