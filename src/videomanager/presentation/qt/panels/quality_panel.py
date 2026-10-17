"""Controles de qualidade, ligados à matriz de formatos da mídia analisada.

Os combos são **populados a partir do que a mídia realmente oferece**, e não de
uma lista fixa. É a diferença entre oferecer "4K" num vídeo que só tem 480p — e
falhar no download — e mostrar só o que existe.

Os combos são em cascata: trocar a resolução repopula framerate e codec, porque a
disponibilidade depende da resolução (é comum haver 4K só em VP9/AV1 e 1080p
também em H.264).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QLabel,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from videomanager.domain.estimator import video_only_kbps
from videomanager.domain.estimator import estimate_download_size
from videomanager.domain.format_policy import available_families
from videomanager.domain.format_policy import available_fps
from videomanager.domain.format_policy import available_heights
from videomanager.domain.format_policy import find_video
from videomanager.application.formatting import DASH
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
from videomanager.domain.selection import keeps_source
from videomanager.domain.selection import VIDEO_BITRATE_MAX
from videomanager.domain.selection import VIDEO_BITRATE_MIN
from videomanager.domain.selection import VIDEO_BITRATE_PRESETS
from videomanager.domain.selection import AudioRequest
from videomanager.domain.selection import VideoRequest
from videomanager.application.media.download_policy import audio_quality_warning
from videomanager.application.media.download_policy import plan_container
from videomanager.application.preferences import Preferences as Settings
from videomanager.presentation.qt import icons, strings
from videomanager.presentation.qt.i18n import bind, on_language_change, retext_items
from videomanager.presentation.qt.panels.fields import captioned, make_grid
from videomanager.presentation.qt.panels.segmented import SegmentButton, segmented
from videomanager.application.format_labels import resolution_label
from videomanager.application.format_labels import choice_label

# O dado do item "Personalizado…" do seletor de bitrate: o valor vem do campo ao lado.
_CUSTOM_BITRATE = "custom"
# O padrão do campo livre: um valor corrente para vídeo de 720p a 1080p.
_DEFAULT_CUSTOM_KBPS = 2500
# O dado do único item da trilha de áudio quando o áudio já vem dentro do vídeo: não há o que escolher.
_MUXED_TRACK = "muxed"


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

        self.set_matrix(FormatMatrix())
        on_language_change(self._retranslate)

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def _build_group(self) -> QFrame:
        """Modo, controles do modo e avisos, num grupo só.

        Um grupo separado só para as duas opções de modo custava uma faixa
        inteira de altura — moldura, título e margens — que a fila aproveita
        melhor. Juntos, o rótulo "O que baixar" ainda divide a coluna de rótulos
        com os campos que ele comanda.
        """
        # Sem título e sem moldura: o cartão "Personalizar" em volta já diz do que se trata.
        group = QFrame()
        group.setProperty("role", "plain")
        outer = QVBoxLayout(group)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # O seletor de modo não mora aqui: ele vai para o cabeçalho do cartão (``PersonalizeCard``), à direita do
        # título, como no protótipo. Os dois botões continuam sendo daqui, no mesmo grupo exclusivo.
        self._radio_video = bind(SegmentButton(glyph=icons.nav_edit), "setText", lambda: strings.MODE_VIDEO)
        self._radio_audio = bind(SegmentButton(glyph=icons.music), "setText", lambda: strings.MODE_AUDIO)
        # Grupo explícito: a exclusividade entre botões de rádio vale por widget
        # pai, e depender do pai quebraria calado se outro rádio aparecesse
        # neste mesmo grupo um dia.
        self._modes = QButtonGroup(self)
        self._modes.addButton(self._radio_video)
        self._modes.addButton(self._radio_audio)
        self._radio_video.setChecked(True)
        self._radio_video.toggled.connect(self._on_mode_changed)
        self.mode_selector = segmented([self._radio_video, self._radio_audio])
        bind(self.mode_selector, "setAccessibleName", lambda: strings.MODE_LABEL)

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

    def _retranslate(self) -> None:
        # Os itens que vêm do catálogo trocam de texto; o dado e a escolha
        # ficam. As medidas e os avisos dependem do texto, e são refeitos.
        retext_items(self._resolution, lambda data: strings.QUALITY_BEST_AVAILABLE if data is None
                     else resolution_label(data) if isinstance(data, VideoChoice) else None)
        retext_items(self._fps, lambda data: strings.ANY_FPS if data is None else None)
        retext_items(self._codec, lambda data: strings.ANY_CODEC if data is None else None)
        retext_items(self._container, lambda data: strings.CONTAINER_AUTO_LABEL if data == CONTAINER_AUTO else None)
        # Os valores prontos levam o separador decimal do idioma ("2,5 Mbps", "2.5 Mbps"): refeitos a cada troca.
        retext_items(self._bitrate, lambda data: self._bitrate_source_text() if data is None
                     else strings.VIDEO_BITRATE_CUSTOM if data == _CUSTOM_BITRATE else format_bitrate(data))
        retext_items(self._audio_codec, lambda data: strings.AUDIO_CODEC_BEST if data == "best" else None)
        for track in self._track_fields():
            retext_items(track, lambda data: strings.QUALITY_BEST_AVAILABLE if data is None
                         else strings.QUALITY_AUDIO_TRACK_MUXED if data == _MUXED_TRACK else choice_label(data))
        self._update_audio_source_hint()
        self._refresh_warnings()
        self._update_estimated_size()

    def _build_video_page(self) -> QWidget:
        page = QWidget()
        page.setProperty("role", "plain")
        grid = make_grid(page)

        self._resolution = bind(QComboBox(), "setToolTip", lambda: strings.TIP_RESOLUTION)
        self._resolution.currentIndexChanged.connect(self._on_resolution_changed)
        grid.addWidget(captioned(lambda: strings.LABEL_RESOLUTION, self._resolution), 0, 0)

        self._fps = QComboBox()
        self._fps.currentIndexChanged.connect(self._on_fps_changed)
        grid.addWidget(captioned(lambda: strings.LABEL_FPS, self._fps), 0, 1)

        self._codec = bind(QComboBox(), "setToolTip", lambda: strings.TIP_CODEC)
        self._codec.currentIndexChanged.connect(self._on_codec_changed)
        grid.addWidget(captioned(lambda: strings.LABEL_CODEC, self._codec), 0, 2)

        self._container = bind(QComboBox(), "setToolTip", lambda: strings.TIP_CONTAINER)
        for value in CONTAINERS:
            label = strings.CONTAINER_AUTO_LABEL if value == CONTAINER_AUTO else f".{value}"
            self._container.addItem(label, value)
        index = self._container.findData(self._settings.default_container)
        self._container.setCurrentIndex(max(0, index))
        self._container.currentIndexChanged.connect(self._emit_changed)
        grid.addWidget(captioned(lambda: strings.LABEL_CONTAINER, self._container), 1, 0)

        # Bitrate do vídeo: "igual ao da fonte" (não recodifica), um valor pronto ou um valor livre. Um número é o
        # consentimento de recodificar (ver ``VideoRequest.video_kbps``).
        self._bitrate = bind(QComboBox(), "setToolTip", lambda: strings.TIP_VIDEO_BITRATE)
        self._bitrate.addItem(self._bitrate_source_text(), None)
        for kbps in VIDEO_BITRATE_PRESETS:
            self._bitrate.addItem(format_bitrate(kbps), kbps)
        self._bitrate.addItem(strings.VIDEO_BITRATE_CUSTOM, _CUSTOM_BITRATE)
        self._bitrate.currentIndexChanged.connect(self._on_bitrate_changed)
        grid.addWidget(captioned(lambda: strings.LABEL_VIDEO_BITRATE, self._bitrate), 1, 1)

        # A trilha de áudio fica sempre à vista, na última coluna da fileira: some só a possibilidade de escolher, não o
        # campo. Escondê-lo quando o site entrega o áudio dentro do vídeo (ou antes de analisar qualquer mídia) fazia a
        # opção parecer perdida, e o campo aparecendo e sumindo mexia na grade a cada análise. Criados nesta ordem, o Tab
        # segue a leitura da grade.
        self._audio_track = QComboBox()
        self._audio_track.currentIndexChanged.connect(lambda index: self._on_track_changed(self._audio_track, index))
        self._audio_track_box = captioned(lambda: strings.LABEL_AUDIO_TRACK, self._audio_track)
        grid.addWidget(self._audio_track_box, 1, 2)

        # O valor livre só aparece quando "Personalizado…" está escolhido, numa fileira sua, sob o bitrate.
        self._bitrate_custom = QSpinBox()
        self._bitrate_custom.setRange(VIDEO_BITRATE_MIN, VIDEO_BITRATE_MAX)
        self._bitrate_custom.setSingleStep(100)
        self._bitrate_custom.setSuffix(" kbps")
        self._bitrate_custom.setValue(_DEFAULT_CUSTOM_KBPS)
        self._bitrate_custom.valueChanged.connect(self._emit_changed)
        self._bitrate_custom_box = captioned(lambda: strings.LABEL_VIDEO_BITRATE_VALUE, self._bitrate_custom)
        self._bitrate_custom_box.setVisible(False)
        grid.addWidget(self._bitrate_custom_box, 2, 1)

        # O tamanho estimado já aparece no rodapé da aba; o texto daqui só guarda o número (``estimated_size``).
        self._video_size_label = QLabel("—")
        return page

    def _build_audio_page(self) -> QWidget:
        page = QWidget()
        page.setProperty("role", "plain")
        grid = make_grid(page)

        self._audio_codec = bind(QComboBox(), "setToolTip", lambda: strings.TIP_AUDIO_FORMAT)
        for codec in AUDIO_CODECS:
            label = strings.AUDIO_CODEC_BEST if codec == "best" else codec.upper()
            self._audio_codec.addItem(label, codec)
        index = self._audio_codec.findData(self._settings.default_audio_format)
        self._audio_codec.setCurrentIndex(max(0, index))
        self._audio_codec.currentIndexChanged.connect(self._on_audio_codec_changed)
        grid.addWidget(captioned(lambda: strings.LABEL_AUDIO_FORMAT, self._audio_codec), 0, 0)

        self._audio_quality = QComboBox()
        for value in AUDIO_BITRATES:
            self._audio_quality.addItem(f"{value} kbps", value)
        index = self._audio_quality.findData(self._settings.default_audio_quality)
        self._audio_quality.setCurrentIndex(max(0, index))
        self._audio_quality.currentIndexChanged.connect(self._emit_changed)
        grid.addWidget(captioned(lambda: strings.LABEL_AUDIO_QUALITY, self._audio_quality), 0, 1)

        # A mesma escolha de trilha da página de vídeo, vista daqui: dois campos, uma escolha (``_on_track_changed``). Em
        # "Somente áudio" é o que decide qual stream da origem vira o arquivo (ou a matéria-prima da recodificação).
        self._audio_page_track = QComboBox()
        self._audio_page_track.currentIndexChanged.connect(
            lambda index: self._on_track_changed(self._audio_page_track, index))
        grid.addWidget(captioned(lambda: strings.LABEL_AUDIO_TRACK, self._audio_page_track), 0, 2)

        self._audio_size_label = QLabel("—")

        # Uma nota sobre o campo de cima, na largura toda.
        self._audio_source = QLabel("")
        self._audio_source.setProperty("role", "hint")
        grid.addWidget(self._audio_source, 1, 0, 1, 3)
        return page

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def mode(self) -> Mode:
        return Mode.AUDIO_ONLY if self._radio_audio.isChecked() else Mode.VIDEO

    def summary(self) -> str:
        """O resultado do que está escolhido, numa linha: "1080p · .mkv · melhor disponível".

        Lê o que os campos mostram agora (e não o pedido guardado), que é o que o usuário vê e o que
        ``build_request`` vai usar. Sem mídia analisada não há resultado a descrever.
        """
        if self._matrix.is_empty:
            return DASH
        if self.mode is Mode.AUDIO_ONLY:
            parts = [self._audio_codec.currentText()]
            if self._audio_quality.isEnabled():
                parts.append(self._audio_quality.currentText())
            if self._audio_track.isEnabled():
                parts.append(self._audio_track.currentText())
        else:
            parts = [self._resolution.currentText(), self._container.currentText()]
            kbps = self.current_video_kbps()
            if kbps:
                parts.append(format_bitrate(kbps))
            if self._audio_track.isEnabled():
                parts.append(self._audio_track.currentText())
        return " · ".join(part for part in parts if part)

    def estimated_size(self) -> str:
        """O tamanho estimado do modo atual, já formatado (ou o traço, se não há como estimar)."""
        label = self._audio_size_label if self.mode is Mode.AUDIO_ONLY else self._video_size_label
        return label.text()

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

        # Só se escolhe a trilha quando o site separa vídeo e áudio; senão o campo fica à vista, apagado, dizendo por quê.
        for track in self._track_fields():
            track.setEnabled(matrix.needs_muxing)

        self._update_audio_source_hint()
        self._update_bitrate_source_label()
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
        self._resolution.addItem(strings.QUALITY_BEST_AVAILABLE, None)
        for height in available_heights(self._matrix):
            self._resolution.addItem(f"{height}p", height)
        # Opções sem altura conhecida (HLS) entram pelo rótulo próprio, que
        # mostra bitrate — não podem simplesmente desaparecer da lista. O dado
        # é a própria escolha, e não o rótulo: o rótulo leva o separador
        # decimal do idioma, e depois de uma troca não acharia mais a faixa.
        for choice in self._matrix.video:
            if choice.height is None:
                self._resolution.addItem(resolution_label(choice), choice)

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

    def _track_fields(self) -> tuple[QComboBox, QComboBox]:
        """Os dois campos da mesma escolha: o da página de vídeo e o da página de áudio."""
        return self._audio_track, self._audio_page_track

    def _populate_audio_tracks(self) -> None:
        muxed = not self._matrix.is_empty and not self._matrix.needs_muxing
        for track in self._track_fields():
            track.blockSignals(True)
            track.clear()
            if muxed:
                # O áudio já vem no vídeo que o site entrega: não há trilha para escolher, e o campo diz isso.
                track.addItem(strings.QUALITY_AUDIO_TRACK_MUXED, _MUXED_TRACK)
            else:
                track.addItem(strings.QUALITY_BEST_AVAILABLE, None)
                for choice in self._matrix.audio:
                    track.addItem(choice_label(choice), choice)
            track.setCurrentIndex(0)
            track.blockSignals(False)

    def _on_track_changed(self, changed: QComboBox, index: int) -> None:
        """A escolha de trilha é uma só: o outro campo acompanha, sem repetir o aviso."""
        other = self._audio_page_track if changed is self._audio_track else self._audio_track
        other.blockSignals(True)
        other.setCurrentIndex(index)
        other.blockSignals(False)
        self._emit_changed()

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

    def _on_bitrate_changed(self) -> None:
        self._bitrate_custom_box.setVisible(self._bitrate.currentData() == _CUSTOM_BITRATE)
        self._emit_changed()

    def _bitrate_source_text(self) -> str:
        """"Igual ao da fonte", com o bitrate que a fonte tem quando se sabe qual é."""
        source = self._source_video_kbps()
        if source:
            return strings.VIDEO_BITRATE_SOURCE_WITH.format(bitrate=format_bitrate(source))
        return strings.VIDEO_BITRATE_SOURCE

    def _source_video_kbps(self) -> float | None:
        """O bitrate do vídeo que seria baixado agora, sem o áudio que um formato muxado leva junto."""
        video = self.current_video_choice() if hasattr(self, "_resolution") else None
        return video_only_kbps(video.best) if video is not None else None

    def current_video_kbps(self) -> int | None:
        """O bitrate de vídeo pedido (kbps), ou ``None`` para "igual ao da fonte"."""
        data = self._bitrate.currentData()
        if data == _CUSTOM_BITRATE:
            return int(self._bitrate_custom.value())
        return int(data) if data else None

    def _update_bitrate_source_label(self) -> None:
        self._bitrate.setItemText(0, self._bitrate_source_text())

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
        self._update_bitrate_source_label()
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
            video_kbps=self.current_video_kbps(),
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

    def _explicit_track(self) -> AudioChoice | None:
        """A trilha que o usuário escolheu a dedo; ``None`` em "Melhor disponível" ou quando não há o que escolher."""
        data = self._audio_track.currentData()
        return data if isinstance(data, AudioChoice) else None

    def _update_audio_source_hint(self) -> None:
        explicit = self._explicit_track()
        best = self._matrix.best_audio_bitrate
        if explicit is not None:
            # Uma trilha extraída do vídeo pode não informar o bitrate: a nota fica em branco, em vez de dizer o da melhor.
            text = strings.AUDIO_SOURCE_CHOSEN.format(bitrate=format_bitrate(explicit.bitrate)) if explicit.bitrate else ""
        else:
            text = strings.AUDIO_SOURCE_INFO.format(bitrate=format_bitrate(best)) if best else ""
        self._audio_source.setText(text)

    def _refresh_warnings(self) -> None:
        """Mostra, antes de baixar, o que a escolha atual implica.

        Avisar aqui — e não depois — é o que permite ao usuário mudar de ideia
        sem ter desperdiçado um download.
        """
        messages: list[str] = []

        if self.mode is Mode.AUDIO_ONLY:
            codec = self._audio_codec.currentData() or "mp3"
            quality = self._audio_quality.currentData() or "192"
            explicit = self._explicit_track()
            # Sem o bitrate da trilha escolhida não há com o que comparar: nenhum aviso, e não o da melhor trilha.
            warning = (None if explicit is not None and not explicit.bitrate else
                       audio_quality_warning(self._matrix, codec, quality,
                                             source_kbps=explicit.bitrate if explicit is not None else None))
            if warning:
                messages.append(warning)
            choice = self.current_audio_choice()
            if choice is not None and choice.is_extracted_from_video:
                messages.append(strings.QUALITY_WARN_EXTRACTED)
        else:
            video = self.current_video_choice()
            if video is not None:
                messages.extend(self._codec_warnings(video))
                plan = plan_container(
                    self._matrix, video, self.current_audio_choice(),
                    self._container.currentData() or CONTAINER_AUTO,
                )
                messages.extend(plan.warnings)
                kbps = self.current_video_kbps()
                if kbps:
                    source = self._source_video_kbps()
                    if keeps_source(source, kbps):
                        messages.append(strings.QUALITY_WARN_BITRATE_ABOVE_SOURCE.format(
                            source=format_bitrate(source), requested=format_bitrate(kbps)))
                    else:
                        messages.append(strings.QUALITY_WARN_RECODE.format(bitrate=format_bitrate(kbps)))

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
                return [strings.QUALITY_WARN_NO_FAMILY.format(family=wanted, actual=video.family)]
            return [strings.QUALITY_WARN_NO_FAMILY_AT.format(
                family=wanted, resolution=resolution_label(video), actual=video.family, reach=reach)]

        # O codec foi atendido, mas pode ser ele que está limitando a resolução
        # de quem pediu "Melhor disponível".
        top = max((c.height for c in self._matrix.video if c.height), default=None)
        if (
            self._resolution.currentData() is None
            and reach is not None
            and top is not None
            and reach < top
        ):
            return [strings.QUALITY_WARN_FAMILY_LIMIT.format(family=wanted, reach=reach, top=top)]
        return []

    # ------------------------------------------------------------------
    # Leitura do pedido
    # ------------------------------------------------------------------

    def current_video_choice(self) -> VideoChoice | None:
        if not self._matrix.has_video:
            return None
        data = self._resolution.currentData()
        if isinstance(data, VideoChoice):
            # Opção sem altura conhecida: já é um stream concreto, não há codec
            # nem framerate a combinar.
            return data
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
            video_kbps=self.current_video_kbps(),
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
            video_kbps=self.current_video_kbps(),
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
                # Um perfil é "sem recodificar": o bitrate volta ao da fonte.
                self._bitrate.setCurrentIndex(0)
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
