"""Nome acessível para controles que só mostram símbolo.

Leitor de tela anuncia o nome do controle. Botões de ícone (▶, ↶, 🧲, −, +),
amostras de cor e campos sem rótulo ao lado eram anunciados como "botão",
"triângulo apontando para a direita" ou nada: medido, 34 dos 131 controles
visíveis das quatro abas sem nome e 24 com nome só de símbolo.

Quase todos já têm uma dica que diz o que fazem; esta passada dá a esses
controles, como nome, a primeira linha da dica (ou o texto de exemplo de um
campo vazio). Ela marca o que nomeou e refaz na troca de idioma, junto com as
dicas. Quem tem nome de verdade — texto com letras, rótulo apontando para ele,
nome posto à mão — não é tocado.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox, QComboBox,
                               QLineEdit, QPlainTextEdit, QScrollBar, QWidget)

_CONTROLES = (QAbstractButton, QAbstractSlider, QAbstractSpinBox, QAbstractItemView, QComboBox, QLineEdit,
              QPlainTextEdit)
_PALAVRA = re.compile(r"[^\W\d_]{2,}")
_AUTOMATICO = "_vm_nome_pela_dica"


def name_controls(root: QWidget) -> None:
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, _CONTROLES) or isinstance(widget, QScrollBar):
            continue
        if widget.property(_AUTOMATICO):
            widget.setAccessibleName("")
        elif _PALAVRA.search(widget.accessibleName()):
            continue
        interface = QAccessible.queryAccessibleInterface(widget)
        if interface is not None and _PALAVRA.search(interface.text(QAccessible.Text.Name) or ""):
            continue
        placeholder = widget.placeholderText() if isinstance(widget, (QLineEdit, QPlainTextEdit)) else ""
        name = (widget.toolTip() or placeholder).split("\n", 1)[0].strip()
        if name:
            widget.setAccessibleName(name)
            widget.setProperty(_AUTOMATICO, True)
