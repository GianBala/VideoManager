"""Aba Metadados: abrir um arquivo, editar tags, trilhas e capa, e salvar numa cópia.

O original nunca é alterado: cada salvamento grava "nome (metadados).ext" ao
lado dele. A cópia é conferida antes de aparecer (mesmas trilhas, mesmos
pacotes), e o que o formato não guardou é dito na tela — gravado sem erro não
quer dizer guardado (ver ``infrastructure/ffmpeg/metadata.py``).

A fila fica fora desta aba, como no editor: salvar não é tarefa da fila, é o
fim de uma edição que se acompanha aqui mesmo, e o espaço vale mais como
formulário.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPainter, QPalette, QPen, QPixmap, QTextDocument, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QStyledItemDelegate,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.errors import JobCancelled
from videomanager.application.formatting import format_duration
from videomanager.application.preferences import Preferences as Settings
from videomanager.domain.metadata import COMMON_TAGS
from videomanager.domain.metadata import FileMetadata
from videomanager.domain.metadata import MetadataEdit
from videomanager.domain.metadata import SavedCopy
from videomanager.domain.metadata import editable_tags
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.i18n import align_label_column, bind, on_language_change
from videomanager.presentation.qt.ports import DesktopRuntimePort
from videomanager.presentation.qt.tasks import WorkerRunner

_COVER_SIZE = 160
# Campos que costumam ter várias linhas (a descrição de um vídeo do YouTube é
# um texto inteiro): numa linha só, as quebras viravam traços na tela.
_MULTILINE = ("comment", "description")
_MULTILINE_ROWS = 3
# Alça de ampliar abaixo desses campos: alta o bastante para acertar com o mouse.
_GRIP_HEIGHT = 8
# Colunas editáveis da tabela de trilhas.
_TITLE, _LANGUAGE = 3, 4
# Linhas visíveis de cada tabela antes de rolar: sem piso próprio o Qt reserva
# 192 px, que não tem relação com o conteúdo.
_TABLE_ROWS = 3
# Menor largura a que o usuário leva uma coluna: a zero ela sumiria sem aviso.
_MIN_COLUMN = 60


class _Header(QHeaderView):
    """Cabeçalho que sabe quando o usuário está com o botão apertado nele.

    ``sectionResized`` sai igual para o arrasto do usuário e para um
    redimensionamento nosso, e o Qt não distingue os dois.
    """

    def __init__(self, orientation: Qt.Orientation, parent: QWidget) -> None:
        super().__init__(orientation, parent)
        self.pressed = False
        # O que o QTableView dá aos cabeçalhos que ele mesmo cria: clicar numa
        # seção a seleciona. Um cabeçalho nosso nasce sem isso.
        self.setSectionsClickable(True)
        self.setHighlightSections(True)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.pressed = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self.pressed = False


# Altura da faixa, no pé de cada linha, onde está a alça de ampliá-la.
_ROW_BAND = 8
# O ajuste automático de uma linha vai até este número de linhas de texto; acima
# disso, só pela alça: uma sinopse de 200 linhas não pode empurrar o resto da aba.
_AUTO_ROW_LINES = 8
# Voltas, no máximo, de um ajuste que a mudança de altura faz recomeçar (a barra
# de rolagem aparece ou some e o texto quebra de outro jeito): a segunda já costuma
# estabilizar, e o limite impede um vaivém de nunca terminar.
_FIT_PASSES = 5
# Folga, em pixels, com que uma linha arrastada "de volta" volta ao ajuste automático:
# ninguém acerta o pixel, e a altura automática de agora ainda muda com a barra de
# rolagem e com a fonte.
_SNAP = 4
# Dado, no item da primeira coluna, que marca a linha que o usuário ajustou à mão: a
# altura automática que ela tinha quando ele a tocou, para ela voltar a ela por um
# arrasto de volta (a de agora pode ser outra, se a barra de rolagem mudou a largura).
_MANUAL = Qt.ItemDataRole.UserRole + 1


# Linhas de texto que o editor de um valor mostra de uma vez: no mínimo as do campo
# Descrição da aba Tags, e no máximo o teto do ajuste automático das linhas.
_EDITOR_MIN_LINES = 3
_EDITOR_MAX_LINES = _AUTO_ROW_LINES
# O que o campo de texto gasta fora das linhas, com o tema: borda de 1 px e
# preenchimento de 6 px na vertical (14), e de 8 px nas laterais (18, sem contar a
# barra de rolagem). Medido no QPlainTextEdit com o QSS; sem o tema seriam 2 e 16.
# O teste do editor confere, nos dois temas, que o texto cabe sem rolar — e falha
# se o QSS mudar isso.
_EDITOR_CHROME_H = 14
_EDITOR_CHROME_W = 18
# Linhas de folga embaixo do texto. O QPlainTextEdit gasta alguns pixels a mais do que
# o QTextDocument mede (4 px medidos com a DejaVu, que a CI usa), e por 1 px a barra de
# rolagem aparecia — com a fonte desta máquina a folga de 2 px bastava, e escondia isso.
_EDITOR_SPARE_LINES = 1


class _ValueDelegate(QStyledItemDelegate):
    """Editor do valor de um campo livre: o mesmo campo de várias linhas da aba Tags.

    O editor padrão da tabela é um ``QLineEdit`` apertado na célula de 30 px: sem
    quebra de linha, sem ver o resto de um texto comprido, e com o Enter
    fechando a edição — no valor de várias linhas, editar era um sofrimento.
    Aqui o Enter quebra a linha, como no campo Descrição; o Tab ou um clique
    fora confirma, o Esc desfaz, e o Ctrl+Enter confirma sem tirar a mão do
    teclado. O editor flutua mais alto que a linha quando o texto pede.
    """

    def createEditor(self, parent, option, index):  # noqa: N802
        editor = QPlainTextEdit(parent)
        editor.setTabChangesFocus(True)
        # Já com o tema: a fonte do QSS (10 pt) só vale depois do polimento, e medir
        # o texto com a fonte antes dele errava as linhas — e a barra de rolagem
        # aparecia, estreitando o texto e escondendo a primeira linha.
        editor.ensurePolished()
        return editor

    def setEditorData(self, editor, index) -> None:  # noqa: N802
        editor.setPlainText(str(index.data(Qt.ItemDataRole.EditRole) or ""))  # o cursor fica no começo, como na aba Tags

    def setModelData(self, editor, model, index) -> None:  # noqa: N802
        model.setData(index, editor.toPlainText(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, editor, option, index) -> None:  # noqa: N802
        rect, viewport = option.rect, option.widget.viewport()
        document = QTextDocument()
        document.setDefaultFont(editor.font())
        wrap = document.defaultTextOption()
        wrap.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)  # o mesmo do campo
        document.setDefaultTextOption(wrap)
        document.setDocumentMargin(editor.document().documentMargin())
        # Já sem a largura da barra de rolagem. O editor nasce pequeno, com o texto
        # dentro, e nessa hora a barra aparece e estreita o texto; medido sem ela,
        # um texto no limite cabia em 4 linhas, o editor ganhava a altura de 4, e
        # com a barra o texto passava a 5 e a barra ficava — dois estados estáveis,
        # o errado escolhido nos casos limítrofes. Medindo já com a barra, não
        # precisa dela em nenhum dos dois estados; no pior caso sobra uma linha.
        document.setTextWidth(max(rect.width() - _EDITOR_CHROME_W - editor.verticalScrollBar().sizeHint().width(), 1))
        document.setPlainText(str(index.data(Qt.ItemDataRole.EditRole) or ""))
        line, margins = editor.fontMetrics().lineSpacing(), 2 * editor.document().documentMargin()
        spare = _EDITOR_SPARE_LINES * line
        wanted = int(document.size().height()) + _EDITOR_CHROME_H + spare
        height = int(min(max(wanted, _EDITOR_MIN_LINES * line + margins + _EDITOR_CHROME_H),
                         _EDITOR_MAX_LINES * line + margins + _EDITOR_CHROME_H + spare))
        # Dentro da área visível: um editor alto no fim da tabela não pode ser cortado,
        # nem passar dela — numa janela estreita o texto pede mais que a tabela mostra,
        # e então é o editor que rola.
        height = min(max(height, rect.height()), viewport.height())
        editor.setGeometry(rect.x(), max(0, min(rect.y(), viewport.height() - height)), rect.width(), height)

    def eventFilter(self, editor, event) -> bool:  # noqa: N802
        if (event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.NoHint)
            return True
        return super().eventFilter(editor, event)


class _Table(QTableWidget):
    """Tabela que pede a altura de ``_TABLE_ROWS`` linhas e cresce com a sobra.

    A dica padrão de uma área de rolagem é um palpite fixo (192 px) sem relação
    com o conteúdo: duas tabelas assim empurravam o botão de salvar para fora
    da janela padrão.

    Com ``adjustable``, a divisão das colunas se arrasta e cada linha se adapta
    ao texto: um valor de várias linhas (a sinopse de um vídeo baixado) cabia em
    30 px, e o Qt o cortava com reticências no fim da primeira linha por mais
    larga que fosse a coluna. A linha também tem uma alça à vista no pé, como os
    campos de texto da aba: arrastá-la a amplia, e o clique duplo devolve o
    ajuste automático. ``row_tip`` dá o texto da dica dessa alça, lido a cada
    vez para acompanhar o idioma.
    """

    def __init__(self, columns: int, *, adjustable: bool = False, row_tip=None) -> None:
        super().__init__(0, columns)
        self._adjustable = adjustable
        self._row_tip = row_tip
        self._split_free = True  # ninguém arrastou a divisão: ela segue a largura da tabela
        self._balancing = False
        self._passes = 0
        # O ajuste das linhas roda depois de o layout assentar, e não de dentro
        # do sinal que o pede: nesse instante o Qt ainda não redistribuiu a
        # última coluna nem decidiu a altura da tabela, e a linha ficava com a
        # medida de uma largura que logo deixava de existir.
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit_now)
        # (linha, y na tela, altura, altura automática ao apertar — ou None se a linha já era manual)
        self._drag: tuple[int, int, int, int | None] | None = None
        self._hover_row = -1
        self.verticalHeader().setVisible(False)
        if adjustable:
            self.setHorizontalHeader(_Header(Qt.Orientation.Horizontal, self))
        self.setMinimumHeight(self.horizontalHeader().sizeHint().height()
                              + self.verticalHeader().defaultSectionSize() * _TABLE_ROWS + 2 * self.frameWidth())
        self._base_min = self.minimumHeight()  # o piso de nascença: é a esta altura que a alça da tabela volta
        self._user_min = self._base_min  # o que o usuário escolheu pela alça da tabela
        if adjustable:
            header, rows = self.horizontalHeader(), self.verticalHeader()
            # No modo Stretch o Qt desliga o arrasto: a primeira coluna passa a
            # ser interativa, e a última pega o que sobra.
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            header.setStretchLastSection(True)
            header.setMinimumSectionSize(_MIN_COLUMN)
            header.sectionResized.connect(self._section_resized)
            rows.setMinimumSectionSize(rows.defaultSectionSize())  # nunca menor que a nascença
            self.setWordWrap(True)
            # Uma linha mais alta que a tabela precisa de rolagem por pixel: por
            # item, o meio dela não se alcança.
            self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            self.viewport().setMouseTracking(True)  # o cursor muda sobre a alça sem botão apertado
            self.itemChanged.connect(lambda _item: self.fit_rows())
            self.model().rowsRemoved.connect(lambda *_: self.fit_rows())

    # --- colunas --------------------------------------------------------------

    def _section_resized(self, *_args) -> None:
        if not self._balancing and self.horizontalHeader().pressed:
            self._split_free = False
        # A largura mudou e o texto quebra em outras linhas. Pelo arrasto do
        # usuário ou por um rebalanceamento nosso é um pedido novo; o resto é o
        # Qt reacomodando a última coluna no meio de um ajuste.
        if self.horizontalHeader().pressed or self._balancing:
            self.fit_rows()
        else:
            self._fit_timer.start()

    def _balance_columns(self) -> None:
        """Até o usuário arrastar a divisão, as colunas se repartem como antes: metade e metade."""
        if self._split_free and self.columnCount() == 2:
            self._balancing = True
            self.horizontalHeader().resizeSection(0, (self.viewport().width() + 1) // 2)
            self._balancing = False

    # --- linhas ---------------------------------------------------------------

    def _remembered_auto(self, row: int) -> int:
        item = self.item(row, 0)
        return int(item.data(_MANUAL) or 0) if item is not None else 0

    def _is_manual(self, row: int) -> bool:
        return self._remembered_auto(row) > 0

    def _set_manual(self, row: int, auto: int | None) -> None:
        """Marca a linha como ajustada à mão, lembrando a altura automática que tinha; ``None`` a solta."""
        item = self.item(row, 0)
        if item is not None:
            blocked = self.blockSignals(True)  # gravar o dado não é edição: não avisa ninguém
            item.setData(_MANUAL, auto)
            self.blockSignals(blocked)

    def _auto_height(self, row: int) -> int:
        """A altura do próprio texto da linha, sem passar do teto."""
        base = self.verticalHeader().defaultSectionSize()
        teto = base + (_AUTO_ROW_LINES - 1) * self.fontMetrics().lineSpacing()
        return max(base, min(self.sizeHintForRow(row), teto))

    def _fit_row(self, row: int) -> bool:
        """Dá à linha a altura do próprio texto, se o usuário não a ajustou.

        Devolve se a altura mudou.
        """
        if not 0 <= row < self.rowCount() or self._is_manual(row):
            return False
        height = self._auto_height(row)
        changed = height != self.rowHeight(row)
        if changed:
            self.setRowHeight(row, height)
        return changed

    def fit_rows(self) -> None:
        """Pede o ajuste de todas as linhas, para quando a largura e o layout já assentaram."""
        if self._adjustable:
            self._passes = 0
            self._fit_timer.start()

    def _fit_now(self) -> None:
        changed = False
        for row in range(self.rowCount()):
            changed |= self._fit_row(row)
        self._update_floor()  # também depois de linhas apagadas ou de uma linha devolvida ao automático
        if changed:
            # Mudar a altura move a barra de rolagem e a altura que a tabela pede
            # (ver sizeHint), e isso pode mudar a largura do texto: outra volta.
            if self._passes < _FIT_PASSES:
                self._passes += 1
                self._fit_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._passes = 0  # a tabela mudou de tamanho de verdade: o limite de voltas recomeça
        super().resizeEvent(event)

    def _grip_row(self, y: int) -> int:
        """A linha cuja alça está na altura ``y`` da área visível, ou -1."""
        row = self.rowAt(y)
        if row < 0 or y < self.rowViewportPosition(row) + self.rowHeight(row) - _ROW_BAND:
            return -1
        return row

    def _hover(self, row: int) -> None:
        if row != self._hover_row:
            self._hover_row = row
            self.viewport().setCursor(Qt.CursorShape.SizeVerCursor) if row >= 0 else self.viewport().unsetCursor()
            self.viewport().update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        row = self._grip_row(int(event.position().y())) if self._adjustable else -1
        if row >= 0 and event.button() == Qt.MouseButton.LeftButton:
            self._drag = (row, int(event.globalPosition().y()), self.rowHeight(row),
                          None if self._is_manual(row) else self.rowHeight(row))
            event.accept()  # a alça não seleciona nem abre editor
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            if not event.buttons() & Qt.MouseButton.LeftButton:  # soltou fora e o release se perdeu
                self._drag = None
                return
            row, start, height = self._drag[:3]
            if not self._is_manual(row):
                self._set_manual(row, self._drag[3])  # a altura automática de antes de tocar
            self.setRowHeight(row, max(self.verticalHeader().defaultSectionSize(),
                                       height + int(event.globalPosition().y()) - start))
            self._update_floor()
            event.accept()
            return
        if self._adjustable:
            self._hover(self._grip_row(int(event.position().y())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            row, self._drag = self._drag[0], None
            # Arrastada de volta à altura automática — a de agora ou a que tinha ao ser
            # tocada, que pode ser outra se a barra de rolagem mudou a largura do texto
            # —, a linha volta a ser automática: segue o texto e a largura de novo, e
            # o piso da tabela deixa de segurá-la.
            alvos = [self._auto_height(row), self._remembered_auto(row)]
            if any(abs(self.rowHeight(row) - alvo) <= _SNAP for alvo in alvos if alvo > 0):
                self._set_manual(row, None)
                self.fit_rows()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        row = self._grip_row(int(event.position().y())) if self._adjustable else -1
        if row >= 0:
            self._set_manual(row, None)
            self.fit_rows()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover(-1)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._adjustable or self.rowCount() == 0:
            return
        painter = QPainter(self.viewport())
        selected = {index.row() for index in self.selectedIndexes()}
        active = {self._hover_row, self._drag[0] if self._drag else -1}
        middle = self.viewport().width() // 2
        first, last = max(self.rowAt(0), 0), self.rowAt(self.viewport().height() - 1)
        for row in range(first, (self.rowCount() if last < 0 else last + 1)):
            bottom = self.rowViewportPosition(row) + self.rowHeight(row)
            # Sobre a linha selecionada o fundo é o destaque: o traço usa o texto dele.
            role = (QPalette.ColorRole.HighlightedText if row in selected
                    else QPalette.ColorRole.Highlight if row in active
                    else QPalette.ColorRole.PlaceholderText)
            painter.setPen(QPen(self.palette().color(role), 1))
            for y in (bottom - 6, bottom - 4):
                painter.drawLine(middle - 12, y, middle + 12, y)

    def viewportEvent(self, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.ToolTip and self._adjustable and self._row_tip is not None:
            if self._grip_row(event.pos().y()) >= 0:
                QToolTip.showText(event.globalPos(), self._row_tip(), self.viewport())
                return True
        # No evento da área visível, e não no da tabela: a barra de rolagem que
        # aparece estreita a área sem mexer na tabela.
        result = super().viewportEvent(event)
        if event.type() == QEvent.Type.Resize:
            self._balance_columns()
        return result

    def sizeHint(self) -> QSize:  # noqa: N802
        """O piso, mais o que as linhas ajustadas sozinhas passam da altura de nascença (até um teto).

        A linha de uma sinopse se adapta ao texto, mas numa tabela de três
        linhas só se veria uma: a janela da tabela acompanha o que a adaptação
        acrescenta. Com todas as linhas de uma linha de texto o acréscimo é zero
        e a tabela pede o que sempre pediu. O que o usuário abriu à mão está no
        piso (:meth:`_update_floor`), e não aqui.
        """
        auto = 0
        if self._adjustable:
            base = self.verticalHeader().defaultSectionSize()
            auto = min(sum(max(0, self.rowHeight(r) - base) for r in range(self.rowCount()) if not self._is_manual(r)),
                       (_AUTO_ROW_LINES - 1) * self.fontMetrics().lineSpacing())
        return QSize(super().sizeHint().width(), max(self.minimumHeight(), self._base_min + auto))

    def set_floor(self, height: int) -> None:
        """A altura mínima que o usuário escolheu pela alça da tabela."""
        self._user_min = height
        self._update_floor()

    def _update_floor(self) -> None:
        """O piso é o maior entre a escolha do usuário e o que as linhas que ele abriu exigem.

        Um piso, e não só o pedido (``sizeHint``): a área de rolagem da página dá
        ao painel no mínimo o tamanho **mínimo** dele, e com a janela mais baixa
        que o conteúdo o layout espreme a tabela até o piso. Aberta além disso, a
        linha levava a alça do pé — a de fechá-la — para fora da área visível,
        bem sobre a alça da tabela, logo abaixo, e não se fechava mais. Com o
        piso a página rola, e a alça continua ao alcance.
        """
        if not self._adjustable:
            return
        base = self.verticalHeader().defaultSectionSize()
        manual = [r for r in range(self.rowCount()) if self._is_manual(r)]
        floor = max(self._user_min, self._base_min)
        if manual:
            # Da primeira linha até a última aberta: as de cima também têm de caber
            # para a alça do pé da aberta aparecer. O resto do piso é a moldura.
            shown = sum(self.rowHeight(r) for r in range(manual[-1] + 1))
            floor = max(floor, self._base_min - _TABLE_ROWS * base + shown)
        self.setMinimumHeight(floor)
        self.updateGeometry()


class _Grip(QWidget):
    """Alça sob um campo de texto: arrastar na vertical o amplia, clique duplo o restaura.

    O Qt não tem campo de texto que o usuário redimensione (o ``QSizeGrip`` só
    alcança janelas), e a descrição de um vídeo costuma ter dezenas de linhas
    para três de altura. O campo nunca fica menor que ``base``, a altura de
    nascença, então restaurar é só voltar a ela.

    A posição é medida na tela, e não no widget: a alça anda junto com o campo
    que cresce, e o ponteiro relativo a ela mudaria a cada passo.

    ``apply`` diz como a altura chega ao alvo: o campo de texto fica com altura
    fixa, mas a tabela só sobe o **piso** (``_Table.set_floor``) e continua
    crescendo com a sobra da coluna, como sempre cresceu.
    """

    def __init__(self, target: QWidget, base: int, apply=QWidget.setFixedHeight) -> None:
        super().__init__()
        self._target = target
        self._base = base
        self._apply = apply
        self._press: tuple[int, int] | None = None  # (y na tela, altura do campo) ao apertar
        self._hover = False
        self.setProperty("role", "plain")
        self.setFixedHeight(_GRIP_HEIGHT)
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def paintEvent(self, _event) -> None:  # noqa: N802
        # Cores do papel do tema, e não fixas: a paleta da aplicação já segue
        # claro e escuro (ver ``theme.qpalette``).
        role = QPalette.ColorRole.Highlight if self._hover or self._press else QPalette.ColorRole.PlaceholderText
        painter = QPainter(self)
        painter.setPen(QPen(self.palette().color(role), 1))
        middle, left, right = self.height() // 2, self.width() // 2 - 12, self.width() // 2 + 12
        for y in (middle - 1, middle + 1):
            painter.drawLine(left, y, right, y)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = (int(event.globalPosition().y()), self._target.height())
            self.update()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None:
            return
        if not event.buttons() & Qt.MouseButton.LeftButton:  # soltou fora e o release se perdeu
            self._press = None
            self.update()
            return
        start, height = self._press
        self._apply(self._target, max(self._base, height + int(event.globalPosition().y()) - start))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press = None
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._apply(self._target, self._base)


class MetadataPanel(QWidget):
    def __init__(
        self,
        settings: Settings,
        ensure_tools: Callable[[], FFmpegTools | None],
        parent: QWidget | None = None,
        *,
        runtime: DesktopRuntimePort,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._ensure_tools = ensure_tools
        self._runtime = runtime
        self._meta: FileMetadata | None = None
        self._cover: bytes | None = None
        self._new_cover: Path | None = None
        self._remove_cover = False
        self._cover_pixmap: QPixmap | None = None
        self._baseline: MetadataEdit | None = None
        self._loading: Path | None = None
        self._saving = None
        self._saved: SavedCopy | None = None
        self._cancelled = False
        self._token = 0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._runner = WorkerRunner(self._pool)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_file_group())
        # Duas colunas: as tags têm linhas curtas e muitas; capa, campos livres
        # e trilhas cabem ao lado, e tudo aparece sem rolar na janela padrão.
        middle = QHBoxLayout()
        middle.setSpacing(10)
        middle.addWidget(self._build_tags_group(), 1, Qt.AlignmentFlag.AlignTop)
        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._build_cover_group())
        right.addWidget(self._build_others_group())
        right.addWidget(self._build_tracks_group())
        middle.addLayout(right, 1)
        layout.addLayout(middle)

        # Em linha própria: texto que quebra ao lado de botões nasce cortado.
        self._result = QLabel()
        self._result.setProperty("role", "dim")
        self._result.setWordWrap(True)
        self._result.setVisible(False)
        layout.addWidget(self._result)
        actions = QHBoxLayout()
        self._reveal = bind(QPushButton(), "setText", lambda: strings.META_REVEAL)
        self._reveal.clicked.connect(lambda: self._saved and self._runtime.reveal_file(self._saved.path))
        self._reveal.setVisible(False)
        actions.addWidget(self._reveal)
        actions.addStretch(1)
        self._discard = bind(QPushButton(), "setText", lambda: strings.META_DISCARD)
        self._discard.clicked.connect(self._discard_changes)
        actions.addWidget(self._discard)
        self._cancel = bind(QPushButton(), "setText", lambda: strings.META_CANCEL)
        self._cancel.clicked.connect(self._runner.cancel_all)
        self._cancel.setVisible(False)
        actions.addWidget(self._cancel)
        self._save = bind(QPushButton(), "setText", lambda: strings.META_SAVE)
        bind(self._save, "setToolTip", lambda: strings.META_SAVE_TIP.format(label=strings.META_SAVE))
        self._save.setProperty("role", "primary")
        self._save.clicked.connect(self.save)
        actions.addWidget(self._save)
        layout.addLayout(actions)
        layout.addStretch(1)

        # Também põe os cabeçalhos das tabelas, que não passam por ``bind``.
        self._retranslate()
        on_language_change(self._retranslate)

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def _build_file_group(self) -> QGroupBox:
        group = bind(QGroupBox(), "setTitle", lambda: strings.META_FILE_GROUP)
        row = QHBoxLayout(group)
        pick = bind(QPushButton(), "setText", lambda: strings.META_OPEN)
        bind(pick, "setToolTip", lambda: strings.META_OPEN_TIP.format(label=strings.META_OPEN))
        pick.clicked.connect(self.choose_file)
        row.addWidget(pick)
        self._info = QLabel()
        self._info.setProperty("role", "dim")
        row.addWidget(self._info, 1)
        return group

    def _build_tags_group(self) -> QGroupBox:
        self._tags_group = bind(QGroupBox(), "setTitle", lambda: strings.META_TAGS_GROUP)
        box = QVBoxLayout(self._tags_group)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        self._fields: dict[str, QLineEdit | QPlainTextEdit] = {}
        self._grips: dict[str, _Grip] = {}
        self._labels: list[QLabel] = []
        for key in COMMON_TAGS:
            label = bind(QLabel(), "setText", lambda key=key: strings.META_FIELDS[key])
            if key in _MULTILINE:
                field = QPlainTextEdit()
                field.setTabChangesFocus(True)
                lines = field.fontMetrics().lineSpacing() * _MULTILINE_ROWS
                base = lines + 2 * field.frameWidth() + 8
                field.setFixedHeight(base)
                field.textChanged.connect(self._refresh)
                # ``plain``: sem ele o contêiner herda o fundo da janela e pinta
                # um retângulo escuro sobre a superfície do grupo.
                row = QWidget()
                row.setProperty("role", "plain")
                column = QVBoxLayout(row)
                column.setContentsMargins(0, 0, 0, 0)
                column.setSpacing(0)
                column.addWidget(field)
                self._grips[key] = bind(_Grip(field, base), "setToolTip", lambda: strings.META_GROW_TIP)
                column.addWidget(self._grips[key])
            else:
                field = row = QLineEdit()
                field.textEdited.connect(self._refresh)
            self._fields[key] = field
            self._labels.append(label)
            form.addRow(label, row)
        align_label_column(self._labels)
        box.addLayout(form)
        return self._tags_group

    def _build_others_group(self) -> QGroupBox:
        self._others_group = bind(QGroupBox(), "setTitle", lambda: strings.META_OTHER_FIELDS)
        box = QVBoxLayout(self._others_group)
        self._others = _Table(2, adjustable=True, row_tip=lambda: strings.META_ROW_TIP)
        self._others.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._others.setItemDelegateForColumn(1, _ValueDelegate(self._others))
        self._others.itemChanged.connect(self._refresh)
        bind(self._others.horizontalHeader(), "setToolTip", lambda: strings.META_COLUMN_TIP)
        # Tabela e alça num contêiner sem espaçamento: a alça fica colada, como
        # nos campos de texto, e não a 6 px do espaçamento do grupo.
        holder = QWidget()
        holder.setProperty("role", "plain")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._others)
        self._others_grip = bind(_Grip(self._others, self._others.minimumHeight(), _Table.set_floor),
                                 "setToolTip", lambda: strings.META_GROW_TABLE_TIP)
        column.addWidget(self._others_grip)
        box.addWidget(holder)
        buttons = QHBoxLayout()
        self._add_field = bind(QPushButton(), "setText", lambda: strings.META_ADD_FIELD)
        self._add_field.clicked.connect(self._add_other)
        self._remove_field = bind(QPushButton(), "setText", lambda: strings.META_REMOVE_FIELD)
        self._remove_field.clicked.connect(self._remove_others)
        buttons.addWidget(self._add_field)
        buttons.addWidget(self._remove_field)
        buttons.addStretch(1)
        box.addLayout(buttons)
        return self._others_group

    def _build_cover_group(self) -> QGroupBox:
        self._cover_group = bind(QGroupBox(), "setTitle", lambda: strings.META_COVER_GROUP)
        box = QHBoxLayout(self._cover_group)
        self._cover_view = QLabel()
        self._cover_view.setFixedSize(_COVER_SIZE, _COVER_SIZE)
        self._cover_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_view.setWordWrap(True)
        self._cover_view.setProperty("role", "dim")
        box.addWidget(self._cover_view)
        buttons = QVBoxLayout()
        self._change_cover = bind(QPushButton(), "setText", lambda: strings.META_COVER_CHANGE)
        self._change_cover.clicked.connect(self._choose_cover)
        self._drop_cover = bind(QPushButton(), "setText", lambda: strings.META_COVER_REMOVE)
        self._drop_cover.clicked.connect(self._clear_cover)
        buttons.addWidget(self._change_cover)
        buttons.addWidget(self._drop_cover)
        buttons.addStretch(1)
        box.addLayout(buttons)
        box.addStretch(1)
        return self._cover_group

    def _build_tracks_group(self) -> QGroupBox:
        self._tracks_group = bind(QGroupBox(), "setTitle", lambda: strings.META_TRACKS_GROUP)
        box = QVBoxLayout(self._tracks_group)
        self._tracks = _Table(len(strings.META_TRACK_HEADERS))
        header = self._tracks.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_TITLE, QHeaderView.ResizeMode.Stretch)
        self._tracks.itemChanged.connect(self._refresh)
        box.addWidget(self._tracks)
        self._tracks_note = bind(QLabel(), "setText", lambda: strings.META_TRACKS_ON_FILE)
        self._tracks_note.setProperty("role", "dim")
        self._tracks_note.setWordWrap(True)
        self._tracks_note.setVisible(False)
        box.addWidget(self._tracks_note)
        return self._tracks_group

    def _retranslate(self) -> None:
        align_label_column(self._labels)
        self._others.setHorizontalHeaderLabels([strings.META_FIELD_HEADER, strings.META_VALUE_HEADER])
        self._tracks.setHorizontalHeaderLabels(list(strings.META_TRACK_HEADERS))
        blocked = self._tracks.blockSignals(True)
        # Célula não passa por ``bind``: o tipo e a dica do idioma são refeitos aqui.
        for row in range(self._tracks.rowCount()):
            kind = self._tracks.item(row, 1)
            kind.setText(strings.META_TRACK_KINDS.get(kind.data(Qt.ItemDataRole.UserRole), kind.data(Qt.ItemDataRole.UserRole)))
            self._tracks.item(row, _LANGUAGE).setToolTip(strings.META_LANGUAGE_TIP)
        self._tracks.blockSignals(blocked)
        self._refresh()

    # ------------------------------------------------------------------
    # Abrir
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.open_file(paths[0])

    def choose_file(self) -> None:
        start = str(self._meta.path.parent if self._meta else Path.home())
        path, _ = QFileDialog.getOpenFileName(self, strings.META_OPEN, start, strings.META_FILE_FILTER)
        if path:
            self.open_file(Path(path))

    def open_file(self, path: Path) -> None:
        if self._saving is not None or not self.confirm_discard():
            return
        tools = self._ensure_tools()
        if tools is None:
            return
        self._token += 1
        self._runner.cancel_all()
        token = self._token
        self._loading = path
        worker = self._runtime.metadata_reader(path, tools)
        worker.signals.finished.connect(lambda result: self._on_loaded(token, result),
                                        Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(lambda error: self._on_load_failed(token, error),
                                      Qt.ConnectionType.QueuedConnection)
        self._runner.start(worker, worker.signals.done)
        self._refresh()

    def _on_loaded(self, token: int, result) -> None:
        if token != self._token:
            return
        self._loading = None
        self._install(*result)

    def _on_load_failed(self, token: int, error) -> None:
        if token != self._token:
            return
        self._loading = None
        self._refresh()
        if not isinstance(error, JobCancelled):
            QMessageBox.warning(self, strings.DIALOG_WARNING_TITLE, str(error))

    def _install(self, meta: FileMetadata, cover: bytes | None) -> None:
        self._meta, self._cover = meta, cover
        self._new_cover, self._remove_cover = None, False
        self._update_cover_pixmap()
        self._saved, self._cancelled = None, False
        tags = dict((key.lower(), (key, value)) for key, value in editable_tags(meta))
        for key, field in self._fields.items():
            value = tags.pop(key, ("", ""))[1]
            if isinstance(field, QPlainTextEdit):
                blocked = field.blockSignals(True)
                field.setPlainText(value)
                field.blockSignals(blocked)
            else:
                field.setText(value)
        blocked = self._others.blockSignals(True)
        self._others.setRowCount(0)
        for key, value in tags.values():
            self._append_other(key, value)
        self._others.blockSignals(blocked)
        self._others.fit_rows()  # com os sinais bloqueados, nenhuma linha se ajustou sozinha

        blocked = self._tracks.blockSignals(True)
        self._tracks.setRowCount(0)
        for number, track in enumerate(meta.tracks, start=1):
            row = self._tracks.rowCount()
            self._tracks.insertRow(row)
            cells = (str(number), strings.META_TRACK_KINDS.get(track.kind, track.kind), track.codec,
                     track.title, track.language)
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                editable = column in (_TITLE, _LANGUAGE) and not meta.tags_on_stream
                if not editable:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, track.index)
                if column == 1:
                    item.setData(Qt.ItemDataRole.UserRole, track.kind)
                if column == _LANGUAGE:
                    item.setToolTip(strings.META_LANGUAGE_TIP)
                self._tracks.setItem(row, column, item)
        self._tracks.blockSignals(blocked)
        self._baseline = self.current_edit()
        self._refresh()

    # ------------------------------------------------------------------
    # Editar
    # ------------------------------------------------------------------

    def _append_other(self, key: str = "", value: str = "") -> int:
        row = self._others.rowCount()
        self._others.insertRow(row)
        self._others.setItem(row, 0, QTableWidgetItem(key))
        self._others.setItem(row, 1, QTableWidgetItem(value))
        return row

    def _add_other(self) -> None:
        row = self._append_other()
        self._others.setCurrentCell(row, 0)
        self._others.editItem(self._others.item(row, 0))
        self._refresh()

    def _remove_others(self) -> None:
        for row in sorted({index.row() for index in self._others.selectedIndexes()}, reverse=True):
            self._others.removeRow(row)
        self._refresh()

    def _choose_cover(self) -> None:
        start = str(self._meta.path.parent if self._meta else Path.home())
        path, _ = QFileDialog.getOpenFileName(self, strings.META_COVER_CHANGE, start, strings.META_COVER_FILTER)
        if path:
            self._new_cover, self._remove_cover = Path(path), False
            self._update_cover_pixmap()
            self._refresh()

    def _clear_cover(self) -> None:
        self._new_cover, self._remove_cover = None, True
        self._update_cover_pixmap()
        self._refresh()

    def _discard_changes(self) -> None:
        if self._meta is not None:
            self._install(self._meta, self._cover)

    def current_edit(self) -> MetadataEdit | None:
        if self._meta is None:
            return None
        # Os valores vão como estão: tirar espaço ou quebra de linha do fim
        # regravaria alterado um campo que o usuário nem tocou.
        tags = [(key, field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text())
                for key, field in self._fields.items()]
        for row in range(self._others.rowCount()):
            key, value = self._others.item(row, 0), self._others.item(row, 1)
            if key is not None and key.text().strip():
                tags.append((key.text().strip(), value.text() if value is not None else ""))
        tracks = tuple(
            (self._tracks.item(row, 0).data(Qt.ItemDataRole.UserRole), self._tracks.item(row, _TITLE).text(),
             self._tracks.item(row, _LANGUAGE).text())
            for row in range(self._tracks.rowCount())
        )
        return MetadataEdit(tuple(tags), tracks, self._new_cover, self._remove_cover)

    @property
    def has_unsaved_changes(self) -> bool:
        return self._meta is not None and self.current_edit() != self._baseline

    def confirm_discard(self) -> bool:
        if not self.has_unsaved_changes:
            return True
        answer = QMessageBox.question(
            self, strings.META_MODIFIED_TITLE, strings.META_MODIFIED_BODY.format(name=self._meta.path.name),
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    # ------------------------------------------------------------------
    # Salvar
    # ------------------------------------------------------------------

    def save(self) -> None:
        edit = self.current_edit()
        if edit is None or self._saving is not None or self._loading is not None:
            return
        tools = self._ensure_tools()
        if tools is None:
            return
        worker = self._runtime.metadata_writer(self._meta, edit, tools,
                                               self._runtime.download_directory(self._settings))
        self._saving = worker
        self._saved, self._cancelled = None, False
        worker.signals.finished.connect(lambda saved: self._on_saved(edit, saved), Qt.ConnectionType.QueuedConnection)
        worker.signals.failed.connect(self._on_save_failed, Qt.ConnectionType.QueuedConnection)
        self._runner.start(worker, worker.signals.done)
        self._refresh()

    def _on_saved(self, edit: MetadataEdit, saved: SavedCopy) -> None:
        self._saving = None
        self._saved = saved
        # A cópia guardou o que se pediu: não há mais o que perder ao fechar.
        self._baseline = edit
        self._refresh()

    def _on_save_failed(self, error) -> None:
        self._saving = None
        self._refresh()
        if isinstance(error, JobCancelled):
            self._cancelled = True
            self._refresh()
            return
        QMessageBox.warning(self, strings.DIALOG_WARNING_TITLE, str(error))

    def apply_settings(self, settings: Settings) -> None:
        self._settings = settings

    def shutdown(self) -> None:
        self._token += 1
        self._runner.cancel_all()
        self._pool.waitForDone(2000)

    # ------------------------------------------------------------------
    # Estado na tela
    # ------------------------------------------------------------------

    def _refresh(self, *_args) -> None:
        meta, busy = self._meta, self._saving is not None or self._loading is not None
        if self._loading is not None:
            self._info.setText(strings.META_LOADING.format(name=self._loading.name))
        elif meta is None:
            self._info.setText(strings.META_DROP_HINT)
        else:
            self._info.setText(strings.META_FILE_INFO.format(
                name=meta.path.name, format=meta.extension.upper(), duration=format_duration(meta.duration)))
        for widget in (self._tags_group, self._others_group, self._tracks_group, self._cover_group):
            widget.setEnabled(meta is not None and not busy)
        self._tracks_note.setVisible(bool(meta and meta.tags_on_stream))
        self._remove_field.setEnabled(self._others.rowCount() > 0)
        self._save.setEnabled(meta is not None and not busy)
        self._discard.setEnabled(self.has_unsaved_changes and not busy)
        self._cancel.setVisible(self._saving is not None)
        self._refresh_cover()
        self._refresh_result()

    def _update_cover_pixmap(self) -> None:
        """Decodifica e reduz a capa uma vez por troca de capa.

        Feito no ``_refresh``, que roda a cada tecla, custava 59 ms por tecla
        com uma capa de 3000×3000 (medido) — e, com capa nova, lia o arquivo
        do disco a cada vez.
        """
        pixmap = QPixmap()
        if self._new_cover is not None:
            pixmap.load(str(self._new_cover))
        elif self._cover and not self._remove_cover:
            pixmap.loadFromData(self._cover)
        self._cover_pixmap = None if pixmap.isNull() else pixmap.scaled(
            _COVER_SIZE, _COVER_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    def _refresh_cover(self) -> None:
        meta = self._meta
        accepts = bool(meta and meta.accepts_cover)
        self._change_cover.setEnabled(accepts)
        self._drop_cover.setEnabled(accepts and (bool(self._cover) or self._new_cover is not None)
                                    and not self._remove_cover)
        if self._cover_pixmap is not None:
            self._cover_view.setPixmap(self._cover_pixmap)
            return
        self._cover_view.setPixmap(QPixmap())
        if meta is not None and not accepts:
            self._cover_view.setText(strings.META_COVER_UNSUPPORTED)
        elif self._remove_cover:
            self._cover_view.setText(strings.META_COVER_REMOVED)
        else:
            self._cover_view.setText(strings.META_COVER_NONE)

    def _refresh_result(self) -> None:
        saved = self._saved
        if self._saving is not None:
            text = strings.META_SAVING
        elif self._cancelled:
            text = strings.META_CANCELLED
        elif saved is None:
            text = ""
        else:
            template = strings.META_SAVED_FALLBACK if saved.fallback_used else strings.META_SAVED
            text = template.format(name=saved.path.name)
            if saved.not_saved:
                text += "\n" + strings.META_NOT_SAVED.format(fields=", ".join(str(item) for item in saved.not_saved))
        self._result.setText(text)
        self._result.setVisible(bool(text))
        self._reveal.setVisible(saved is not None)
