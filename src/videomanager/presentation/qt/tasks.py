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
from weakref import ref

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
        reference = ref(worker)
        for signal in done_signals:
            # A coleção mantém o worker vivo; o callback não deve formar um
            # ciclo worker → sinais → callback → worker depois da conclusão.
            signal.connect(lambda *_, reference=reference: self._alive.discard(reference()))
        self._pool.start(worker)

    def cancel_all(self) -> None:
        """Pede a interrupção de todo worker vivo que saiba ser interrompido.

        Existe para o fechamento da janela. O destrutor do ``QThreadPool``
        chama ``waitForDone()`` sem prazo, então um worker que esteja esperando
        um ffmpeg de prazo longo — a onda são 120 s, os keyframes 180 s —
        segurava a saída do aplicativo por todo esse tempo, com a janela já fora
        da tela e nada explicando a espera.

        A lista vem daqui, e não de um registro próprio de cada painel, porque
        ``_alive`` já é exatamente "começou e ainda não terminou". Quem não sabe
        cancelar é ignorado em silêncio: é o caso de um trabalho curto demais
        para valer a pena interromper.
        """
        for worker in list(self._alive):
            cancel = getattr(worker, "cancel", None)
            if callable(cancel):
                cancel()

    @property
    def active(self) -> int:
        return len(self._alive)
