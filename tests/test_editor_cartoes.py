"""O editor como no protótipo: colunas em cartões, grade de mídia em duas colunas e abas com o ícone sobre o texto.

O que uma troca de desenho perde em silêncio: a grade que volta a ter uma coluna só porque a barra de rolagem rouba 10 px
do cálculo, o selo da duração numa foto, a barra de abas que deixa de ocupar a coluna, o título "Adicionais" que sai e
leva o nome acessível junto. Os testes medem a geometria e os pixels, com o tema aplicado como no aplicativo real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
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
    # Esquerda e direita a uma margem das bordas (é onde cabe o anel da seleção): o que sobra no meio é o vão do protótipo.
    margem = _MediaCardDelegate.MARGEM
    esquerda_comeca = celulas[0].x() + margem
    esquerda_acaba = esquerda_comeca + miniatura.width()
    sobra = largura - 2 * celulas[0].width()  # os pixels que sobram depois das duas células
    direita_acaba = celulas[1].right() + 1 + sobra - margem
    direita_comeca = direita_acaba - miniatura.width()
    assert celulas[0].x() == 0 and direita_comeca - esquerda_acaba == _MediaCardDelegate.ENTRE == 10
    assert esquerda_comeca == margem and direita_acaba == largura - margem
    assert abs(miniatura.width() / miniatura.height() - 16 / 9) < 0.05


def test_o_anel_da_selecao_aparece_inteiro_nas_duas_colunas_e_nao_e_cortado_pelas_bordas_da_lista(
        tema_do_app, painel_de_edicao, desktop_app):
    """O anel passa 2 px para fora da miniatura, e o viewport recorta o que sai dele: com as miniaturas coladas nas bordas, o
    anel da coluna da esquerda e o da direita saíam sem a borda de fora (e a seleção parecia mais fina que a do protótipo)."""
    lista = _com_midias(painel_de_edicao, 5)
    acento = QColor(theme.papeis("dark", "grafite")["accent"])
    largura = lista.viewport().width()

    def anel(x: int, y: int) -> bool:
        cor = lista.viewport().grab().toImage().pixelColor(x, y)
        return abs(cor.red() - acento.red()) + abs(cor.green() - acento.green()) + abs(cor.blue() - acento.blue()) < 40

    for linha, coluna in ((0, 0), (1, largura - 1)):
        lista.setCurrentRow(linha)
        desktop_app.processEvents()
        meio = lista.visualItemRect(lista.item(linha)).y() + 3 + _MediaCardDelegate.miniatura(largura).height() // 2
        assert anel(coluna, meio), f"o anel da linha {linha} está cortado na borda da lista"
        assert anel(coluna + (1 if coluna == 0 else -1), meio)  # e tem os 2 px da espessura, não só 1


class _RegiaoPintada(QObject):
    """Soma as regiões que o viewport de fato repinta: é o que o Qt entrega ao delegate, e o que fica fora dela não muda."""

    def __init__(self) -> None:
        super().__init__()
        self.regiao = QRegion()

    def eventFilter(self, objeto, evento) -> bool:  # noqa: N802
        if evento.type() == QEvent.Type.Paint:
            self.regiao = self.regiao.united(evento.region())
        return False


def test_o_anel_de_quem_sai_e_de_quem_entra_na_selecao_e_repintado_por_inteiro(tema_do_app, painel_de_edicao, desktop_app):
    """Na coluna da direita o anel passa 2 px da célula do item, e o Qt só repinta a célula: ao trocar a seleção a ponta
    direita do anel antigo ficava desenhada (e a do novo nascia sem ela) até a próxima pintura da lista inteira."""
    lista = _com_midias(painel_de_edicao, 4)
    largura = lista.viewport().width()
    espiao = _RegiaoPintada()
    lista.viewport().installEventFilter(espiao)
    lista.setCurrentRow(0)
    for _ in range(4):
        desktop_app.processEvents()
    for antes, depois in ((0, 1), (1, 3), (3, 2), (2, 0)):
        lista.setCurrentRow(antes)
        for _ in range(4):
            desktop_app.processEvents()
        espiao.regiao = QRegion()
        lista.setCurrentRow(depois)
        for _ in range(4):
            desktop_app.processEvents()
        for linha in (antes, depois):
            caixa = lista.visualItemRect(lista.item(linha))
            anel = _MediaCardDelegate.area_do_anel(caixa, linha, largura).toAlignedRect()
            fora = QRegion(anel).subtracted(espiao.regiao)
            assert fora.isEmpty(), f"{antes}→{depois}: o anel da linha {linha} tem {fora.boundingRect()} fora do que foi repintado"


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
    # Os fios da barra de cima: a barra de ferramentas da linha do tempo tem o dela (entre desfazer e dividir), à parte.
    barra_de_cima = painel._project_label.parentWidget()
    fios = [f for f in painel.findChildren(QFrame) if f.property("role") == "divider" and f.parentWidget() is barra_de_cima]
    assert len(fios) == 2 and {(f.width(), f.height()) for f in fios} == {(1, 22)}
    assert painel._project_label.property("role") == "doc-title" and painel._project_label.font().pixelSize() == 15
    assert not painel._canvas_selector.icon().isNull()


def test_a_margem_do_editor_e_a_do_prototipo(tema_do_app, desktop_app, monkeypatch):
    from videomanager.presentation.qt.panels.edit_panel import _EDITOR_MARGINS
    assert _EDITOR_MARGINS == (14, 17, 14, 12)


def _quadro_de(largura: int, altura: int, cor: str) -> QImage:
    quadro = QImage(largura, altura, QImage.Format.Format_RGB888)
    quadro.fill(QColor(cor))
    return quadro


def test_quadro_16_9_preenche_a_ficha_da_miniatura_sem_coluna_de_fundo(tema_do_app):
    """O quadro 16:9 (224×126) é 0,3% mais estreito que a ficha de 214×120, e o ``KeepAspectRatio`` o levava a 213 colunas:
    a que sobrava ficava com a cor do fundo, um pixel escuro junto do anel de seleção."""
    from videomanager.presentation.qt.panels.edit_panel import _FRAME_H, _FRAME_W, _THUMB_H, _THUMB_W, _ficha_do_quadro
    fundo = QColor("#101010")
    for largura, altura in ((_FRAME_W, _FRAME_H), (212, 120), (214, 120), (213, 120), (214, 119)):
        ficha = _ficha_do_quadro(_quadro_de(largura, altura, "#ff0000"), fundo).toImage()
        assert (ficha.width(), ficha.height()) == (_THUMB_W, _THUMB_H)
        pontas = [ficha.pixelColor(x, y).name() for x in (0, _THUMB_W - 1) for y in (0, _THUMB_H // 2, _THUMB_H - 1)]
        assert set(pontas) == {"#ff0000"}, f"{largura}×{altura}: {pontas}"


def test_quadro_de_outra_proporcao_continua_com_as_faixas_de_fundo(tema_do_app):
    """Um 4:3 ou um vertical não é arredondamento: as faixas são conteúdo e não podem virar imagem esticada."""
    from videomanager.presentation.qt.panels.edit_panel import _THUMB_H, _THUMB_W, _ficha_do_quadro
    fundo = QColor("#101010")
    quatro_tres = _ficha_do_quadro(_quadro_de(160, 120, "#ff0000"), fundo).toImage()
    assert quatro_tres.pixelColor(2, _THUMB_H // 2).name() == fundo.name()
    assert quatro_tres.pixelColor(_THUMB_W // 2, _THUMB_H // 2).name() == "#ff0000"
    vertical = _ficha_do_quadro(_quadro_de(68, 120, "#ff0000"), fundo).toImage()
    assert vertical.pixelColor(2, _THUMB_H // 2).name() == fundo.name() and vertical.pixelColor(_THUMB_W - 3, 5).name() == fundo.name()


def test_o_quadro_pedido_ao_ffmpeg_e_16_9_exato_e_sem_preenchimento_dentro():
    """A ficha é 214×120 (107:60), mas o quadro é pedido numa caixa 16:9 exata: pedido a 214×120, um 16:9 saía do
    ``_fit_filter`` com 212 colunas de imagem e 2 de preto dentro dos dados, que nenhum ajuste do lado do Qt enxerga."""
    from videomanager.presentation.qt.panels.edit_panel import _FRAME_H, _FRAME_W
    assert _FRAME_W * 9 == _FRAME_H * 16 and _FRAME_W % 2 == 0 and _FRAME_H % 2 == 0


@pytest.mark.ffmpeg
@pytest.mark.parametrize("origem", [(1280, 720), (1920, 1080), (854, 480), (1366, 768), (3840, 2160)])
def test_miniatura_de_video_16_9_chega_do_ffmpeg_sem_coluna_nem_linha_preta(tmp_path, origem):
    import subprocess
    from videomanager.infrastructure.ffmpeg.preview import filmstrip_frames
    from videomanager.infrastructure.system import binaries
    from videomanager.presentation.qt.panels.edit_panel import _FRAME_H, _FRAME_W
    tools = binaries.find_tools()
    if tools is None:
        pytest.skip("ffmpeg não disponível")
    arquivo = tmp_path / "v.mp4"
    subprocess.run([tools.ffmpeg_str, "-v", "error", "-f", "lavfi", "-i", f"color=lime:s={origem[0]}x{origem[1]}:r=30:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(arquivo)], check=True)
    quadro = next(iter(filmstrip_frames(arquivo, 0.0, 2.0, 1, (_FRAME_W, _FRAME_H), tools)))[1]
    assert (quadro.width, quadro.height) == (_FRAME_W, _FRAME_H)

    def preto(x: int, y: int) -> bool:
        i = (y * quadro.width + x) * 3
        return quadro.data[i + 1] < 100  # o verde da mídia sumiu: é fundo

    assert not any(preto(x, y) for x in (0, quadro.width - 1) for y in range(quadro.height))
    assert not any(preto(x, y) for y in (0, quadro.height - 1) for x in range(quadro.width))
