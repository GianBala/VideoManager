"""Iniciador de workers que mantém referência até eles terminarem.

Existe por causa de uma armadilha real do PySide6: ``QThreadPool.start()`` assume
a posse do ``QRunnable`` no lado C++, mas **não** impede o Python de coletar o
objeto. Quando isso acontece com a thread ainda rodando, o ``QObject`` de sinais é
destruído junto e a emissão levanta ``RuntimeError: Signal source has been
deleted`` — normalmente longe da causa, o que torna o diagnóstico penoso.

Guardar a referência até o worker sinalizar conclusão resolve de forma explícita.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRunnable, QThreadPool, SignalInstance


class WorkerRunner:
    """Inicia workers e os mantém vivos enquanto trabalham."""

    def __init__(self, pool: QThreadPool | None = None) -> None:
        self._pool = pool or QThreadPool.globalInstance()
        self._alive: set[QRunnable] = set()

    def start(self, worker: Any, *done_signals: SignalInstance) -> None:
        """Inicia ``worker``, liberando-o quando qualquer sinal final chegar.

        Todos os sinais que encerram o trabalho precisam ser passados — inclusive
        os de falha e cancelamento. Um sinal esquecido faz o worker vazar, e é um
        vazamento silencioso: nada quebra, a memória só não é liberada.
        """
        self._alive.add(worker)
        for signal in done_signals:
            signal.connect(lambda *_, ref=worker: self._alive.discard(ref))
        self._pool.start(worker)

    @property
    def active(self) -> int:
        return len(self._alive)
