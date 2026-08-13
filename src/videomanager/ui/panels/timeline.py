"""A linha do tempo da aba de edição.

Segue o que os editores de consumo (CapCut, Filmora) padronizaram, porque é o
que quem usa já sabe operar sem aprender nada: **uma trilha com os trechos que
sobraram**, um cursor que se arrasta, alças nas pontas do trecho selecionado, e
a tesoura dividindo no cursor. O que se vê é o que vai ser exportado — não há
"marca de entrada" e "marca de saída" invisíveis num formulário à parte.

É um widget pintado, e não uma composição de widgets, por dois motivos. Um
``QWidget`` por trecho tornaria o desenho da tira de miniaturas e da forma de
onda — que atravessam os trechos e são recortadas por eles — um problema de
empilhamento de camadas. E cada movimento do cursor obrigaria o Qt a recalcular
o layout, várias vezes por segundo, durante um arrasto.

**Miniaturas e onda são desenhadas pelo tempo que representam, não pela posição
em que chegaram.** Cada imagem carrega o intervalo de onde saiu; ao aproximar a
linha do tempo, a imagem antiga continua no lugar certo, esticada, até a nova
chegar. Sem isso a tira piscaria em branco a cada movimento de zoom.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...core.trimmer import (
    MIN_SEGMENT,
    Segment,
    format_timecode,
    frame_step,
    nearest_keyframe,
)

# Faixas horizontais do widget, de cima para baixo.
RULER_HEIGHT = 20
FILM_HEIGHT = 44
WAVE_HEIGHT = 20
TRACK_HEIGHT = FILM_HEIGHT + WAVE_HEIGHT
WIDGET_HEIGHT = RULER_HEIGHT + TRACK_HEIGHT + 8

# Largura de uma miniatura: 16:9 sobre a altura da tira. É o que decide quantas
# miniaturas cabem no trecho visível — e portanto quantas são geradas.
FILM_CELL_WIDTH = int(FILM_HEIGHT * 16 / 9)

# Distância, em pixels, para pegar a alça de uma ponta. Larga o suficiente para
# o ponteiro não exigir pontaria, estreita o bastante para sobrar corpo de
# trecho onde clicar quando ele está bem aproximado.
_HANDLE_GRAB = 9
_HANDLE_WIDTH = 5

# Imantação: um arrasto que passe a menos disto de um ponto notável (o cursor, a
# ponta de outro trecho, um keyframe) gruda nele. É o "magnetismo" dos editores,
# e é o que torna possível encostar dois trechos sem deixar um quadro de sobra.
_SNAP_PIXELS = 7

# Passos de régua aceitáveis, em segundos. O escolhido é o menor que ainda deixa
# espaço para o rótulo — sem isso os números se sobrepõem ao aproximar.
_RULER_STEPS = (
    0.04, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600,
)
_RULER_LABEL_SPACE = 78

# Menor janela visível: dez quadros a 25 fps. Aproximar além disso não mostra
# mais nada — o quadro é a menor unidade que existe.
_MIN_VIEW = 0.4


@dataclass
class _Strip:
    """Miniaturas geradas para um intervalo, guardadas com o intervalo."""

    start: float = 0.0
    end: float = 0.0
    count: int = 0
    images: dict[int, QImage] | None = None

    def slice_for(self, index: int) -> tuple[float, float]:
        step = (self.end - self.start) / self.count if self.count else 0.0
        begin = self.start + step * index
        return begin, begin + step


class Timeline(QWidget):
    """Trilha única com os trechos, cursor, alças e régua."""

    # O cursor foi movido pelo usuário (clique ou arrasto).
    scrubbed = Signal(float)
    # Um arrasto de alça vai começar. Existe para o painel guardar o estado
    # anterior antes de ele mudar — é o que faz o desfazer voltar para onde o
    # trecho estava, e não para um passo intermediário do arrasto.
    edit_started = Signal()
    # Um trecho mudou de tamanho — o arrasto de alça terminou.
    clips_edited = Signal()
    # A janela visível mudou: miniaturas e onda precisam ser refeitas.
    view_changed = Signal()
    selection_changed = Signal(int)

    def __init__(self, colors: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._c = colors
        self._duration = 0.0
        self._fps: float | None = None
        self._clips: list[Segment] = []
        self._position = 0.0
        self._selected = -1
        self._view_start = 0.0
        self._view_end = 1.0
        self._keyframes: tuple[float, ...] = ()
        self._show_keyframes = False
        self._strip = _Strip()
        self._wave: QImage | None = None
        self._wave_start = 0.0
        self._wave_end = 0.0

        # Arrasto em curso: "cursor", "inicio", "fim" ou "deslocar".
        self._drag = ""
        self._drag_index = -1
        self._pan_origin: QPointF | None = None
        self._pan_start = 0.0

        self.setMinimumHeight(WIDGET_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    def load(self, duration: float, fps: float | None) -> None:
        self._duration = max(0.0, duration)
        self._fps = fps
        self._clips = [Segment(0.0, self._duration)] if self._duration else []
        self._selected = 0 if self._clips else -1
        self._position = 0.0
        self._keyframes = ()
        self._strip = _Strip()
        self._wave = None
        self._view_start, self._view_end = 0.0, max(_MIN_VIEW, self._duration)
        self.update()
        self.view_changed.emit()

    @property
    def clips(self) -> tuple[Segment, ...]:
        return tuple(self._clips)

    def set_clips(self, clips: tuple[Segment, ...], *, selected: int | None = None) -> None:
        """Substitui os trechos — usado pelo desfazer e pelas ações da barra."""
        self._clips = [Segment(c.start, c.end) for c in clips]
        if selected is not None:
            self._selected = max(-1, min(selected, len(self._clips) - 1))
        elif self._selected >= len(self._clips):
            self._selected = len(self._clips) - 1
        self.update()
        self.selection_changed.emit(self._selected)

    @property
    def selected(self) -> int:
        return self._selected

    @property
    def selected_clip(self) -> Segment | None:
        if 0 <= self._selected < len(self._clips):
            return self._clips[self._selected]
        return None

    @property
    def position(self) -> float:
        return self._position

    def set_position(self, seconds: float, *, follow: bool = True) -> None:
        self._position = min(max(0.0, seconds), self._duration)
        if follow:
            self._keep_visible(self._position)
        self.update()

    def set_keyframes(self, times: tuple[float, ...]) -> None:
        self._keyframes = times
        self.update()

    def set_show_keyframes(self, show: bool) -> None:
        """Marcas de keyframe aparecem só quando importam — no modo rápido."""
        self._show_keyframes = show
        self.update()

    def set_strip(self, start: float, end: float, count: int) -> None:
        """Anuncia a tira que está sendo gerada, para as imagens irem chegando."""
        self._strip = _Strip(start, end, count, {})

    def set_strip_image(self, index: int, image: QImage) -> None:
        if self._strip.images is not None:
            self._strip.images[index] = image
            self.update()

    def set_waveform(self, image: QImage | None, start: float, end: float) -> None:
        self._wave, self._wave_start, self._wave_end = image, start, end
        self.update()

    # ------------------------------------------------------------------
    # Janela visível
    # ------------------------------------------------------------------

    @property
    def view(self) -> tuple[float, float]:
        return self._view_start, self._view_end

    @property
    def view_span(self) -> float:
        return max(1e-6, self._view_end - self._view_start)

    def set_view(self, start: float, end: float) -> None:
        span = max(_MIN_VIEW, min(end - start, max(_MIN_VIEW, self._duration)))
        start = max(0.0, min(start, max(0.0, self._duration - span)))
        self._view_start, self._view_end = start, start + span
        self.update()
        self.view_changed.emit()

    def zoom(self, factor: float, anchor: float | None = None) -> None:
        """Aproxima ou afasta mantendo ``anchor`` no mesmo ponto da tela.

        Ancorar no ponteiro (ou no cursor de reprodução) é o que faz o zoom
        parecer uma lupa em vez de um salto: o que estava sob o mouse continua
        sob o mouse.
        """
        anchor = self._position if anchor is None else anchor
        ratio = (anchor - self._view_start) / self.view_span
        span = self.view_span / factor
        self.set_view(anchor - ratio * span, anchor - ratio * span + span)

    def _keep_visible(self, seconds: float) -> None:
        """Acompanha o cursor quando ele sai pela borda, como uma esteira."""
        span = self.view_span
        if seconds < self._view_start:
            self.set_view(seconds, seconds + span)
        elif seconds > self._view_end:
            # Recua um pouco em vez de encostar na borda: reproduzindo, o cursor
            # some da vista no quadro seguinte se ele parar na ponta.
            self.set_view(seconds - span * 0.85, seconds + span * 0.15)

    # ------------------------------------------------------------------
    # Conversão tempo <-> pixel
    # ------------------------------------------------------------------

    def _x_of(self, seconds: float) -> float:
        return (seconds - self._view_start) / self.view_span * self.width()

    def _time_of(self, x: float) -> float:
        raw = self._view_start + x / max(1, self.width()) * self.view_span
        return min(max(0.0, raw), self._duration)

    def _seconds_per_pixel(self) -> float:
        return self.view_span / max(1, self.width())

    # ------------------------------------------------------------------
    # Desenho
    # ------------------------------------------------------------------

    def _color(self, key: str, alpha: int = 255) -> QColor:
        color = QColor(self._c[key])
        color.setAlpha(alpha)
        return color

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self._color("bg"))

        self._paint_ruler(painter)
        self._paint_track(painter)
        self._paint_keyframes(painter)
        self._paint_playhead(painter)
        painter.end()

    def _paint_ruler(self, painter: QPainter) -> None:
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 2))
        painter.setFont(font)

        step = next(
            (
                candidate
                for candidate in _RULER_STEPS
                if candidate / self._seconds_per_pixel() >= _RULER_LABEL_SPACE
            ),
            _RULER_STEPS[-1],
        )
        first = int(self._view_start / step) * step
        moment = first
        while moment <= self._view_end:
            x = self._x_of(moment)
            painter.setPen(QPen(self._color("border"), 1))
            painter.drawLine(int(x), RULER_HEIGHT - 5, int(x), RULER_HEIGHT)
            painter.setPen(self._color("text_dim"))
            painter.drawText(
                QRectF(x + 3, 0, _RULER_LABEL_SPACE, RULER_HEIGHT - 4),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                _ruler_label(moment, step),
            )
            moment += step

    def _track_rect(self) -> QRectF:
        return QRectF(0, RULER_HEIGHT + 4, self.width(), TRACK_HEIGHT)

    def _clip_rect(self, clip: Segment) -> QRectF:
        track = self._track_rect()
        left = self._x_of(clip.start)
        right = self._x_of(clip.end)
        return QRectF(left, track.top(), max(2.0, right - left), track.height())

    def _paint_track(self, painter: QPainter) -> None:
        track = self._track_rect()
        # Leito da trilha: mostra onde havia vídeo e agora há um vão, que é o
        # que dá sentido visual a "excluir trecho".
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color("surface_alt"))
        painter.drawRoundedRect(track, 6, 6)

        for index, clip in enumerate(self._clips):
            rect = self._clip_rect(clip)
            if rect.right() < 0 or rect.left() > self.width():
                continue
            path = QPainterPath()
            path.addRoundedRect(rect, 6, 6)
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(rect, self._color("surface"))
            self._paint_film(painter, rect)
            self._paint_wave(painter, rect)
            painter.restore()

            selected = index == self._selected
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(self._color("accent") if selected else self._color("border"),
                     2 if selected else 1)
            )
            painter.drawPath(path)
            if selected:
                self._paint_handles(painter, rect)

    def _paint_film(self, painter: QPainter, clip_rect: QRectF) -> None:
        """Desenha a tira inteira; o recorte do trecho corta o que sobra.

        Cada miniatura ocupa exatamente a faixa de tempo que representa, e não
        uma fatia igual do trecho: é isso que mantém a imagem no lugar certo
        quando o trecho é encurtado por uma alça.
        """
        images = self._strip.images
        if not images:
            return
        top = clip_rect.top()
        for index, image in images.items():
            begin, end = self._strip.slice_for(index)
            left, right = self._x_of(begin), self._x_of(end)
            if right < clip_rect.left() or left > clip_rect.right():
                continue
            painter.drawImage(
                QRectF(left, top, max(1.0, right - left), FILM_HEIGHT), image
            )

    def _paint_wave(self, painter: QPainter, clip_rect: QRectF) -> None:
        area = QRectF(
            clip_rect.left(), clip_rect.top() + FILM_HEIGHT, clip_rect.width(), WAVE_HEIGHT
        )
        painter.fillRect(area, self._color("surface_alt"))
        if self._wave is None or self._wave_end <= self._wave_start:
            return
        left, right = self._x_of(self._wave_start), self._x_of(self._wave_end)
        painter.drawImage(
            QRectF(left, area.top(), max(1.0, right - left), area.height()), self._wave
        )

    def _paint_handles(self, painter: QPainter, rect: QRectF) -> None:
        """Alças nas pontas do trecho selecionado, como nos editores de vídeo."""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color("accent"))
        for x in (rect.left(), rect.right() - _HANDLE_WIDTH):
            painter.drawRoundedRect(
                QRectF(x, rect.top(), _HANDLE_WIDTH, rect.height()), 2, 2
            )

    def _paint_keyframes(self, painter: QPainter) -> None:
        if not self._show_keyframes or not self._keyframes:
            return
        # Só quando dá para distinguir uma marca da outra: num vídeo de uma hora
        # visto por inteiro, elas formariam uma barra cinza sem informação.
        spacing_ok = self._seconds_per_pixel() * 5 < _average_gap(self._keyframes)
        if not spacing_ok:
            return
        track = self._track_rect()
        painter.setPen(QPen(self._color("warn", 150), 1))
        start = bisect.bisect_left(self._keyframes, self._view_start)
        for moment in self._keyframes[start:]:
            if moment > self._view_end:
                break
            x = int(self._x_of(moment))
            painter.drawLine(x, int(track.top()), x, int(track.top() + 6))

    def _paint_playhead(self, painter: QPainter) -> None:
        x = self._x_of(self._position)
        if x < -8 or x > self.width() + 8:
            return
        painter.setPen(QPen(self._color("error"), 2))
        painter.drawLine(QPointF(x, RULER_HEIGHT - 8), QPointF(x, self.height() - 4))
        # Cabeça arredondada em cima: é onde se pega o cursor, e o alvo precisa
        # ser maior que a linha de 2 px.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color("error"))
        painter.drawRoundedRect(QRectF(x - 6, RULER_HEIGHT - 16, 12, 11), 3, 3)

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------

    def _hit(self, x: float, y: float) -> tuple[str, int]:
        """O que está sob o ponteiro: alça, corpo de trecho ou régua."""
        if y < RULER_HEIGHT:
            return "cursor", -1
        for index, clip in enumerate(self._clips):
            rect = self._clip_rect(clip)
            if abs(x - rect.left()) <= _HANDLE_GRAB:
                return "inicio", index
            if abs(x - rect.right()) <= _HANDLE_GRAB:
                return "fim", index
            if rect.left() <= x <= rect.right():
                return "corpo", index
        return "cursor", -1

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_origin = event.position()
            self._pan_start = self._view_start
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        kind, index = self._hit(event.position().x(), event.position().y())
        if index >= 0 and index != self._selected:
            self._selected = index
            self.selection_changed.emit(index)
        if kind in ("inicio", "fim"):
            self._drag, self._drag_index = kind, index
            self.edit_started.emit()
        else:
            self._drag, self._drag_index = "cursor", -1
            self.set_position(self._time_of(event.position().x()), follow=False)
            self.scrubbed.emit(self._position)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pan_origin is not None:
            delta = (event.position().x() - self._pan_origin.x()) * self._seconds_per_pixel()
            self.set_view(self._pan_start - delta, self._pan_start - delta + self.view_span)
            return

        if not self._drag:
            kind, _ = self._hit(event.position().x(), event.position().y())
            self.setCursor(
                Qt.CursorShape.SizeHorCursor
                if kind in ("inicio", "fim")
                else Qt.CursorShape.ArrowCursor
            )
            return

        moment = self._time_of(event.position().x())
        if self._drag == "cursor":
            self.set_position(moment, follow=False)
            self.scrubbed.emit(self._position)
            return
        self._drag_edge(moment)

    def set_edge(self, index: int, edge: str, seconds: float) -> bool:
        """Move uma ponta do trecho, respeitando os vizinhos e a duração mínima.

        A regra é a mesma para o arrasto da alça e para o timecode digitado no
        formulário ao lado. Sem um lugar só para ela, um valor digitado passava
        por cima do trecho vizinho e o ffmpeg recebia dois pedaços cruzados.
        """
        if not 0 <= index < len(self._clips):
            return False
        clip = self._clips[index]
        if edge == "inicio":
            floor = self._clips[index - 1].end if index else 0.0
            value = min(max(floor, seconds), clip.end - MIN_SEGMENT)
            self._clips[index] = Segment(value, clip.end)
        else:
            ceiling = (
                self._clips[index + 1].start
                if index + 1 < len(self._clips)
                else self._duration
            )
            value = max(min(ceiling, seconds), clip.start + MIN_SEGMENT)
            self._clips[index] = Segment(clip.start, value)
        self.update()
        return True

    def _drag_edge(self, moment: float) -> None:
        self.set_edge(self._drag_index, self._drag, self._snap(moment, self._drag_index))

    def _snap(self, moment: float, index: int) -> float:
        """Imanta a pontos notáveis, o mais próximo primeiro."""
        tolerance = _SNAP_PIXELS * self._seconds_per_pixel()
        candidates = [self._position, 0.0, self._duration]
        for other, clip in enumerate(self._clips):
            if other != index:
                candidates += [clip.start, clip.end]
        if self._show_keyframes:
            # Só no modo rápido: imantar num keyframe é o que transforma um corte
            # "sem recodificar" em um corte exato, e fora desse modo o keyframe
            # não tem nenhum significado para quem está arrastando.
            keyframe = nearest_keyframe(self._keyframes, moment)
            if keyframe is not None:
                candidates.append(keyframe)
        best = min(candidates, key=lambda value: abs(value - moment))
        return best if abs(best - moment) <= tolerance else moment

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pan_origin is not None:
            self._pan_origin = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        if self._drag in ("inicio", "fim"):
            self.clips_edited.emit()
        self._drag = ""
        self._drag_index = -1

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Duplo clique num trecho enquadra o trecho — o "ajustar à seleção"."""
        _, index = self._hit(event.position().x(), event.position().y())
        if 0 <= index < len(self._clips):
            clip = self._clips[index]
            folga = max(0.2, clip.duration * 0.05)
            self.set_view(clip.start - folga, clip.end + folga)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120
        if not steps:
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            delta = -steps * self.view_span * 0.15
            self.set_view(self._view_start + delta, self._view_end + delta)
            return
        self.zoom(1.25**steps, self._time_of(event.position().x()))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Setas andam quadro a quadro — só quando a linha do tempo tem o foco.

        Deixar isto aqui, e não num atalho de janela, é o que permite digitar um
        timecode nos campos ao lado sem que cada seta mova o cursor do vídeo.
        """
        step = frame_step(self._fps)
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            step = 1.0
        if event.key() == Qt.Key.Key_Left:
            self.set_position(self._position - step)
        elif event.key() == Qt.Key.Key_Right:
            self.set_position(self._position + step)
        elif event.key() == Qt.Key.Key_Home:
            self.set_position(0.0)
        elif event.key() == Qt.Key.Key_End:
            self.set_position(self._duration)
        else:
            super().keyPressEvent(event)
            return
        self.scrubbed.emit(self._position)


def _average_gap(times: tuple[float, ...]) -> float:
    if len(times) < 2:
        return float("inf")
    return (times[-1] - times[0]) / (len(times) - 1)


def _ruler_label(seconds: float, step: float) -> str:
    # Um decimal basta abaixo de um segundo: três encheriam a régua de números
    # que ninguém lê, e o timecode completo está sempre no campo de tempo.
    label = format_timecode(seconds, milliseconds=step < 1)
    if step < 1:
        label = label[:-2]
    # A hora sai do rótulo enquanto for zero: é a maior parte da régua de um
    # arquivo comum, e repetir "0:" em cada marca só ocupa espaço.
    return label[2:] if label.startswith("0:") else label


def image_from_frame(data: bytes, width: int, height: int) -> QImage:
    """Converte um quadro rgb24 do ffmpeg em ``QImage``.

    A cópia é obrigatória: ``QImage`` construído sobre um buffer não assume a
    posse dele, e o ``bytes`` do sinal é liberado assim que o slot retorna —
    deixando a imagem apontando para memória já devolvida.
    """
    image = QImage(data, width, height, width * 3, QImage.Format.Format_RGB888)
    return image.copy()


def pixmap_from_frame(data: bytes, width: int, height: int) -> QPixmap:
    return QPixmap.fromImage(image_from_frame(data, width, height))
