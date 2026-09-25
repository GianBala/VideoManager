"""Perfis rápidos: um clique configura a qualidade e enfileira.

Os quatro perfis cobrem o que a maioria das pessoas quer na prática. Nenhum deles
recodifica sem necessidade: "MP4 1080p" prefere H.264+AAC na origem justamente
para que baste remuxar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QLabel, QPushButton, QVBoxLayout, QWidget

from videomanager.domain.formats import Mode
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.i18n import bind


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


PROFILES = (
    Profile(
        title=lambda: strings.PROFILE_MP4_1080,
        subtitle=lambda: strings.PROFILE_MP4_1080_SUB,
        mode=Mode.VIDEO,
        height=1080,
        container="mp4",
    ),
    Profile(
        title=lambda: strings.PROFILE_MAX,
        subtitle=lambda: strings.PROFILE_MAX_SUB,
        mode=Mode.VIDEO,
        height=None,
        container="mkv",
    ),
    Profile(
        title=lambda: strings.PROFILE_MP3_320,
        subtitle=lambda: strings.PROFILE_MP3_320_SUB,
        mode=Mode.AUDIO_ONLY,
        audio_codec="mp3",
        audio_quality="320",
    ),
    Profile(
        title=lambda: strings.PROFILE_AUDIO_ORIGINAL,
        subtitle=lambda: strings.PROFILE_AUDIO_ORIGINAL_SUB,
        mode=Mode.AUDIO_ONLY,
        audio_codec="best",
    ),
)


class ProfilesPanel(QGroupBox):
    """Botões de perfil. Emite o perfil escolhido."""

    profile_chosen = Signal(object)  # Profile

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        bind(self, "setTitle", lambda: strings.PROFILES_GROUP)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        hint = bind(QLabel(), "setText", lambda: strings.PROFILE_HINT)
        hint.setProperty("role", "dim")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._buttons: list[QPushButton] = []
        for profile in PROFILES:
            button = bind(QPushButton(), "setText", lambda p=profile: f"{p.title()}\n{p.subtitle()}")
            button.setProperty("role", "profile")
            button.clicked.connect(lambda _=False, p=profile: self.profile_chosen.emit(p))
            layout.addWidget(button)
            self._buttons.append(button)

        layout.addStretch(1)
        self.set_enabled(False)

    def set_enabled(self, enabled: bool) -> None:
        for button in self._buttons:
            button.setEnabled(enabled)
