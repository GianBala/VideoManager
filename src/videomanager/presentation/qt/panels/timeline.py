"""A linha do tempo multipista da aba de edição.

Segue o que os editores de consumo (CapCut, Filmora) padronizaram, porque é o
que quem vai usar já sabe operar: **trilhas empilhadas**, blocos que se arrastam
no tempo e entre trilhas, alças nas pontas, tesoura no cursor, cabeçalho de
trilha com o botão de mudo. O que está nas trilhas é o que vai ser exportado.

**O widget não é dono de nada.** O projeto vive no painel, imutável, e aqui só se
desenha e se avisa a intenção: "este bloco foi solto naquela trilha, naquele
instante". Quem aplica é o painel, que devolve o projeto novo para ser
desenhado. É o que faz o desfazer funcionar sem o widget guardar histórico, e o
que impede a tela e o modelo de discordarem sobre onde um bloco está.

É pintado à mão, e não montado com um widget por bloco: um ``QWidget`` por bloco
tornaria as miniaturas — que são recortadas pelas bordas do bloco — um problema
de empilhamento de camadas, e cada movimento do cursor obrigaria o Qt a refazer
o layout várias vezes por segundo durante um arrasto.

**Miniaturas e onda são desenhadas pelo tempo de origem que representam.** Ao
encurtar um bloco pela alça, a imagem que sobra continua sendo a do trecho
certo, em vez de se esticar para preencher o novo tamanho.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QHelpEvent,
    QImage,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QWheelEvent,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from videomanager.domain.project import Clip
from videomanager.domain.project import Project
from videomanager.domain.project import TrackKind
from videomanager.domain.project import accepts
from videomanager.domain.constants import MIN_SEGMENT
from videomanager.domain.timing import format_timecode
from videomanager.domain.timing import frame_step
from videomanager.presentation.qt import strings

# Faixas do widget.
RULER_HEIGHT = 20
HEADER_WIDTH = 148
VIDEO_TRACK_HEIGHT = 58
AUDIO_TRACK_HEIGHT = 42
TRACK_GAP = 4

# Miniatura de bloco de vídeo: 16:9 sobre a altura útil da trilha.
FILM_CELL_WIDTH = int((VIDEO_TRACK_HEIGHT - 14) * 16 / 9)

_HANDLE_GRAB = 8
_HANDLE_WIDTH = 5
# O marcador é um controle do corte, não uma representação em escala pura.
# Mesmo uma transição muito curta precisa continuar fácil de selecionar, como
# o ícone entre clipes do CapCut. A duração real segue sendo dada pela régua;
# só a área interativa recebe este piso visual.
_TRANSITION_MIN_WIDTH = 36
_SNAP_PIXELS = 7
_MIN_VIEW = 0.4


def _image_preview(image: QImage, target: QRectF) -> tuple[QImage, QRectF]:
    """Prepara uma imagem para preencher a área sem deformá-la.

    Blocos de imagem podem durar vários minutos e, por isso, o retângulo do
    bloco costuma ser muito mais largo que a proporção da fotografia. Passar
    esse retângulo diretamente a ``drawImage`` comprime a fotografia até virar
    uma faixa colorida. O modo *keep* mantém a proporção e limita a imagem à
    altura da trilha, evitando que logos cresçam em blocos longos.
    """
    width = max(1, round(target.width()))
    height = max(1, round(target.height()))
    scaled = image.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    rect = QRectF(
        target.left() + (target.width() - scaled.width()) / 2,
        target.top() + (target.height() - scaled.height()) / 2,
        scaled.width(),
        scaled.height(),
    )
    return scaled, rect

# Quanto o ponteiro precisa andar para um clique virar arrasto. Sem essa folga,
# selecionar um bloco já contava como edição: cada clique empilhava um desfazer
# que não desfazia nada, e o Ctrl+Z passava a exigir uma dúzia de repetições
# para voltar uma alteração de verdade. Também evita mover um bloco um quadro
# sem querer, pelo tremor da mão no clique.
_DRAG_SLACK = 4

# Altura mínima do widget: régua, uma trilha de vídeo e uma de áudio inteiras.
_FLOOR_HEIGHT = RULER_HEIGHT + VIDEO_TRACK_HEIGHT + AUDIO_TRACK_HEIGHT + 20

# Até onde se pode afastar **além** do fim da edição. Parar em "cabe tudo" deixa
# a linha do tempo sem vazio nenhum depois do último bloco — e é justamente
# nesse vazio que se solta um bloco para o fim, ou que se olha uma montagem
# curta sem ela ocupar a largura inteira da tela.
_MAX_VIEW_FACTOR = 4.0
_MAX_VIEW_MARGIN = 30.0
# Janela de uma linha do tempo ainda vazia: sem conteúdo não há o que enquadrar,
# e meio segundo de régua não ajudaria a soltar o primeiro arquivo.
_EMPTY_VIEW = 30.0
# Quanto do conteúdo tem de continuar à vista ao deslocar para o vazio final.
# Sem esse mínimo, dava para rolar até um lugar onde não há nada e nada explica
# como voltar.
_KEEP_VISIBLE = 0.25

_RULER_STEPS = (
    0.04, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600,
)
_RULER_LABEL_SPACE = 78


@dataclass
class _Strip:
    """Imagens de um bloco, guardadas pelo **instante da origem** que mostram.

    A chave é o instante, e não a posição na tira, porque a posição muda de
    significado a cada zoom: aproximar reduz o trecho visível e o número de
    miniaturas, e a imagem que era "a terceira de doze" passa a ser desenhada
    onde agora está "a terceira de seis" — outro momento do vídeo. Enquanto a
    chave era o índice, dar zoom mostrava as imagens antigas nos lugares
    errados até as novas chegarem, e as que sobravam de uma tira mais longa
    eram desenhadas fora do trecho.

    Pelo instante, uma imagem já gerada continua certa onde quer que o zoom a
    coloque, e o que muda é só a largura da célula em volta dela.
    """

    in_point: float = 0.0
    out_point: float = 0.0
    count: int = 0
    thumbs: dict[float, QImage] = field(default_factory=dict)
    wave: QImage | None = None

    def matches(self, in_point: float, out_point: float) -> bool:
        """Se a tira ainda corresponde ao trecho de origem do bloco."""
        return (
            abs(self.in_point - in_point) < 1e-6
            and abs(self.out_point - out_point) < 1e-6
        )

    @property
    def span(self) -> float:
        """Largura, em segundos de origem, da célula de cada miniatura."""
        return (self.out_point - self.in_point) / self.count if self.count else 0.0

    def _inherit(self, antigas: dict[float, QImage]) -> dict[float, QImage]:
        """Aproveita da tira anterior **uma imagem por célula**: a mais central.

        Guardar todas faria o dicionário crescer a cada zoom — ir e voltar duas
        vezes já dobrava o número de imagens vivas, sem nada aparecer a mais na
        tela, já que as células novas cobrem a mesma faixa.

        A mais próxima do centro é a melhor aproximação disponível para aquela
        célula até a imagem definitiva chegar, e é o que faz o zoom parecer
        contínuo em vez de piscar.
        """
        if not antigas or self.count <= 0:
            return {}
        herdadas: dict[float, QImage] = {}
        for index in range(self.count):
            centro = self.in_point + self.span * (index + 0.5)
            perto = min(antigas, key=lambda m: abs(m - centro))
            if abs(perto - centro) <= self.span:
                herdadas[perto] = antigas[perto]
        return herdadas

    def cell_of(self, moment: float) -> tuple[float, float]:
        """O trecho que a imagem daquele instante ocupa.

        O instante é o **meio** da célula: é assim que ``filmstrip_times`` os
        escolhe, e é o que faz uma imagem gerada noutro zoom continuar centrada
        onde deve.
        """
        metade = self.span / 2
        return moment - metade, moment + metade


class Timeline(QWidget):
    """Trilhas, blocos, cursor e régua."""

    scrubbed = Signal(float)
    # Uma alteração vai começar: o painel guarda o estado para o desfazer.
    edit_started = Signal()
    # Intenções, aplicadas pelo painel sobre o projeto imutável.
    clip_moved = Signal(int, int, float)  # clip_id, índice da trilha, início
    clip_resized = Signal(int, str, float)  # clip_id, ponta, instante
    edit_finished = Signal()
    clip_selected = Signal(int)
    track_mute_clicked = Signal(int)
    track_visibility_clicked = Signal(int)
    track_reordered = Signal(int, int)  # índice de origem, índice de destino
    view_changed = Signal()
    # Botão direito: o widget diz **onde** foi clicado e o painel monta o menu.
    # As ações são dele (é ele quem tem o projeto e o histórico), e assim o menu
    # e os atalhos de teclado partem do mesmo lugar.
    menu_requested = Signal(str, int, int, object)  # espécie, trilha, clip, posição

    def __init__(self, colors: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._c = colors
        self._project = Project()
        self._position = 0.0
        self._selected = -1
        self._view_start = 0.0
        self._view_end = _EMPTY_VIEW
        self._strips: dict[int, _Strip] = {}

        self._drag = ""
        self._drag_clip = -1
        self._drag_track = -1
        self._drop_track_target = -1
        self._grab_offset = 0.0
        self._drag_edge_origin = 0.0
        # Onde o botão foi apertado, e se o arrasto já passou da folga: até lá
        # nada é alterado no projeto (ver :data:`_DRAG_SLACK`).
        self._press_at: QPointF | None = None
        self._dragging = False
        self._pan_origin: QPointF | None = None
        self._pan_start = 0.0

        self.setMinimumHeight(_FLOOR_HEIGHT)
        # **Cresce até o fim da área**, em vez de parar onde as trilhas acabam.
        # Com altura fixa, o vazio abaixo da última trilha não pertencia a este
        # widget: era do painel, e o clique com o botão direito ali não chegava
        # aqui — o menu de criar trilha só aparecia em cima das trilhas, que é
        # justamente onde ele serve menos. Medido numa janela de 1200 px: 488 px
        # da área de trilhas ficavam mortos.
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    def set_project(self, project: Project, *, refit: bool = False) -> None:
        self._project = project
        # O cursor não pode ficar além do fim: apagar um bloco ou desfazer
        # encurta a edição, e um cursor solto lá fora pede quadros que não
        # existem e mostra um tempo que não é mais possível.
        self._position = min(self._position, max(0.0, project.duration))
        if refit:
            self.fit()
        # Imagens de blocos que não existem mais saem da memória junto com eles.
        alive = {clip.clip_id for clip in project.clips}
        self._strips = {k: v for k, v in self._strips.items() if k in alive}
        # Piso, e não altura fixa: com muitas trilhas é ele que faz a área de
        # rolagem rolar, e com poucas o widget se estica até o fim da área — o
        # que mantém o vazio abaixo das trilhas clicável.
        self.setMinimumHeight(self._needed_height())
        self.update()

    def _needed_height(self) -> int:
        total = RULER_HEIGHT + 6
        for track in self._project.tracks:
            total += self._track_height(track.kind) + TRACK_GAP
        # O piso é a constante, e **não** ``self.minimumHeight()``: lendo a
        # altura corrente, cada chamada partiria da anterior e a linha do tempo
        # nunca encolheria ao se excluir uma trilha.
        return max(_FLOOR_HEIGHT, total + 4)

    @staticmethod
    def _track_height(kind: TrackKind) -> int:
        return VIDEO_TRACK_HEIGHT if kind in (TrackKind.VIDEO, TrackKind.ADDITIONAL) else AUDIO_TRACK_HEIGHT

    @property
    def project(self) -> Project:
        return self._project

    @property
    def selected(self) -> int:
        return self._selected

    @property
    def selected_clip(self) -> Clip | None:
        found = self._project.find(self._selected)
        return found[1] if found else None

    def select(self, clip_id: int) -> None:
        if clip_id != self._selected:
            self._selected = clip_id
            self.clip_selected.emit(clip_id)
            self.update()

    @property
    def position(self) -> float:
        return self._position

    def set_position(self, seconds: float, *, follow: bool = True) -> None:
        self._position = min(max(0.0, seconds), max(0.0, self._project.duration))
        if follow:
            self._keep_visible(self._position)
        self.update()

    def set_strip(self, clip_id: int, in_point: float, out_point: float, count: int) -> None:
        # As imagens anteriores ficam até as novas chegarem: apagá-las aqui
        # faria o bloco piscar em branco a cada mudança de zoom.
        antiga = self._strips.get(clip_id)
        nova = _Strip(in_point, out_point, count, wave=antiga.wave if antiga else None)
        if antiga is not None:
            nova.thumbs = nova._inherit(antiga.thumbs)
        self._strips[clip_id] = nova

    def strip_count(self, clip_id: int) -> int:
        """Quantas miniaturas o bloco tem pedidas — zero se ainda não tem tira."""
        strip = self._strips.get(clip_id)
        return strip.count if strip else 0

    def strip_range(self, clip_id: int) -> tuple[float, float] | None:
        strip = self._strips.get(clip_id)
        return (strip.in_point, strip.out_point) if strip else None

    def set_thumb(self, clip_id: int, moment: float, image: QImage) -> None:
        """Guarda a imagem pelo instante da origem que ela mostra.

        A imagem definitiva de uma célula desaloja a aproximação herdada do zoom
        anterior. Sem isso as duas conviveriam com células sobrepostas, e a mais
        tardia — que pode ser a velha — ficaria por cima da certa.
        """
        strip = self._strips.get(clip_id)
        if strip is None:
            return
        metade = strip.span / 2
        for antigo in [
            m for m in strip.thumbs if m != moment and abs(m - moment) < metade
        ]:
            del strip.thumbs[antigo]
        strip.thumbs[moment] = image
        self.update()

    def set_wave(self, clip_id: int, in_point: float, out_point: float, image: QImage) -> None:
        strip = self._strips.setdefault(clip_id, _Strip(in_point, out_point, 0, {}))
        strip.in_point, strip.out_point, strip.wave = in_point, out_point, image
        self.update()

    def has_strip(self, clip_id: int) -> bool:
        return clip_id in self._strips

    # ------------------------------------------------------------------
    # Janela visível
    # ------------------------------------------------------------------

    @property
    def view(self) -> tuple[float, float]:
        return self._view_start, self._view_end

    @property
    def view_span(self) -> float:
        return max(1e-6, self._view_end - self._view_start)

    @property
    def _lane_width(self) -> int:
        return max(1, self.width() - HEADER_WIDTH)

    @property
    def _max_span(self) -> float:
        """Maior janela possível — bem além do fim da edição, de propósito."""
        duration = self._project.duration
        if duration <= 0:
            return _EMPTY_VIEW
        return max(duration * _MAX_VIEW_FACTOR, duration + _MAX_VIEW_MARGIN)

    def max_view_start(self, span: float) -> float:
        """Começo mais à direita que uma janela deste tamanho pode ter.

        O começo pode passar do fim da edição, mas nunca ao ponto de sumir com o
        conteúdo: sempre sobra um pedaço dele na tela para voltar. É nesse vazio
        à direita que se solta um bloco para o fim.

        Fica exposto porque a barra de navegação precisa do **mesmo** limite: com
        um teto próprio, ela parava antes de onde a roda do mouse chegava, e o
        pedaço da direita ficava sem como alcançar por ela.
        """
        return max(0.0, self._project.duration - span * _KEEP_VISIBLE)

    def set_view(self, start: float, end: float) -> None:
        span = max(_MIN_VIEW, min(end - start, self._max_span))
        ceiling = self.max_view_start(span)
        self._view_start = max(0.0, min(start, ceiling))
        self._view_end = self._view_start + span
        self.update()
        self.view_changed.emit()

    def fit(self) -> None:
        """Enquadra a edição inteira — ou uma janela útil, se ainda não há nada.

        Com conteúdo, é a duração exata: "ver tudo" que sobrasse vazio dos lados
        mostraria menos do que se pediu.
        """
        duration = self._project.duration
        self.set_view(0.0, duration if duration > 0 else _EMPTY_VIEW)

    def zoom(self, factor: float, anchor: float | None = None) -> None:
        anchor = self._position if anchor is None else anchor
        ratio = (anchor - self._view_start) / self.view_span
        span = self.view_span / factor
        self.set_view(anchor - ratio * span, anchor - ratio * span + span)

    def _keep_visible(self, seconds: float) -> None:
        span = self.view_span
        if seconds < self._view_start:
            self.set_view(seconds, seconds + span)
        elif seconds > self._view_end:
            self.set_view(seconds - span * 0.85, seconds + span * 0.15)

    # ------------------------------------------------------------------
    # Conversão tempo <-> pixel
    # ------------------------------------------------------------------

    def _x_of(self, seconds: float) -> float:
        return HEADER_WIDTH + (seconds - self._view_start) / self.view_span * self._lane_width

    def _time_of(self, x: float) -> float:
        raw = self._view_start + (x - HEADER_WIDTH) / self._lane_width * self.view_span
        return max(0.0, raw)

    def _seconds_per_pixel(self) -> float:
        return self.view_span / self._lane_width

    # ------------------------------------------------------------------
    # Geometria das trilhas
    # ------------------------------------------------------------------

    def _lane_rect(self, index: int) -> QRectF:
        top = RULER_HEIGHT + 6
        for position, track in enumerate(self._project.tracks):
            height = self._track_height(track.kind)
            if position == index:
                return QRectF(HEADER_WIDTH, top, self._lane_width, height)
            top += height + TRACK_GAP
        return QRectF()

    def _header_rect(self, index: int) -> QRectF:
        lane = self._lane_rect(index)
        return QRectF(0, lane.top(), HEADER_WIDTH - 6, lane.height())

    def _track_at(self, y: float) -> int:
        top = RULER_HEIGHT + 6
        for index, track in enumerate(self._project.tracks):
            height = self._track_height(track.kind)
            if top <= y < top + height + TRACK_GAP:
                return index
            top += height + TRACK_GAP
        return -1

    def _clip_rect(self, index: int, clip: Clip) -> QRectF:
        lane = self._lane_rect(index)
        left, right = self._x_of(clip.start), self._x_of(clip.end)
        if clip.is_transition and right - left < _TRANSITION_MIN_WIDTH:
            center = (left + right) / 2.0
            left = center - _TRANSITION_MIN_WIDTH / 2.0
            right = center + _TRANSITION_MIN_WIDTH / 2.0
        return QRectF(left, lane.top(), max(3.0, right - left), lane.height())

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
        for index, track in enumerate(self._project.tracks):
            self._paint_header(painter, index, track)
            self._paint_lane(painter, index, track)
        if (
            self._drag == "cabecalho"
            and self._dragging
            and 0 <= self._drop_track_target < len(self._project.tracks)
            and self._drop_track_target != self._drag_track
        ):
            self._paint_track_drop_indicator(painter)
        self._paint_playhead(painter)
        painter.end()

    def _paint_ruler(self, painter: QPainter) -> None:
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 2))
        painter.setFont(font)
        step = next(
            (s for s in _RULER_STEPS if s / self._seconds_per_pixel() >= _RULER_LABEL_SPACE),
            _RULER_STEPS[-1],
        )
        painter.setClipRect(QRectF(HEADER_WIDTH, 0, self._lane_width, RULER_HEIGHT))
        moment = int(self._view_start / step) * step
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
        painter.setClipping(False)

    def _paint_header(self, painter: QPainter, index: int, track) -> None:
        rect = self._header_rect(index)
        is_dragged = (
            self._drag == "cabecalho"
            and self._dragging
            and self._drag_track == index
        )
        if is_dragged:
            painter.setPen(QPen(self._color("accent"), 1.5))
            painter.setBrush(self._color("accent", 40))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color("surface"))
        painter.drawRoundedRect(rect, 5, 5)

        font = QFont(self.font())
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1.5))
        painter.setFont(font)
        painter.setPen(
            self._color("accent_text") if is_dragged else self._color("text_dim")
        )
        right_margin = -28
        if track.kind is TrackKind.VIDEO:
            right_margin = -54
        painter.drawText(
            rect.adjusted(10, 0, right_margin, 0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            track.name,
        )

        # Botão de visibilidade (olho): para vídeo e adicionais
        if track.kind in (TrackKind.VIDEO, TrackKind.ADDITIONAL):
            box = self._eye_rect(index)
            painter.setBrush(self._color("surface_alt") if track.visible else QColor("#1a1b24"))
            painter.setPen(QPen(self._color("border"), 1))
            painter.drawRoundedRect(box, 4, 4)
            self._paint_eye_icon(painter, box, track.visible)

        # Botão de mudo: para vídeo e áudio
        if track.kind in (TrackKind.VIDEO, TrackKind.AUDIO):
            box = self._mute_rect(index)
            painter.setBrush(self._color("error") if track.muted else self._color("surface_alt"))
            painter.setPen(QPen(self._color("border"), 1))
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(
                self._color("accent_text") if track.muted else self._color("text_dim")
            )
            font_m = QFont(self.font())
            font_m.setBold(True)
            painter.setFont(font_m)
            painter.drawText(
                box, int(Qt.AlignmentFlag.AlignCenter), "M"
            )

    def _paint_eye_icon(self, painter: QPainter, box: QRectF, visible: bool) -> None:
        cx = box.center().x()
        cy = box.center().y()
        path = QPainterPath()
        path.moveTo(cx - 7, cy)
        path.cubicTo(cx - 3.5, cy - 4.5, cx + 3.5, cy - 4.5, cx + 7, cy)
        path.cubicTo(cx + 3.5, cy + 4.5, cx - 3.5, cy + 4.5, cx - 7, cy)

        if visible:
            painter.setPen(QPen(self._color("text_dim"), 1.3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.setBrush(self._color("text_dim"))
            painter.drawEllipse(QPointF(cx, cy), 2.2, 2.2)
        else:
            painter.setPen(QPen(QColor("#64748b"), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.setPen(QPen(self._color("error"), 1.6))
            painter.drawLine(QPointF(cx - 6, cy + 5), QPointF(cx + 6, cy - 5))

    def _paint_track_drop_indicator(self, painter: QPainter) -> None:
        lane = self._lane_rect(self._drop_track_target)
        header = self._header_rect(self._drop_track_target)
        y = (
            lane.top() - 1
            if self._drop_track_target < self._drag_track
            else lane.bottom() + 1
        )
        painter.setPen(QPen(self._color("accent"), 3))
        painter.drawLine(
            int(header.left()), int(y), int(lane.right()), int(y)
        )

    def _eye_rect(self, index: int) -> QRectF:
        rect = self._header_rect(index)
        return QRectF(rect.right() - 25, rect.center().y() - 10, 22, 20)

    def _mute_rect(self, index: int) -> QRectF:
        rect = self._header_rect(index)
        track = self._project.tracks[index]
        if track.kind is TrackKind.VIDEO:
            return QRectF(rect.right() - 50, rect.center().y() - 10, 22, 20)
        return QRectF(rect.right() - 25, rect.center().y() - 10, 22, 20)

    def _paint_lane(self, painter: QPainter, index: int, track) -> None:
        lane = self._lane_rect(index)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color("surface_alt", 120))
        painter.drawRoundedRect(lane, 5, 5)

        painter.save()
        painter.setClipRect(lane)
        if not track.visible:
            painter.setOpacity(0.35)
        # Clipes comuns primeiro, marcador de transição por último. Ele ocupa o
        # mesmo trecho dos dois vizinhos e precisa permanecer visível e clicável
        # em cima deles.
        for clip in sorted(track.clips, key=lambda item: item.is_transition):
            self._paint_clip(painter, index, clip, track)
        painter.restore()

    def _paint_clip(self, painter: QPainter, index: int, clip: Clip, track) -> None:
        rect = self._clip_rect(index, clip)
        if rect.right() < HEADER_WIDTH or rect.left() > self.width():
            return

        path = QPainterPath()
        path.addRoundedRect(rect, 5, 5)
        painter.save()
        painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
        if clip.is_transition:
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            grad.setColorAt(0.0, QColor("#d97706"))
            grad.setColorAt(0.5, QColor("#f59e0b"))
            grad.setColorAt(1.0, QColor("#b45309"))
            painter.fillRect(rect, grad)
        elif track.kind is TrackKind.ADDITIONAL:
            if clip.overlay_type == "filter":
                fname = clip.filter_name
                if fname == "pb":
                    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                    grad.setColorAt(0.0, QColor("#455a64"))
                    grad.setColorAt(1.0, QColor("#263238"))
                    painter.fillRect(rect, grad)
                elif fname == "sepia":
                    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                    grad.setColorAt(0.0, QColor("#5d4037"))
                    grad.setColorAt(1.0, QColor("#3e2723"))
                    painter.fillRect(rect, grad)
                elif fname == "vinheta":
                    grad = QRadialGradient(rect.center(), max(rect.width(), rect.height()) / 1.5)
                    grad.setColorAt(0.0, QColor("#283593"))
                    grad.setColorAt(1.0, QColor("#0d1224"))
                    painter.fillRect(rect, grad)
                elif fname == "inverter":
                    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                    grad.setColorAt(0.0, QColor("#00695c"))
                    grad.setColorAt(1.0, QColor("#004d40"))
                    painter.fillRect(rect, grad)
                elif fname == "contraste":
                    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                    grad.setColorAt(0.0, QColor("#e65100"))
                    grad.setColorAt(1.0, QColor("#bf360c"))
                    painter.fillRect(rect, grad)
                else:
                    painter.fillRect(rect, QColor(94, 53, 177, 200))
            elif clip.is_image or clip.overlay_type == "image":
                painter.fillRect(rect, QColor("#1e1e24"))
            else:
                painter.fillRect(rect, QColor(106, 27, 154, 190))
        else:
            painter.fillRect(rect, self._color("surface"))

        if clip.is_transition:
            pass
        elif track.kind is TrackKind.VIDEO or clip.is_image or clip.overlay_type == "image":
            self._paint_thumbs(painter, clip, rect)
        elif track.kind is TrackKind.AUDIO:
            self._paint_wave(painter, clip, rect)
        self._paint_clip_label(painter, clip, rect, track)
        painter.restore()

        selected = clip.clip_id == self._selected
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if selected:
            border_pen = QPen(self._color("accent"), 2)
        elif clip.is_transition:
            border_pen = QPen(QColor("#fbbf24"), 1)
        elif track.kind is TrackKind.ADDITIONAL:
            if clip.overlay_type == "filter":
                f_borders = {
                    "pb": QColor("#90a4ae"),
                    "sepia": QColor("#bcaaa4"),
                    "vinheta": QColor("#7986cb"),
                    "inverter": QColor("#80cbc4"),
                    "contraste": QColor("#ffb74d"),
                }
                border_pen = QPen(f_borders.get(clip.filter_name, QColor(186, 104, 200)), 1)
            elif clip.is_image or clip.overlay_type == "image":
                border_pen = QPen(QColor("#00bcd4"), 1)
            else:
                border_pen = QPen(QColor(186, 104, 200), 1)
        else:
            border_pen = QPen(self._color("border"), 1)
        painter.setPen(border_pen)
        painter.drawPath(path)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color("accent"))
            for x in (rect.left(), rect.right() - _HANDLE_WIDTH):
                painter.drawRoundedRect(
                    QRectF(x, rect.top(), _HANDLE_WIDTH, rect.height()), 2, 2
                )

    def _source_rect(self, clip: Clip, rect: QRectF, begin: float, end: float) -> QRectF:
        """Onde um trecho de origem cai dentro do bloco, em pixels."""
        left = self._x_of(clip.start + (begin - clip.in_point))
        right = self._x_of(clip.start + (end - clip.in_point))
        return QRectF(left, rect.top(), max(1.0, right - left), rect.height())

    def _paint_thumbs(self, painter: QPainter, clip: Clip, rect: QRectF) -> None:
        strip = self._strips.get(clip.clip_id)
        if strip is None or not strip.thumbs:
            return
        if clip.is_image or clip.overlay_type == "image":
            first_thumb = next(iter(strip.thumbs.values()), None)
            if first_thumb is not None:
                area = QRectF(
                    rect.left(), rect.top() + 13, rect.width(), max(1.0, rect.height() - 13)
                )
                image, image_rect = _image_preview(first_thumb, area)
                painter.drawImage(image_rect, image)
            return
        for moment, image in sorted(strip.thumbs.items()):
            begin, end = strip.cell_of(moment)
            cell = self._source_rect(clip, rect, begin, end)
            if cell.right() < rect.left() or cell.left() > rect.right():
                continue
            painter.drawImage(
                QRectF(cell.left(), rect.top(), cell.width(), rect.height() - 12), image
            )

    def _paint_wave(self, painter: QPainter, clip: Clip, rect: QRectF) -> None:
        strip = self._strips.get(clip.clip_id)
        if strip is None or strip.wave is None:
            return
        area = self._source_rect(clip, rect, strip.in_point, strip.out_point)
        painter.drawImage(
            QRectF(area.left(), rect.top() + 12, area.width(), rect.height() - 14),
            strip.wave,
        )

    def _paint_clip_label(
        self, painter: QPainter, clip: Clip, rect: QRectF, track
    ) -> None:
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 2))
        painter.setFont(font)

        strip = QRectF(rect.left(), rect.top(), rect.width(), 13)
        painter.fillRect(strip, self._color("bg", 190))
        silenced = clip.muted or track.muted
        painter.setPen(
            self._color("warn") if silenced else self._color("text")
        )

        badges: list[str] = []
        if clip.speed_label:
            badges.append(f"⚡ {clip.speed_label}")
        if clip.gain_label:
            badges.append(clip.gain_label)

        if clip.overlay_type == "text":
            text = f"🔤 {clip.text_content or 'Texto'}"
        elif clip.overlay_type == "filter":
            fname = clip.filter_name
            f_labels = {
                "pb": "P&B",
                "sepia": "Sépia",
                "vinheta": "Vinheta",
                "inverter": "Inversão",
                "contraste": "Contraste",
            }
            text = f"🎨 {f_labels.get(fname, fname or 'Filtro')}"
        elif clip.overlay_type == "transition":
            tname = clip.transition_name
            t_labels = {
                "fade": "Fade",
                "fadeblack": "Fade para Preto",
                "fadewhite": "Fade para Branco",
                "dissolve": "Dissolve",
                "wipeleft": "Wipe para Esquerda",
                "wiperight": "Wipe para Direita",
                "slideleft": "Slide para Esquerda",
                "slideright": "Slide para Direita",
            }
            text = f"⏳ {t_labels.get(tname, tname or 'Transição')}"
        elif clip.overlay_type == "image" or clip.is_image:
            text = f"🖼️ {clip.media.name}"
        else:
            text = clip.media.name

        if badges:
            text = f"{text}   {' · '.join(badges)}"

        painter.drawText(
            strip.adjusted(6, 0, -4, 0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            QFontMetrics(font).elidedText(
                text, Qt.TextElideMode.ElideRight, int(rect.width()) - 10
            ),
        )

    def _paint_playhead(self, painter: QPainter) -> None:
        x = self._x_of(self._position)
        if x < HEADER_WIDTH - 8 or x > self.width() + 8:
            return
        painter.setPen(QPen(self._color("error"), 2))
        painter.drawLine(QPointF(x, RULER_HEIGHT - 8), QPointF(x, self.height() - 4))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color("error"))
        painter.drawRoundedRect(QRectF(x - 6, RULER_HEIGHT - 16, 12, 11), 3, 3)

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip:
            help_event = cast(QHelpEvent, event)
            pos = help_event.position()
            kind, index, _ = self._hit(pos.x(), pos.y())
            if kind == "olho" and 0 <= index < len(self._project.tracks):
                track = self._project.tracks[index]
                text = (
                    strings.EDIT_TRACK_HIDE
                    if track.visible
                    else strings.EDIT_TRACK_SHOW
                )
                QToolTip.showText(help_event.globalPosition().toPoint(), text, self)
                return True
            if kind == "mudo" and 0 <= index < len(self._project.tracks):
                track = self._project.tracks[index]
                text = (
                    strings.EDIT_TRACK_UNMUTE
                    if track.muted
                    else strings.EDIT_TRACK_MUTE
                )
                QToolTip.showText(help_event.globalPosition().toPoint(), text, self)
                return True
            if kind == "cabecalho" and 0 <= index < len(self._project.tracks):
                QToolTip.showText(
                    help_event.globalPosition().toPoint(),
                    strings.EDIT_TRACK_DRAG_TIP,
                    self,
                )
                return True
            QToolTip.hideText()
        return super().event(event)

    def _hit(self, x: float, y: float) -> tuple[str, int, int]:
        """O que está sob o ponteiro: (espécie, índice da trilha, clip_id)."""
        if y < RULER_HEIGHT:
            return "cursor", -1, -1
        index = self._track_at(y)
        if index < 0:
            return "cursor", -1, -1
        if x < HEADER_WIDTH:
            track = self._project.tracks[index]
            if track.kind in (TrackKind.VIDEO, TrackKind.ADDITIONAL) and self._eye_rect(index).adjusted(-3, -3, 3, 3).contains(x, y):
                return "olho", index, -1
            if track.kind in (TrackKind.VIDEO, TrackKind.AUDIO) and self._mute_rect(index).adjusted(-3, -3, 3, 3).contains(x, y):
                return "mudo", index, -1
            return "cabecalho", index, -1

        # A transição se sobrepõe aos clipes que une. Testá-la primeiro faz o
        # clique escolher o marcador desenhado por cima, não o vídeo de baixo.
        ordered = sorted(
            self._project.tracks[index].clips,
            key=lambda item: not item.is_transition,
        )
        for clip in ordered:
            rect = self._clip_rect(index, clip)
            if abs(x - rect.left()) <= _HANDLE_GRAB:
                return "inicio", index, clip.clip_id
            if abs(x - rect.right()) <= _HANDLE_GRAB:
                return "fim", index, clip.clip_id
            if rect.left() <= x <= rect.right():
                return "corpo", index, clip.clip_id
        return "cursor", index, -1

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        x, y = event.position().x(), event.position().y()
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_origin = event.position()
            self._pan_start = self._view_start
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() == Qt.MouseButton.RightButton:
            kind, index, clip_id = self._hit(x, y)
            if clip_id >= 0:
                self.select(clip_id)
            self.menu_requested.emit(
                kind, index, clip_id, event.globalPosition().toPoint()
            )
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        kind, index, clip_id = self._hit(x, y)
        if kind == "olho":
            self.track_visibility_clicked.emit(index)
            return
        if kind == "mudo":
            self.track_mute_clicked.emit(index)
            return
        if kind == "cabecalho":
            self._drag, self._drag_track = "cabecalho", index
            self._drop_track_target = index
            self._press_at, self._dragging = event.position(), False
            return
        if clip_id >= 0:
            self.select(clip_id)
        if kind in ("inicio", "fim", "corpo"):
            # O aviso de que uma edição começou fica para o primeiro movimento
            # que passe da folga: um clique de seleção não é uma edição.
            self._drag, self._drag_clip = kind, clip_id
            self._press_at, self._dragging = event.position(), False
            found = self._project.find(clip_id)
            if found is not None and found[1].is_transition:
                if kind == "corpo":
                    # A posição pertence ao corte; arrastar o corpo não pode
                    # descolar o efeito dos vídeos. O clique ainda seleciona.
                    self._drag = ""
                    return
                self._drag_edge_origin = (
                    found[1].start if kind == "inicio" else found[1].end
                )
            if found is not None and kind == "corpo":
                # Guarda onde no bloco o mouse pegou: sem isso o bloco pula para
                # ficar com o começo debaixo do ponteiro.
                self._grab_offset = self._time_of(x) - found[1].start
            return

        self._drag, self._drag_clip = "cursor", -1
        self._press_at, self._dragging = None, False
        self.set_position(self._time_of(x), follow=False)
        self.scrubbed.emit(self._position)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        x, y = event.position().x(), event.position().y()
        if self._pan_origin is not None:
            delta = (x - self._pan_origin.x()) * self._seconds_per_pixel()
            self.set_view(self._pan_start - delta, self._pan_start - delta + self.view_span)
            return

        if not self._drag:
            kind, _, _ = self._hit(x, y)
            self.setCursor(
                Qt.CursorShape.SizeHorCursor
                if kind in ("inicio", "fim")
                else Qt.CursorShape.OpenHandCursor
                if kind in ("corpo", "cabecalho")
                else Qt.CursorShape.PointingHandCursor
                if kind == "mudo"
                else Qt.CursorShape.ArrowCursor
            )
            return

        if self._drag == "cabecalho":
            if not self._past_slack(event.position()):
                return
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            target = self._target_reorder_track(y)
            if target != self._drop_track_target:
                self._drop_track_target = target
                self.update()
            return

        if self._drag == "cursor":
            self.set_position(self._time_of(x), follow=False)
            self.scrubbed.emit(self._position)
            return

        if not self._past_slack(event.position()):
            return

        found = self._project.find(self._drag_clip)
        if found is None:
            return
        origin, clip = found

        if self._drag == "corpo":
            start = self._snap_start(self._time_of(x) - self._grab_offset, clip)
            target = self._drop_track(y, clip, origin)
            self.clip_moved.emit(clip.clip_id, target, max(0.0, start))
            return

        if clip.is_transition and self._press_at is not None:
            # O retângulo pode ser visualmente maior que sua duração. Medir o
            # deslocamento desde o clique evita o primeiro movimento dar um
            # salto para o instante correspondente à borda ampliada.
            delta = (x - self._press_at.x()) * self._seconds_per_pixel()
            moment = self._drag_edge_origin + delta
        else:
            moment = self._snap(self._time_of(x), clip)
        self.clip_resized.emit(clip.clip_id, self._drag, moment)

    def _target_reorder_track(self, y: float) -> int:
        if not (0 <= self._drag_track < len(self._project.tracks)):
            return -1
        moving_kind = self._project.tracks[self._drag_track].kind
        valid_indices = [
            i for i, t in enumerate(self._project.tracks) if t.kind is moving_kind
        ]
        if not valid_indices:
            return self._drag_track

        for i in valid_indices:
            rect = self._lane_rect(i)
            if rect.top() <= y < rect.bottom() + TRACK_GAP:
                return i

        first = valid_indices[0]
        if y < self._lane_rect(first).top():
            return first
        return valid_indices[-1]

    def _past_slack(self, point: QPointF) -> bool:
        """Se o ponteiro já andou o bastante para isto ser um arrasto.

        O aviso de início vai daqui, e só uma vez: é ele que empilha o desfazer,
        e um desfazer por clique tornaria o Ctrl+Z inútil.
        """
        if self._dragging:
            return True
        if self._press_at is None:
            return False
        delta = point - self._press_at
        if max(abs(delta.x()), abs(delta.y())) < _DRAG_SLACK:
            return False
        self._dragging = True
        self.edit_started.emit()
        return True

    def _drop_track(self, y: float, clip: Clip, origin: int) -> int:
        """Trilha sob o ponteiro, se ela aceitar este bloco."""
        index = self._track_at(y)
        if index < 0 or not accepts(self._project.tracks[index].kind, clip):
            return origin
        return index

    def _snap_targets(self, moving: Clip) -> list[float]:
        targets = [self._position, 0.0]
        for track in self._project.tracks:
            for clip in track.clips:
                if clip.clip_id != moving.clip_id:
                    targets += [clip.start, clip.end]
        return targets

    def _snap(self, moment: float, moving: Clip) -> float:
        tolerance = _SNAP_PIXELS * self._seconds_per_pixel()
        best = min(self._snap_targets(moving), key=lambda value: abs(value - moment))
        return best if abs(best - moment) <= tolerance else moment

    def _snap_start(self, start: float, moving: Clip) -> float:
        """Imanta o começo **ou o fim** do bloco arrastado.

        Encostar dois blocos é a operação mais comum de uma linha do tempo, e
        ela falha quando só a ponta esquerda gruda: quem arrasta para encostar
        no vizinho da direita mira o fim do bloco, não o começo.
        """
        tolerance = _SNAP_PIXELS * self._seconds_per_pixel()
        candidates = self._snap_targets(moving)
        options = [(abs(t - start), t) for t in candidates]
        options += [(abs(t - (start + moving.duration)), t - moving.duration) for t in candidates]
        distance, value = min(options, key=lambda pair: pair[0])
        return value if distance <= tolerance else start

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pan_origin is not None:
            self._pan_origin = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        if self._drag == "cabecalho":
            if (
                self._dragging
                and self._drop_track_target >= 0
                and self._drop_track_target != self._drag_track
            ):
                self.track_reordered.emit(self._drag_track, self._drop_track_target)
            self._drag = ""
            self._drag_track = -1
            self._drop_track_target = -1
            self._press_at, self._dragging = None, False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
            return
        if self._dragging and self._drag in ("inicio", "fim", "corpo"):
            self.edit_finished.emit()
        self._drag, self._drag_clip = "", -1
        self._press_at, self._dragging = None, False

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        kind, index, clip_id = self._hit(event.position().x(), event.position().y())
        found = self._project.find(clip_id) if clip_id >= 0 else None
        if found is not None:
            clip = found[1]
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
        step = frame_step(self._project.fps)
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            step = 1.0
        if event.key() == Qt.Key.Key_Left:
            self.set_position(self._position - step)
        elif event.key() == Qt.Key.Key_Right:
            self.set_position(self._position + step)
        elif event.key() == Qt.Key.Key_Home:
            self.set_position(0.0)
        elif event.key() == Qt.Key.Key_End:
            self.set_position(self._project.duration)
        else:
            super().keyPressEvent(event)
            return
        self.scrubbed.emit(self._position)


def _ruler_label(seconds: float, step: float) -> str:
    label = format_timecode(seconds, milliseconds=step < 1)
    if step < 1:
        label = label[:-2]
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


# Reexportado para o painel, que fatia o tempo dos blocos com a mesma regra.
__all__ = [
    'AUDIO_TRACK_HEIGHT',
    'FILM_CELL_WIDTH',
    'HEADER_WIDTH',
    'MIN_SEGMENT',
    'RULER_HEIGHT',
    'Timeline',
    'VIDEO_TRACK_HEIGHT',
    'image_from_frame',
    'pixmap_from_frame',
]
