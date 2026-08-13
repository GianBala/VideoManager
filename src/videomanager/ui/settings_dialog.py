"""Diálogo de configurações."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from yt_dlp.cookies import SUPPORTED_BROWSERS

from ..core import hwaccel
from ..core.binaries import find_tools
from ..core.settings import Settings
from ..workers.hwaccel_worker import HardwareProbeWorker
from ..workers.runner import WorkerRunner
from . import strings
from .theme import FIELD_WIDTH

# Campos numéricos são curtos; esticá-los pela largura do diálogo deixaria uma
# caixa de 400 px para escrever "3".
_NUMBER_WIDTH = 110


class SettingsDialog(QDialog):
    """Edita as preferências. Grava só quando o usuário confirma."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # A sondagem da placa corre fora da thread da interface (ver
        # :meth:`_describe_encoder`).
        self._runner = WorkerRunner()
        self.setWindowTitle(strings.SETTINGS_TITLE)
        # Largura suficiente para o caminho de destino caber ao lado da coluna
        # de rótulos, que é comum às três abas.
        self.setMinimumWidth(620)
        self._settings = settings
        # Rótulos das três abas: recebem no fim a mesma largura, para os campos
        # não pularem de lado ao trocar de aba.
        self._labels: list[QLabel] = []

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_general(), strings.SETTINGS_TAB_GENERAL)
        tabs.addTab(self._build_network(), strings.SETTINGS_TAB_NETWORK)
        tabs.addTab(self._build_subs(), strings.SETTINGS_TAB_SUBS)
        self._align_label_column()
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------

    def _make_page(self) -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        page.setProperty("role", "plain")
        form = QFormLayout(page)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        return page, form

    def _add_row(self, form: QFormLayout, text: str, field: QWidget | QHBoxLayout) -> None:
        label = QLabel(text)
        self._labels.append(label)
        form.addRow(label, field)

    @staticmethod
    def _add_check(form: QFormLayout, box: QCheckBox) -> None:
        """Caixa de marcação ocupando a linha inteira.

        Posta na coluna dos campos, ela ficava recuada no meio do diálogo, longe
        do texto que a explica e sem nada à esquerda.
        """
        form.addRow(box)

    def _describe_encoder(self) -> None:
        """Diz o que **vai** acontecer, não o que foi pedido.

        A escolha do usuário é uma preferência; quem decide é a máquina. Um
        diálogo que só ecoasse "NVIDIA (NVENC)" esconderia que o driver é antigo
        demais e que a exportação vai sair em software de qualquer forma.

        A resposta sai de uma sondagem que **codifica um quadro de verdade**, e
        isso custa até 3,4 s nesta máquina — o VAAPI daqui aborta o processo, e
        um aborto demora mais que uma recusa. Feita aqui, direto, esse tempo era
        de janela congelada: o diálogo abria travado, e o botão de testar de novo
        travava outra vez. Agora a sondagem corre fora, e a linha diz que está
        verificando enquanto isso — que é a resposta honesta nesse intervalo.
        """
        tools = find_tools()
        if tools is None or hwaccel.probes_ready(tools):
            self._show_encoder_state()
            return
        self._encoder_state.setText(strings.SETTINGS_ENCODER_TESTING)
        worker = HardwareProbeWorker(tools)
        worker.signals.done.connect(self._show_encoder_state)
        self._runner.start(worker, worker.signals.done)

    def _show_encoder_state(self) -> None:
        escolha = self._encoder.currentData() or hwaccel.SOFTWARE
        self._encoder_state.setText(hwaccel.describe(escolha, find_tools()))

    def _retest_encoder(self) -> None:
        """Refaz as sondagens: driver atualizado ou placa liberada mudam a resposta."""
        hwaccel.forget_probes()
        self._describe_encoder()

    def _align_label_column(self) -> None:
        width = max((label.sizeHint().width() for label in self._labels), default=0)
        for label in self._labels:
            label.setMinimumWidth(width)

    def _build_general(self) -> QWidget:
        page, form = self._make_page()

        row = QHBoxLayout()
        # Sem margem própria: com ela a linha do destino terminava antes das
        # outras da mesma coluna.
        row.setContentsMargins(0, 0, 0, 0)
        self._dest = QLineEdit(self._settings.download_dir)
        row.addWidget(self._dest, 1)
        browse = QPushButton(strings.DEST_BROWSE)
        browse.clicked.connect(self._choose_dir)
        row.addWidget(browse)
        self._add_row(form, strings.SETTINGS_DEST, row)

        self._separate = QCheckBox(strings.SETTINGS_SEPARATE_BY_SITE)
        self._separate.setChecked(self._settings.separate_by_site)
        self._add_check(form, self._separate)

        self._theme = QComboBox()
        self._theme.addItem(strings.THEME_DARK, "dark")
        self._theme.addItem(strings.THEME_LIGHT, "light")
        self._theme.setCurrentIndex(max(0, self._theme.findData(self._settings.theme)))
        self._theme.setFixedWidth(FIELD_WIDTH)
        self._add_row(form, strings.SETTINGS_THEME, self._theme)

        self._encoder = QComboBox()
        for value, label in hwaccel.CHOICES:
            self._encoder.addItem(label, value)
        self._encoder.setCurrentIndex(
            max(0, self._encoder.findData(self._settings.hardware_encoder))
        )
        self._encoder.setFixedWidth(FIELD_WIDTH)
        self._encoder.setToolTip(strings.SETTINGS_ENCODER_TIP)
        self._encoder.currentIndexChanged.connect(self._describe_encoder)
        self._add_row(form, strings.SETTINGS_ENCODER, self._encoder)

        # O resultado do teste fica na linha de baixo, e não numa dica: é a
        # resposta à única pergunta que importa aqui — "a minha placa vai ser
        # usada?" —, e ela depende da máquina, não da escolha.
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self._encoder_state = QLabel("")
        self._encoder_state.setProperty("role", "dim")
        self._encoder_state.setWordWrap(True)
        row.addWidget(self._encoder_state, 1)
        test = QPushButton(strings.SETTINGS_ENCODER_TEST)
        test.setToolTip(strings.SETTINGS_ENCODER_TEST_TIP)
        test.clicked.connect(self._retest_encoder)
        row.addWidget(test)
        form.addRow(row)
        self._describe_encoder()

        return page

    def _build_network(self) -> QWidget:
        page, form = self._make_page()

        self._concurrent = QSpinBox()
        self._concurrent.setRange(1, 10)
        self._concurrent.setValue(self._settings.max_concurrent_jobs)
        self._add_row(form, strings.SETTINGS_CONCURRENT, self._concurrent)

        self._fragments = QSpinBox()
        self._fragments.setRange(1, 16)
        self._fragments.setValue(self._settings.concurrent_fragments)
        self._add_row(form, strings.SETTINGS_FRAGMENTS, self._fragments)

        self._rate = QSpinBox()
        self._rate.setRange(0, 1_000_000)
        self._rate.setSingleStep(256)
        self._rate.setValue(self._settings.rate_limit_kbps)
        self._add_row(form, strings.SETTINGS_RATE_LIMIT, self._rate)

        for spin in (self._concurrent, self._fragments, self._rate):
            spin.setFixedWidth(_NUMBER_WIDTH)

        self._cookies = QComboBox()
        self._cookies.addItem(strings.SETTINGS_COOKIES_NONE, "")
        for browser in sorted(SUPPORTED_BROWSERS):
            self._cookies.addItem(browser.capitalize(), browser)
        self._cookies.setCurrentIndex(
            max(0, self._cookies.findData(self._settings.cookies_browser))
        )
        self._cookies.setToolTip(strings.SETTINGS_COOKIES_TIP)
        self._cookies.setFixedWidth(FIELD_WIDTH)
        self._add_row(form, strings.SETTINGS_COOKIES, self._cookies)

        return page

    def _build_subs(self) -> QWidget:
        page, form = self._make_page()

        self._embed_thumb = QCheckBox(strings.SETTINGS_EMBED_THUMB)
        self._embed_thumb.setChecked(self._settings.embed_thumbnail)
        self._add_check(form, self._embed_thumb)

        self._embed_meta = QCheckBox(strings.SETTINGS_EMBED_META)
        self._embed_meta.setChecked(self._settings.embed_metadata)
        self._add_check(form, self._embed_meta)

        self._write_subs = QCheckBox(strings.SETTINGS_WRITE_SUBS)
        self._write_subs.setChecked(self._settings.write_subtitles)
        self._add_check(form, self._write_subs)

        self._embed_subs = QCheckBox(strings.SETTINGS_EMBED_SUBS)
        self._embed_subs.setChecked(self._settings.embed_subtitles)
        self._add_check(form, self._embed_subs)

        self._auto_subs = QCheckBox(strings.SETTINGS_AUTO_SUBS)
        self._auto_subs.setChecked(self._settings.include_auto_subtitles)
        self._add_check(form, self._auto_subs)

        self._sub_langs = QLineEdit(", ".join(self._settings.subtitle_langs))
        self._add_row(form, strings.SETTINGS_SUB_LANGS, self._sub_langs)

        return page

    def _choose_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, strings.SETTINGS_DEST, self._dest.text() or str(Path.home())
        )
        if chosen:
            self._dest.setText(chosen)

    # ------------------------------------------------------------------

    def result_settings(self) -> Settings:
        """Novas preferências a partir dos campos, sem alterar as antigas."""
        langs = [
            part.strip()
            for part in self._sub_langs.text().split(",")
            if part.strip()
        ]
        updated = Settings(**{**self._settings.__dict__})
        updated.download_dir = self._dest.text().strip() or self._settings.download_dir
        updated.separate_by_site = self._separate.isChecked()
        updated.theme = self._theme.currentData() or "dark"
        updated.hardware_encoder = (
            self._encoder.currentData() or hwaccel.SOFTWARE
        )
        updated.max_concurrent_jobs = self._concurrent.value()
        updated.concurrent_fragments = self._fragments.value()
        updated.rate_limit_kbps = self._rate.value()
        updated.cookies_browser = self._cookies.currentData() or ""
        updated.embed_thumbnail = self._embed_thumb.isChecked()
        updated.embed_metadata = self._embed_meta.isChecked()
        updated.write_subtitles = self._write_subs.isChecked()
        updated.embed_subtitles = self._embed_subs.isChecked()
        updated.include_auto_subtitles = self._auto_subs.isChecked()
        updated.subtitle_langs = langs or self._settings.subtitle_langs
        return updated
