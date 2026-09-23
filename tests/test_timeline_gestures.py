"""Gestos de mouse na linha do tempo, com eventos reais sobre o painel.

Os dois casos daqui não levantavam erro nenhum: a alça simplesmente pegava o
bloco errado, e o bloco animado andava aos saltos.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt.panels.edit_panel import EditPanel

pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")


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


def test_bloco_animado_acompanha_o_arrasto_sem_grudar_nos_proprios_quadros_chave(panel):
    """O ímã não pode atrair o bloco para os próprios quadros-chave.

    Eles andam junto com o bloco: um quadro-chave no começo virava alvo a
    cada movimento, e o bloco só saía do lugar quando a mão passava da
    tolerância do ímã — aos saltos de 8 px.
    """
    texto = Clip(MediaRef(Path("Texto_x"), MediaKind.IMAGE, duration=5.0), 2.0, 3.0, overlay_type="text",
                 text_content="x", keyframes=(Keyframe(0.0, opacity=0.0), Keyframe(0.5, opacity=1.0)))
    panel.install_project(Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(texto,)),)), None, [], {})
    timeline = panel._timeline
    timeline.set_view(0.0, 10.0)
    inicio = QPoint(round(timeline._x_of(3.0)), round(timeline._lane_rect(0).center().y()))

    posicoes = []
    timeline.clip_moved.connect(lambda *_: posicoes.append(panel._project.clips[0].start))
    _drag(timeline, inicio, 40)

    assert len(set(posicoes)) >= 30, f"o bloco andou só {len(set(posicoes))} vezes em 36 movimentos"
    assert panel._project.clips[0].start > 2.0 + 30 * timeline._seconds_per_pixel()


def test_duracao_do_filtro_pelo_campo_nao_invade_o_bloco_seguinte(panel):
    """O campo de duração da aba Filtros respeita o vizinho, como a alça.

    Aplicada direto no bloco, a duração sobrepunha dois filtros na mesma
    trilha — o estado que nenhum outro gesto permite criar.
    """
    def filtro(nome, inicio):
        return Clip(MediaRef(Path(f"Filtro_{nome}"), MediaKind.IMAGE, duration=5.0), inicio, 5.0,
                    overlay_type="filter", filter_name=nome)

    primeiro, segundo = filtro("pb", 0.0), filtro("sepia", 5.0)
    panel.install_project(Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(primeiro, segundo)),)), None, [], {})
    panel._timeline.select(primeiro.clip_id)

    panel._filter_dur.setValue(8.0)

    antes, depois = panel._project.tracks[0].sorted_clips()
    assert antes.end == pytest.approx(5.0) and depois.start == pytest.approx(5.0)
    assert panel._filter_dur.value() == pytest.approx(5.0), "o campo anuncia uma duração que não existe"
    panel._filter_dur.setValue(3.0)
    assert panel._project.tracks[0].sorted_clips()[0].end == pytest.approx(3.0)
