"""A linha do tempo e o painel diante de um bloco invertido: onde cai cada trecho da mídia.

O bloco invertido cobre o mesmo trecho da mídia e a edição o percorre ao contrário:
o que está no topo do trecho aparece no começo do bloco. Miniaturas, onda, janela
de miniaturas e salto de quadro-chave guardam tempos da **mídia** e os desenham ou
usam no relógio da **edição**, então cada um tem de saber o sentido. Nenhum deles
levanta erro quando erra: a tira continua aparecendo, só que espelhada.
"""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
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
    QApplication.processEvents()
    yield painel
    painel.shutdown()


def _video(tmp_path: Path) -> MediaRef:
    # Arquivo de verdade: o bloco de referência da prévia só vale se a mídia existe.
    arquivo = tmp_path / "video.mp4"
    arquivo.write_bytes(b"x")
    return MediaRef(arquivo, MediaKind.VIDEO, duration=30.0, width=160, height=90, fps=30.0, has_audio=True, channels=2)


def _instala(panel, clip: Clip) -> None:
    panel.install_project(Project(tracks=(Track(TrackKind.VIDEO, clips=(clip,)),)), None, [], {})
    panel._timeline.set_view(0.0, 20.0)


def _bloco(tmp_path: Path, **campos) -> Clip:
    """Dez segundos da edição, de 2 s a 12 s, cobrindo o trecho 4 s a 14 s da mídia."""
    return Clip(_video(tmp_path), 2.0, 10.0, in_point=4.0, **campos)


def test_miniatura_do_topo_do_trecho_cai_no_comeco_do_bloco_invertido(panel, tmp_path):
    clip = _bloco(tmp_path, reversed=True)
    _instala(panel, clip)
    timeline, rect = panel._timeline, QRectF(0.0, 0.0, 100.0, 40.0)

    topo = timeline._source_rect(clip, rect, 10.0, 14.0)   # os 4 s de cima do trecho
    assert topo.left() == pytest.approx(timeline._x_of(2.0))
    assert topo.right() == pytest.approx(timeline._x_of(6.0))

    normal = timeline._source_rect(replace(clip, reversed=False), rect, 4.0, 8.0)   # os 4 s de baixo
    assert normal.left() == pytest.approx(timeline._x_of(2.0))
    assert normal.right() == pytest.approx(timeline._x_of(6.0))


def _pinta_onda(panel, clip: Clip) -> tuple[int, int]:
    """Vermelho sob o quarto esquerdo e o quarto direito do bloco, com a onda branca à esquerda da mídia."""
    onda = QImage(100, 20, QImage.Format.Format_RGB32)
    onda.fill(QColor("black"))
    for x in range(50):
        for y in range(20):
            onda.setPixelColor(x, y, QColor("white"))
    timeline = panel._timeline
    _instala(panel, clip)
    timeline.set_wave(clip.clip_id, clip.in_point, clip.out_point, onda)
    destino = QImage(timeline.width(), 80, QImage.Format.Format_ARGB32_Premultiplied)
    destino.fill(0)
    esquerda, direita = timeline._x_of(clip.start), timeline._x_of(clip.end)
    painter = QPainter(destino)
    timeline._paint_wave(painter, clip, QRectF(esquerda, 0.0, direita - esquerda, 60.0))
    painter.end()
    largura = direita - esquerda
    return (destino.pixelColor(int(esquerda + largura * 0.25), 30).red(),
            destino.pixelColor(int(esquerda + largura * 0.75), 30).red())


def test_onda_do_invertido_sai_espelhada(panel, tmp_path):
    # A onda é uma imagem da mídia, da esquerda para a direita no sentido dela: o começo da
    # mídia (a metade branca) fica no fim do bloco invertido.
    esquerda, direita = _pinta_onda(panel, _bloco(tmp_path))
    assert esquerda > 200 and direita < 50

    esquerda, direita = _pinta_onda(panel, _bloco(tmp_path, reversed=True))
    assert esquerda < 50 and direita > 200


def test_janela_das_miniaturas_do_invertido_vem_em_ordem_crescente(panel, tmp_path):
    clip = _bloco(tmp_path, reversed=True)
    _instala(panel, clip)
    panel._timeline.set_view(3.0, 6.0)
    vista_inicio, vista_fim = panel._timeline.view
    inicio, fim = panel._strip_window(clip)
    assert inicio < fim
    assert (inicio, fim) == pytest.approx((clip.source_time(vista_fim), clip.source_time(vista_inicio)))


@pytest.mark.parametrize(("invertido", "esperados"), [
    # Quadros-chave da mídia em 5 s, 8 s e 12 s. No bloco normal (começa em 2 s e lê desde 4 s) caem em 3, 6 e 10 s
    # da edição; no invertido (lê de 14 s para baixo) caem em 11, 8 e 4 s — a mesma lista, pela outra ponta.
    (False, [3.0, 6.0, 10.0]),
    (True, [4.0, 8.0, 11.0]),
], ids=["normal", "invertido"])
def test_salto_de_quadro_chave_segue_o_sentido_do_bloco(panel, tmp_path, invertido, esperados):
    clip = _bloco(tmp_path, reversed=invertido)
    _instala(panel, clip)
    panel._keyframe_source = clip.media.path
    panel._keyframes = (5.0, 8.0, 12.0)
    panel._timeline.set_position(0.0)
    visitados = []
    for _ in esperados:
        panel._jump_keyframe(+1)
        visitados.append(panel._position)
    assert visitados == pytest.approx(esperados)
    for anterior in reversed(esperados[:-1]):
        panel._jump_keyframe(-1)
        assert panel._position == pytest.approx(anterior)
