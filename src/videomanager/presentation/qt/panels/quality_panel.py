"""Controles de qualidade, ligados à matriz de formatos da mídia analisada.

Os combos são **populados a partir do que a mídia realmente oferece**, e não de
uma lista fixa. É a diferença entre oferecer "4K" num vídeo que só tem 480p — e
falhar no download — e mostrar só o que existe.

Os combos são em cascata: trocar a resolução repopula framerate e codec, porque a
disponibilidade depende da resolução (é comum haver 4K só em VP9/AV1 e 1080p
também em H.264).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from videomanager.domain.estimator import estimate_download_size
from videomanager.domain.format_policy import available_families
from videomanager.domain.format_policy import available_fps
from videomanager.domain.format_policy import available_heights
from videomanager.domain.format_policy import find_video
from videomanager.application.formatting import format_bitrate
from videomanager.application.formatting import format_size
from videomanager.domain.formats import AudioChoice
from videomanager.domain.formats import FormatMatrix
from videomanager.domain.formats import Mode
from videomanager.domain.formats import VideoChoice
from videomanager.domain.selection import AUDIO_BITRATES
from videomanager.domain.selection import AUDIO_CODECS
from videomanager.domain.selection import CONTAINER_AUTO
from videomanager.domain.selection import CONTAINERS
from videomanager.domain.selection import LOSSLESS_AUDIO
from videomanager.domain.selection import AudioRequest
from videomanager.domain.selection import VideoRequest
from videomanager.application.media.download_policy import audio_quality_warning
from videomanager.application.media.download_policy import plan_container
from videomanager.application.preferences import Preferences as Settings
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.theme import FIELD_WIDTH
from videomanager.application.format_labels import resolution_label
from videomanager.application.format_labels import choice_label

_BEST_AVAILABLE = "Melhor disponível"


def _make_form(parent: QWidget | None = None) -> QFormLayout:
    form = QFormLayout(parent)
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(6)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return form


class QualityPanel(QWidget):
    """Escolha de modo (vídeo/áudio) e de todos os parâmetros de qualidade."""

    changed = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._matrix = FormatMatrix()
        # Evita reentrância: repopular um combo emite currentIndexChanged, que
        # dispararia a repopulação de novo em cascata.
        self._loading = False
        # Todos os rótulos de formulário do painel. Recebem no fim a mesma
        # largura mínima: sem isso cada formulário calcula a sua própria coluna
        # de rótulos, e trocar de vídeo para áudio desloca os campos de lado.
        self._labels: list[QLabel] = []
        # O que o usuário pediu, e não o que o combo mostra agora: o combo é
        # repopulado a cada troca de resolução e perde a escolha quando ela não
        # existe na resolução nova. Guardar o pedido é o que permite repô-lo
        # depois e avisar quando esta mídia não puder atendê-lo.
        self._wanted_family: str | None = None
        self._wanted_fps: int | None = None
        self._duration: float | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_group())
        layout.addStretch(1)

        self._align_label_column()
        self.set_matrix(FormatMatrix())

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def _build_group(self) -> QGroupBox:
        """Modo, controles do modo e avisos, num grupo só.

        Um grupo separado só para as duas opções de modo custava uma faixa
        inteira de altura — moldura, título e margens — que a fila aproveita
        melhor. Juntos, o rótulo "O que baixar" ainda divide a coluna de rótulos
        com os campos que ele comanda.
        """
        group = QGroupBox(strings.QUALITY_GROUP)
        outer = QVBoxLayout(group)
        outer.setSpacing(8)

        mode_form = _make_form()
        box = QHBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(18)
        self._radio_video = QRadioButton(strings.MODE_VIDEO)
        self._radio_audio = QRadioButton(strings.MODE_AUDIO)
        # Grupo explícito: a exclusividade entre botões de rádio vale por widget
        # pai, e depender do pai quebraria calado se outro rádio aparecesse
        # neste mesmo grupo um dia.
        self._modes = QButtonGroup(self)
        self._modes.addButton(self._radio_video)
        self._modes.addButton(self._radio_audio)
        self._radio_video.setChecked(True)
        self._radio_video.toggled.connect(self._on_mode_changed)
        box.addWidget(self._radio_video)
        box.addWidget(self._radio_audio)
        box.addStretch(1)
        self._add_row(mode_form, strings.MODE_LABEL, box)
        outer.addLayout(mode_form)

        self._stack = QStackedWidget()
        self._stack.setProperty("role", "plain")
        self._stack.addWidget(self._build_video_page())
        self._stack.addWidget(self._build_audio_page())
        outer.addWidget(self._stack)

        self._warning = QLabel("")
        self._warning.setProperty("role", "warn")
        self._warning.setWordWrap(True)
        self._warning.setVisible(False)
        outer.addWidget(self._warning)

        return group

    def _add_row(
        self, form: QFormLayout, text: str, field: QWidget | QLayout
    ) -> QLabel:
        """Adiciona uma linha guardando o rótulo, para alinhá-lo depois."""
        label = QLabel(text)
        self._labels.append(label)
        form.addRow(label, field)
        return label

    def _align_label_column(self) -> None:
        width = max(label.sizeHint().width() for label in self._labels)
        for label in self._labels:
            label.setMinimumWidth(width)

    def _build_video_page(self) -> QWidget:
        page = QWidget()
        page.setProperty("role", "plain")
        form = _make_form(page)

        self._resolution = QComboBox()
        self._resolution.setToolTip(strings.TIP_RESOLUTION)
        self._resolution.currentIndexChanged.connect(self._on_resolution_changed)
        self._add_row(form, strings.LABEL_RESOLUTION, self._resolution)

        self._fps = QComboBox()
        self._fps.currentIndexChanged.connect(self._on_fps_changed)
        self._add_row(form, strings.LABEL_FPS, self._fps)

        self._codec = QComboBox()
        self._codec.setToolTip(strings.TIP_CODEC)
        self._codec.currentIndexChanged.connect(self._on_codec_changed)
        self._add_row(form, strings.LABEL_CODEC, self._codec)

        self._container = QComboBox()
        self._container.setToolTip(strings.TIP_CONTAINER)
        for value in CONTAINERS:
            label = strings.CONTAINER_AUTO_LABEL if value == CONTAINER_AUTO else f".{value}"
            self._container.addItem(label, value)
        index = self._container.findData(self._settings.default_container)
        self._container.setCurrentIndex(max(0, index))
        self._container.currentIndexChanged.connect(self._emit_changed)
        self._add_row(form, strings.LABEL_CONTAINER, self._container)

        self._audio_track = QComboBox()
        self._audio_track.currentIndexChanged.connect(self._emit_changed)
        self._audio_track_label = self._add_row(
            form, strings.LABEL_AUDIO_TRACK, self._audio_track
        )

        self._video_size_label = QLabel("—")
        self._video_size_label.setProperty("role", "dim")
        self._add_row(form, strings.LABEL_ESTIMATED_SIZE, self._video_size_label)

        for combo in (self._resolution, self._fps, self._codec, self._container, self._audio_track):
            combo.setFixedWidth(FIELD_WIDTH)
        return page

    def _build_audio_page(self) -> QWidget:
        page = QWidget()
        page.setProperty("role", "plain")
        form = _make_form(page)

        self._audio_codec = QComboBox()
        self._audio_codec.setToolTip(strings.TIP_AUDIO_FORMAT)
        for codec in AUDIO_CODECS:
            label = strings.AUDIO_CODEC_BEST if codec == "best" else codec.upper()
            self._audio_codec.addItem(label, codec)
        index = self._audio_codec.findData(self._settings.default_audio_format)
        self._audio_codec.setCurrentIndex(max(0, index))
        self._audio_codec.currentIndexChanged.connect(self._on_audio_codec_changed)
        self._add_row(form, strings.LABEL_AUDIO_FORMAT, self._audio_codec)

        self._audio_quality = QComboBox()
        for value in AUDIO_BITRATES:
            self._audio_quality.addItem(f"{value} kbps", value)
        index = self._audio_quality.findData(self._settings.default_audio_quality)
        self._audio_quality.setCurrentIndex(max(0, index))
        self._audio_quality.currentIndexChanged.connect(self._emit_changed)
        self._add_row(form, strings.LABEL_AUDIO_QUALITY, self._audio_quality)

        self._audio_size_label = QLabel("—")
        self._audio_size_label.setProperty("role", "dim")
        self._add_row(form, strings.LABEL_ESTIMATED_SIZE, self._audio_size_label)

        # Sem rótulo, mas na coluna dos campos: é uma nota sobre o campo de cima.
        self._audio_source = QLabel("")
        self._audio_source.setProperty("role", "dim")
        self._audio_source.setMinimumWidth(FIELD_WIDTH)
        self._add_row(form, "", self._audio_source)

        for combo in (self._audio_codec, self._audio_quality):
            combo.setFixedWidth(FIELD_WIDTH)
        return page

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def mode(self) -> Mode:
        return Mode.AUDIO_ONLY if self._radio_audio.isChecked() else Mode.VIDEO

    def set_mode(self, mode: Mode) -> None:
        """Troca de modo, respeitando o que a mídia oferece.

        Marcar por código funciona mesmo num botão desabilitado, então sem esta
        guarda um perfil de vídeo aplicado a uma mídia só de áudio deixava a
        tela dizendo "Vídeo" numa mídia que não tem vídeo nenhum.
        """
        target = self._radio_audio if mode is Mode.AUDIO_ONLY else self._radio_video
        if target.isEnabled():
            target.setChecked(True)

    def set_matrix(
        self, matrix: FormatMatrix, duration: float | None = None
    ) -> None:
        """Repopula todos os combos a partir de uma mídia recém-analisada."""
        self._matrix = matrix
        self._duration = duration
        self._loading = True
        try:
            self._populate_resolutions()
            self._populate_dependent()
            self._populate_audio_tracks()
        finally:
            self._loading = False

        self._update_mode_availability(matrix)
        self._stack.setCurrentIndex(1 if self.mode is Mode.AUDIO_ONLY else 0)

        separate = matrix.needs_muxing
        self._audio_track.setVisible(separate)
        self._audio_track_label.setVisible(separate)

        self._update_audio_source_hint()
        self._refresh_warnings()
        self._update_estimated_size()

    def _update_mode_availability(self, matrix: FormatMatrix) -> None:
        """Desabilita o modo que esta mídia não oferece.

        Enquanto não há mídia analisada não há o que restringir, e as duas
        opções continuam clicáveis: desabilitar "Vídeo" numa tela em que nada
        foi analisado ainda só parecia defeito.
        """
        if matrix.is_empty:
            self._radio_video.setEnabled(True)
            self._radio_audio.setEnabled(True)
            return

        self._radio_video.setEnabled(matrix.has_video)
        self._radio_audio.setEnabled(matrix.has_audio)
        # Uma opção desabilitada continua marcada se ninguém trocar por ela: sem
        # isto a mídia só de áudio ficava no modo vídeo, que ela não tem.
        if not matrix.has_video and matrix.has_audio:
            self._radio_audio.setChecked(True)
        elif not matrix.has_audio and matrix.has_video:
            self._radio_video.setChecked(True)

    def _populate_resolutions(self) -> None:
        self._resolution.clear()
        self._resolution.addItem(_BEST_AVAILABLE, None)
        for height in available_heights(self._matrix):
            self._resolution.addItem(f"{height}p", height)
        # Opções sem altura conhecida (HLS) entram pelo rótulo próprio, que
        # mostra bitrate — não podem simplesmente desaparecer da lista.
        for choice in self._matrix.video:
            if choice.height is None:
                self._resolution.addItem(resolution_label(choice), resolution_label(choice))

        target = self._settings.default_height
        index = self._resolution.findData(target)
        self._resolution.setCurrentIndex(index if index >= 0 else 0)

    def _populate_dependent(self) -> None:
        """Repopula framerate e codec conforme a resolução selecionada.

        A escolha é reposta a partir do que o usuário pediu (``_wanted_*``), e
        não do que estava no combo: trocar de resolução repopula a lista, e
        reler o combo faria a escolha se perder para sempre na primeira
        resolução que não a oferecesse. Assim, pedir H.264, subir para 2160p —
        onde ele não existe — e voltar para 1080p traz o H.264 de volta.
        """
        height = self._selected_height()

        self._fps.clear()
        self._fps.addItem(strings.ANY_FPS, None)
        for value in available_fps(self._matrix, height):
            self._fps.addItem(f"{value} fps", value)
        index = self._fps.findData(self._wanted_fps)
        self._fps.setCurrentIndex(index if index >= 0 else 0)

        self._codec.clear()
        self._codec.addItem(strings.ANY_CODEC, None)
        for family in available_families(self._matrix, height):
            self._codec.addItem(family, family)
        index = self._codec.findData(self._wanted_family)
        self._codec.setCurrentIndex(index if index >= 0 else 0)

    def _populate_audio_tracks(self) -> None:
        self._audio_track.clear()
        self._audio_track.addItem(_BEST_AVAILABLE, None)
        for choice in self._matrix.audio:
            self._audio_track.addItem(choice_label(choice), choice)

    def _selected_height(self) -> int | None:
        data = self._resolution.currentData()
        return data if isinstance(data, int) else None

    # ------------------------------------------------------------------
    # Reações
    # ------------------------------------------------------------------

    def _on_mode_changed(self) -> None:
        self._stack.setCurrentIndex(1 if self.mode is Mode.AUDIO_ONLY else 0)
        self._emit_changed()

    def _on_resolution_changed(self) -> None:
        if self._loading:
            return
        self._loading = True
        try:
            self._populate_dependent()
        finally:
            self._loading = False
        self._emit_changed()

    def _on_codec_changed(self) -> None:
        # Só conta como pedido o que veio do usuário: repopular o combo também
        # dispara este sinal, e aí a escolha dele é que manda.
        if not self._loading:
            self._wanted_family = self._codec.currentData()
        self._emit_changed()

    def _on_fps_changed(self) -> None:
        if not self._loading:
            self._wanted_fps = self._fps.currentData()
        self._emit_changed()

    def _on_audio_codec_changed(self) -> None:
        codec = self._audio_codec.currentData()
        # Bitrate não se aplica a formato sem perda nem à cópia do original.
        applicable = codec not in LOSSLESS_AUDIO and codec != "best"
        self._audio_quality.setEnabled(applicable)
        self._emit_changed()

    def _emit_changed(self) -> None:
        if self._loading:
            return
        self._update_audio_source_hint()
        self._refresh_warnings()
        self._update_estimated_size()
        self.changed.emit()

    def _update_estimated_size(self) -> None:
        if self._matrix.is_empty:
            self._video_size_label.setText("—")
            self._audio_size_label.setText("—")
            return

        v_choice = self.current_video_choice()
        a_choice = self.current_audio_choice()
        v_bytes = estimate_download_size(
            self._matrix,
            Mode.VIDEO,
            v_choice,
            a_choice,
            duration=self._duration,
        )
        self._video_size_label.setText(format_size(v_bytes, estimated=True))

        codec = self._audio_codec.currentData() or "mp3"
        quality = self._audio_quality.currentData() or "192"
        a_bytes = estimate_download_size(
            self._matrix,
            Mode.AUDIO_ONLY,
            None,
            a_choice,
            audio_codec=codec,
            audio_quality=quality,
            duration=self._duration,
        )
        self._audio_size_label.setText(format_size(a_bytes, estimated=True))

    def _update_audio_source_hint(self) -> None:
        best = self._matrix.best_audio_bitrate
        self._audio_source.setText(
            strings.AUDIO_SOURCE_INFO.format(bitrate=format_bitrate(best)) if best else ""
        )

    def _refresh_warnings(self) -> None:
        """Mostra, antes de baixar, o que a escolha atual implica.

        Avisar aqui — e não depois — é o que permite ao usuário mudar de ideia
        sem ter desperdiçado um download.
        """
        messages: list[str] = []

        if self.mode is Mode.AUDIO_ONLY:
            codec = self._audio_codec.currentData() or "mp3"
            quality = self._audio_quality.currentData() or "192"
            warning = audio_quality_warning(self._matrix, codec, quality)
            if warning:
                messages.append(warning)
            choice = self.current_audio_choice()
            if choice is not None and choice.is_extracted_from_video:
                messages.append(
                    "Esta mídia não separa as trilhas: será preciso baixar o "
                    "vídeo inteiro e extrair o áudio dele."
                )
        else:
            video = self.current_video_choice()
            if video is not None:
                messages.extend(self._codec_warnings(video))
                plan = plan_container(
                    self._matrix, video, self.current_audio_choice(),
                    self._container.currentData() or CONTAINER_AUTO,
                )
                messages.extend(plan.warnings)

        self._warning.setText("\n".join(f"• {m}" for m in messages))
        self._warning.setVisible(bool(messages))

    def _codec_warnings(self, video: VideoChoice) -> list[str]:
        """Diz em voz alta o que o codec pedido custa nesta mídia.

        Acima de 1080p é comum não existir H.264 — o YouTube só entrega 1440p e
        2160p em VP9 e AV1. Antes, quem pedia H.264 nessas resoluções recebia
        AV1 sem nenhum aviso; o combo até voltava sozinho para "Qualquer".
        """
        wanted = self._wanted_family
        if not wanted:
            return []

        with_family = [
            c.height for c in self._matrix.video if c.family == wanted and c.height
        ]
        reach = max(with_family) if with_family else None

        if video.family != wanted:
            if reach is None:
                return [f"Esta mídia não tem {wanted}: será baixado {video.family}."]
            return [
                f"Esta mídia não tem {wanted} em {resolution_label(video)}: será "
                f"baixado {video.family}. Com {wanted}, a maior resolução "
                f"disponível é {reach}p."
            ]

        # O codec foi atendido, mas pode ser ele que está limitando a resolução
        # de quem pediu "Melhor disponível".
        top = max((c.height for c in self._matrix.video if c.height), default=None)
        if (
            self._resolution.currentData() is None
            and reach is not None
            and top is not None
            and reach < top
        ):
            return [
                f"{wanted} nesta mídia vai até {reach}p. Há {top}p, mas só em "
                "outros codecs."
            ]
        return []

    # ------------------------------------------------------------------
    # Leitura do pedido
    # ------------------------------------------------------------------

    def current_video_choice(self) -> VideoChoice | None:
        if not self._matrix.has_video:
            return None
        data = self._resolution.currentData()
        if isinstance(data, str):
            # Opção sem altura conhecida, identificada pelo próprio rótulo. Ela
            # já é um stream concreto: não há codec nem framerate a combinar.
            return next(
                (c for c in self._matrix.video if resolution_label(c) == data),
                self._matrix.video[0],
            )
        # ``data`` é a altura escolhida, ou None em "Melhor disponível" — que
        # significa "a maior resolução", e não "ignore o resto do formulário":
        # sem passar codec e framerate adiante, pedir H.264 e receber o AV1 de
        # 2160p era o resultado normal.
        return find_video(
            self._matrix,
            height=data,
            fps=self._fps.currentData(),
            family=self._codec.currentData(),
        )

    def current_audio_choice(self) -> AudioChoice | None:
        data = self._audio_track.currentData()
        if isinstance(data, AudioChoice):
            return data
        return self._matrix.audio[0] if self._matrix.audio else None

    def build_request(self) -> VideoRequest | AudioRequest:
        """Traduz o estado dos controles no pedido que o seletor consome."""
        if self.mode is Mode.AUDIO_ONLY:
            return AudioRequest(
                audio=self.current_audio_choice(),
                codec=self._audio_codec.currentData() or "mp3",
                quality=self._audio_quality.currentData() or "192",
            )
        return VideoRequest(
            video=self.current_video_choice(),
            audio=self.current_audio_choice(),
            container=self._container.currentData() or CONTAINER_AUTO,
        )

    def build_batch_request(
        self, max_height: int | None
    ) -> VideoRequest | AudioRequest:
        """Pedido para itens ainda não analisados, como os de uma playlist.

        Sem streams concretos — cada item oferece formatos próprios, e um id
        fixo não valeria para todos —, mas com o formato e a qualidade que
        estão na tela. Antes isto era montado com os padrões das Configurações,
        e escolher FLAC no painel ainda baixava o MP3 do padrão.
        """
        if self.mode is Mode.AUDIO_ONLY:
            return AudioRequest(
                audio=None,
                codec=self._audio_codec.currentData() or "mp3",
                quality=self._audio_quality.currentData() or "192",
            )
        return VideoRequest(
            video=None,
            audio=None,
            container=self._container.currentData() or CONTAINER_AUTO,
            max_height=max_height,
        )

    # ------------------------------------------------------------------
    # Perfis rápidos
    # ------------------------------------------------------------------

    def apply_profile(
        self,
        *,
        mode: Mode,
        height: int | None = None,
        container: str = CONTAINER_AUTO,
        audio_codec: str = "mp3",
        audio_quality: str = "320",
    ) -> None:
        """Configura os controles conforme um perfil rápido.

        Aplicar no painel — em vez de montar um pedido por baixo — deixa visível
        o que o perfil escolheu, e o usuário pode ajustar a partir dali.
        """
        self._loading = True
        try:
            self.set_mode(mode)
            # O modo que valeu pode não ser o pedido: numa mídia só de áudio,
            # um perfil de vídeo não tem como ser atendido. O resto do perfil
            # segue o modo que ficou, e não o que foi pedido.
            mode = self.mode
            if mode is Mode.VIDEO:
                index = self._resolution.findData(height) if height else 0
                if index < 0:
                    # A mídia não tem a resolução do perfil: usa a melhor que
                    # respeite o limite, em vez de não fazer nada.
                    available = [h for h in available_heights(self._matrix) if not height or h <= height]
                    index = self._resolution.findData(available[0]) if available else 0
                self._resolution.setCurrentIndex(max(0, index))
                self._populate_dependent()
                container_index = self._container.findData(container)
                self._container.setCurrentIndex(max(0, container_index))
            else:
                codec_index = self._audio_codec.findData(audio_codec)
                self._audio_codec.setCurrentIndex(max(0, codec_index))
                quality_index = self._audio_quality.findData(audio_quality)
                self._audio_quality.setCurrentIndex(max(0, quality_index))
                applicable = audio_codec not in LOSSLESS_AUDIO and audio_codec != "best"
                self._audio_quality.setEnabled(applicable)
        finally:
            self._loading = False
        self._stack.setCurrentIndex(1 if mode is Mode.AUDIO_ONLY else 0)
        self._emit_changed()
