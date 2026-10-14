"""O editor como no protótipo: colunas em cartões, grade de mídia em duas colunas e abas com o ícone sobre o texto.

O que uma troca de desenho perde em silêncio: a grade que volta a ter uma coluna só porque a barra de rolagem rouba 10 px
do cálculo, o selo da duração numa foto, a barra de abas que deixa de ocupar a coluna, o título "Adicionais" que sai e
leva o nome acessível junto. Os testes medem a geometria e os pixels, com o tema aplicado como no aplicativo real.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from videomanager.domain.project import MediaKind, MediaRef
from videomanager.presentation.qt import strings, theme
from videomanager.presentation.qt.panels.edit_widgets import _MediaCardDelegate


def _midias(n: int) -> list[MediaRef]:
    tipos = (MediaKind.VIDEO, MediaKind.VIDEO, MediaKind.AUDIO, MediaKind.IMAGE, MediaKind.VIDEO)
    return [MediaRef(Path(f"/x/m{i}.mp4"), tipos[i % len(tipos)], duration=7.0 + i, width=640, height=360, fps=30.0)
            for i in range(n)]


def _com_midias(painel, n: int = 5):
    painel._pool.extend(_midias(n))
    painel._refresh_pool()
    painel.resize(1500, 900)
    painel.show()
    for _ in range(6):
        QApplication.processEvents()
    return painel._media_list


def test_as_colunas_de_midia_e_adicionais_sao_cartoes_no_plano_do_cartao(tema_do_app, painel_de_edicao, desktop_app):
    painel = painel_de_edicao
    painel.resize(1500, 900)
    painel.show()
    for _ in range(5):
        desktop_app.processEvents()
    cores = theme.papeis("dark", "grafite")
    pagina = painel.grab().toImage()
    for coluna in (painel._media_box, painel._extras_box):
        assert coluna.property("role") == "pane"
        topo = coluna.mapTo(painel, coluna.rect().topLeft())
        # O canto de cima é arredondado (aparece o fundo da página), e o miolo é o plano do cartão.
        assert pagina.pixelColor(topo.x() + 1, topo.y() + 1).name().lower() == cores["canvas"].lower()
        # Na folga de cima do cartão (acima do cabeçalho e do ícone da primeira aba), longe dos controles.
        assert pagina.pixelColor(topo.x() + coluna.width() // 2, topo.y() + 4).name().lower() == cores["card"].lower()


def test_a_grade_de_midia_tem_duas_colunas_que_dividem_a_largura_com_10_px_entre_elas(tema_do_app, painel_de_edicao, desktop_app):
    lista = _com_midias(painel_de_edicao, 5)
    largura = lista.viewport().width()
    celulas = [lista.visualItemRect(lista.item(i)) for i in range(5)]
    assert celulas[0].y() == celulas[1].y() < celulas[2].y() == celulas[3].y() < celulas[4].y()
    assert celulas[0].x() < celulas[1].x() and celulas[0].x() == celulas[2].x() == celulas[4].x()
    miniatura = _MediaCardDelegate.miniatura(largura)
    # Esquerda encostada na borda esquerda, direita na direita: o que sobra no meio é o vão do protótipo.
    esquerda_acaba = celulas[0].x() + miniatura.width()
    sobra = largura - 2 * celulas[0].width()  # os pixels que sobram depois das duas células
    direita_comeca = celulas[1].right() + 1 + sobra - miniatura.width()
    assert celulas[0].x() == 0 and direita_comeca - esquerda_acaba == _MediaCardDelegate.ENTRE == 10
    assert celulas[1].right() + 1 + sobra == largura  # a miniatura da direita termina na borda da lista
    assert abs(miniatura.width() / miniatura.height() - 16 / 9) < 0.05


def test_a_grade_acompanha_a_largura_e_nao_depende_da_barra_de_rolagem(tema_do_app, painel_de_edicao, desktop_app):
    lista = _com_midias(painel_de_edicao, 5)
    assert lista.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    antes = _MediaCardDelegate.miniatura(lista.viewport().width())
    painel_de_edicao._top_splitter.setSizes([420, 400, 600])
    for _ in range(5):
        desktop_app.processEvents()
    depois = _MediaCardDelegate.miniatura(lista.viewport().width())
    assert depois.width() > antes.width()
    celulas = [lista.visualItemRect(lista.item(i)) for i in range(4)]
    assert celulas[0].y() == celulas[1].y() and celulas[0].x() < celulas[1].x()  # ainda duas colunas


def _pinta(lista, linha: int) -> QImage:
    """A célula ``linha`` como o delegate a pinta, sobre um fundo neutro."""
    delegate = lista.itemDelegate()
    celula = _MediaCardDelegate.celula(lista.viewport().width())
    imagem = QImage(celula.width() + 4, celula.height(), QImage.Format.Format_ARGB32)
    imagem.fill(Qt.GlobalColor.black)
    opcao = QStyleOptionViewItem()
    opcao.rect = QRect(0, 0, celula.width(), celula.height())
    opcao.widget = lista
    opcao.font = lista.font()
    painter = QPainter(imagem)
    delegate.paint(painter, opcao, lista.model().index(linha, 0))
    painter.end()
    return imagem


def test_a_duracao_aparece_no_canto_da_miniatura_so_do_que_tem_tempo(tema_do_app, painel_de_edicao, desktop_app):
    lista = _com_midias(painel_de_edicao, 5)
    miniatura = _MediaCardDelegate.miniatura(lista.viewport().width())
    # Canto de baixo e à direita da miniatura da coluna esquerda (a linha 0 é vídeo; a 3, foto).
    ponto = QSize(miniatura.width() - 14, miniatura.height() - 12)
    com_tempo = _pinta(lista, 0)
    foto = _pinta(lista, 3)
    # No vídeo há o selo escuro com o texto claro; na foto, o ponto é o da própria miniatura (sem selo).
    claro = lambda imagem: max(imagem.pixelColor(x, ponto.height() + 3).lightness() for x in range(ponto.width() - 6, ponto.width() + 10))
    assert claro(com_tempo) > 150  # o texto branco do selo
    assert claro(foto) < 60  # nada ali


def test_o_selo_da_coluna_de_midia_e_so_o_numero_e_some_sem_midia(tema_do_app, painel_de_edicao, desktop_app):
    painel = painel_de_edicao
    assert not painel._pool_count_label.isVisibleTo(painel._media_box)
    _com_midias(painel, 5)
    assert painel._pool_count_label.text() == "5" and painel._pool_count_label.isVisibleTo(painel._media_box)


def test_a_barra_de_abas_empilha_icone_e_texto_e_ocupa_a_coluna_inteira(tema_do_app, painel_de_edicao, desktop_app):
    painel = painel_de_edicao
    painel.resize(1500, 900)
    painel.show()
    for _ in range(5):
        desktop_app.processEvents()
    abas = painel._extras_tabs
    barra = abas.tabBar()
    assert barra.width() == abas.width()  # de ponta a ponta, e não a largura mínima do conteúdo
    larguras = [barra.tabRect(i).width() for i in range(barra.count())]
    assert max(larguras) - min(larguras) <= 1 and sum(larguras) <= barra.width()
    assert all(not barra.tabIcon(i).isNull() for i in range(barra.count()))
    assert barra.tabRect(0).height() >= 56 and barra.sizeHint().width() <= barra.width()
    # O ícone fica em cima do texto: o desenho da aba marcada leva o acento no sublinhado da base.
    imagem = barra.grab().toImage()
    acento = theme.papeis("dark", "grafite")["accent"].lower()
    caixa = barra.tabRect(abas.currentIndex())
    assert imagem.pixelColor(caixa.center().x(), barra.height() - 1).name().lower() == acento
    outra = barra.tabRect((abas.currentIndex() + 1) % barra.count())
    assert imagem.pixelColor(outra.center().x(), barra.height() - 1).name().lower() != acento


def test_a_dica_da_coluna_de_adicionais_nao_depende_da_largura_que_ela_tem(tema_do_app, painel_de_edicao, desktop_app):
    painel = painel_de_edicao
    painel.resize(1500, 900)
    painel.show()
    for _ in range(5):
        desktop_app.processEvents()
    coluna, barra = painel._extras_box, painel._extras_tabs.tabBar()
    # A barra pede a soma dos pisos das abas, e não a largura que a coluna já tem: pedindo a do pai, a coluna
    # alargada a 700 px passava a pedir 700 e o divisor deixava de caber a prévia (616 px onde eram 512).
    piso = sum(barra._minimo(i) for i in range(barra.count()))
    assert barra.sizeHint().width() == barra.minimumSizeHint().width() == piso
    antes = coluna.sizeHint().width()
    painel._top_splitter.setSizes([292, 700, 400])
    for _ in range(3):
        desktop_app.processEvents()
    assert painel._extras_tabs.width() > antes + 100
    assert coluna.sizeHint().width() == antes
    assert barra.width() == painel._extras_tabs.width()


def test_o_titulo_adicionais_saiu_e_o_nome_acessivel_ficou(painel_de_edicao):
    from PySide6.QtWidgets import QLabel
    painel = painel_de_edicao
    textos = [label.text() for label in painel._extras_box.findChildren(QLabel)]
    assert strings.EDIT_EXTRAS_TITLE not in textos
    assert painel._extras_box.accessibleName() == strings.EDIT_EXTRAS_TITLE


def test_a_barra_de_cima_tem_dois_fios_o_titulo_de_15_px_e_o_icone_da_tela(tema_do_app, painel_de_edicao, desktop_app):
    from PySide6.QtWidgets import QFrame
    painel = painel_de_edicao
    painel.resize(1500, 900)
    painel.show()
    for _ in range(5):
        desktop_app.processEvents()
    fios = [f for f in painel.findChildren(QFrame) if f.property("role") == "divider"]
    assert len(fios) == 2 and {(f.width(), f.height()) for f in fios} == {(1, 22)}
    assert painel._project_label.property("role") == "doc-title" and painel._project_label.font().pixelSize() == 15
    assert not painel._canvas_selector.icon().isNull()


def test_a_margem_do_editor_e_a_do_prototipo(tema_do_app, desktop_app, monkeypatch):
    from videomanager.presentation.qt.panels.edit_panel import _EDITOR_MARGINS
    assert _EDITOR_MARGINS == (14, 17, 14, 12)
