"""Testes do contrato da prévia: taxa e tamanho fiéis ao material.

O caminho da prévia tem um acoplamento que não falha alto quando se rompe: o
fluxo de quadros é **gerado** numa taxa e **entregue** noutra, e se as duas se
separarem a reprodução sai em velocidade errada sem erro nenhum — foi assim que
o som já saiu ao dobro. Estes testes fixam as duas pontas.
"""

from __future__ import annotations

import inspect

import pytest

from videomanager.core.preview import MAX_PREVIEW_FPS, FramePump, fit_size, preview_fps
from videomanager.workers.preview_worker import PlaybackWorker


class TestTaxaDaPrevia:
    @pytest.mark.parametrize("nativo", [24.0, 25.0, 29.97, 30.0, 50.0, 60.0])
    def test_segue_a_taxa_do_material(self, nativo: float) -> None:
        # Uma taxa fixa mais baixa deixa a imagem aos trancos num vídeo de 30 ou
        # 60 fps — foi o que se via com os 15 fps de antes.
        assert preview_fps(nativo) == round(nativo)

    def test_teto_para_material_muito_rapido(self) -> None:
        assert preview_fps(240.0) == MAX_PREVIEW_FPS

    def test_sem_taxa_conhecida_usa_um_padrao_utilizavel(self) -> None:
        assert preview_fps(None) == 30
        assert preview_fps(0.0) == 30


class TestAcoplamentoDaTaxa:
    """A taxa não pode ter valor padrão em nenhuma das duas pontas.

    Um padrão faz o descuido passar calado: o comando é montado a 30 fps, o
    fluxo é entregue a 15, e a reprodução roda pela metade da velocidade sem
    levantar nada.
    """

    @pytest.mark.parametrize("alvo", [FramePump.__init__, PlaybackWorker.__init__])
    def test_fps_e_obrigatorio(self, alvo) -> None:
        parametro = inspect.signature(alvo).parameters["fps"]
        assert parametro.default is inspect.Parameter.empty
        assert parametro.kind is inspect.Parameter.KEYWORD_ONLY


class TestTamanho:
    def test_cabe_na_area_preservando_a_proporcao(self) -> None:
        assert fit_size(1920, 1080, 1920, 1080) == (1920, 1080)
        assert fit_size(1920, 1080, 960, 1080) == (960, 540)
        # Vertical de celular numa área larga: limita pela altura.
        assert fit_size(1080, 1920, 1920, 540) == (302, 540)

    def test_dimensoes_sempre_pares(self) -> None:
        # Escaladores e codificadores trabalham em blocos de dois pixels.
        largura, altura = fit_size(1919, 1079, 777, 777)
        assert largura % 2 == 0 and altura % 2 == 0
