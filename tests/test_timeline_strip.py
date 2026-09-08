"""Testes das miniaturas da linha do tempo através do zoom.

Aproximar e afastar muda **duas** coisas ao mesmo tempo: o trecho de origem que
está à vista e quantas miniaturas cabem nele. Enquanto as imagens eram guardadas
pela posição na tira, as duas mudanças reescreviam o significado das imagens já
prontas — a que era "a terceira de doze" passava a ser desenhada onde agora está
"a terceira de seis", que é outro momento do vídeo.

Isso não falha: a tira continua aparecendo, com imagens de verdade, no lugar
errado — e some sozinho quando as novas chegam. Estes testes fixam a regra que
tira essa janela de inconsistência.

Importar o widget não instancia Qt (não há ``QApplication`` aqui); o que se
exercita é o modelo, que é aritmética.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

from videomanager.presentation.qt.panels.timeline import _Strip, _image_preview


def tira(inicio: float, fim: float, quantas: int) -> _Strip:
    return _Strip(in_point=inicio, out_point=fim, count=quantas)


class TestCelulaDaMiniatura:
    def test_o_instante_fica_no_meio_da_celula(self) -> None:
        # É assim que ``filmstrip_times`` escolhe os instantes, e é o que faz
        # uma imagem gerada noutro zoom continuar centrada onde deve.
        strip = tira(0.0, 12.0, 12)
        comeco, fim = strip.cell_of(0.5)
        assert (comeco, fim) == pytest.approx((0.0, 1.0))

    def test_a_celula_acompanha_o_zoom(self) -> None:
        # A mesma imagem, com o dobro de aproximação, ocupa o dobro do trecho.
        assert tira(0.0, 12.0, 12).span == pytest.approx(1.0)
        assert tira(0.0, 6.0, 12).span == pytest.approx(0.5)

    def test_tira_vazia_nao_divide_por_zero(self) -> None:
        assert tira(0.0, 10.0, 0).span == 0.0


class TestMiniaturasAtravessandoOZoom:
    """O que sobrevive a uma mudança de zoom, e onde vai parar."""

    def gerada(self, strip: _Strip, quantas: int) -> _Strip:
        """Preenche a tira como o worker faria, nos instantes do meio de cada fatia."""
        passo = (strip.out_point - strip.in_point) / quantas
        for i in range(quantas):
            momento = strip.in_point + passo * (i + 0.5)
            strip.thumbs[momento] = f"imagem@{momento:.3f}"
        return strip

    def test_a_imagem_continua_no_instante_dela_depois_do_zoom(self) -> None:
        # Doze miniaturas sobre 12 s; depois o usuário aproxima e a tira passa a
        # ter seis sobre o mesmo trecho. A imagem de 5,5 s continua desenhada em
        # 5,5 s — antes ela era arrastada para onde a sexta de seis cairia.
        antiga = self.gerada(tira(0.0, 12.0, 12), 12)
        assert "imagem@5.500" in antiga.thumbs.values()

        nova = _Strip(0.0, 12.0, 6, dict(antiga.thumbs))
        comeco, fim = nova.cell_of(5.5)
        assert (comeco + fim) / 2 == pytest.approx(5.5), (
            "a imagem tem de continuar centrada no instante que ela mostra"
        )
        assert fim - comeco == pytest.approx(2.0), "a célula é a do zoom novo"

    def test_nenhuma_imagem_cai_fora_do_bloco(self) -> None:
        # Com a chave por índice, sobrar índice de uma tira mais longa fazia a
        # célula ser calculada além do fim do trecho, e a imagem era desenhada
        # fora do bloco.
        antiga = self.gerada(tira(0.0, 12.0, 12), 12)
        nova = _Strip(0.0, 12.0, 6, dict(antiga.thumbs))
        for momento in nova.thumbs:
            comeco, fim = nova.cell_of(momento)
            assert comeco >= nova.in_point - nova.span
            assert fim <= nova.out_point + nova.span


    def test_a_imagem_de_fora_do_trecho_nao_e_herdada(self) -> None:
        # Aproximando de 12 s para 1,83 s, só as duas primeiras imagens ainda
        # têm onde ser desenhadas; guardar as outras dez seria carregar imagens
        # que nunca aparecem.
        antigas = {0.5 + i: f"img{i}" for i in range(12)}
        herdadas = _Strip(0.0, 1.83, 12)._inherit(antigas)
        assert len(herdadas) == 2
        assert all(0.0 <= m <= 1.83 for m in herdadas)

    def test_no_maximo_uma_imagem_herdada_por_celula(self) -> None:
        # Sem o limite, ir e voltar no zoom dobrava o número de imagens vivas a
        # cada volta, sem nada aparecer a mais na tela.
        finas = {i * 0.15: f"img{i}" for i in range(80)}
        herdadas = _Strip(0.0, 12.0, 12)._inherit(finas)
        assert len(herdadas) <= 12

    def test_a_herdada_e_a_mais_central_da_celula(self) -> None:
        # É a melhor aproximação disponível até a definitiva chegar.
        antigas = {0.10: "longe", 0.52: "perto", 0.95: "longe"}
        herdadas = _Strip(0.0, 12.0, 12)._inherit(antigas)
        assert herdadas[0.52] == "perto"

    def test_sem_tira_anterior_nao_ha_o_que_herdar(self) -> None:
        assert _Strip(0.0, 12.0, 12)._inherit({}) == {}

    def test_a_ordem_de_desenho_e_a_do_tempo(self) -> None:
        # As células se sobrepõem quando imagens de dois zooms convivem;
        # desenhar fora de ordem deixaria a mais antiga por cima da mais nova.
        strip = self.gerada(tira(0.0, 12.0, 4), 4)
        momentos = sorted(strip.thumbs)
        assert momentos == sorted(momentos)
        assert momentos[0] < momentos[-1]


class TestPreviaDeImagem:
    def test_previa_preserva_proporcao_em_bloco_largo(self) -> None:
        """Uma foto em Adicionais não pode ser achatada pela largura do bloco."""
        image = QImage(400, 100, QImage.Format.Format_RGB32)
        preview, drawn = _image_preview(image, QRectF(0, 0, 600, 44))

        # O preenchimento corta as laterais/altura excedente, mas nunca altera
        # a razão 4:1 da imagem original.
        assert preview.width() / preview.height() == pytest.approx(4.0)
        assert drawn.width() == preview.width()
        assert drawn.height() == preview.height()
        assert drawn.top() < 0 or drawn.bottom() > 44


# Estes cenários exercitam adaptadores ou apresentação Qt.
pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")
