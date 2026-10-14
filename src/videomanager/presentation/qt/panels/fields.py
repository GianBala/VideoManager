"""Campos com a legenda em cima, em grade de três colunas: o formulário das abas Download e Convert.

Um ``QFormLayout`` põe o rótulo ao lado do campo e obriga uma coluna de rótulos com largura comum (que desloca os campos
ao trocar de modo). O protótipo põe a legenda **acima** do campo, e cada campo ocupa uma coluna: escondê-lo é esconder o
bloco inteiro, legenda junto.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel, QVBoxLayout, QWidget

from videomanager.presentation.qt.i18n import bind


def make_grid(parent: QWidget | None = None) -> QGridLayout:
    """Três colunas iguais, com 14 px entre elas e 16 entre as fileiras de campos."""
    grid = QGridLayout(parent)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(16)
    for coluna in range(3):
        grid.setColumnStretch(coluna, 1)
    return grid


def captioned(caption: Callable[[], str], widget: QWidget) -> QWidget:
    """A legenda em cima e o campo embaixo, num bloco só: esconder o campo esconde a legenda junto."""
    box = QWidget()
    box.setProperty("role", "plain")
    column = QVBoxLayout(box)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(6)
    label = bind(QLabel(), "setText", caption)
    label.setProperty("role", "caption")
    column.addWidget(label)
    widget.setProperty("role", "field")
    if isinstance(widget, QComboBox):
        # O tamanho que o combo pede não pode decidir a largura da coluna: três colunas iguais, e o texto mais longo
        # se corta com reticências em vez de empurrar as vizinhas.
        widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        widget.setMinimumContentsLength(6)
    column.addWidget(widget)
    return box
