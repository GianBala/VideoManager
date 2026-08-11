"""Seleção de itens de uma playlist ou canal."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.humanize import format_duration
from ..core.models import PlaylistEntry, PlaylistInfo
from . import strings

# Limites oferecidos para playlists. A escolha é por limite, e não por formato
# fixo, porque cada item pode oferecer resoluções diferentes.
_HEIGHT_LIMITS = ((None, "Melhor disponível"), (2160, "até 2160p"), (1440, "até 1440p"),
                  (1080, "até 1080p"), (720, "até 720p"), (480, "até 480p"), (360, "até 360p"))
# Equilíbrio entre qualidade e tamanho para um lote inteiro.
_DEFAULT_LIMIT = 1080


class PlaylistDialog(QDialog):
    """Lista os itens e devolve os que o usuário marcou."""

    def __init__(self, playlist: PlaylistInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.PLAYLIST_TITLE)
        self.resize(680, 560)
        self._playlist = playlist

        layout = QVBoxLayout(self)

        header = QLabel(
            strings.PLAYLIST_HEADER.format(
                title=playlist.title, count=len(playlist.entries)
            )
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self._list = QListWidget()
        for entry in playlist.entries:
            duration = format_duration(entry.duration)
            item = QListWidgetItem(f"{entry.index:>3}. {entry.title}   ({duration})")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._list.addItem(item)
        layout.addWidget(self._list, 1)

        toggles = QHBoxLayout()
        select_all = QPushButton(strings.PLAYLIST_SELECT_ALL)
        select_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        toggles.addWidget(select_all)
        select_none = QPushButton(strings.PLAYLIST_SELECT_NONE)
        select_none.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        toggles.addWidget(select_none)
        toggles.addStretch(1)
        toggles.addWidget(QLabel(strings.LABEL_RESOLUTION))
        self._limit = QComboBox()
        for value, label in _HEIGHT_LIMITS:
            self._limit.addItem(label, value)
        # Por dado, e não por índice: reordenar a tabela acima mudaria o padrão
        # sem ninguém perceber.
        self._limit.setCurrentIndex(max(0, self._limit.findData(_DEFAULT_LIMIT)))
        toggles.addWidget(self._limit)
        layout.addLayout(toggles)

        note = QLabel(strings.PLAYLIST_NOTE)
        note.setProperty("role", "dim")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._list.itemChanged.connect(self._update_ok)
        self._update_ok()

    # ------------------------------------------------------------------

    def _set_all(self, state: Qt.CheckState) -> None:
        # Sinais bloqueados durante o laço: cada setCheckState emitia
        # itemChanged, que recontava a lista inteira. Num canal com centenas de
        # itens isso é quadrático, e "Marcar todos" travava a janela por
        # segundos. A contagem é feita uma vez, no fim.
        blocked = self._list.blockSignals(True)
        try:
            for row in range(self._list.count()):
                self._list.item(row).setCheckState(state)
        finally:
            self._list.blockSignals(blocked)
        self._update_ok()

    def _update_ok(self) -> None:
        count = len(self.selected_entries())
        if self._ok is not None:
            self._ok.setText(strings.PLAYLIST_ADD.format(count=count))
            self._ok.setEnabled(count > 0)

    def selected_entries(self) -> list[PlaylistEntry]:
        entries: list[PlaylistEntry] = []
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                entry = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(entry, PlaylistEntry):
                    entries.append(entry)
        return entries

    def height_limit(self) -> int | None:
        return self._limit.currentData()
