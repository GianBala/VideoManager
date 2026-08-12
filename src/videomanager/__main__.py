"""Ponto de entrada: ``python -m videomanager``."""

from __future__ import annotations

# Import absoluto de propósito. Este mesmo arquivo é o script inicial do
# PyInstaller, que o executa como ``__main__`` sem pacote: com ``from .app`` o
# import falha em tempo de execução e, pior, o analisador de dependências para
# aqui — o pacote saía sem o PySide6 inteiro.
from videomanager.app import main

if __name__ == "__main__":
    raise SystemExit(main())
