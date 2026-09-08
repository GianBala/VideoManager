"""Adapta uma chamada de aplicação para a pool Qt sem modificar estado visual."""
from collections.abc import Callable
from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from videomanager.infrastructure.qt.workers.signals import emit_safely


class FunctionSignals(QObject):
    finished = Signal(object)
    failed = Signal(object)
    done = Signal()


class FunctionWorker(QRunnable):
    def __init__(self, operation: Callable[[], object]):
        super().__init__()
        self.operation = operation
        self.signals = FunctionSignals()

    @Slot()
    def run(self):
        try:
            result = self.operation()
        except Exception as exc:
            emit_safely(self.signals.failed, exc)
        else:
            emit_safely(self.signals.finished, result)
        finally:
            emit_safely(self.signals.done)
