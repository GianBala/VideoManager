"""Aba Propriedades: seções recolhíveis, cabeçalho com a espécie do bloco e a mensagem do bloco sem ajustes.

A visibilidade das sete seções por tipo de bloco é o contrato de ``test_propriedades_por_tipo``; aqui fica o
que é do desenho novo: a seção que se recolhe sem perder o que o usuário pôs nos campos, a ordem de cima para
baixo, o cabeçalho que diz de que bloco se trata e o filtro, que não tem seção nenhuma, e por isso diz o que há.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from videomanager.domain import i18n
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.i18n import apply_language

_ORDEM = ("_transform_group", "_speed_group", "_volume_group", "_animation_group", "_chromakey_group",
          "_blur_group", "_transition_group")


def _abrir(painel, bloco) -> None:
    painel._timeline.select(bloco.clip_id)
    painel._open_properties_tab(bloco.clip_id)
    painel._properties_widget.show()
    painel.show()
    for _ in range(5):
        QApplication.processEvents()


def test_as_secoes_vem_na_ordem_do_contrato(painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    _abrir(painel, blocos_de_edicao["video com som"])
    widget = painel._properties_widget
    visiveis = [nome for nome in _ORDEM if getattr(widget, nome).isVisibleTo(widget)]
    assert visiveis == ["_transform_group", "_speed_group", "_volume_group", "_animation_group", "_chromakey_group",
                        "_blur_group"]
    posicoes = [getattr(widget, nome).mapTo(widget, getattr(widget, nome).rect().topLeft()).y() for nome in visiveis]
    assert posicoes == sorted(posicoes)


def test_recolher_uma_secao_esconde_o_corpo_e_nao_destroi_o_que_foi_posto_nos_campos(painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    _abrir(painel, blocos_de_edicao["video com som"])
    widget = painel._properties_widget
    secao = widget._speed_group
    widget._spin_speed.setValue(2.0)
    assert secao.expanded and widget._spin_speed.isVisibleTo(widget)
    QTest.mouseClick(secao._header, Qt.MouseButton.LeftButton)
    assert not secao.expanded and not widget._spin_speed.isVisibleTo(widget)
    assert widget._spin_speed.value() == 2.0
    # As outras seções não são afetadas, e o cabeçalho da recolhida continua à vista.
    assert widget._transform_group.expanded and secao.isVisibleTo(widget) and secao._header.isVisibleTo(widget)
    QTest.mouseClick(secao._header, Qt.MouseButton.LeftButton)
    assert secao.expanded and widget._spin_speed.isVisibleTo(widget) and widget._spin_speed.value() == 2.0


def test_o_teclado_recolhe_e_abre(painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    _abrir(painel, blocos_de_edicao["video com som"])
    secao = painel._properties_widget._volume_group
    secao._header.setFocus()
    QTest.keyClick(secao._header, Qt.Key.Key_Space)
    assert not secao.expanded
    QTest.keyClick(secao._header, Qt.Key.Key_Space)
    assert secao.expanded


def test_recolher_nao_conta_como_alteracao_do_projeto(painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    _abrir(painel, blocos_de_edicao["video com som"])
    antes = painel._project
    for nome in _ORDEM:
        getattr(painel._properties_widget, nome).set_expanded(False)
        getattr(painel._properties_widget, nome).set_expanded(True)
    assert painel._project is antes


def test_o_titulo_da_secao_segue_o_idioma(painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    _abrir(painel, blocos_de_edicao["video com som"])
    secao = painel._properties_widget._speed_group
    assert secao.title() == strings.PROP_SPEED
    apply_language(i18n.ENGLISH)
    try:
        assert secao.title() == strings.PROP_SPEED and secao.title() != "Velocidade"
    finally:
        apply_language(i18n.PORTUGUESE)


def test_o_cabecalho_traz_a_especie_o_id_e_fecha(painel_de_edicao, blocos_de_edicao):
    painel = painel_de_edicao
    widget = painel._properties_widget
    imagens = {}
    for tipo in ("video com som", "audio", "texto", "filtro", "transicao"):
        _abrir(painel, blocos_de_edicao[tipo])
        assert str(blocos_de_edicao[tipo].clip_id) in widget._lbl_clip_type.text()
        assert not widget._kind_tile.pixmap().isNull()
        imagens[tipo] = widget._kind_tile.pixmap().toImage()
    pares = list(imagens.values())
    assert all(a != b for i, a in enumerate(pares) for b in pares[i + 1:])  # cada espécie, o seu ladrilho
    pedidos = []
    widget.close_requested.connect(lambda: pedidos.append(1))
    widget._btn_close.click()
    assert pedidos == [1] and not widget._btn_close.icon().isNull()


def test_o_filtro_so_tem_a_secao_filtro_e_todo_tipo_de_bloco_tem_alguma_secao(painel_de_edicao, blocos_de_edicao):
    """Antes da caixa "Filtro móvel" o filtro não tinha seção nenhuma e a aba dizia "sem ajustes". Agora tem uma, e é
    só ela: a pose, a animação e o resto só aparecem quando o filtro é móvel. Nenhum tipo de bloco fica com a aba vazia
    (por isso o aviso "sem ajustes" deixou de existir): um tipo novo sem seção pede o aviso de volta."""
    painel = painel_de_edicao
    widget = painel._properties_widget
    _abrir(painel, blocos_de_edicao["filtro"])
    assert widget._filter_group.isVisibleTo(widget) and widget._chk_movable.isVisibleTo(widget)
    assert not any(getattr(widget, nome).isVisibleTo(widget) for nome in _ORDEM)
    for tipo in ("video com som", "imagem", "audio", "texto", "transicao"):
        _abrir(painel, blocos_de_edicao[tipo])
        assert any(grupo.isVisibleTo(widget) for grupo in widget._groups()), tipo
        assert not widget._filter_group.isVisibleTo(widget), tipo     # a caixa é só do filtro
    widget.clear()
    assert not any(grupo.isVisibleTo(widget) for grupo in widget._groups())
