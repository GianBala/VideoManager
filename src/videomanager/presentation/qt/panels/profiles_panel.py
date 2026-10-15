"""Perfis rápidos: um clique configura a qualidade e enfileira.

Os quatro perfis cobrem o que a maioria das pessoas quer na prática. Nenhum deles
recodifica sem necessidade: "MP4 1080p" prefere H.264+AAC na origem justamente
para que baste remuxar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from videomanager.application.formatting import format_size_compact
from videomanager.domain.formats import Mode
from videomanager.presentation.qt import fonts, icons, strings, theme
from videomanager.presentation.qt.i18n import bind

_PAD = 14
_TILE = 38
_ICON = 20
_DOWNLOAD_TILE = 28
# O espaço entre o ladrilho, o texto e o pé do cartão.
_GAP = 10


@dataclass(frozen=True)
class Profile:
    """Uma configuração pronta, aplicada aos controles ao ser clicada.

    Título e subtítulo são lidos do catálogo na hora de mostrar: guardados
    como texto no import, ficariam no idioma da abertura.
    """

    title: Callable[[], str]
    subtitle: Callable[[], str]
    mode: Mode
    height: int | None = None
    container: str = "auto"
    audio_codec: str = "mp3"
    audio_quality: str = "320"
    # Como o cartão se desenha: um ícone que diz de relance o que o perfil faz.
    icon: Callable = icons.nav_edit


PROFILES = (
    Profile(
        title=lambda: strings.PROFILE_MP4_1080,
        subtitle=lambda: strings.PROFILE_MP4_1080_SUB,
        mode=Mode.VIDEO,
        height=1080,
        container="mp4",
        icon=icons.nav_edit,
    ),
    Profile(
        title=lambda: strings.PROFILE_MAX,
        subtitle=lambda: strings.PROFILE_MAX_SUB,
        mode=Mode.VIDEO,
        height=None,
        container="mkv",
        icon=icons.star,
    ),
    Profile(
        title=lambda: strings.PROFILE_MP3_320,
        subtitle=lambda: strings.PROFILE_MP3_320_SUB,
        mode=Mode.AUDIO_ONLY,
        audio_codec="mp3",
        audio_quality="320",
        icon=icons.music,
    ),
    Profile(
        title=lambda: strings.PROFILE_AUDIO_ORIGINAL,
        subtitle=lambda: strings.PROFILE_AUDIO_ORIGINAL_SUB,
        mode=Mode.AUDIO_ONLY,
        audio_codec="best",
        icon=icons.waveform,
    ),
)


class ProfileCard(QPushButton):
    """Cartão de um perfil, pintado: ladrilho com ícone, nome, descrição, tamanho estimado e o botão de baixar.

    É um ``QPushButton`` de verdade (foco, Enter, Espaço, desabilitado até haver mídia), com o texto
    ``"título\nsubtítulo"`` para quem lê o botão sem vê-lo; só o desenho é próprio. Sob o mouse (ou com o foco) o
    cartão "esquenta": o fundo ganha um tom, o ladrilho e o botão viram o degradê do botão primário e um anel o cerca.
    """

    def __init__(self, profile: Profile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profile = profile
        self._size_text = ""
        bind(self, "setText", lambda: f"{profile.title()}\n{profile.subtitle()}")
        self.setProperty("role", "profile-card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(self._altura())
        self.setMaximumHeight(self._altura())
        theme.on_theme_change(self._retheme)

    def set_size_text(self, text: str) -> None:
        """O tamanho estimado deste perfil para a mídia analisada ("" enquanto não há análise)."""
        self._size_text = text
        self.update()

    def size_text(self) -> str:
        return self._size_text

    def _retheme(self) -> None:
        self.update()

    @staticmethod
    def _linha(fonte: QFont) -> int:
        """A altura de uma linha de texto, com o espaçamento de 1,4 do protótipo."""
        return round(fonte.pixelSize() * 1.4)

    def _altura(self) -> int:
        titulo, normal = self._fontes()
        return _PAD + _TILE + _GAP + self._linha(titulo) + 1 + self._linha(normal) + _GAP + _DOWNLOAD_TILE + _PAD

    def _fontes(self) -> tuple[QFont, QFont]:
        titulo = fonts.resized(self.font(), delta=1)
        titulo.setWeight(QFont.Weight.DemiBold)
        return titulo, fonts.resized(self.font(), delta=-1)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(170, self._altura())

    def paintEvent(self, event) -> None:  # noqa: N802
        c = theme.papeis(*theme.atual())
        derivadas = theme.derivadas(c)
        cor_foco = theme.palette(*theme.atual())["focus"]
        ativo = self.isEnabled()
        foco = ativo and self.hasFocus()
        quente = ativo and (self.underMouse() or foco)
        titulo, normal = self._fontes()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not ativo:
            p.setOpacity(0.55)
        corpo = QRectF(0.75, 0.75, self.width() - 1.5, self.height() - 1.5)
        p.setBrush(QColor(derivadas["hot"] if quente else c["card"]))
        p.setPen(QPen(QColor(cor_foco if foco else derivadas["ring"]), 1.5) if quente else Qt.PenStyle.NoPen)
        p.drawRoundedRect(corpo, 12, 12)

        def degrade(caixa: QRectF) -> QLinearGradient:
            g = QLinearGradient(caixa.topLeft(), caixa.bottomRight())
            g.setColorAt(0, QColor(c["fill_a"]))
            g.setColorAt(1, QColor(c["fill_b"]))
            return g

        # Ladrilho do ícone.
        tile = QRectF(_PAD, _PAD, _TILE, _TILE)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(degrade(tile) if quente else QColor(c["raised"]))
        p.drawRoundedRect(tile, 10, 10)
        icone = self._profile.icon(c["on_fill"] if quente else c["t2"], _ICON)
        icone.paint(p, QRect(int(tile.x()) + (_TILE - _ICON) // 2, int(tile.y()) + (_TILE - _ICON) // 2, _ICON, _ICON))

        largura = self.width() - 2 * _PAD
        y = _PAD + _TILE + _GAP
        mt, mn = QFontMetrics(titulo), QFontMetrics(normal)
        p.setFont(titulo)
        p.setPen(QColor(c["text"]))
        linha = self._linha(titulo)
        p.drawText(QPointF(_PAD, y + (linha + mt.ascent() - mt.descent()) / 2), mt.elidedText(self._profile.title(), Qt.TextElideMode.ElideRight, largura))
        y += linha + 1
        p.setFont(normal)
        p.setPen(QColor(c["t3"]))
        linha = self._linha(normal)
        p.drawText(QPointF(_PAD, y + (linha + mn.ascent() - mn.descent()) / 2), mn.elidedText(self._profile.subtitle(), Qt.TextElideMode.ElideRight, largura))

        # O pé: o tamanho estimado à esquerda e, à direita, o botão de baixar — que diz que o clique faz algo já.
        if ativo:
            baixar = QRectF(self.width() - _PAD - _DOWNLOAD_TILE, self.height() - _PAD - _DOWNLOAD_TILE, _DOWNLOAD_TILE, _DOWNLOAD_TILE)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(degrade(baixar) if quente else QColor(c["raised"]))
            p.drawRoundedRect(baixar, 8, 8)
            lado = 16
            icons.nav_download(c["on_fill"] if quente else c["t2"], lado).paint(
                p, QRect(int(baixar.x()) + (_DOWNLOAD_TILE - lado) // 2, int(baixar.y()) + (_DOWNLOAD_TILE - lado) // 2, lado, lado))
            if self._size_text:
                p.setFont(normal)
                p.setPen(QColor(c["t2"]))
                p.drawText(QPointF(_PAD, baixar.center().y() + (mn.ascent() - mn.descent()) / 2), self._size_text)
        p.end()


class ProfilesPanel(QWidget):
    """Os cartões de perfil, numa fileira. Emite o perfil escolhido."""

    profile_chosen = Signal(object)  # Profile

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "plain")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = bind(QLabel(), "setText", lambda: strings.PROFILES_GROUP)
        title.setProperty("role", "section-title")
        header.addWidget(title, 0, Qt.AlignmentFlag.AlignBaseline)
        hint = bind(QLabel(), "setText", lambda: strings.PROFILE_HINT)
        hint.setProperty("role", "hint")
        header.addWidget(hint, 1, Qt.AlignmentFlag.AlignBaseline)
        layout.addLayout(header)

        row = QHBoxLayout()
        row.setSpacing(12)
        self._buttons: list[ProfileCard] = []
        for profile in PROFILES:
            button = ProfileCard(profile)
            button.clicked.connect(lambda _=False, p=profile: self.profile_chosen.emit(p))
            row.addWidget(button, 1)
            self._buttons.append(button)
        layout.addLayout(row)
        self.set_enabled(False)

    def set_enabled(self, enabled: bool) -> None:
        for button in self._buttons:
            button.setEnabled(enabled)
        if not enabled:
            self.set_estimates([])

    def set_estimates(self, sizes: list[int | None]) -> None:
        """O tamanho estimado de cada perfil, na ordem de ``PROFILES`` (vazio apaga todos)."""
        for index, button in enumerate(self._buttons):
            size = sizes[index] if index < len(sizes) else None
            button.set_size_text(format_size_compact(size, estimated=True) if size is not None else "")
