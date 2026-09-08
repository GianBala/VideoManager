"""Objetos de sinal usados pelos workers.

``QRunnable`` não é um ``QObject`` e por isso não pode declarar sinais. O padrão
é compor: o runnable carrega um ``QObject`` só com os sinais. Como esse objeto é
criado na thread da interface, as emissões feitas de dentro de ``run()`` chegam
por conexão enfileirada — que é exatamente o que se quer.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, SignalInstance


def emit_safely(signal: SignalInstance, *args: object) -> None:
    """Emite tolerando que o destinatário já não exista.

    Fechar a janela com tarefa em andamento destrói os objetos de sinal antes
    de a thread de trabalho terminar, e a emissão levanta ``RuntimeError:
    Signal source has been deleted``. Não é defeito: quem receberia a notícia
    já foi embora. Deixar a exceção subir só sujava a saída do programa com um
    traceback no encerramento — invisível num app empacotado, e assustador em
    quem roda pelo terminal.
    """
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


class ProbeSignals(QObject):
    """Resultado da análise de uma URL."""

    done = Signal()
    # MediaInfo ou PlaylistInfo
    finished = Signal(object)
    failed = Signal(str)


class DownloadSignals(QObject):
    """Andamento de um download."""

    progress = Signal(int, object)  # job_id, Progress
    finished = Signal(int, object)  # job_id, DownloadResult
    failed = Signal(int, str)  # job_id, mensagem
    cancelled = Signal(int)  # job_id


class ConvertSignals(QObject):
    """Andamento de uma conversão local."""

    progress = Signal(int, object)  # job_id, Progress
    finished = Signal(int, object)  # job_id, Path
    failed = Signal(int, str)
    cancelled = Signal(int)


class PreviewSignals(QObject):
    """Imagens da aba de edição, prontas para a tela.

    ``token`` identifica o pedido: navegar arrasta o cursor e dispara vários
    pedidos por segundo, e sem ele um quadro de um pedido antigo chegaria depois
    do atual e apareceria na tela como um salto para trás.
    """

    frame = Signal(int, object)  # token, RawFrame
    strip = Signal(int, int, object)  # token, índice na tira, RawFrame
    waveform = Signal(int, bytes)  # token, PNG
    keyframes = Signal(object)  # tuple[float, ...]
    # Emitido sempre, inclusive em falha: é por ele que o WorkerRunner solta a
    # referência do worker (ver presentation/qt/tasks.py).
    done = Signal()
