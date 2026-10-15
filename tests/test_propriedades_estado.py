"""O botão marcado da aba Propriedades é o que o bloco diz, depois de cada clique.

Um usuário relatou botões que "aplicam mas não ficam marcados de primeira" e funcionam na segunda tentativa. A causa era o
bloco **desmarcado na linha do tempo** com a aba aberta nele (um clique na prévia ou num vão basta): a primeira edição
gravava o valor no modelo e a seleção que ela refazia recarregava os controles pelo projeto antigo da linha do tempo, que
ainda não tinha recebido o novo. Este arquivo fixa a invariante que o relato quebrava: **depois de um clique, o estado
exibido de todo botão marcável é o mesmo que o painel produz ao recarregar o bloco** (é o que ele faz a cada edição, por
``_sync_extras_controls``). Se a tela está "atrasada" em relação ao bloco, o recarregamento a desmente.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication

from videomanager.presentation.qt.panels.field_box import WrapCheck
from videomanager.presentation.qt.panels.segmented import SegmentButton

# O bloco de filtro só tem deslizantes: não há botão marcável nele para medir.
BLOCOS = ["video com som", "video sem som", "imagem", "audio", "texto", "transicao"]


def _processar(vezes: int = 4) -> None:
    for _ in range(vezes):
        QApplication.processEvents()


def _marcaveis(propriedades) -> list[QAbstractButton]:
    return [b for b in propriedades.findChildren(QAbstractButton)
            if isinstance(b, (WrapCheck, SegmentButton)) and b.isVisibleTo(propriedades) and b.isEnabled()]


def _clicar(botao: QAbstractButton) -> None:
    """Clique de verdade no meio do botão (a linha inteira do ``WrapCheck`` responde, como a de qualquer botão)."""
    QTest.mouseClick(botao, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, botao.rect().center())


def _estados(propriedades) -> dict[int, tuple[str, bool]]:
    return {i: (b.text(), b.isChecked()) for i, b in enumerate(_marcaveis(propriedades))}


@pytest.mark.parametrize("desmarcado", [False, True], ids=["selecionado", "desmarcado"])
@pytest.mark.parametrize("nome", BLOCOS)
def test_depois_de_cada_clique_o_botao_mostra_o_que_o_bloco_diz(tema_do_app, painel_de_edicao, blocos_de_edicao, nome,
                                                                  desmarcado):
    painel = painel_de_edicao
    bloco = blocos_de_edicao[nome]
    painel.resize(1500, 1100)
    painel.show()
    painel._timeline.select(bloco.clip_id)
    painel._open_properties_tab(bloco.clip_id)
    _processar(8)
    propriedades = painel._properties_widget
    botoes = _marcaveis(propriedades)
    assert botoes, f"a aba Propriedades de um bloco de {nome} não tem botão marcável: o teste não mede nada"
    for botao in botoes:
        for tentativa in (1, 2):
            if not botao.isEnabled():  # "Fundo desfocado" fica desligado com o chroma key ligado: é regra do painel
                break
            if desmarcado:
                painel._timeline.select(-1)
            marcado_antes = botao.isChecked()
            _clicar(botao)
            _processar()
            if isinstance(botao, WrapCheck):  # um clique que o botão ignora passaria pela comparação abaixo sem medir nada
                assert botao.isChecked() != marcado_antes, f"{nome}: o clique em {botao.text()!r} não alternou a caixa"
            exibido = _estados(propriedades)
            atual = painel._project.find(bloco.clip_id)[1]
            propriedades.load_clip(atual, painel._project.width, painel._project.height, fps=painel._project.fps,
                                   text_ratio=painel._project.text_ratio)
            _processar()
            recarregado = _estados(propriedades)
            # O recarregamento pode habilitar ou desabilitar controles (o chroma liga e desliga o fundo desfocado):
            # compara só o que está nos dois conjuntos.
            diferentes = [(exibido[i][0], exibido[i][1], recarregado[i][1]) for i in exibido
                          if i in recarregado and exibido[i][0] == recarregado[i][0] and exibido[i] != recarregado[i]]
            assert not diferentes, (f"{nome}: depois do clique {tentativa} em {botao.text()!r} a tela diz uma coisa e o bloco "
                                    f"outra (botão, exibido, bloco): {diferentes}")


def test_editar_pela_aba_com_o_bloco_desmarcado_o_marca_de_novo_e_mostra_o_valor(tema_do_app, painel_de_edicao,
                                                                                  blocos_de_edicao):
    """O relato do usuário, ponta a ponta: um clique em 90° com o bloco de texto desmarcado.

    A tela tem de mostrar 90° já no primeiro clique, o campo de rotação tem de dizer 90 e o bloco volta à seleção,
    que é o que a edição pela aba sempre prometeu.
    """
    painel = painel_de_edicao
    bloco = blocos_de_edicao["texto"]
    painel.resize(1500, 1100)
    painel.show()
    painel._timeline.select(bloco.clip_id)
    painel._open_properties_tab(bloco.clip_id)
    _processar(8)
    propriedades = painel._properties_widget
    painel._timeline.select(-1)
    noventa = next(b for b in _marcaveis(propriedades) if b.text() == "90°")
    _clicar(noventa)
    _processar()
    assert painel._project.find(bloco.clip_id)[1].rotation == 90.0
    assert propriedades._spin_rot.value() == 90.0
    assert noventa.isChecked()
    assert painel._timeline.selected == bloco.clip_id
