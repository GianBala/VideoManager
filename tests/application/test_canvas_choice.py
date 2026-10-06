"""Escolha de tela e proporção da saída, comum ao painel e à janela de exportação."""

from pathlib import Path

from videomanager.application.editor.canvas import aspect_of, canvas_for_aspect, output_canvas
from videomanager.domain.project import MediaKind, MediaRef, new_project


def test_proporcao_mantem_a_tela_que_ja_tem_ela_e_senao_pega_a_primeira_da_lista():
    assert canvas_for_aspect("16:9", (1280, 720)) == (1280, 720)
    assert canvas_for_aspect("9:16", (1280, 720)) == (1080, 1920)
    assert canvas_for_aspect(None, (1280, 720)) is None


def test_tela_escolhida_define_a_proporcao():
    assert aspect_of((1080, 1080)) == "1:1"
    assert aspect_of(None) is None


def test_automatica_segue_o_material_em_cada_metade():
    projeto = new_project(MediaRef(Path("v.mp4"), MediaKind.VIDEO, duration=5, width=1920, height=1080, fps=30000 / 1001))
    assert output_canvas(projeto, None, None) == (1920, 1080, 30000 / 1001)
    assert output_canvas(projeto, (1280, 720), None) == (1280, 720, 30000 / 1001)
    assert output_canvas(projeto, None, 60.0) == (1920, 1080, 60.0)
