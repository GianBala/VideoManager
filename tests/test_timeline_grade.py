"""Os gestos da linha do tempo caem na grade de quadros, e o ímã continua mandando.

O ponteiro anda em frações de quadro (a 1 s de janela, 1 px são ~0,7 ms), e uma ponta solta
ali ficava entre dois quadros: a exportação a arredonda, e o quadro que sai não é o que se
viu. Nada disto levantava erro — o corte saía um quadro adiante —, por isso os testes medem
o instante gravado no projeto a cada movimento do mouse, e não o fim do gesto.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt.panels.edit_panel import EditPanel
from videomanager.presentation.qt.panels.timeline import RULER_HEIGHT

pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")

FPS = 30.0
QUADRO = 1 / FPS
VIDEO = MediaRef(Path("/tmp/v.mp4"), MediaKind.VIDEO, duration=60.0, width=160, height=90, fps=FPS)
SOM = MediaRef(Path("/tmp/s.mp3"), MediaKind.AUDIO, duration=60.0, has_audio=True, channels=2)


@pytest.fixture
def panel():
    painel = EditPanel(settings=Settings(), ensure_tools=lambda: None, editor=build_editor_service(),
                       processing=build_processing_service(), runtime=build_desktop_runtime(audio_enabled=False))
    painel.resize(1600, 900)
    painel.show()
    painel.activateWindow()
    QApplication.processEvents()
    yield painel
    painel.shutdown()


def instalar(panel, *trilhas: Track) -> None:
    panel.install_project(Project(tracks=trilhas, fps=FPS), None, [], {})


def na_grade(segundos: float) -> bool:
    return abs(segundos * FPS - round(segundos * FPS)) < 1e-6


def arrastar(timeline, inicio: QPoint, passos: int, dx: int, ao_mover) -> None:
    """Pressiona, move 1 px por vez chamando ``ao_mover`` a cada passo, e solta."""
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, inicio)
    ponto = inicio
    for passo in range(1, passos + 1):
        ponto = QPoint(inicio.x() + passo * dx, inicio.y())
        QTest.mouseMove(timeline, ponto)
        ao_mover()
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)


def y_da_trilha(timeline, indice: int = 0) -> int:
    return round(timeline._lane_rect(indice).center().y())


def test_a_alca_final_cai_no_limite_de_quadro_a_cada_movimento(panel):
    instalar(panel, Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 0.0, 5.0),)))
    timeline = panel._timeline
    timeline.set_view(4.0, 5.0)
    fins = []
    arrastar(timeline, QPoint(round(timeline._x_of(5.0)) - 2, y_da_trilha(timeline)), 120, -1,
             lambda: fins.append(panel._project.clips[0].end))
    assert len(set(round(f * FPS) for f in fins)) >= 3, "a alça não se mexeu"
    assert all(na_grade(f) for f in fins), f"ponta fora da grade: {[f * FPS for f in fins if not na_grade(f)][:3]}"


def test_a_alca_inicial_cai_no_limite_de_quadro_a_cada_movimento(panel):
    instalar(panel, Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 10.0, 5.0, in_point=10.0),)))
    timeline = panel._timeline
    timeline.set_view(9.5, 10.5)
    inicios = []
    arrastar(timeline, QPoint(round(timeline._x_of(10.0)) + 2, y_da_trilha(timeline)), 120, 1,
             lambda: inicios.append(panel._project.clips[0].start))
    assert len(set(round(i * FPS) for i in inicios)) >= 3
    assert all(na_grade(i) for i in inicios)
    # O começo no arquivo acompanha: o quadro que abre o bloco é o mesmo que a grade escolheu.
    bloco = panel._project.clips[0]
    assert na_grade(bloco.in_point)


def test_o_corpo_anda_de_quadro_em_quadro(panel):
    instalar(panel, Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 2.0, 3.0),)))
    timeline = panel._timeline
    timeline.set_view(1.5, 3.0)
    inicios = []
    arrastar(timeline, QPoint(round(timeline._x_of(3.0)), y_da_trilha(timeline)), 150, 1,
             lambda: inicios.append(panel._project.clips[0].start))
    assert all(na_grade(i) for i in inicios), [i * FPS for i in inicios if not na_grade(i)][:3]
    passos = sorted(set(inicios))
    assert len(passos) >= 3 and all(b - a == pytest.approx(QUADRO) for a, b in zip(passos, passos[1:])), \
        "o bloco pulou quadros no caminho"


def test_o_ima_vence_a_grade_e_encosta_no_vizinho_fora_dela(panel):
    """Um vizinho de projeto antigo termina fora da grade; encostar nele tem de ser exato."""
    vizinho = Clip(VIDEO, 0.0, 2.0123)
    arrastado = Clip(VIDEO, 5.0, 2.0)
    instalar(panel, Track(TrackKind.VIDEO, clips=(vizinho,)), Track(TrackKind.VIDEO, clips=(arrastado,)))
    timeline = panel._timeline
    timeline.set_view(1.0, 6.0)
    pressao = QPoint(round(timeline._x_of(5.5)), y_da_trilha(timeline, 1))
    # O bloco foi pego 0,5 s depois do começo: levar o mouse a 2,5123 s põe o começo dele a 1 px do fim do vizinho.
    passos = pressao.x() - round(timeline._x_of(2.0123 + 0.5))
    arrastar(timeline, pressao, passos, -1, lambda: None)
    achado = next(c for c in panel._project.clips if c.clip_id == arrastado.clip_id)
    assert achado.start == pytest.approx(2.0123, abs=1e-9), \
        f"o ímã devia encostar no vizinho (2,0123), e o bloco parou em {achado.start}"


def test_a_agulha_posta_pelo_mouse_fica_no_quadro_que_esta_sob_ela(panel):
    instalar(panel, Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 0.0, 5.0),)))
    timeline = panel._timeline
    timeline.set_view(0.0, 5.0)
    vistos = []
    timeline.scrubbed.connect(vistos.append)
    # 1,2345 s é o quadro 37 (37,035): o que está na tela é o 37, e a agulha vai ao começo dele.
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(round(timeline._x_of(1.2345)), RULER_HEIGHT // 2))
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       QPoint(round(timeline._x_of(1.2345)), RULER_HEIGHT // 2))
    assert vistos and all(na_grade(v) for v in vistos)
    assert timeline.position == pytest.approx(int(1.2345 * FPS) / FPS, abs=0.5 * QUADRO), timeline.position
    assert na_grade(timeline.position)


def test_so_audio_nao_tem_grade_e_a_agulha_segue_livre(panel):
    instalar(panel, Track(TrackKind.AUDIO, clips=(Clip(SOM, 0.0, 5.0),)))
    timeline = panel._timeline
    timeline.set_view(0.0, 5.0)
    QTest.mousePress(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(round(timeline._x_of(1.2345)), RULER_HEIGHT // 2))
    QTest.mouseRelease(timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       QPoint(round(timeline._x_of(1.2345)), RULER_HEIGHT // 2))
    assert timeline.position == pytest.approx(1.2345, abs=2 * timeline._seconds_per_pixel())
    assert not na_grade(timeline.position), "sem imagem não há quadro: a posição não devia ir para a grade"


def test_so_audio_a_alca_para_nos_50_ms_como_sempre(panel):
    instalar(panel, Track(TrackKind.AUDIO, clips=(Clip(SOM, 0.0, 1.0),)))
    timeline = panel._timeline
    timeline.set_view(0.0, 1.2)
    arrastar(timeline, QPoint(round(timeline._x_of(1.0)) - 2, y_da_trilha(timeline)),
             round(timeline._x_of(1.0) - timeline._x_of(0.0)) + 40, -1, lambda: None)
    assert panel._project.clips[0].duration == pytest.approx(0.05)


def test_a_tesoura_corta_no_comeco_do_quadro_mostrado(panel):
    instalar(panel, Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 0.0, 5.0),)))
    # A agulha parada entre os quadros 36 e 37, como fica ao pausar um material de outra taxa.
    panel._timeline.set_position(36.6 * QUADRO)
    assert panel._cursor == pytest.approx(36 * QUADRO)
    panel._split_here()
    esquerdo, direito = sorted(panel._project.clips, key=lambda c: c.start)
    assert esquerdo.end == pytest.approx(36 * QUADRO, abs=1e-12)
    assert direito.start == esquerdo.end
    assert direito.in_point == pytest.approx(36 * QUADRO, abs=1e-12)


def test_um_quadro_so_se_faz_com_duas_tesouras_e_a_alca_nao_o_desfaz(panel):
    instalar(panel, Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 0.0, 5.0),)))
    timeline = panel._timeline
    timeline.set_position(10 * QUADRO)
    panel._split_here()
    timeline.select(-1)
    timeline.set_position(11 * QUADRO)
    panel._split_here()
    blocos = sorted(panel._project.clips, key=lambda c: c.start)
    assert [round(b.duration * FPS) for b in blocos] == [10, 1, 139]
    meio = blocos[1]
    assert meio.duration == pytest.approx(QUADRO)
    # Com o bloco de um quadro à vista, a alça final não o encolhe nem o zera.
    timeline.set_view(0.1, 0.6)
    timeline.select(meio.clip_id)
    arrastar(timeline, QPoint(round(timeline._x_of(meio.end)) - 2, y_da_trilha(timeline)), 60, -1, lambda: None)
    depois = next(c for c in panel._project.clips if c.clip_id == meio.clip_id)
    assert depois.duration == pytest.approx(QUADRO), "a alça passou do piso de um quadro"


def test_aparar_no_cursor_deixa_exatamente_um_quadro(panel):
    instalar(panel, Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 0.0, 5.0),)))
    timeline = panel._timeline
    timeline.select(panel._project.clips[0].clip_id)
    timeline.set_position(1 * QUADRO)
    assert panel._can_trim(timeline.selected_clip, "fim"), "o primeiro quadro tem de poder ficar sozinho"
    panel._trim_to_cursor("fim")
    bloco = panel._project.clips[0]
    assert bloco.duration == pytest.approx(QUADRO) and bloco.start == 0.0


def test_colar_e_inserir_no_cursor_caem_na_grade(panel):
    instalar(panel, Track(TrackKind.VIDEO, clips=(Clip(VIDEO, 0.0, 5.0),)))
    timeline = panel._timeline
    timeline.select(panel._project.clips[0].clip_id)
    panel._copy_clip()
    timeline.set_position(3.0 + 0.4 * QUADRO)          # fora da grade, no meio do quadro 90
    panel._paste_clip()
    colado = max(panel._project.clips, key=lambda c: c.start)
    assert colado.start == pytest.approx(3.0, abs=1e-12) and na_grade(colado.start)
