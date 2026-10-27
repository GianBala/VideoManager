"""O desfoque de região não toma o clique dos itens que ele borra.

O retângulo do desfoque fica sempre numa trilha **acima** do que borra, e a prévia escolhe o primeiro
bloco que acerta, de cima para baixo. Se o corpo da região valesse como acerto, nenhuma imagem, vídeo ou
texto sob ela poderia ser clicado ou arrastado. Inativa, a região só se seleciona pela borda (ou pela linha
do tempo); ativa, ela se arrasta por dentro como qualquer bloco.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtGui import QPixmap

from videomanager.domain.constants import REGION_BLUR
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import OverlayType
from videomanager.domain.project import pseudo_media
from videomanager.presentation.qt.panels.edit_widgets import _Preview

pytestmark = pytest.mark.usefixtures("desktop_app")

LARGURA, ALTURA = 640, 360
VIDEO_ID, IMAGEM_ID, DESFOQUE_ID, ACIMA_ID = 1, 2, 3, 4


def _midia(nome: str, tipo: MediaKind) -> MediaRef:
    return MediaRef(Path(nome), tipo, duration=6.0, width=1280, height=720, fps=30.0)


def _video() -> Clip:
    return Clip(_midia("v.mp4", MediaKind.VIDEO), 0.0, 6.0, clip_id=VIDEO_ID)


def _imagem(clip_id: int = IMAGEM_ID, x: float = 0.35) -> Clip:
    return Clip(_midia("i.png", MediaKind.IMAGE), 0.0, 5.0, clip_id=clip_id, x=x, y=0.5,
                scale=0.4, scale_x=0.4, scale_y=0.4, overlay_type="image")


def _desfoque() -> Clip:
    """Cobre o meio da imagem: o centro dela cai dentro do retângulo do desfoque."""
    return Clip(pseudo_media(OverlayType.FILTER, REGION_BLUR, 5.0), 0.0, 5.0, clip_id=DESFOQUE_ID,
                overlay_type="filter", filter_name=REGION_BLUR, x=0.35, y=0.5, scale=0.3, scale_x=0.3, scale_y=0.3)


class _Cena:
    """Prévia com a pilha de baixo para cima (vídeo, imagem, desfoque) e o que cada gesto fez."""

    def __init__(self, ativo: Clip | None, pilha: tuple[Clip, ...]) -> None:
        self.previa = _Preview()
        self.previa.resize(LARGURA, ALTURA)
        self.previa.set_frame_pixmap(QPixmap(LARGURA, ALTURA))
        self.previa.set_active_clip(ativo, LARGURA, ALTURA)
        self.previa.set_position(1.0)
        self.previa._selectable_clips = pilha
        self.selecionados: list[int] = []
        self.fora: list[int] = []
        self.movidos: list[int] = []
        self.previa.clip_selected.connect(self.selecionados.append)
        self.previa.clicked_outside.connect(lambda: self.fora.append(1))
        self.previa.overlay_transformed.connect(lambda cid, *_: self.movidos.append(cid))

    def centro(self, clip: Clip, fx: float = 0.0, fy: float = 0.0) -> tuple[float, float]:
        cx, cy, w, h = self.previa._clip_geometry(clip)
        return cx + w * fx, cy + h * fy

    def _evento(self, tipo, ponto, botoes=Qt.MouseButton.LeftButton) -> QMouseEvent:
        p = QPointF(*ponto)
        return QMouseEvent(tipo, p, p, Qt.MouseButton.LeftButton, botoes, Qt.KeyboardModifier.NoModifier)

    def clicar(self, ponto: tuple[float, float]) -> None:
        self.previa.mousePressEvent(self._evento(QMouseEvent.Type.MouseButtonPress, ponto))
        self.previa.mouseReleaseEvent(
            self._evento(QMouseEvent.Type.MouseButtonRelease, ponto, Qt.MouseButton.NoButton))

    def arrastar(self, de: tuple[float, float], dx: float = 40, dy: float = 20) -> None:
        para = (de[0] + dx, de[1] + dy)
        self.previa.mousePressEvent(self._evento(QMouseEvent.Type.MouseButtonPress, de))
        self.previa.mouseMoveEvent(self._evento(QMouseEvent.Type.MouseMove, para))
        self.previa.mouseReleaseEvent(
            self._evento(QMouseEvent.Type.MouseButtonRelease, para, Qt.MouseButton.NoButton))


def _pilha(*extra: Clip) -> tuple[Clip, ...]:
    return (_video(), _imagem(), _desfoque(), *extra)


# -- o corpo da região deixa o gesto passar ----------------------------------------------------

def test_clicar_na_imagem_sob_o_desfoque_seleciona_a_imagem():
    cena = _Cena(None, _pilha())
    cena.clicar(cena.centro(_imagem()))
    assert cena.selecionados == [IMAGEM_ID]


def test_arrastar_a_imagem_ativa_sob_o_desfoque_move_a_imagem_e_so_ela():
    imagem = _imagem()
    cena = _Cena(imagem, _pilha())
    cena.arrastar(cena.centro(imagem))
    assert cena.selecionados == []
    assert cena.movidos and set(cena.movidos) == {IMAGEM_ID}
    assert cena.previa._active_clip.x > imagem.x


def test_arrastar_o_video_ativo_sob_o_desfoque_move_o_video():
    video, desfoque = _video(), _desfoque()
    cena = _Cena(video, (video, desfoque))
    cena.arrastar(cena.centro(desfoque))
    assert cena.selecionados == []
    assert cena.movidos and set(cena.movidos) == {VIDEO_ID}


def test_o_video_ativo_cede_o_gesto_a_imagem_que_esta_acima_dele_e_nao_ao_desfoque():
    """Como antes do desfoque: de dois blocos que acertam, o de cima ganha — e o desfoque, inativo, não acerta."""
    video = _video()
    cena = _Cena(video, _pilha())
    cena.arrastar(cena.centro(_desfoque()))
    assert cena.selecionados == [IMAGEM_ID]


def test_clicar_no_corpo_do_desfoque_sem_nada_embaixo_deixa_o_clique_passar():
    """Sem item sob o ponteiro, o clique é "fora" (tira a seleção), como em qualquer área vazia."""
    desfoque = _desfoque()
    cena = _Cena(None, (desfoque,))
    cena.clicar(cena.centro(desfoque))
    assert cena.selecionados == [] and cena.fora == [1]


# -- a borda continua sendo o jeito de pegar a região inativa ------------------------------------

@pytest.mark.parametrize("fx, fy, dentro", [
    (0.5, 0.0, 2), (-0.5, 0.0, 2), (0.0, 0.5, 2), (0.0, -0.5, 2),      # as quatro bordas, 2 px para dentro
    (0.5, 0.5, 2), (-0.5, -0.5, 6),                                    # os cantos
    (0.5, 0.0, -3),                                                    # 3 px para fora
])
def test_clicar_na_borda_do_desfoque_inativo_seleciona_o_desfoque(fx, fy, dentro):
    desfoque = _desfoque()
    cena = _Cena(None, _pilha())
    cx, cy, w, h = cena.previa._clip_geometry(desfoque)
    x, y = cx + w * fx, cy + h * fy
    x -= dentro * (1 if fx > 0 else -1 if fx < 0 else 0)
    y -= dentro * (1 if fy > 0 else -1 if fy < 0 else 0)
    cena.clicar((x, y))
    assert cena.selecionados == [DESFOQUE_ID]


def test_a_borda_tem_largura_limitada_para_dentro_e_para_fora():
    desfoque = _desfoque()
    cena = _Cena(None, _pilha())
    cx, cy, w, h = cena.previa._clip_geometry(desfoque)
    # 20 px para dentro: já é corpo, passa ao item de baixo (a imagem).
    cena.clicar((cx + w / 2 - 20, cy))
    assert cena.selecionados == [IMAGEM_ID]
    # 10 px para fora: já não é da região (cai na imagem, que é maior que o desfoque).
    cena.selecionados.clear()
    cena.clicar((cx + w / 2 + 10, cy))
    assert DESFOQUE_ID not in cena.selecionados


# -- o desfoque ativo continua se comportando como um bloco -------------------------------------

def test_o_desfoque_ativo_se_arrasta_por_dentro():
    desfoque = _desfoque()
    cena = _Cena(desfoque, _pilha())
    cena.arrastar(cena.centro(desfoque))
    assert cena.selecionados == []
    assert cena.movidos and set(cena.movidos) == {DESFOQUE_ID}
    assert cena.previa._active_clip.x > desfoque.x


def test_o_desfoque_ativo_cede_o_gesto_a_um_item_que_esteja_acima_dele():
    """A regra de antes: com dois blocos no mesmo ponto, o de cima recebe o clique."""
    desfoque = _desfoque()
    acima = _imagem(ACIMA_ID)
    cena = _Cena(desfoque, _pilha(acima))
    cena.clicar(cena.centro(desfoque))
    assert cena.selecionados == [ACIMA_ID]


def test_clicar_no_desfoque_inativo_sob_um_item_ainda_seleciona_o_item_de_cima():
    acima = _imagem(ACIMA_ID)
    cena = _Cena(None, _pilha(acima))
    cena.clicar(cena.centro(_desfoque()))
    assert cena.selecionados == [ACIMA_ID]
