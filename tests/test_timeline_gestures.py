"""Gestos de mouse na linha do tempo, com eventos reais sobre o painel."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from videomanager.application.capabilities import FFmpegTools
from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt.panels.edit_panel import EditPanel

pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")

TOOLS = FFmpegTools(ffmpeg=Path("/bin/false"), ffprobe=Path("/bin/false"), source="system")


@pytest.fixture
def panel():
    painel = EditPanel(settings=Settings(), ensure_tools=lambda: None, editor=build_editor_service(),
                       processing=build_processing_service(), runtime=build_desktop_runtime(audio_enabled=False))
    painel.resize(1600, 900)
    painel.show()
    yield painel
    painel.shutdown()


def _drag(timeline, start: QPoint, steps: int, dx: int = 1) -> list[QPoint]:
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    points = []
    for step in range(1, steps + 1):
        point = QPoint(start.x() + step * dx, start.y())
        QTest.mouseMove(timeline, point)
        points.append(point)
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, points[-1])
    return points


def test_alca_inicial_de_bloco_encostado_no_anterior_e_alcancavel(panel):
    """Entre dois blocos encostados, o lado direito da emenda pega o segundo.

    Medindo só a distância, a faixa inteira de ±8 px ia para a ponta final do
    primeiro: aparar o começo do segundo pela alça era impossível.
    """
    video = MediaRef(Path("/tmp/v.mp4"), MediaKind.VIDEO, duration=20.0, width=160, height=90, fps=10.0)
    primeiro, segundo = Clip(video, 0.0, 5.0), Clip(video, 5.0, 5.0, in_point=5.0)
    panel.install_project(Project(tracks=(Track(TrackKind.VIDEO, clips=(primeiro, segundo)),)), None, [], {})
    timeline = panel._timeline
    timeline.set_view(0.0, 10.0)
    emenda = round(timeline._x_of(5.0))
    y = round(timeline._lane_rect(0).center().y())

    _drag(timeline, QPoint(emenda + 3, y), 50)

    antes, depois = panel._project.tracks[0].sorted_clips()
    assert (antes.start, antes.end) == (0.0, 5.0), "a ponta do primeiro bloco não podia mudar"
    assert depois.start > 5.3, "a alça inicial do segundo bloco não foi arrastada"
    assert depois.end == pytest.approx(10.0)

