"""Prévia em tela cheia, com a barra de controles que some sozinha.

**Esta janela não reproduz nada.** Ela é uma superfície de exibição e um punhado
de controles: quem decodifica, conta o tempo e toca o som continua sendo a aba de
edição (ver ``panels/edit_panel.py``). O que muda ao entrar em tela cheia é para
onde os quadros vão e em que tamanho são pedidos — nada do relógio nem do fluxo
de áudio se duplica aqui, que é o que evita as duas telas discordarem sobre onde
a reprodução está.

**A barra some por inatividade, e não por tempo.** O contador reinicia a cada
movimento do mouse e não corre enquanto o ponteiro está sobre a barra ou
arrastando o cursor de posição — uma barra que desaparece debaixo do dedo é pior
que uma barra que nunca some. O ponteiro some junto com ela: numa imagem em tela
cheia, uma seta parada no meio do vídeo é a única coisa que denuncia que aquilo é
um programa.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QFontDatabase, QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..core.trimmer import format_timecode
from . import strings

# Inatividade até a barra sumir. Curto o bastante para a imagem ficar limpa
# depressa, longo o bastante para dar tempo de mirar um botão.
_IDLE_MS = 2500
_FADE_MS = 260

# Altura da faixa de controles e afastamento das bordas da tela.
_BAR_HEIGHT = 64
_BAR_MARGIN = 28
_BUTTON_WIDTH = 64


class _SeekBar(QSlider):
    """Barra de posição que salta para onde foi clicada.

    O comportamento padrão do Qt é avançar uma "página" por clique, que num
    vídeo de uma hora move alguns minutos e nunca leva aonde se apontou —
    ninguém espera isso de um player.
    """

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.width():
            fraction = min(max(0.0, event.position().x() / self.width()), 1.0)
            self.setValue(round(self.minimum() + fraction * (self.maximum() - self.minimum())))
            self.sliderMoved.emit(self.value())
            event.accept()
            return
        super().mousePressEvent(event)


class FullscreenPreview(QWidget):
    """Janela de tela cheia com a imagem e os controles essenciais."""

    play_toggled = Signal()
    seeked = Signal(float)  # segundos
    # O arrasto da barra de posição terminou. Existe para a reprodução voltar
    # ao fim do arrasto, e não a cada movimento do mouse — que seria reiniciar
    # o som e o fluxo de quadros dezenas de vezes por segundo.
    seek_finished = Signal()
    stepped = Signal(int)  # quadros, -1 ou +1
    volume_changed = Signal(int)
    mute_toggled = Signal(bool)
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        # Janela de verdade, mas filha do painel: assim ela é destruída junto
        # com ele e não segura a aplicação aberta depois de a janela principal
        # fechar.
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(strings.EDIT_FULLSCREEN_TITLE)
        self.setStyleSheet("background: #000000;")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._image = QLabel()
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setMouseTracking(True)
        self._image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout.addWidget(self._image)

        self._bar = self._build_bar()
        self._effect = QGraphicsOpacityEffect(self._bar)
        self._bar.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(_FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade.finished.connect(self._on_fade_finished)

        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(_IDLE_MS)
        self._idle.timeout.connect(self._hide_bar)

        # Duração para a qual a largura dos relógios já foi calculada.
        self._locked = -1.0

    # ------------------------------------------------------------------
    # Montagem
    # ------------------------------------------------------------------

    def _build_bar(self) -> QWidget:
        bar = QWidget(self)
        bar.setObjectName("fullscreenBar")
        # Fundo próprio, translúcido: a barra fica sobre a imagem, e sem ele os
        # rótulos claros somem num quadro claro.
        bar.setStyleSheet(
            "#fullscreenBar { background: rgba(18, 20, 25, 0.86);"
            " border-radius: 10px; }"
            " QLabel { background: transparent; color: #e6e8ec; }"
        )
        bar.setMouseTracking(True)

        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)

        # Largura folgada: o QSS reserva 14 px de recuo de cada lado, e com
        # menos que isto o "|" dos botões de quadro fica de fora do desenho.
        self._play = QPushButton("▶")
        self._play.setFixedWidth(_BUTTON_WIDTH)
        self._play.clicked.connect(self.play_toggled)
        row.addWidget(self._play)

        for glyph, step, tip in (
            ("◀|", -1, strings.EDIT_PREV_FRAME),
            ("|▶", +1, strings.EDIT_NEXT_FRAME),
        ):
            button = QPushButton(glyph)
            button.setFixedWidth(_BUTTON_WIDTH)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, s=step: self.stepped.emit(s))
            row.addWidget(button)

        # Mesmo tratamento dos números da aba: fonte monoespaçada e largura
        # travada em set_state(), senão o tempo corrente empurraria a barra de
        # posição para os lados a cada quadro.
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._elapsed = QLabel(format_timecode(0))
        self._elapsed.setFont(mono)
        row.addWidget(self._elapsed)

        self._seek = _SeekBar(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 0)
        self._seek.sliderMoved.connect(lambda ms: self.seeked.emit(ms / 1000))
        self._seek.sliderReleased.connect(self.seek_finished)
        row.addWidget(self._seek, 1)

        self._total = QLabel(format_timecode(0))
        self._total.setFont(mono)
        row.addWidget(self._total)

        self._mute = QPushButton(strings.EDIT_SOUND)
        self._mute.setCheckable(True)
        self._mute.setFixedWidth(46)
        self._mute.toggled.connect(self._on_mute)
        row.addWidget(self._mute)

        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.setFixedWidth(110)
        self._volume.setToolTip(strings.EDIT_VOLUME)
        self._volume.valueChanged.connect(self.volume_changed)
        row.addWidget(self._volume)

        leave = QPushButton(strings.EDIT_EXIT_FULLSCREEN)
        leave.setToolTip(strings.EDIT_EXIT_FULLSCREEN_TIP)
        leave.clicked.connect(self.close)
        row.addWidget(leave)
        return bar

    # ------------------------------------------------------------------
    # Estado vindo do painel
    # ------------------------------------------------------------------

    def set_frame(self, pixmap: QPixmap) -> None:
        """Mostra o quadro, ajustando só o que não couber.

        Os quadros chegam já no tamanho da tela (ver
        ``EditPanel._preview_size``), então normalmente não há nada a fazer aqui:
        ampliar um quadro menor deixaria a imagem borrada, que se lê como perda
        de qualidade do vídeo e não como escolha da prévia. O ajuste continua
        para o intervalo entre trocar de tamanho e o quadro novo chegar.
        """
        area = self._image.size()
        if pixmap.width() != area.width() and pixmap.height() != area.height():
            pixmap = pixmap.scaled(
                area,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._image.setPixmap(pixmap)

    def set_state(self, position: float, duration: float, playing: bool) -> None:
        if duration != self._locked:
            self._lock_readouts(duration)
        self._play.setText("❚❚" if playing else "▶")
        self._play.setToolTip(
            strings.EDIT_PAUSE if playing else strings.EDIT_PLAY
        )
        self._elapsed.setText(format_timecode(position))
        self._total.setText(format_timecode(duration))
        # Não mexe na barra enquanto o usuário a está arrastando: seria puxá-la
        # de volta a cada quadro que chega.
        if not self._seek.isSliderDown():
            self._seek.setRange(0, max(0, int(duration * 1000)))
            self._seek.setValue(int(position * 1000))

    def _lock_readouts(self, duration: float) -> None:
        """Trava a largura dos dois relógios pelo maior valor deste arquivo."""
        self._locked = duration
        width = (
            QFontMetrics(self._elapsed.font()).horizontalAdvance(
                format_timecode(duration)
            )
            + 6
        )
        for label in (self._elapsed, self._total):
            label.setFixedWidth(width)

    def set_audio(self, available: bool, volume: int, muted: bool) -> None:
        for widget in (self._mute, self._volume):
            widget.setEnabled(available)
        self._volume.blockSignals(True)
        self._volume.setValue(volume)
        self._volume.blockSignals(False)
        self._mute.blockSignals(True)
        self._mute.setChecked(muted)
        self._mute.blockSignals(False)
        self._refresh_mute()

    def _on_mute(self, muted: bool) -> None:
        self._refresh_mute()
        self.mute_toggled.emit(muted)

    def _refresh_mute(self) -> None:
        silent = self._mute.isChecked() or self._volume.value() == 0
        self._mute.setText(strings.EDIT_MUTED if silent else strings.EDIT_SOUND)

    # ------------------------------------------------------------------
    # Barra que some
    # ------------------------------------------------------------------

    def _place_bar(self) -> None:
        self._bar.setGeometry(
            _BAR_MARGIN,
            self.height() - _BAR_HEIGHT - _BAR_MARGIN,
            max(320, self.width() - 2 * _BAR_MARGIN),
            _BAR_HEIGHT,
        )
        self._bar.raise_()

    def _show_bar(self) -> None:
        if not self._bar.isVisible():
            self._bar.setVisible(True)
        self._fade.stop()
        self._fade.setEndValue(1.0)
        self._fade.start()
        self.unsetCursor()
        self._idle.start()

    def _hide_bar(self) -> None:
        # Some tudo menos o que está sendo usado: com o ponteiro sobre a barra,
        # ou com a posição sendo arrastada, o contador simplesmente recomeça.
        if self._bar.underMouse() or self._seek.isSliderDown():
            self._idle.start()
            return
        self._fade.stop()
        self._fade.setEndValue(0.0)
        self._fade.start()
        self.setCursor(Qt.CursorShape.BlankCursor)

    def _on_fade_finished(self) -> None:
        if self._fade.endValue() == 0.0:
            self._bar.setVisible(False)

    # ------------------------------------------------------------------
    # Eventos
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_bar()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._show_bar()
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.close()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Teclas do player. As mesmas da aba, para não haver o que reaprender."""
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_F, Qt.Key.Key_F11):
            self.close()
        elif key == Qt.Key.Key_Space:
            self.play_toggled.emit()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Comma):
            self.stepped.emit(-1)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Period):
            self.stepped.emit(+1)
        elif key == Qt.Key.Key_Up:
            self._volume.setValue(self._volume.value() + 5)
        elif key == Qt.Key.Key_Down:
            self._volume.setValue(self._volume.value() - 5)
        else:
            super().keyPressEvent(event)
            return
        # Qualquer tecla também traz a barra de volta: é a confirmação visual de
        # que o comando foi recebido.
        self._show_bar()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._place_bar()
        self._effect.setOpacity(1.0)
        self._bar.setVisible(True)
        self._idle.start()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._idle.stop()
        self.unsetCursor()
        self.closed.emit()
        super().closeEvent(event)
