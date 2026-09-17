"""Registro em arquivo para o aplicativo empacotado.

No Windows o pacote roda sem console (``console=False`` no spec): tudo o que ia
para ``stderr`` — avisos do ``logging``, exceções dentro de slots do Qt e de
threads de trabalho — simplesmente desaparecia. Um defeito que só existe no
pacote ficava sem nenhum rastro para diagnosticar.

O arquivo fica na pasta de logs do usuário, com rotação para não crescer sem
limite. Não guarda cookies, cabeçalhos nem URLs assinadas: o que chega aqui são
mensagens do próprio aplicativo e do extrator, que já as omitem.
"""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import user_log_dir

from videomanager import APP_NAME

_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s"
_MAX_BYTES = 1024 * 1024
_BACKUPS = 3


def log_path() -> Path:
    return Path(user_log_dir(APP_NAME, appauthor=False)) / "videomanager.log"


def configure_file_logging(level: int = logging.INFO) -> Path | None:
    """Liga o log em arquivo e o registro de exceções não tratadas.

    Idempotente: chamar de novo não duplica o arquivo nem os ganchos. Devolve o
    caminho do arquivo, ou ``None`` se a pasta não puder ser criada — o
    aplicativo continua funcionando sem log, que é melhor que não abrir.
    """
    root = logging.getLogger()
    path = log_path()
    if not any(getattr(handler, "_videomanager", False) for handler in root.handlers):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8")
        except OSError:
            return None
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._videomanager = True  # type: ignore[attr-defined]
        root.addHandler(handler)
        _install_exception_hooks()
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    return path


def _install_exception_hooks() -> None:
    logger = logging.getLogger("videomanager.uncaught")
    previous = sys.excepthook
    previous_thread = threading.excepthook

    def excepthook(kind, value, traceback) -> None:
        if not issubclass(kind, KeyboardInterrupt):
            logger.error("Exceção não tratada", exc_info=(kind, value, traceback))
        previous(kind, value, traceback)

    def thread_excepthook(args) -> None:
        if args.exc_type is not SystemExit:
            logger.error(
                "Exceção não tratada na thread %s",
                getattr(args.thread, "name", "?"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
        previous_thread(args)

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook
