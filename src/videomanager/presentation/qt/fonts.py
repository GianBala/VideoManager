"""Gerenciamento e carregamento de fontes personalizadas da aplicação."""

from __future__ import annotations

import sys
from pathlib import Path
from PySide6.QtGui import QFont, QFontDatabase

_LOADED = False


def _fonts_dir() -> Path:
    """Diretório de fontes embutidas na aplicação."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parents[2]
    return root / "resources" / "fonts"


def ensure_application_fonts() -> None:
    """Carrega fontes embutidas (ex: Rapier Zero, Carlito/Calibri) no QFontDatabase.

    Configura também substituição de fonte para que 'Calibri' resolva perfeitamente
    tanto em plataformas Windows (onde Calibri é nativa do sistema) quanto em
    Linux/macOS (onde Carlito é a métrica correspondente 1:1 de código aberto).
    """
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    # 1. Carrega todos os arquivos de fonte (.ttf, .otf) do diretório de recursos
    fdir = _fonts_dir()
    if fdir.is_dir():
        for fpath in sorted(fdir.iterdir()):
            if fpath.suffix.lower() in (".ttf", ".otf"):
                try:
                    QFontDatabase.addApplicationFont(str(fpath))
                except Exception:
                    pass

    # 2. Configura substituição transparente para 'Calibri' -> 'Carlito' caso Calibri não esteja presente
    QFont.insertSubstitution("Calibri", "Carlito")
