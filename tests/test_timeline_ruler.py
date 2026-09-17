"""Régua e agulha fixas no topo, com as trilhas rolando por baixo.

Antes a timeline inteira ficava dentro de uma área de rolagem: com muitas
trilhas, rolar para as de baixo levava a régua e a cabeça da agulha para fora da
vista, e não havia onde pegar o cursor.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent

from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.presentation.qt.panels.timeline import RULER_HEIGHT, Timeline
from videomanager.presentation.qt.theme import DARK

pytestmark = pytest.mark.usefixtures("desktop_app")

VIDEO = MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=30, width=320, height=180)


def _timeline(tracks: int = 10, height: int = 220) -> tuple[Timeline, list[Clip]]:
    clips = [Clip(VIDEO, 0, 10) for _ in range(tracks)]
    timeline = Timeline(DARK)
    timeline.set_project(Project(tracks=tuple(Track(TrackKind.VIDEO, clips=(clip,)) for clip in clips)))
    timeline.resize(900, height)
    timeline.set_view(0, 10)
    return timeline, clips


def _press(timeline: Timeline, x: float, y: float) -> None:
    pos = QPointF(x, y)
    for kind, handler in ((QMouseEvent.Type.MouseButtonPress, timeline.mousePressEvent),
                          (QMouseEvent.Type.MouseButtonRelease, timeline.mouseReleaseEvent)):
        handler(QMouseEvent(kind, pos, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier))


def test_trilhas_rolam_ate_a_ultima_sem_crescer_o_widget() -> None:
    timeline, _ = _timeline()
    assert timeline.max_scroll > 0
    timeline.set_scroll(10_000)
    assert timeline.scroll == timeline.max_scroll
    last = timeline._lane_rect(len(timeline.project.tracks) - 1)
    assert last.bottom() <= timeline.height()
    assert timeline.minimumHeight() < timeline._content_height()


def test_regua_continua_clicavel_com_as_trilhas_roladas() -> None:
    timeline, clips = _timeline()
    timeline.set_scroll(timeline.max_scroll)
    timeline.select(clips[-1].clip_id)
    scrubbed = []
    timeline.scrubbed.connect(scrubbed.append)
    _press(timeline, timeline._x_of(7), RULER_HEIGHT / 2)
    assert scrubbed and abs(scrubbed[-1] - 7) < 0.05
    assert timeline.selected == clips[-1].clip_id


def test_trilha_escondida_sob_a_regua_nao_recebe_clique() -> None:
    timeline, clips = _timeline()
    timeline.set_scroll(timeline._lane_rect(0).height() + 20)
    assert timeline._lane_rect(0).bottom() < RULER_HEIGHT + 20
    kind, index, clip_id = timeline._hit(timeline._x_of(5), RULER_HEIGHT - 2)
    assert index == -1 and clip_id == -1


def test_clique_em_bloco_rolado_acerta_o_bloco_certo() -> None:
    timeline, clips = _timeline()
    timeline.set_scroll(timeline.max_scroll)
    last = len(clips) - 1
    center = timeline._clip_rect(last, clips[last]).center()
    kind, index, clip_id = timeline._hit(center.x(), center.y())
    assert (index, clip_id) == (last, clips[last].clip_id)


def test_roda_rola_as_trilhas_e_nao_o_tempo() -> None:
    timeline, _ = _timeline()
    view = timeline.view
    changes = []
    timeline.scroll_changed.connect(changes.append)
    event = QWheelEvent(QPointF(450, 100), QPointF(450, 100), QPoint(), QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    timeline.wheelEvent(event)
    assert event.isAccepted()
    assert changes and timeline.scroll > 0
    assert timeline.view == view


def test_poucas_trilhas_nao_rolam() -> None:
    timeline, _ = _timeline(tracks=2, height=400)
    assert timeline.max_scroll == 0
    timeline.set_scroll(50)
    assert timeline.scroll == 0


def test_arrastar_bloco_na_borda_de_baixo_rola_e_troca_de_trilha() -> None:
    timeline, clips = _timeline()
    moves = []
    timeline.clip_moved.connect(lambda clip_id, track, start: moves.append(track))
    center = timeline._clip_rect(0, clips[0]).center()
    press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, center, center, Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    timeline.mousePressEvent(press)
    # Dentro da faixa de rolagem e ainda sobre a última trilha quando tudo
    # rolou: abaixo dela vale a regra de sempre, e o bloco fica na origem.
    edge = QPointF(center.x(), timeline.height() - 12)
    for _ in range(40):
        move = QMouseEvent(QMouseEvent.Type.MouseMove, edge, edge, Qt.MouseButton.NoButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        timeline.mouseMoveEvent(move)
        timeline._autoscroll_step()
    assert timeline.scroll > 0
    assert moves and moves[-1] > 0


def test_painel_sincroniza_barra_vertical(monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.panels.edit_panel import EditPanel

    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    panel = EditPanel(Settings(), ensure_tools=lambda: None, editor=build_editor_service(),
                      processing=build_processing_service(), runtime=build_desktop_runtime(audio_enabled=False))
    try:
        project = Project(tracks=tuple(Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 0, 10),)) for _ in range(12)))
        panel.install_project(project, None, [], {})
        panel.resize(1100, 700)
        panel.show()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        bar = panel._timeline_vbar
        assert bar.maximum() == panel._timeline.max_scroll > 0
        bar.setValue(40)
        assert panel._timeline.scroll == 40
        panel._timeline.set_scroll(10)
        assert bar.value() == 10
    finally:
        panel.shutdown()
