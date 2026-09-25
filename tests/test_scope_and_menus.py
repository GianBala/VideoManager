"""Testes de escopo contextual de menus, atalhos e botões."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Forçar backend offscreen antes do carregamento do Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication

from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import LocalStream
from videomanager.domain.project import TrackKind
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.main_window import _TAB_CONVERT
from videomanager.presentation.qt.main_window import _TAB_DOWNLOAD
from videomanager.presentation.qt.main_window import _TAB_EDIT
from videomanager.presentation.qt.main_window import MainWindow
from videomanager.presentation.qt.panels.convert_panel import ConvertPanel
from videomanager.presentation.qt.panels.edit_panel import EditPanel
from videomanager.bootstrap import build_editor_service
from videomanager.bootstrap import build_processing_service
from videomanager.bootstrap import build_download_service
from videomanager.bootstrap import build_desktop_runtime


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def dummy_tools() -> FFmpegTools:
    return FFmpegTools(
        ffmpeg=Path("/bin/ffmpeg"),
        ffprobe=Path("/bin/ffprobe"),
        source="system",
    )


def test_main_window_menu_scope_per_tab(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings()
    # Mock do FFmpeg setup para não disparar sondagens pesadas
    monkeypatch.setattr("videomanager.presentation.qt.main_window.ensure_ffmpeg", lambda parent, **kw: None)

    window = MainWindow(settings, editor=build_editor_service(), processing=build_processing_service(), downloads=build_download_service(), runtime=build_desktop_runtime())
    try:
        # 1. Aba Download
        window._tabs.setCurrentIndex(_TAB_DOWNLOAD)
        assert window._tabs.currentIndex() == _TAB_DOWNLOAD

        file_actions = [a.text() for a in window._file_menu.actions() if not a.isSeparator()]
        tools_actions = [a.text() for a in window._tools_menu.actions() if not a.isSeparator()]

        assert strings.ACTION_OPEN_DOWNLOAD_DEST in file_actions
        assert strings.ACTION_QUIT in file_actions
        # Ações de projeto NÃO devem estar no menu Arquivo em Download
        assert strings.ACTION_NEW_PROJECT not in file_actions
        assert strings.ACTION_OPEN_PROJECT not in file_actions
        assert strings.ACTION_SAVE_PROJECT not in file_actions
        assert strings.ACTION_SAVE_PROJECT_AS not in file_actions
        assert strings.ACTION_CONVERT_ADD not in file_actions

        # Ferramentas deve ter atualização do yt-dlp e configurações
        assert strings.ACTION_SETTINGS in tools_actions
        assert strings.ACTION_UPDATE_ENGINE in tools_actions

        # Atalhos de edição e conversão devem estar desativados
        assert window._convert_add_action.shortcut().isEmpty()
        assert window._new_proj_action.shortcut().isEmpty()
        assert window._save_proj_action.shortcut().isEmpty()

        # 2. Aba Converter
        window._tabs.setCurrentIndex(_TAB_CONVERT)
        assert window._tabs.currentIndex() == _TAB_CONVERT

        file_actions_convert = [a.text() for a in window._file_menu.actions() if not a.isSeparator()]
        tools_actions_convert = [a.text() for a in window._tools_menu.actions() if not a.isSeparator()]

        assert strings.ACTION_CONVERT_ADD in file_actions_convert
        assert strings.ACTION_CONVERT_REMOVE in file_actions_convert
        assert strings.ACTION_CONVERT_CLEAR in file_actions_convert
        assert strings.ACTION_OPEN_CONVERT_DEST in file_actions_convert
        assert strings.ACTION_QUIT in file_actions_convert

        # Ações de projeto NÃO devem estar na aba Converter
        assert strings.ACTION_NEW_PROJECT not in file_actions_convert
        assert strings.ACTION_OPEN_PROJECT not in file_actions_convert
        assert strings.ACTION_SAVE_PROJECT not in file_actions_convert

        # Ferramentas NÃO deve ter atualização do yt-dlp em Converter
        assert strings.ACTION_UPDATE_ENGINE not in tools_actions_convert
        assert strings.ACTION_SETTINGS in tools_actions_convert

        # Atalho Ctrl+O deve pertencer a adicionar arquivos na conversão
        assert window._convert_add_action.shortcut() == QKeySequence("Ctrl+O")
        assert window._open_proj_action.shortcut().isEmpty()

        # 3. Aba Editar
        window._tabs.setCurrentIndex(_TAB_EDIT)
        assert window._tabs.currentIndex() == _TAB_EDIT

        file_actions_edit = [a.text() for a in window._file_menu.actions() if not a.isSeparator()]
        tools_actions_edit = [a.text() for a in window._tools_menu.actions() if not a.isSeparator()]

        assert strings.ACTION_NEW_PROJECT in file_actions_edit
        assert strings.ACTION_OPEN_PROJECT in file_actions_edit
        assert strings.ACTION_SAVE_PROJECT in file_actions_edit
        assert strings.ACTION_SAVE_PROJECT_AS in file_actions_edit
        assert strings.ACTION_IMPORT_MEDIA in file_actions_edit
        assert strings.ACTION_EXPORT_VIDEO in file_actions_edit
        assert strings.ACTION_QUIT in file_actions_edit

        # Ferramentas NÃO deve ter atualização do yt-dlp em Editar
        assert strings.ACTION_UPDATE_ENGINE not in tools_actions_edit
        assert strings.ACTION_SETTINGS in tools_actions_edit

        # Atalhos de edição ativados
        assert window._convert_add_action.shortcut().isEmpty()
        assert window._new_proj_action.shortcut() == QKeySequence("Ctrl+N")
        assert window._open_proj_action.shortcut() == QKeySequence("Ctrl+O")
        assert window._save_proj_action.shortcut() == QKeySequence("Ctrl+S")
        assert window._save_as_proj_action.shortcut() == QKeySequence("Ctrl+Shift+S")
        assert window._import_media_action.shortcut() == QKeySequence("Ctrl+I")
        assert window._export_action.shortcut() == QKeySequence("Ctrl+E")
    finally:
        window.close()


def test_edit_panel_top_project_controls_and_label(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        # Verifica a existência dos novos botões de projeto no topo do editor
        assert hasattr(panel, "_new_btn")
        assert hasattr(panel, "_open_btn")
        assert hasattr(panel, "_save_btn")
        assert hasattr(panel, "_project_label")

        # Rótulo inicial
        assert strings.EDIT_UNTITLED in panel._project_label.text()
        assert "*" not in panel._project_label.text()

        # Altera projeto para sujo e verifica atualização do rótulo
        panel._apply(panel._project.with_track(TrackKind.VIDEO))
        panel._update_project_label()
        # Uma trilha nova também faz parte do conteúdo persistido.
        assert "*" in panel._project_label.text()

        # Simula salvar
        panel._project_path = Path("/tmp/teste_video.vmp")
        panel._session.mark_saved()
        panel._update_project_label()
        assert "teste_video.vmp" in panel._project_label.text()
    finally:
        panel.shutdown()


def test_convert_panel_clear_and_delete_key(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = ConvertPanel(settings=settings, ensure_tools=lambda: dummy_tools, processing=build_processing_service(), runtime=build_desktop_runtime())

    media1 = LocalMedia(
        path=Path("/tmp/sample1.mp4"),
        duration=10.0,
        format_name="mp4",
        size=1024,
        streams=(
            LocalStream(index=0, kind="video", codec="h264", width=1920, height=1080),
            LocalStream(index=1, kind="audio", codec="aac"),
        ),
    )
    panel._media.append(media1)
    panel._list.addItem("sample1.mp4")
    panel._update_remove_button()

    assert panel._list.count() == 1
    assert panel._clear_btn.isEnabled()

    # Teste do delete_requested via evento de tecla no _DropList
    key_event = QKeyEvent(QEvent.Type.KeyPress, int(Qt.Key.Key_Delete), Qt.KeyboardModifier.NoModifier)
    panel._list.keyPressEvent(key_event)

    # Teste de limpar lista completa
    panel.clear_files()
    assert panel._list.count() == 0
    assert len(panel._media) == 0
    assert not panel._clear_btn.isEnabled()
    assert not panel._remove.isEnabled()


def test_edit_panel_splitter_anti_overlap_bounds(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        # Sem sobreposição em nenhuma largura — e sem impor ~1000 px à aba
        # inteira: estreita, a barra de transporte quebra em duas linhas. O
        # piso fixo de 1040 px deixava a aba maior que uma tela de 1366 px (ou
        # de 1920 px com escala de 125%) e o botão Exportar fora da vista.
        from PySide6.QtCore import QPoint, QRect
        panel.show()
        assert panel.minimumSizeHint().width() <= 1280
        controles = [*panel._buttons, panel._time_label, panel._frame_label, panel._loop,
                     panel._mute, panel._volume]
        for largura in (panel.minimumSizeHint().width(), 1920):
            panel.resize(largura, 900)
            qapp.processEvents()
            areas = [QRect(w.mapTo(panel, QPoint(0, 0)), w.size()) for w in controles]
            for i, area in enumerate(areas):
                assert area.right() <= panel.width(), "controle fora da aba"
                for outra in areas[i + 1:]:
                    assert not area.intersects(outra), "controles da barra de transporte sobrepostos"
        assert panel._media_box.minimumWidth() >= 200
        assert panel._extras_box.minimumWidth() >= 260
        assert not panel._top_splitter.childrenCollapsible()
    finally:
        panel.shutdown()


def test_edit_panel_abas_roladas_nao_encolhem_a_previa(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    from PySide6.QtWidgets import QScrollArea
    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        # As abas de Adicionais rolam sem pedir menos altura que o conteúdo: o
        # divisor vertical reparte pela dica, e com o teto de 24 linhas do
        # QScrollArea a prévia nascia mais baixa que antes de a aba rolar.
        paginas = [panel._extras_tabs.widget(i) for i in range(panel._extras_tabs.count())]
        roladas = [p for p in paginas if isinstance(p, QScrollArea)]
        assert roladas
        for pagina in roladas:
            assert pagina.sizeHint() == pagina.widget().sizeHint()
    finally:
        panel.shutdown()


def test_edit_panel_previa_e_a_ultima_a_perder_largura(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        panel.show()
        # Estreitando a janela, a biblioteca e os Adicionais cedem antes do
        # monitor — em 1680 px a prévia perdia 92 px com as colunas cheias...
        panel.resize(1680, 900)
        qapp.processEvents()
        assert panel._top_splitter.sizes()[2] >= 1040
        # ... e ela só encolhe depois de as duas chegarem ao mínimo.
        panel.resize(1280, 900)
        qapp.processEvents()
        media, extras, _ = panel._top_splitter.sizes()
        assert (media, extras) == (panel._media_box.minimumWidth(), panel._extras_box.minimumWidth())
        # Mudar só a altura (o divisor vertical) não desfaz a largura que o
        # usuário arrastou.
        panel._top_splitter.setSizes([media, extras + 100, panel._top_splitter.sizes()[2] - 100])
        arrastado = panel._top_splitter.sizes()
        panel.resize(1280, 800)
        qapp.processEvents()
        assert panel._top_splitter.sizes() == arrastado
    finally:
        panel.shutdown()


def test_edit_panel_colunas_voltam_a_largura_natural_ao_alargar(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        panel.show()
        panel.resize(1920, 900)
        qapp.processEvents()
        natural = panel._top_splitter.sizes()[:2]
        # Largas, as colunas têm a largura que pedem — o painel nasce pequeno e
        # cresce depois, e essa primeira passagem já as prendia no mínimo.
        assert natural == [panel._media_box.sizeHint().width(), panel._extras_box.sizeHint().width()]
        # Estreita, as colunas cedem para a prévia; alargando de novo, voltam.
        # Gravadas pelo setSizes, ficavam no mínimo depois de qualquer passagem
        # por uma janela estreita — inclusive a primeira disposição da aba
        # escondida, que o grab() da janela provoca.
        panel.resize(1280, 900)
        qapp.processEvents()
        assert panel._top_splitter.sizes()[:2] != natural
        panel.resize(1920, 900)
        qapp.processEvents()
        assert panel._top_splitter.sizes()[:2] == natural
    finally:
        panel.shutdown()


def test_edit_panel_rotulo_de_contagem_so_encolhe_o_que_tem(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track
    panel = EditPanel(settings=Settings(), ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        # Vazio, sem projeto, o piso de 40 px empurrava o nome do bloco para o
        # lado; com texto, ele é o que deixa o rótulo encolher em tela estreita.
        rotulo = panel._count_label
        assert rotulo.text() == "" and rotulo.minimumWidth() < 40
        video = MediaRef(Path("/tmp/v.mp4"), MediaKind.VIDEO, duration=5.0, width=160, height=90, fps=10.0)
        panel.install_project(Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(video, 0.0, 5.0),)),)), None, [video], {})
        assert rotulo.text() and rotulo.minimumWidth() == 40
        # E de volta ao vazio, o piso sai de novo: medido pelo sizeHint, que já
        # vinha inflado pelos 40 px em vigor, ele ficava.
        from videomanager.domain.project import new_project
        panel.install_project(new_project(), None, [], {})
        assert rotulo.text() == "" and rotulo.minimumWidth() < 40
    finally:
        panel.shutdown()


def test_edit_panel_track_reordered_undo_redo(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        # Projeto inicial: 1 trilha de vídeo e 1 de áudio
        assert len(panel._project.tracks) == 2
        panel._add_track(TrackKind.VIDEO)
        assert len(panel._project.tracks) == 3
        v0 = panel._project.tracks[0]
        v1 = panel._project.tracks[1]
        assert v0.kind == TrackKind.VIDEO
        assert v1.kind == TrackKind.VIDEO

        # Reordena trilha 0 e 1
        panel._on_track_reordered(0, 1)
        assert panel._project.tracks[0] == v1
        assert panel._project.tracks[1] == v0

        # Testa desfazer (Ctrl+Z)
        assert panel._undo.isEnabled()
        panel._undo_edit()
        assert panel._project.tracks[0] == v0
        assert panel._project.tracks[1] == v1

        # Testa refazer (Ctrl+Shift+Z)
        assert panel._redo.isEnabled()
        panel._redo_edit()
        assert panel._project.tracks[0] == v1
        assert panel._project.tracks[1] == v0
    finally:
        panel.shutdown()


def test_timeline_track_reordering_target_detection(qapp: QApplication, dummy_tools: FFmpegTools) -> None:
    settings = Settings()
    panel = EditPanel(settings=settings, ensure_tools=lambda: dummy_tools, editor=build_editor_service(), processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        timeline = panel._timeline
        panel._add_track(TrackKind.VIDEO)
        assert len(panel._project.tracks) == 3

        # Arrastando a trilha 0 (Vídeo):
        timeline._drag_track = 0
        y_track_1 = timeline._lane_rect(1).center().y()
        assert timeline._target_reorder_track(y_track_1) == 1

        # A ordem é livre: o vídeo pode descer abaixo da trilha de áudio.
        y_track_2 = timeline._lane_rect(2).center().y()
        assert timeline._target_reorder_track(y_track_2) == 2

        # Acima do topo: primeira posição
        assert timeline._target_reorder_track(0.0) == 0

        # A trilha de áudio também sobe para qualquer posição
        timeline._drag_track = 2
        assert timeline._target_reorder_track(0.0) == 0
    finally:
        panel.shutdown()



# Estes cenários exercitam adaptadores ou apresentação Qt.
pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")


def test_atalhos_de_projeto_funcionam_com_o_foco_no_editor(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ctrl+S, Ctrl+N e Ctrl+E acionam o menu Arquivo com o foco na linha do tempo.

    O painel registrava as mesmas teclas que as ações do menu. Com as duas
    ativas, o Qt considerava o atalho ambíguo e não acionava nenhuma: salvar
    pelo teclado não fazia nada em qualquer ponto do editor.
    """
    from PySide6.QtTest import QTest

    monkeypatch.setattr("videomanager.presentation.qt.main_window.ensure_ffmpeg", lambda parent, **kw: None)
    window = MainWindow(Settings(), editor=build_editor_service(), processing=build_processing_service(),
                        downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))
    chamadas = []
    monkeypatch.setattr(window._edit, "save_project", lambda: chamadas.append("salvar"))
    monkeypatch.setattr(window._edit, "new_project", lambda: chamadas.append("novo"))
    monkeypatch.setattr(window._edit, "_open_export_dialog", lambda: chamadas.append("exportar"))
    # A ação guarda o método de antes; o atalho precisa chegar ao que foi trocado.
    window._export_action.triggered.disconnect()
    window._export_action.triggered.connect(lambda: window._edit._open_export_dialog())
    try:
        window.show()
        window._tabs.setCurrentIndex(_TAB_EDIT)
        window.activateWindow()
        window._edit._timeline.setFocus()
        qapp.processEvents()
        for tecla in (Qt.Key.Key_S, Qt.Key.Key_N, Qt.Key.Key_E):
            QTest.keyClick(window._edit._timeline, tecla, Qt.KeyboardModifier.ControlModifier)
            qapp.processEvents()
        assert chamadas == ["salvar", "novo", "exportar"]
    finally:
        window.close()


def test_titulo_da_janela_nao_repete_o_nome_do_aplicativo(tmp_path):
    """O Qt acrescenta o nome de exibição a todo título que não termina com
    ele: com "Video Manager" como nome, a janela aparecia como "Video Manager
    2.1 - Video Manager". Roda a abertura de verdade, que é quem define o nome."""
    import ast
    import subprocess
    import sys

    import videomanager
    script = (
        "from pathlib import Path\n"
        "from videomanager.infrastructure.storage import settings\n"
        f"settings.config_dir = lambda: Path({str(tmp_path)!r})\n"
        "from videomanager.app import build_app\n"
        "app, janela = build_app([], audio_enabled=False)\n"
        "print(repr((janela.windowTitle(), app.applicationDisplayName())))\n"
    )
    raiz = Path(__file__).resolve().parents[1]
    ambiente = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(raiz / "src"),
                "XDG_DATA_HOME": str(tmp_path / "dados")}
    saida = subprocess.run([sys.executable, "-c", script], env=ambiente, capture_output=True, text=True,
                           timeout=120, cwd=raiz)
    titulo, nome = ast.literal_eval(saida.stdout.strip().splitlines()[-1])
    assert titulo == f"Video Manager {videomanager.__version__}"
    assert titulo.endswith(nome)
