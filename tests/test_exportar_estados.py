"""Contrato do diálogo de exportação: o que aparece e o que fica habilitado em cada estado.

A reorganização visual do diálogo (seções em cartões, tamanho estimado no rodapé) mexe em
onde cada controle fica, e é fácil, nesse caminho, deixar um campo visível onde devia sumir
— o codec numa exportação só de áudio, a qualidade num GIF — ou habilitar o que o projeto
não permite. Nada disso levanta exceção. Os valores abaixo foram **medidos no diálogo de
hoje**, num projeto de um clipe só (o único caso em que "Corte rápido" é permitido).
"""

from __future__ import annotations


import pytest

from videomanager.presentation.qt import strings

_ORDEM = ("_audio_only_check", "_container_box", "_video_codec_box", "_quality_box", "_aspect_box", "_canvas_box",
          "_rate_box", "_fast", "_interpolate", "_audio_format_box", "_same_folder", "_dest_edit",
          "_pick_folder_button", "_filename_edit", "_size_label", "_plan", "_warning", "_enqueue_button",
          "_cancel_button")

# (visível, habilitado), na ordem de _ORDEM.
_VIDEO = ((1, 1), (1, 1), (1, 1), (1, 1), (1, 1), (1, 1), (1, 1), (1, 1), (1, 0), (0, 1), (1, 1), (1, 0),
          (1, 0), (1, 1), (1, 1), (1, 1), (0, 1), (1, 1), (1, 1))
_AUDIO = ((1, 1), (0, 1), (0, 1), (0, 1), (0, 1), (0, 1), (0, 1), (0, 0), (0, 0), (1, 1), (1, 1), (1, 0),
          (1, 0), (1, 1), (1, 1), (1, 1), (0, 1), (1, 1), (1, 1))
_GIF = ((1, 1), (1, 1), (0, 1), (0, 1), (1, 1), (1, 1), (1, 1), (1, 0), (1, 0), (0, 1), (1, 1), (1, 0),
        (1, 0), (1, 1), (1, 1), (1, 1), (1, 1), (1, 1), (1, 1))


@pytest.fixture
def dialogo(dialogo_de_exportacao):
    return dialogo_de_exportacao


def _estado(dialogo) -> tuple[tuple[int, int], ...]:
    return tuple((int(getattr(dialogo, nome).isVisibleTo(dialogo)), int(getattr(dialogo, nome).isEnabled()))
                 for nome in _ORDEM)


def _diferencas(obtido, esperado) -> list[str]:
    return [f"{nome}: obtido {o}, esperado {e}" for nome, o, e in zip(_ORDEM, obtido, esperado) if o != e]


def test_estado_de_video_e_o_de_hoje(dialogo):
    assert not _diferencas(_estado(dialogo), _VIDEO)
    assert ".mp4 (H.264)" in dialogo._plan.text()


def test_somente_audio_deixa_so_o_formato_de_audio(dialogo):
    dialogo._audio_only_check.setChecked(True)
    assert not _diferencas(_estado(dialogo), _AUDIO)
    assert ".mp3" in dialogo._plan.text()


def test_gif_tira_codec_e_qualidade_e_avisa_que_nao_tem_som(dialogo):
    dialogo._container_box.setCurrentIndex(dialogo._container_box.findData("gif"))
    assert not _diferencas(_estado(dialogo), _GIF)
    assert strings.EXPORT_GIF_NOTE in dialogo._warning.text()
    assert ".gif" in dialogo._plan.text()


def test_voltar_de_gif_para_mp4_restaura_o_estado_de_video(dialogo):
    dialogo._container_box.setCurrentIndex(dialogo._container_box.findData("gif"))
    dialogo._container_box.setCurrentIndex(dialogo._container_box.findData("mp4"))
    assert not _diferencas(_estado(dialogo), _VIDEO)
