"""Gerenciamento e carregamento de fontes personalizadas da aplicação."""

from __future__ import annotations

import sys
from pathlib import Path
from PySide6.QtGui import QFont, QFontDatabase, QFontInfo
from PySide6.QtWidgets import QApplication

_LOADED = False

# A interface e os números que mudam sozinhos (tempo, quadro, caminhos) têm uma família cada, embutida: o que se vê não
# depende das fontes que o sistema do usuário tem, e a medida de texto dos testes é a mesma na CI e aqui.
INTERFACE_FAMILY = "Inter"
MONO_FAMILY = "JetBrains Mono"
# O tamanho do texto corrente, em pixels: é o do QSS (``theme._QSS``) e o das medidas de layout.
INTERFACE_PIXELS = 13


def _fonts_dir() -> Path:
    """Diretório de fontes embutidas na aplicação."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parents[2]
    return root / "resources" / "fonts"


def ensure_application_fonts() -> None:
    """Carrega as fontes embutidas (a Carlito, no lugar da Calibri) no QFontDatabase.

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

    # 3. A fonte da interface. Sem isto o Qt usa a "Sans Serif" do sistema, que cai numa fonte diferente em cada máquina.
    app = QApplication.instance()
    if app is not None and INTERFACE_FAMILY in QFontDatabase.families():
        app.setFont(interface_font())


def interface_font() -> QFont:
    """A fonte do texto corrente: Inter em 13 px."""
    font = QFont(INTERFACE_FAMILY)
    font.setPixelSize(INTERFACE_PIXELS)
    return font


def resized(font: QFont, *, factor: float = 1.0, delta: int = 0, minimum: int = 8) -> QFont:
    """Cópia de ``font`` em outro tamanho, sempre em pixels.

    A fonte da interface é em pixels e o ``pointSizeF`` dela é -1: ``max(7, pointSizeF() - 2)`` virava 7 pt fixo, e
    ``setPointSize(pointSize() + 1)`` pedia 0. Quem quer "um pouco menor" ou "um pouco maior" passa por aqui.
    """
    copia = QFont(font)
    base = font.pixelSize() if font.pixelSize() > 0 else QFontInfo(font).pixelSize()
    copia.setPixelSize(max(minimum, round(base * factor) + delta))
    return copia


def mono(pixels: int | None = None) -> QFont:
    """A monoespaçada embutida, para o que muda sozinho e precisa de largura fixa; cai na do sistema sem ela."""
    if MONO_FAMILY not in QFontDatabase.families():
        return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font = QFont(MONO_FAMILY)
    font.setPixelSize(pixels or INTERFACE_PIXELS)
    return font
