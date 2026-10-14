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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from videomanager.application import encoding as hwaccel
from videomanager.application.capabilities import FFmpegTools
from videomanager.application.preferences import Preferences as Settings
from videomanager.application.preferences import RANGES
from videomanager.presentation.qt.tasks import WorkerRunner
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.arrow_spin import ArrowSpinBox
from videomanager.presentation.qt.i18n import align_label_column
from videomanager.presentation.qt.palette_picker import SeletorDePaleta
from videomanager.presentation.qt.theme import FIELD_WIDTH
from videomanager.presentation.qt.ports import DesktopRuntimePort

# Campos numéricos são curtos; esticá-los pela largura do diálogo deixaria uma
# caixa de 400 px para escrever "3".
_NUMBER_WIDTH = 110


class SettingsDialog(QDialog):
    """Edita as preferências. Grava só quando o usuário confirma."""

    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        *,
        runtime: DesktopRuntimePort,
        tools: FFmpegTools | None = None,
    ) -> None:
        super().__init__(parent)
        self._runtime = runtime
        self._tools = tools
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
        tabs.tabBar().setProperty("role", "underline")
        tabs.addTab(self._build_general(), strings.SETTINGS_TAB_GENERAL)
        tabs.addTab(self._build_theme(), strings.SETTINGS_TAB_THEME)
        tabs.addTab(self._build_network(), strings.SETTINGS_TAB_NETWORK)
        tabs.addTab(self._build_subs(), strings.SETTINGS_TAB_SUBS)
        self._align_label_column()
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "primary")
        layout.addWidget(buttons)
        # Sem foco inicial, o Qt entrega o foco ao primeiro da ordem de Tab — a barra de abas — ao ativar o
        # diálogo, e "Geral" abria com a borda de foco, como se Tab já tivesse sido apertado. O foco nasce no
        # próprio diálogo, que não desenha nada: o Tab continua alcançando a barra (como em ``MainWindow``).
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setFocus()

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

    @staticmethod
    def _add_heading(form: QFormLayout, text: str) -> None:
        """Título de um grupo de campos: "DOWNLOADS", "VÍDEO"… Só agrupa, não guarda nada."""
        heading = QLabel(text.upper())
        heading.setProperty("role", "group-heading")
        form.addRow(heading)

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
        tools = self._runtime.find_tools()
        if tools is None or self._runtime.hardware_ready(tools):
            self._show_encoder_state()
            return
        self._encoder_state.setText(strings.SETTINGS_ENCODER_TESTING)
        worker = self._runtime.hardware_worker(tools)
        worker.signals.done.connect(self._show_encoder_state)
        self._runner.start(worker, worker.signals.done)

    def _show_encoder_state(self) -> None:
        escolha = self._encoder.currentData() or hwaccel.SOFTWARE
        self._encoder_state.setText(self._runtime.hardware_description(escolha, self._runtime.find_tools()))

    def _retest_encoder(self) -> None:
        """Refaz as sondagens: driver atualizado ou placa liberada mudam a resposta."""
        self._runtime.reset_hardware()
        self._describe_encoder()

    def _align_label_column(self) -> None:
        align_label_column(self._labels)

    def _build_general(self) -> QWidget:
        page, form = self._make_page()

        self._add_heading(form, strings.SETTINGS_GROUP_DOWNLOADS)
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

        self._add_heading(form, strings.SETTINGS_GROUP_LANGUAGE)
        self._language = QComboBox()
        for code, name in strings.LANGUAGE_NAMES.items():
            self._language.addItem(name, code)
        self._language.setCurrentIndex(max(0, self._language.findData(self._settings.language)))
        self._language.setFixedWidth(FIELD_WIDTH)
        self._add_row(form, strings.SETTINGS_LANGUAGE, self._language)

        self._add_heading(form, strings.SETTINGS_GROUP_VIDEO)
        self._encoder = QComboBox()
        for value, label in hwaccel.choices():
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
        self._add_row(form, strings.SETTINGS_FFMPEG, self._build_ffmpeg_info())

        return page

    def _build_ffmpeg_info(self) -> QVBoxLayout:
        """De onde veio o ffmpeg em uso e onde ele está.

        Mora ao lado da codificação porque as duas linhas respondem à mesma pergunta: com o que este
        aplicativo vai codificar. Era a única coisa que a barra de status dizia só ali, em português de
        uma palavra ("ffmpeg: sistema"), e só enquanto a janela estava aberta.
        """
        coluna = QVBoxLayout()
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(2)
        if self._tools is None:
            origem, caminho = strings.SETTINGS_FFMPEG_UNKNOWN, ""
        else:
            origem = strings.FFMPEG_SOURCES.get(self._tools.source, self._tools.source)
            caminho = str(self._tools.ffmpeg)
        self._ffmpeg_source = QLabel(origem)
        self._ffmpeg_source.setWordWrap(True)
        coluna.addWidget(self._ffmpeg_source)
        self._ffmpeg_path = QLabel(caminho)
        self._ffmpeg_path.setProperty("role", "dim")
        self._ffmpeg_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._ffmpeg_path.setWordWrap(True)
        self._ffmpeg_path.setVisible(bool(caminho))
        coluna.addWidget(self._ffmpeg_path)
        return coluna

    def _build_theme(self) -> QWidget:
        """Modo (escuro ou claro) e paleta: as duas escolhas que definem as cores do aplicativo."""
        page, form = self._make_page()

        self._theme = QComboBox()
        self._theme.addItem(strings.THEME_DARK, "dark")
        self._theme.addItem(strings.THEME_LIGHT, "light")
        self._theme.setCurrentIndex(max(0, self._theme.findData(self._settings.theme)))
        self._theme.setFixedWidth(FIELD_WIDTH)
        self._add_row(form, strings.SETTINGS_THEME_MODE, self._theme)

        self._add_heading(form, strings.SETTINGS_PALETTE)
        self._palette_picker = SeletorDePaleta(self._settings.palette, self._settings.theme)
        form.addRow(self._palette_picker)
        hint = QLabel(strings.SETTINGS_PALETTE_HINT)
        hint.setProperty("role", "dim")
        hint.setWordWrap(True)
        form.addRow(hint)
        # As miniaturas mostram a paleta no modo escolhido, antes de confirmar.
        self._theme.currentIndexChanged.connect(
            lambda _index: self._palette_picker.set_mode(self._theme.currentData() or "dark"))
        return page

    def _build_network(self) -> QWidget:
        page, form = self._make_page()

        self._add_heading(form, strings.SETTINGS_GROUP_SPEED)
        self._concurrent = ArrowSpinBox()
        self._concurrent.setRange(*RANGES["max_concurrent_jobs"])
        self._concurrent.setValue(self._settings.max_concurrent_jobs)
        self._add_row(form, strings.SETTINGS_CONCURRENT, self._concurrent)

        self._fragments = ArrowSpinBox()
        self._fragments.setRange(*RANGES["concurrent_fragments"])
        self._fragments.setValue(self._settings.concurrent_fragments)
        self._add_row(form, strings.SETTINGS_FRAGMENTS, self._fragments)

        self._rate = ArrowSpinBox()
        self._rate.setRange(*RANGES["rate_limit_kbps"])
        self._rate.setSingleStep(256)
        self._rate.setValue(self._settings.rate_limit_kbps)
        self._add_row(form, strings.SETTINGS_RATE_LIMIT, self._rate)

        for spin in (self._concurrent, self._fragments, self._rate):
            spin.setFixedWidth(_NUMBER_WIDTH)

        self._add_heading(form, strings.SETTINGS_GROUP_COOKIES)
        self._cookies = QComboBox()
        self._cookies.addItem(strings.SETTINGS_COOKIES_NONE, "")
        for browser in sorted(self._runtime.cookie_browsers):
            self._cookies.addItem(browser.capitalize(), browser)
        self._cookies.setCurrentIndex(
            max(0, self._cookies.findData(self._settings.cookies_browser))
        )
        self._cookies.setToolTip(strings.SETTINGS_COOKIES_TIP)
        self._cookies.setFixedWidth(FIELD_WIDTH)
        self._add_row(form, strings.SETTINGS_COOKIES, self._cookies)

        cookie_file_row = QHBoxLayout()
        cookie_file_row.setContentsMargins(0, 0, 0, 0)
        self._cookies_file = QLineEdit(self._settings.cookies_file)
        self._cookies_file.setPlaceholderText(strings.SETTINGS_COOKIES_FILE_PLACEHOLDER)
        self._cookies_file.setToolTip(strings.SETTINGS_COOKIES_FILE_TIP)
        cookie_file_row.addWidget(self._cookies_file, 1)
        browse_cookies = QPushButton(strings.SETTINGS_COOKIES_FILE_BROWSE)
        browse_cookies.clicked.connect(self._choose_cookies_file)
        cookie_file_row.addWidget(browse_cookies)
        self._add_row(form, strings.SETTINGS_COOKIES_FILE, cookie_file_row)

        return page

    def _build_subs(self) -> QWidget:
        page, form = self._make_page()

        self._add_heading(form, strings.SETTINGS_GROUP_FILE)
        self._embed_thumb = QCheckBox(strings.SETTINGS_EMBED_THUMB)
        self._embed_thumb.setChecked(self._settings.embed_thumbnail)
        self._add_check(form, self._embed_thumb)

        self._embed_meta = QCheckBox(strings.SETTINGS_EMBED_META)
        self._embed_meta.setChecked(self._settings.embed_metadata)
        self._add_check(form, self._embed_meta)

        self._add_heading(form, strings.SETTINGS_GROUP_SUBS)
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

    def _choose_cookies_file(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            strings.SETTINGS_COOKIES_FILE,
            self._cookies_file.text() or str(Path.home()),
            strings.SETTINGS_COOKIES_FILTER,
        )
        if chosen:
            self._cookies_file.setText(chosen)

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
        updated.palette = self._palette_picker.palette()
        updated.language = self._language.currentData() or self._settings.language
        updated.hardware_encoder = (
            self._encoder.currentData() or hwaccel.SOFTWARE
        )
        updated.max_concurrent_jobs = self._concurrent.value()
        updated.concurrent_fragments = self._fragments.value()
        updated.rate_limit_kbps = self._rate.value()
        updated.cookies_browser = self._cookies.currentData() or ""
        updated.cookies_file = self._cookies_file.text().strip()
        updated.embed_thumbnail = self._embed_thumb.isChecked()
        updated.embed_metadata = self._embed_meta.isChecked()
        updated.write_subtitles = self._write_subs.isChecked()
        updated.embed_subtitles = self._embed_subs.isChecked()
        updated.include_auto_subtitles = self._auto_subs.isChecked()
        updated.subtitle_langs = langs or self._settings.subtitle_langs
        return updated
