"""Ponto de entrada: ``python -m videomanager``."""

from __future__ import annotations

# Import absoluto de propósito. Este mesmo arquivo é o script inicial do
# PyInstaller, que o executa como ``__main__`` sem pacote: com ``from .preflight``
# o import falha em tempo de execução e, pior, o analisador de dependências para
# aqui — o pacote saía sem o PySide6 inteiro.
from videomanager.preflight import refuse_if_missing


def main() -> int:
    # ``videomanager.app`` importa o PySide6, e sem a libGL o próprio import falha com um traceback de Python:
    # a conferência das bibliotecas do sistema tem de vir antes dele, e por isso ele é importado aqui dentro.
    refused = refuse_if_missing()
    if refused is not None:
        return refused
    from videomanager.app import main as run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
