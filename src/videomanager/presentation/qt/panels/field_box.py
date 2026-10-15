"""Caixa de campo da aba Propriedades: o rótulo e a unidade moram dentro dela, e o controle de dentro fica sem moldura.

No protótipo ``X  640 px`` é uma caixa só — o "X" à esquerda, o número encostado à direita e o "px" apagado depois dele —,
e não um rótulo solto ao lado de um ``QSpinBox`` com setinhas. O controle continua sendo o ``QSpinBox`` (ou
``QDoubleSpinBox``) de sempre: o teclado, a roda do mouse, o sinal de mudança, o nome acessível. Só a moldura é nova.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QStyle, QStyleOptionButton,
                               QStylePainter, QWidget)

from videomanager.presentation.qt.i18n import bind

Text = Callable[[], str] | str


def _put(label: QLabel, text: Text) -> QLabel:
    if callable(text):
        return bind(label, "setText", text)
    label.setText(text)
    return label


class FieldBox(QFrame):
    def __init__(self, control: QAbstractSpinBox, *, lead: Text | None = None, tail: Text | None = None,
                 height: int = 34, align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignRight,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.control = control
        self.setProperty("role", "field-box")
        self.setProperty("focused", "false")
        self.setFixedHeight(height)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(6)
        if lead is not None:
            self.lead = _put(QLabel(), lead)
            self.lead.setProperty("role", "lead")
            row.addWidget(self.lead)
        control.setProperty("role", "bare")
        control.setFrame(False)
        control.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        control.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(control, 1)
        if tail is not None:
            self.tail = _put(QLabel(), tail)
            self.tail.setProperty("role", "unit")
            row.addWidget(self.tail)
        # O foco de um spin mora no campo de texto de dentro, e é lá que ele chega (o spin só o repassa).
        self._target = control.lineEdit()
        self._target.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        # O anel de foco é da caixa inteira, e o QSS não tem "foco em algum filho".
        if obj is self._target and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.setProperty("focused", "true" if event.type() == QEvent.Type.FocusIn else "false")
            self.style().unpolish(self)
            self.style().polish(self)
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # Clicar no rótulo ou na unidade vai para o campo, como clicar numa caixa de texto qualquer.
        self.control.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)


class WrapCheck(QCheckBox):
    """Caixa de marcar cujo texto quebra linha, como na coluna estreita do protótipo.

    O ``QCheckBox`` do Qt desenha o texto numa linha só e, na coluna de 304 px, "Preencher as bordas com o bloco
    desfocado" saía cortado pela borda. Continua sendo um ``QCheckBox`` de verdade (marcar, o sinal, o teclado, o
    nome acessível): o indicador sai do estilo, e só o texto é desenhado aqui, dentro da largura que sobra.
    """

    _GAP = 8

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def hitButton(self, pos) -> bool:  # noqa: N802
        # A linha inteira é a caixa, como no protótipo: o clique do Qt só vale no indicador e no texto de uma linha, e o que
        # sobrava (a parte vazia à direita, a segunda linha do texto, a folga em cima e embaixo) ficava surdo.
        return self.rect().contains(pos)

    def _indicator_rect(self) -> QRect:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        return self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)

    def _indicator(self) -> int:
        return self._indicator_rect().right() + 1 + self._GAP

    def _line(self) -> int:
        # Não pergunta ao ``QCheckBox.minimumSizeHint``: ele chama o ``sizeHint`` daqui, que chama este, e o laço não acaba.
        return max(self._indicator_rect().height(), self.fontMetrics().height()) + 4

    def _text_rect(self, width: int) -> QRect:
        left = self._indicator()
        return QRect(left, 0, max(1, width - left), 100000)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        wanted = self.fontMetrics().boundingRect(self._text_rect(width), int(Qt.TextFlag.TextWordWrap), self.text())
        return max(self._line(), wanted.height() + 4)

    def sizeHint(self) -> QSize:  # noqa: N802
        # Na largura que o texto pediria numa linha só; o layout encolhe e a altura cresce com ``heightForWidth``.
        width = self._indicator() + self.fontMetrics().horizontalAdvance(self.text())
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._indicator() + 40, self._line())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        text, option.text = option.text, ""
        painter.drawControl(QStyle.ControlElement.CE_CheckBox, option)
        painter.setPen(self.palette().color(QPalette.ColorGroup.Disabled if not self.isEnabled() else QPalette.ColorGroup.Active,
                                            QPalette.ColorRole.WindowText))
        # Centrado na altura que o widget tem, como o indicador: numa linha mais alta que o texto (a do campo ao lado) os
        # dois ficam no mesmo meio, e no texto de duas linhas o indicador fica entre elas, como no protótipo.
        rect = self._text_rect(self.width())
        rect.setHeight(self.height())
        painter.drawText(rect, int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        painter.end()
