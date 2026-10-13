"""Aviso flutuante: uma confirmação ou um erro passageiro, sobre a janela, que some sozinho.

A barra de status dava a única resposta a certos gestos (clicar em "Adicionar à fila" com a fila
escondida no editor, uma falha ao gravar as preferências), e a renovação visual a tira. O aviso
é o que a substitui: aparece embaixo, no centro, empilha quando há mais de um, some em alguns
segundos (ou fica, se pedirem) e se anuncia a quem usa leitor de tela.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QSize, QTimer, Signal
from PySide6.QtGui import QAccessible, QAccessibleEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from videomanager.presentation.qt import icons, strings, theme

DURACAO_PADRAO_MS = 5000
_MARGEM_INFERIOR = 28
_ESPACO = 8
_LARGURA_MAXIMA = 560


class _Aviso(QFrame):
    fechado = Signal(object)

    def __init__(self, texto: str, tipo: str, acao: tuple[str, Callable[[], None]] | None, ms: int,
                 parent: QWidget) -> None:
        super().__init__(parent)
        self.setProperty("role", "toast")
        self.setProperty("tipo", tipo)
        self.setAccessibleName(texto)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(14, 10, 8, 10)
        linha.setSpacing(10)
        cores = theme.papeis(*theme.atual())
        icone = QLabel()
        desenho = icons.warn if tipo == "error" else icons.check
        icone.setPixmap(desenho(cores["err" if tipo == "error" else "ok"]).pixmap(QSize(18, 18)))
        linha.addWidget(icone)
        self.mensagem = QLabel(texto)
        self.mensagem.setWordWrap(True)
        # Um QLabel com quebra de linha pede, por padrão, uma largura estreita: o texto curto quebrava em
        # três linhas com a janela inteira livre. A largura é a do texto, até o máximo; só o longo quebra.
        # ``ensurePolished`` antes de medir: sem ele a fonte ainda é a de antes do estilo, menor que a real.
        self.mensagem.ensurePolished()
        self.mensagem.setFixedWidth(min(self.mensagem.fontMetrics().horizontalAdvance(texto) + 10, _LARGURA_MAXIMA - 140))
        linha.addWidget(self.mensagem, 1)
        self.acao: QPushButton | None = None
        if acao is not None:
            rotulo, chamada = acao
            self.acao = QPushButton(rotulo)
            self.acao.setProperty("role", "toast-action")
            self.acao.clicked.connect(lambda: (chamada(), self.fechar()))
            linha.addWidget(self.acao)
        self.botao_fechar = QPushButton()
        self.botao_fechar.setProperty("role", "toast-close")
        self.botao_fechar.setIcon(icons.close(cores["t2"]))
        self.botao_fechar.setIconSize(QSize(14, 14))
        self.botao_fechar.setToolTip(strings.TOAST_CLOSE)
        self.botao_fechar.clicked.connect(self.fechar)
        linha.addWidget(self.botao_fechar)
        self._temporizador: QTimer | None = None
        if ms > 0:
            self._temporizador = QTimer(self)
            self._temporizador.setSingleShot(True)
            self._temporizador.timeout.connect(self.fechar)
            self._temporizador.start(ms)

    def fechar(self) -> None:
        if self._temporizador is not None:
            self._temporizador.stop()
        self.hide()
        self.fechado.emit(self)
        self.deleteLater()


class ToastHost(QObject):
    """Mostra avisos sobre ``janela`` e os empilha de baixo para cima, centralizados."""

    def __init__(self, janela: QWidget) -> None:
        super().__init__(janela)
        self._janela = janela
        self._ativos: list[_Aviso] = []
        janela.installEventFilter(self)

    @property
    def ativos(self) -> list[_Aviso]:
        return list(self._ativos)

    def mostrar(self, texto: str, tipo: str = "ok", acao: tuple[str, Callable[[], None]] | None = None,
                ms: int = DURACAO_PADRAO_MS) -> _Aviso:
        """``tipo`` é ``"ok"`` ou ``"error"``; ``ms <= 0`` deixa o aviso até ser fechado."""
        aviso = _Aviso(texto, tipo, acao, ms, self._janela)
        aviso.fechado.connect(self._retirar)
        self._ativos.append(aviso)
        aviso.show()
        aviso.raise_()
        self._reposicionar()
        # Quem usa leitor de tela precisa ouvir a resposta ao gesto, que não tem outra marca na tela.
        QAccessible.updateAccessibility(QAccessibleEvent(aviso, QAccessible.Event.Alert))
        return aviso

    def _retirar(self, aviso: _Aviso) -> None:
        if aviso in self._ativos:
            self._ativos.remove(aviso)
        self._reposicionar()

    def _reposicionar(self) -> None:
        y = self._janela.height() - _MARGEM_INFERIOR
        for aviso in reversed(self._ativos):
            aviso.setMaximumWidth(_LARGURA_MAXIMA)
            aviso.adjustSize()
            y -= aviso.height()
            aviso.move((self._janela.width() - aviso.width()) // 2, y)
            y -= _ESPACO

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._janela and event.type() == QEvent.Type.Resize:
            self._reposicionar()
        return False
