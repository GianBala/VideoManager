"""Importar só leva ao acervo; é o usuário quem põe a mídia numa trilha.

Antes, importar já colocava cada arquivo na agulha, empilhando trilhas novas a
cada arquivo de uma importação múltipla. Agora a mídia fica no acervo e é
arrastada até a trilha e o instante desejados — ou inserida pelo botão.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragMoveEvent, QDropEvent

from videomanager.application.editor.media import MediaResult
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind

VIDEO = MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=4, width=320, height=180, fps=30)
FOTO = MediaRef(Path("/m/foto.png"), MediaKind.IMAGE, width=400, height=300)
SOM = MediaRef(Path("/m/som.mp3"), MediaKind.AUDIO, duration=6, has_audio=True, channels=2)


class TestColocacao:
    def _base(self) -> Project:
        return Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 2, 4),), name="V1"),
                               Track(TrackKind.AUDIO, name="S1")))

    def test_vao_livre_recebe_o_bloco_no_instante(self) -> None:
        project, index = self._base().with_dropped_clip(Clip(VIDEO, 10, 4), 0, 0)
        assert index == 0 and [c.start for c in project.tracks[0].sorted_clips()] == [2, 10]

    def test_vao_curto_do_lado_encosta_dentro_do_vao(self) -> None:
        base = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 0, 2), Clip(VIDEO, 8, 4))),))
        project, index = base.with_dropped_clip(Clip(VIDEO, 5, 4), 0, 0)
        assert index == 0 and [c.start for c in project.tracks[0].sorted_clips()] == [0, 4, 8]

    def test_sobre_um_bloco_nasce_trilha_acima_sem_mexer_no_existente(self) -> None:
        base = self._base()
        project, index = base.with_dropped_clip(Clip(VIDEO, 3, 4), 0, 0)
        assert index == 0 and [t.kind for t in project.tracks] == [TrackKind.VIDEO, TrackKind.VIDEO, TrackKind.AUDIO]
        assert project.tracks[0].clips[0].start == 3
        assert project.tracks[1] == base.tracks[0]

    def test_trilha_incompativel_cria_trilha_da_especie_certa(self) -> None:
        project, index = self._base().with_dropped_clip(Clip(SOM, 1, 6), 0, 0)
        assert project.tracks[index].kind is TrackKind.AUDIO and index == 0

    def test_abaixo_de_todas_as_trilhas_acrescenta_no_fim(self) -> None:
        base = self._base()
        project, index = base.with_dropped_clip(Clip(FOTO, 0, 5), -1, len(base.tracks))
        assert index == 2 and project.tracks[2].kind is TrackKind.VIDEO

    def test_trilha_nova_em_posicao_pedida(self) -> None:
        project = self._base().with_track(TrackKind.ADDITIONAL, index=1)
        assert [t.kind for t in project.tracks] == [TrackKind.VIDEO, TrackKind.ADDITIONAL, TrackKind.AUDIO]


@pytest.fixture
def panel(desktop_app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.panels.edit_panel import EditPanel

    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    instance = EditPanel(Settings(), ensure_tools=lambda: None, editor=build_editor_service(),
                         processing=build_processing_service(), runtime=build_desktop_runtime(audio_enabled=False))
    yield instance
    instance.shutdown()


def test_importar_pelo_botao_nao_insere(panel, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog
    calls = []
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: (["/m/video.mp4"], ""))
    monkeypatch.setattr(panel._project_actions, "import_files", lambda paths, **kw: calls.append(kw))
    panel._choose_files()
    assert calls and not calls[-1].get("insert")


def test_soltar_arquivos_fora_da_timeline_so_importa(panel, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(panel._project_actions, "import_files", lambda paths, **kw: calls.append(kw))
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile("/m/video.mp4")])
    event = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    panel.dropEvent(event)
    assert calls and not calls[-1].get("insert")


def test_resultado_da_importacao_vai_so_para_o_acervo(panel) -> None:
    panel.accept_import(MediaResult(references=(VIDEO, SOM)))
    assert panel._project.is_empty
    assert {ref.path for ref in panel._pool} == {VIDEO.path, SOM.path}


def test_acervo_exporta_a_midia_arrastada(panel) -> None:
    from videomanager.presentation.qt.panels.timeline import MEDIA_MIME
    panel.accept_import(MediaResult(references=(VIDEO,)))
    item = panel._media_list.item(0)
    data = panel._media_list.mimeData([item])
    payload = json.loads(bytes(data.data(MEDIA_MIME)).decode("utf-8"))
    assert payload == [{"path": str(VIDEO.path), "kind": "VIDEO", "duration": 4.0}]


def _media_mime(*refs: MediaRef) -> QMimeData:
    from videomanager.presentation.qt.panels.timeline import MEDIA_MIME
    data = QMimeData()
    data.setData(MEDIA_MIME, json.dumps([{"path": str(r.path), "kind": r.kind.name,
                                          "duration": r.natural_duration} for r in refs]).encode("utf-8"))
    return data


def _drop_on_timeline(panel, data: QMimeData, seconds: float, track: int) -> None:
    timeline = panel._timeline
    timeline.resize(1000, 400)
    timeline.set_view(0, 20)
    point = QPointF(timeline._x_of(seconds), timeline._lane_rect(track).center().y())
    move = QDragMoveEvent(point.toPoint(), Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
    timeline.dragMoveEvent(move)
    assert move.isAccepted()
    drop = QDropEvent(point, Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
    timeline.dropEvent(drop)


def test_arrastar_do_acervo_coloca_na_trilha_e_instante(panel) -> None:
    panel.accept_import(MediaResult(references=(VIDEO, SOM)))
    _drop_on_timeline(panel, _media_mime(VIDEO), 5, 0)
    track = panel._project.tracks[0]
    assert track.kind is TrackKind.VIDEO and len(track.clips) == 1
    assert track.clips[0].start == pytest.approx(5, abs=0.05)
    assert panel._timeline.selected == track.clips[0].clip_id
    panel._undo_edit()
    assert panel._project.is_empty


def test_varias_midias_entram_em_sequencia(panel) -> None:
    other = MediaRef(Path("/m/outro.mp4"), MediaKind.VIDEO, duration=3, width=320, height=180, fps=30)
    panel.accept_import(MediaResult(references=(VIDEO, other)))
    _drop_on_timeline(panel, _media_mime(VIDEO, other), 2, 0)
    starts = [round(c.start, 2) for c in panel._project.tracks[0].sorted_clips()]
    assert starts == [pytest.approx(2, abs=.05), pytest.approx(6, abs=.05)]


def test_arquivo_do_sistema_solto_na_timeline_importa_e_coloca(panel, monkeypatch) -> None:
    captured = {}

    def fake_import(paths, **kwargs):
        captured.update(kwargs, paths=paths)

    monkeypatch.setattr(panel._project_actions, "import_files", fake_import)
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(SOM.path))])
    _drop_on_timeline(panel, data, 3, 1)
    assert not captured.get("insert") and captured["placement"][0] == 1
    panel.accept_import(MediaResult(references=(SOM,)), placement=captured["placement"])
    audio = panel._project.tracks[1]
    assert audio.kind is TrackKind.AUDIO and audio.clips[0].start == pytest.approx(3, abs=0.05)


def test_acervo_inicia_o_arrasto_com_o_mouse(panel, monkeypatch) -> None:
    """Eventos de mouse de verdade, e não o handler chamado direto.

    ``QListView.setMovement(Static)`` desliga ``dragEnabled`` por dentro; com a
    ordem errada no construtor, o cartão nunca começava a ser arrastado e o
    teste que chamava ``mimeData`` direto não percebia.
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from videomanager.presentation.qt.panels.edit_widgets import _MediaListWidget

    started = []
    monkeypatch.setattr(_MediaListWidget, "startDrag", lambda self, actions: started.append(actions))
    panel.resize(1300, 800)
    panel.show()
    panel.accept_import(MediaResult(references=(VIDEO,)))
    QApplication.processEvents()
    media = panel._media_list
    assert media.dragEnabled()
    center = media.visualItemRect(media.item(0)).center()
    viewport = media.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    distance = QApplication.startDragDistance() + 10
    for step in range(1, 4):
        QTest.mouseMove(viewport, center + QPoint(distance * step, 0))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       center + QPoint(distance * 3, 0))
    assert started, "o arrasto do cartão não começou"


def test_soltura_chega_a_linha_do_tempo_pelo_despacho_de_eventos(panel) -> None:
    """Enter, move e drop enviados pelo Qt, passando por ``Timeline.event``."""
    from PySide6.QtGui import QDragEnterEvent
    from PySide6.QtWidgets import QApplication

    panel.resize(1300, 800)
    panel.show()
    panel.accept_import(MediaResult(references=(VIDEO,)))
    QApplication.processEvents()
    timeline = panel._timeline
    timeline.set_view(0, 20)
    data = _media_mime(VIDEO)
    point = QPointF(timeline._x_of(3), timeline._lane_rect(0).center().y())
    enter = QDragEnterEvent(point.toPoint(), Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(timeline, enter)
    assert enter.isAccepted()
    move = QDragMoveEvent(point.toPoint(), Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(timeline, move)
    assert move.isAccepted()
    drop = QDropEvent(point, Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(timeline, drop)
    clips = panel._project.tracks[0].clips
    assert len(clips) == 1 and clips[0].start == pytest.approx(3, abs=0.05)
