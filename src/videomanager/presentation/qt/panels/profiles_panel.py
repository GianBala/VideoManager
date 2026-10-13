"""Perfis rápidos: um clique configura a qualidade e enfileira.

Os quatro perfis cobrem o que a maioria das pessoas quer na prática. Nenhum deles
recodifica sem necessidade: "MP4 1080p" prefere H.264+AAC na origem justamente
para que baste remuxar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from videomanager.domain.formats import Mode
from videomanager.presentation.qt import fonts, icons, strings, theme
from videomanager.presentation.qt.i18n import bind

_PAD = 14
_TILE = 36
_ICON = 20
_DOWNLOAD_TILE = 28


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
    """Cartão de um perfil, pintado: ladrilho com ícone, nome, descrição e o botão de baixar.

    É um ``QPushButton`` de verdade (foco, Enter, Espaço, desabilitado até haver mídia), com o texto
    ``"título\\nsubtítulo"`` para quem lê o botão sem vê-lo; só o desenho é próprio.
    """

    def __init__(self, profile: Profile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._profile = profile
        bind(self, "setText", lambda: f"{profile.title()}\n{profile.subtitle()}")
        self.setProperty("role", "profile-card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(self._altura())
        self.setMaximumHeight(self._altura())
        theme.on_theme_change(self._retheme)

    def _retheme(self) -> None:
        self.update()

    def _altura(self) -> int:
        titulo, normal = self._fontes()
        return _PAD + _TILE + 10 + QFontMetrics(titulo).lineSpacing() + 2 + QFontMetrics(normal).lineSpacing() + _PAD

    def _fontes(self) -> tuple[QFont, QFont]:
        titulo = QFont(self.font())
        titulo.setBold(True)
        return titulo, fonts.resized(self.font(), factor=0.93)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(170, self._altura())

    def paintEvent(self, event) -> None:  # noqa: N802
        c = theme.papeis(*theme.atual())
        cor_foco = theme.palette(*theme.atual())["focus"]
        ativo = self.isEnabled()
        passando = ativo and self.underMouse()
        foco = ativo and self.hasFocus()
        titulo, normal = self._fontes()
        mt, mn = QFontMetrics(titulo), QFontMetrics(normal)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not ativo:
            p.setOpacity(0.55)
        corpo = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setBrush(QColor(c["raised2"] if passando else c["raised"]))
        p.setPen(QPen(QColor(cor_foco), 1.5) if foco else Qt.PenStyle.NoPen)
        p.drawRoundedRect(corpo, 12, 12)
        # Ladrilho do ícone.
        tile = QRect(_PAD, _PAD, _TILE, _TILE)
        p.setPen(Qt.PenStyle.NoPen)
        fundo = QColor(c["accent"])
        fundo.setAlpha(38 if ativo else 0)
        p.setBrush(fundo if ativo else QColor(c["raised2"]))
        p.drawRoundedRect(QRectF(tile), 10, 10)
        icone = self._profile.icon(c["accent"] if ativo else c["t3"], _ICON)
        icone.paint(p, QRect(tile.x() + (_TILE - _ICON) // 2, tile.y() + (_TILE - _ICON) // 2, _ICON, _ICON))
        # Botão de baixar, no canto: diz que o clique faz alguma coisa já.
        if ativo:
            baixar = QRect(self.width() - _PAD - _DOWNLOAD_TILE, _PAD, _DOWNLOAD_TILE, _DOWNLOAD_TILE)
            p.setBrush(QColor(c["accent"] if passando else c["raised2"]))
            p.drawRoundedRect(QRectF(baixar), 8, 8)
            lado = 16
            icons.nav_download(c["on_fill"] if passando else c["t2"], lado).paint(
                p, QRect(baixar.x() + (_DOWNLOAD_TILE - lado) // 2, baixar.y() + (_DOWNLOAD_TILE - lado) // 2, lado, lado))
        largura = self.width() - 2 * _PAD
        y = _PAD + _TILE + 10
        p.setFont(titulo)
        p.setPen(QColor(c["text"]))
        p.drawText(QPoint(_PAD, y + mt.ascent()), mt.elidedText(self._profile.title(), Qt.TextElideMode.ElideRight, largura))
        y += mt.lineSpacing() + 2
        p.setFont(normal)
        p.setPen(QColor(c["t2"]))
        p.drawText(QPoint(_PAD, y + mn.ascent()), mn.elidedText(self._profile.subtitle(), Qt.TextElideMode.ElideRight, largura))
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
        header.addWidget(title)
        hint = bind(QLabel(), "setText", lambda: strings.PROFILE_HINT)
        hint.setProperty("role", "dim")
        header.addWidget(hint, 1)
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
