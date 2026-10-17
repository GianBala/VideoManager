"""A fila como lista de cartões: o que cada tarefa mostra, onde ficam os botões e quanto custa atualizar.

A tabela de cinco colunas deu lugar a cartões pintados (``queue_cards``). O que a suíte antiga não via é o
que um desenho novo perde em silêncio: o erro cortado na própria tarefa, um botão que não responde ao clique,
o cartão que muda de altura a cada quadro de progresso. Os testes abaixo medem a geometria e o resultado de
cada ação, e contam as medidas refeitas — o que fez a lista custar doze vezes a tabela antes de a altura ser guardada.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QItemSelectionModel, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyleOptionViewItem

from videomanager.application.events import Progress
from videomanager.application.jobs.models import Job, JobKind, JobStatus
from videomanager.domain import i18n
from videomanager.presentation.qt import strings, theme
from videomanager.presentation.qt.i18n import apply_language
from videomanager.presentation.qt.panels import queue_cards, queue_panel
from videomanager.presentation.qt.panels.queue_cards import medir, quebrar
from videomanager.presentation.qt.theme import apply as aplicar_tema


class _Fila(QObject):
    """A fila que o painel enxerga: sinais, a lista de tarefas e o registro do que foi pedido."""

    job_added = Signal(object)
    job_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.jobs: list[Job] = []
        self.pedidos: list[tuple[str, int | None]] = []

    def cancel(self, job_id): self.pedidos.append(("cancelar", job_id))
    def retry(self, job_id): self.pedidos.append(("repetir", job_id))
    def cancel_all(self): self.pedidos.append(("cancelar todos", None))
    def remove_finished(self): self.jobs[:] = [j for j in self.jobs if not j.status.is_final]


@pytest.fixture
def fila(desktop_app):
    antes = (desktop_app.palette(), desktop_app.styleSheet(), theme.atual())
    yield _Fila()
    desktop_app.setPalette(antes[0])
    desktop_app.setStyleSheet(antes[1])
    theme._atual = antes[2]


@pytest.fixture
def painel(fila, desktop_app):
    instancia = queue_panel.QueuePanel(fila, runtime=None)
    instancia.resize(560, 700)
    instancia.show()
    for _ in range(3):
        desktop_app.processEvents()
    yield instancia
    instancia.close()
    instancia.deleteLater()


def _adicionar(fila, desktop_app, *tarefas: Job) -> None:
    for tarefa in tarefas:
        fila.jobs.append(tarefa)
        fila.job_added.emit(tarefa)
    for _ in range(5):
        desktop_app.processEvents()


def _tarefa(titulo: str, status: JobStatus, **campos) -> Job:
    return Job("", titulo, campos.pop("description", "MP4 1080p"), kind=campos.pop("kind", JobKind.DOWNLOAD),
               status=status, **campos)


def _estados(tmp_path: Path) -> dict[str, Job]:
    pronto = tmp_path / "pronto.mp3"
    pronto.write_bytes(b"x")
    return {
        "baixando": _tarefa("Curta-metragem", JobStatus.RUNNING,
                            progress=Progress(phase="Baixando", percent=63, speed=8e6, eta=41)),
        "processando": _tarefa("aurora.mp4", JobStatus.PROCESSING, progress=Progress(phase="Processando", percent=82)),
        "na fila": _tarefa("Playlist", JobStatus.PENDING),
        "concluida": _tarefa("Podcast", JobStatus.DONE, result_path=pronto, result_size=24_100_000),
        "falhou": _tarefa("Vídeo privado", JobStatus.FAILED, error="HTTP 403: Forbidden", log=("[download] 403",)),
        "cancelada": _tarefa("Playlist 4", JobStatus.CANCELLED),
    }


def _fonte() -> QFont:
    return QFont()


# -- texto --------------------------------------------------------------------------------------------------

def test_quebrar_respeita_a_largura_e_poe_reticencias_na_ultima_linha(desktop_app):
    metricas = QFontMetrics(_fonte())
    texto = "um texto bem comprido que não cabe em duas linhas curtas de jeito nenhum mesmo"
    linhas = quebrar(metricas, texto, 120, 2)
    assert len(linhas) == 2
    assert all(metricas.horizontalAdvance(linha) <= 120 for linha in linhas)
    assert linhas[-1].endswith("…")
    assert quebrar(metricas, "curto", 120, 2) == ["curto"]
    # Uma palavra só, mais larga que a linha, também é cortada: não há onde quebrá-la.
    sozinha = quebrar(metricas, "arquivo_sem_espaco_nenhum_com_nome_enorme.mkv", 80, 2)
    assert len(sozinha) == 1 and metricas.horizontalAdvance(sozinha[0]) <= 80 and sozinha[0].endswith("…")


def test_a_situacao_junta_o_que_a_tarefa_tem_a_dizer(desktop_app, tmp_path):
    estados = _estados(tmp_path)
    assert queue_cards.situacao(estados["baixando"]) == "Baixando · MP4 1080p"
    fragmentada = _tarefa("x", JobStatus.RUNNING, progress=Progress(phase="Baixando", fragment_index=2, fragment_count=3))
    assert queue_cards.situacao(fragmentada) == "Baixando · MP4 1080p · parte 2/3"
    assert queue_cards.situacao(estados["na fila"]) == "Na fila · MP4 1080p"
    assert queue_cards.situacao(estados["concluida"]).startswith("Concluído · MP4 1080p · 23")
    assert queue_cards.situacao(estados["falhou"]) == "Falhou · MP4 1080p"
    assert queue_cards.situacao(estados["cancelada"]) == "Cancelado · MP4 1080p"
    # Sem descrição (o traço do catálogo), não sobra um " · —" no fim.
    assert queue_cards.situacao(_tarefa("x", JobStatus.PENDING, description="—")) == "Na fila"


# -- geometria ----------------------------------------------------------------------------------------------

def test_cada_situacao_mostra_as_partes_que_tem(desktop_app, tmp_path):
    e = _estados(tmp_path)
    cartoes = {nome: medir(job, 520, _fonte()) for nome, job in e.items()}
    # Andamento: barra e rodapé, e o botão de cancelar.
    for nome in ("baixando", "processando"):
        assert cartoes[nome].barra is not None and cartoes[nome].rodape is not None
        assert cartoes[nome].acao_nome == "cancelar" and cartoes[nome].erro is None
    # Na fila: cancelar, sem barra (a animação sugeriria trabalho em curso).
    assert cartoes["na fila"].acao_nome == "cancelar" and cartoes["na fila"].barra is None
    # Concluída com arquivo: abrir a pasta. Sem barra e sem repetir.
    assert cartoes["concluida"].acao_nome == "pasta" and cartoes["concluida"].repetir is None
    # Falhou: o erro na própria tarefa, repetir e detalhes (há log); nada de cancelar.
    falhou = cartoes["falhou"]
    assert falhou.erro is not None and falhou.repetir is not None and falhou.detalhes is not None
    assert falhou.acao is None
    # Cancelada: repetir, sem erro e sem detalhes.
    assert cartoes["cancelada"].repetir is not None
    assert cartoes["cancelada"].erro is None and cartoes["cancelada"].detalhes is None
    # Sem log não há o que detalhar.
    sem_log = medir(_tarefa("x", JobStatus.FAILED, error="e"), 520, _fonte())
    assert sem_log.repetir is not None and sem_log.detalhes is None


def test_nada_vaza_do_cartao_nem_se_sobrepoe(desktop_app, tmp_path):
    for largura in (320, 520, 1100):
        for nome, job in _estados(tmp_path).items():
            job.title = "Um título muito comprido para obrigar a quebra de linha " * 3
            cartao = medir(job, largura, _fonte())
            area = cartao.tile.united(cartao.titulo_em).united(cartao.situacao_em)
            for parte in (cartao.acao, cartao.barra, cartao.rodape, cartao.erro, cartao.repetir, cartao.detalhes):
                if parte is not None:
                    area = area.united(parte)
                    assert 0 <= parte.left() and parte.right() < largura, (nome, largura, parte)
                    assert parte.bottom() < cartao.altura, (nome, largura, parte)
            assert area.bottom() < cartao.altura and area.right() < largura, (nome, largura)
            # O texto não passa por baixo do botão de cancelar/pasta.
            if cartao.acao is not None:
                assert cartao.titulo_em.right() < cartao.acao.left(), (nome, largura)
            if cartao.repetir is not None and cartao.detalhes is not None:
                assert cartao.repetir.right() < cartao.detalhes.left()


def test_o_texto_com_caractere_de_fonte_de_reserva_cabe_no_espaco_reservado_e_nao_cobre_o_de_baixo(desktop_app, tmp_path):
    """Título japonês (「」 e kanji) sobrepunha a linha de situação: o texto é pintado de uma vez, e uma linha com caractere que
    a fonte do cartão não tem usa uma fonte de reserva mais alta (46 px em duas linhas, contra 32 da conta de ``lineSpacing``).
    O teste acima mede a geometria pela mesma conta que o cartão usa e não vê isso; aqui se compara com a altura real."""
    titulo = "「Creditless」Blue Box OP / Opening「UHD 60FPS」 【東方】ライブ映像 第二部「完全版」"
    fonte_titulo, fonte = queue_cards.fontes(_fonte())

    def real(f: QFont, linhas: list[str]) -> int:
        caixa = QRect(0, 0, 100_000, 100_000)
        return QFontMetrics(f).boundingRect(caixa, queue_cards._FLAGS_DO_TEXTO, "\n".join(linhas)).height()

    for largura in (320, 520):
        for nome, job in _estados(tmp_path).items():
            job.title, job.description = titulo, "1080p60 · H.264 · 「AAC」"
            if job.error:
                job.error = "「失敗」 HTTP 403: Forbidden (vídeo privado ou com restrição de região) " * 2
            cartao = medir(job, largura, _fonte())
            assert real(fonte_titulo, cartao.titulo) <= cartao.titulo_em.height(), (nome, largura)
            assert real(fonte, cartao.situacao) <= cartao.situacao_em.height(), (nome, largura)
            assert cartao.situacao_em.top() >= cartao.titulo_em.bottom(), (nome, largura)
            if cartao.erro is not None:
                assert real(fonte, cartao.erro_linhas) + 2 * queue_cards._ERRO_PAD <= cartao.erro.height(), (nome, largura)
    # O texto latino não muda de altura: o piso é a conta de antes.
    latino = QFontMetrics(fonte_titulo)
    assert queue_cards.altura_do_texto(latino, ["Episódio comum", "sem caracteres"]) == 2 * latino.lineSpacing()


def test_um_cartao_com_barra_ou_erro_e_mais_alto_que_um_simples(desktop_app, tmp_path):
    e = _estados(tmp_path)
    altura = {nome: medir(job, 520, _fonte()).altura for nome, job in e.items()}
    assert altura["baixando"] > altura["na fila"] and altura["falhou"] > altura["cancelada"] > altura["na fila"]
    assert altura["na fila"] == altura["concluida"]


# -- pintura ------------------------------------------------------------------------------------------------

def _pintado(painel, desktop_app, linha: int):
    """O cartão da linha ``linha`` como a lista o pinta, e onde ele está na lista."""
    for _ in range(3):
        desktop_app.processEvents()
    lista = painel._list
    retangulo = lista.visualRect(lista.model().index(linha, 0))
    return lista.viewport().grab(retangulo).toImage(), retangulo


def test_a_barra_de_progresso_preenche_a_fracao_do_percentual(painel, fila, desktop_app):
    tarefa = _tarefa("a", JobStatus.RUNNING, progress=Progress(phase="Baixando", percent=50))
    _adicionar(fila, desktop_app, tarefa)
    cartao = medir(tarefa, painel._list.delegate.largura(), painel._list.font())
    imagem, _ = _pintado(painel, desktop_app, 0)
    faixa_y = cartao.barra.center().y()
    trilho = QColor(theme.papeis(*theme.atual())["raised2"])
    antes = imagem.pixelColor(cartao.barra.left() + cartao.barra.width() // 4, faixa_y)
    depois = imagem.pixelColor(cartao.barra.left() + 3 * cartao.barra.width() // 4, faixa_y)
    assert antes != trilho and depois == trilho
    tarefa.progress = Progress(phase="Baixando", percent=100)
    fila.job_changed.emit(tarefa)
    imagem, _ = _pintado(painel, desktop_app, 0)
    assert imagem.pixelColor(cartao.barra.left() + 3 * cartao.barra.width() // 4, faixa_y) != trilho


def test_selecao_desenha_a_borda_de_destaque(painel, fila, desktop_app):
    _adicionar(fila, desktop_app, _tarefa("a", JobStatus.PENDING), _tarefa("b", JobStatus.PENDING))
    painel._list.selectionModel().select(painel._list.model().index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    primeira, _ = _pintado(painel, desktop_app, 0)
    segunda, _ = _pintado(painel, desktop_app, 1)
    destaque = QColor(theme.papeis(*theme.atual())["accent"])
    meio = primeira.height() // 2
    assert primeira.pixelColor(0, meio).name() == destaque.name() or primeira.pixelColor(1, meio).name() == destaque.name()
    assert segunda.pixelColor(0, meio).name() != destaque.name() and segunda.pixelColor(1, meio).name() != destaque.name()


def test_fila_vazia_desenha_a_mensagem_e_com_tarefa_ela_some(painel, fila, desktop_app):
    cores = theme.papeis(*theme.atual())
    area = painel._list.viewport()
    vazio = area.grab().toImage()
    azulejo = QColor(cores["raised"])
    assert any(QColor(vazio.pixel(x, y)) == azulejo
               for x in range(vazio.width() // 2 - 30, vazio.width() // 2 + 30, 4)
               for y in range(vazio.height() // 2 - 60, vazio.height() // 2, 4))
    _adicionar(fila, desktop_app, _tarefa("a", JobStatus.PENDING))
    cheio = area.grab().toImage()
    # Com tarefa, o ladrilho da mensagem não é desenhado (o cartão tem o dele, bem mais acima e à esquerda).
    centro = QPoint(cheio.width() // 2, cheio.height() // 2 + 40)
    assert QColor(cheio.pixel(centro)) != azulejo


# -- cliques ------------------------------------------------------------------------------------------------

def _clicar(painel, desktop_app, linha: int, regiao: str, duplo: bool = False) -> None:
    lista = painel._list
    for _ in range(3):
        desktop_app.processEvents()
    indice = lista.model().index(linha, 0)
    job = indice.data(Qt.ItemDataRole.UserRole)
    cartao = medir(job, lista.delegate.largura(), lista.font())
    alvo = {"cancelar": cartao.acao, "pasta": cartao.acao, "repetir": cartao.repetir, "detalhes": cartao.detalhes}[regiao]
    ponto = lista.visualRect(indice).topLeft() + alvo.center()
    if duplo:
        QTest.mouseDClick(lista.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    else:
        QTest.mouseClick(lista.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    desktop_app.processEvents()


def test_cada_botao_do_cartao_faz_o_que_o_menu_de_contexto_faz(painel, fila, desktop_app, tmp_path, monkeypatch):
    e = _estados(tmp_path)
    abertos: list = []
    monkeypatch.setattr(painel, "_show_log", lambda job: abertos.append(("detalhes", job)))
    monkeypatch.setattr(painel, "_reveal", lambda caminho: abertos.append(("pasta", caminho)))
    ordem = ["baixando", "concluida", "falhou", "cancelada"]
    _adicionar(fila, desktop_app, *(e[nome] for nome in ordem))
    _clicar(painel, desktop_app, 0, "cancelar")
    _clicar(painel, desktop_app, 1, "pasta")
    _clicar(painel, desktop_app, 2, "repetir")
    _clicar(painel, desktop_app, 2, "detalhes")
    _clicar(painel, desktop_app, 3, "repetir")
    assert fila.pedidos == [("cancelar", e["baixando"].job_id), ("repetir", e["falhou"].job_id),
                            ("repetir", e["cancelada"].job_id)]
    assert abertos == [("pasta", e["concluida"].result_path), ("detalhes", e["falhou"])]


def test_clique_duplo_num_botao_nao_abre_o_arquivo(painel, fila, desktop_app, tmp_path, monkeypatch):
    abertos: list = []
    monkeypatch.setattr(painel, "_open_path", lambda caminho: abertos.append(caminho))
    monkeypatch.setattr(painel, "_reveal", lambda caminho: None)
    _adicionar(fila, desktop_app, _estados(tmp_path)["concluida"])
    _clicar(painel, desktop_app, 0, "pasta", duplo=True)
    assert abertos == []
    # Fora dos botões, o clique duplo continua abrindo o arquivo, como a tabela abria.
    indice = painel._list.model().index(0, 0)
    ponto = painel._list.visualRect(indice).topLeft() + QPoint(200, 30)
    QTest.mouseClick(painel._list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    QTest.mouseDClick(painel._list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    assert len(abertos) == 1


def test_o_cursor_vira_mao_so_sobre_os_botoes(painel, fila, desktop_app, tmp_path):
    _adicionar(fila, desktop_app, _estados(tmp_path)["falhou"])
    lista = painel._list
    indice = lista.model().index(0, 0)
    cartao = medir(indice.data(Qt.ItemDataRole.UserRole), lista.delegate.largura(), lista.font())
    origem = lista.visualRect(indice).topLeft()
    # ``QTest.mouseMove`` de widget não gera movimento sem botão (CLAUDE.md): o evento é entregue direto à lista.
    for ponto, esperado in ((cartao.repetir.center(), Qt.CursorShape.PointingHandCursor),
                            (cartao.erro.center(), Qt.CursorShape.ArrowCursor)):
        _mover(lista, origem + ponto)
        assert lista.viewport().cursor().shape() == esperado


def _mover(lista, ponto):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    evento = QMouseEvent(QEvent.Type.MouseMove, QPointF(ponto), QPointF(lista.viewport().mapToGlobal(ponto)),
                         Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    lista.mouseMoveEvent(evento)


def test_a_dica_do_erro_traz_o_texto_inteiro(painel, fila, desktop_app):
    longo = "HTTP 403: Forbidden " + "motivo muito longo " * 40
    tarefa = _tarefa("a", JobStatus.FAILED, error=longo)
    _adicionar(fila, desktop_app, tarefa)
    cartao = medir(tarefa, painel._list.delegate.largura(), painel._list.font())
    assert cartao.erro_linhas[-1].endswith("…") and len(cartao.erro_linhas) == 4
    assert cartao.regiao_em(cartao.erro.center()) == "erro"


def test_a_dica_do_cartao_traz_os_avisos_da_tarefa(painel, fila, desktop_app):
    """Os avisos moravam na dica da coluna "destino", que o cartão (uma coluna só) nunca mostra."""
    from videomanager.domain.i18n import Text

    tarefa = _tarefa("a", JobStatus.DONE)
    tarefa.warnings = (Text("RECODE_FALLBACK", error="sem encoder"),)
    sem_aviso = _tarefa("b", JobStatus.DONE)
    _adicionar(fila, desktop_app, tarefa, sem_aviso)
    modelo = painel._list.model()
    dica = modelo.data(modelo.index(0, 0), Qt.ItemDataRole.ToolTipRole)
    assert tarefa.url in dica and str(tarefa.warnings[0]) in dica
    assert modelo.data(modelo.index(1, 0), Qt.ItemDataRole.ToolTipRole) == sem_aviso.url


# -- botões de baixo -----------------------------------------------------------------------------------------

def test_cancelar_todos_e_limpar_so_ficam_a_mao_quando_ha_o_que_fazer(painel, fila, desktop_app, tmp_path):
    assert not painel._cancel_all.isEnabled() and not painel._clear.isEnabled()
    e = _estados(tmp_path)
    _adicionar(fila, desktop_app, e["baixando"])
    assert painel._cancel_all.isEnabled() and not painel._clear.isEnabled()
    _adicionar(fila, desktop_app, e["concluida"])
    assert painel._clear.isEnabled()
    e["baixando"].status = JobStatus.DONE
    fila.job_changed.emit(e["baixando"])
    assert not painel._cancel_all.isEnabled()
    painel._clear.click()
    assert not painel._clear.isEnabled() and painel._list.model().rowCount() == 0


# -- idioma e tema -------------------------------------------------------------------------------------------

def test_a_troca_de_idioma_retraduz_os_cartoes(painel, fila, desktop_app, tmp_path):
    _adicionar(fila, desktop_app, *_estados(tmp_path).values())
    pt = {linha: painel._list.visualRect(painel._list.model().index(linha, 0)).height() for linha in range(6)}
    apply_language(i18n.ENGLISH)
    for _ in range(5):
        desktop_app.processEvents()
    falhou = painel._list.model().index(4, 0).data(Qt.ItemDataRole.UserRole)
    assert queue_cards.situacao(falhou) == "Failed · MP4 1080p"
    # Mesma lista, medidas refeitas: o texto em inglês pode ocupar outra altura, mas a lista tem de concordar
    # com o que o delegate diria agora, e não com o que ele guardou em português.
    delegado = painel._list.delegate
    for linha in range(6):
        job = painel._list.model().index(linha, 0).data(Qt.ItemDataRole.UserRole)
        assert painel._list.visualRect(painel._list.model().index(linha, 0)).height() == \
            medir(job, delegado.largura(), painel._list.font()).altura + queue_cards.ENTRE_CARTOES
    assert set(pt) == set(range(6))


def test_a_troca_de_paleta_repinta_os_cartoes(painel, fila, desktop_app):
    _adicionar(fila, desktop_app, _tarefa("a", JobStatus.DONE))
    cartao = lambda: painel._list.viewport().grab(painel._list.visualRect(painel._list.model().index(0, 0))).toImage()
    antes = cartao().pixelColor(100, 6).name()
    aplicar_tema(desktop_app, "light", "mare")
    for _ in range(3):
        desktop_app.processEvents()
    depois = cartao().pixelColor(100, 6).name()
    assert antes != depois
    assert depois == theme.papeis("light", "mare")["card"].lower()


# -- custo ---------------------------------------------------------------------------------------------------

def test_atualizar_o_progresso_nao_refaz_a_medida_de_200_tarefas(painel, fila, desktop_app, monkeypatch):
    # O caso que custou doze vezes a tabela: a lista refaz o layout a cada aviso do modelo, e cada layout
    # perguntava a altura de todas as tarefas. A altura só muda com situação, texto e erro — não com percentual.
    tarefas = [_tarefa(f"tarefa {i}", JobStatus.RUNNING, progress=Progress(phase="Baixando", percent=i % 100))
               for i in range(200)]
    _adicionar(fila, desktop_app, *tarefas)
    medidas: list[int] = []
    original = queue_cards.medir
    monkeypatch.setattr(queue_cards, "medir", lambda *a, **k: medidas.append(1) or original(*a, **k))
    for rodada in range(5):
        for tarefa in tarefas[:4]:
            tarefa.progress = Progress(phase="Baixando", percent=(rodada * 7) % 100, speed=1e6, eta=10 + rodada)
            fila.job_changed.emit(tarefa)
        for _ in range(3):
            desktop_app.processEvents()
    # Só as linhas à vista se repintam (e medem para pintar): uma dúzia, nunca as 200.
    assert len(medidas) < 5 * 30, len(medidas)
    # E mudar o que tem efeito na altura continua refazendo o layout: o erro novo abre a caixa dele.
    altura_antes = painel._list.visualRect(painel._list.model().index(0, 0)).height()
    tarefas[0].status, tarefas[0].error = JobStatus.FAILED, "falhou"
    fila.job_changed.emit(tarefas[0])
    for _ in range(3):
        desktop_app.processEvents()
    assert painel._list.visualRect(painel._list.model().index(0, 0)).height() != altura_antes


def test_a_largura_do_delegate_acompanha_a_da_lista_com_e_sem_barra_de_rolagem(painel, fila, desktop_app):
    lista = painel._list
    assert lista.delegate.largura() == lista.viewport().width()
    _adicionar(fila, desktop_app, *(_tarefa(f"t{i}", JobStatus.PENDING) for i in range(40)))
    assert lista.verticalScrollBar().isVisible()
    assert lista.delegate.largura() == lista.viewport().width()
    assert lista.visualRect(lista.model().index(0, 0)).width() == lista.viewport().width()
    painel.resize(900, 700)
    for _ in range(3):
        desktop_app.processEvents()
    assert lista.delegate.largura() == lista.viewport().width() == lista.visualRect(lista.model().index(0, 0)).width()


def test_o_piso_da_lista_cabe_dois_cartoes_simples(painel):
    lista = painel._list
    simples = lista.delegate.altura_minima(lista.font())
    assert lista.minimumHeight() >= 2 * simples
    assert strings.QUEUE_EMPTY


def test_a_altura_pedida_nao_depende_da_largura_que_o_qt_entrega(painel, fila, desktop_app):
    # O Qt entrega ``option.rect`` ora zerado, ora com a largura de antes de a barra de rolagem aparecer;
    # medir por ele guardava alturas de duas larguras e refazia o layout a cada aviso de progresso.
    _adicionar(fila, desktop_app, _tarefa("Um título bem comprido " * 6, JobStatus.RUNNING,
                                          progress=Progress(phase="Baixando", percent=1)))
    delegado, indice = painel._list.delegate, painel._list.model().index(0, 0)
    opcao = QStyleOptionViewItem()
    opcao.font = painel._list.font()
    tamanhos = set()
    for largura in (0, 37, 1038, delegado.largura()):
        opcao.rect = QRect(0, 0, largura, 0)
        tamanhos.add((delegado.sizeHint(opcao, indice).width(), delegado.sizeHint(opcao, indice).height()))
    assert len(tamanhos) == 1


def _sobre(cor: str, fundo: str, alfa: int) -> QColor:
    a, b = QColor(cor), QColor(fundo)
    mistura = lambda x, y: round(y + (x - y) * alfa / 255)
    return QColor(mistura(a.red(), b.red()), mistura(a.green(), b.green()), mistura(a.blue(), b.blue()))


@pytest.mark.parametrize("modo,nome", [("dark", "atual"), ("light", "atual"), ("dark", "estudio"), ("light", "mare")])
def test_cada_situacao_tem_o_ladrilho_do_seu_papel_de_cor(painel, fila, desktop_app, tmp_path, modo, nome):
    aplicar_tema(desktop_app, modo, nome)
    cores = theme.papeis(modo, nome)
    esperado = {"baixando": _sobre(cores["accent"], cores["card"], 38),
                "concluida": _sobre(cores["ok"], cores["card"], 38),
                "falhou": _sobre(cores["err"], cores["card"], 38),
                "na fila": QColor(cores["raised2"]), "cancelada": QColor(cores["raised2"])}
    estados = _estados(tmp_path)
    ordem = list(esperado)
    _adicionar(fila, desktop_app, *(estados[n] for n in ordem))
    for linha, estado in enumerate(ordem):
        imagem, _ = _pintado(painel, desktop_app, linha)
        # Três pixels para dentro da borda esquerda do ladrilho, longe do ícone e do canto arredondado.
        meio = queue_cards._PAD + queue_cards._TILE // 2
        obtido = imagem.pixelColor(queue_cards._PAD + 3, meio)
        alvo = esperado[estado]
        if estado == "na fila":
            # A tarefa que espera é pintada a 72% (o protótipo a esmaece): o ladrilho é o papel a 72% sobre o corpo do
            # cartão, que por sua vez já está a 72% sobre a lista.
            alvo = _sobre(cores["raised2"], imagem.pixelColor(queue_cards._PAD // 2, meio).name(), 184)
        assert max(abs(obtido.red() - alvo.red()), abs(obtido.green() - alvo.green()),
                   abs(obtido.blue() - alvo.blue())) <= 2, (estado, obtido.name(), alvo.name())


# -- fidelidade ao protótipo: cabeçalho, plano do cartão, espaçamento e botões do pé ----------------------------------

def _centro_y(painel, widget) -> int:
    return widget.mapTo(painel, widget.rect().center()).y()


def test_os_selos_ficam_na_linha_do_titulo_quando_cabem_e_descem_quando_nao(painel, fila, desktop_app):
    aplicar_tema(desktop_app, "dark", "grafite")
    _adicionar(fila, desktop_app, _tarefa("a", JobStatus.RUNNING, progress=Progress(phase="Baixando", percent=10)),
               _tarefa("b", JobStatus.PENDING))
    # Dois selos (ativas e na fila) cabem ao lado do título.
    assert abs(_centro_y(painel, painel._chip_row) - _centro_y(painel, painel._title)) <= 6
    # Com os quatro à vista não cabem nos 344 px: a linha desce.
    _adicionar(fila, desktop_app, _tarefa("c", JobStatus.FAILED, error="x"), _tarefa("d", JobStatus.CANCELLED))
    assert _centro_y(painel, painel._chip_row) > _centro_y(painel, painel._title) + 12
    # E sobem de novo quando os encerrados saem.
    fila.remove_finished()
    painel._sync_state()
    for _ in range(3):
        desktop_app.processEvents()
    assert abs(_centro_y(painel, painel._chip_row) - _centro_y(painel, painel._title)) <= 6


def test_o_selo_tem_22_px_e_nao_estica_com_o_cabecalho(painel, fila, desktop_app):
    aplicar_tema(desktop_app, "dark", "grafite")
    _adicionar(fila, desktop_app, _tarefa("a", JobStatus.RUNNING, progress=Progress(phase="Baixando", percent=10)))
    visiveis = [chip for chip in painel._chips.values() if chip.isVisible()]
    assert visiveis and {chip.height() for chip in visiveis} == {22}


def test_o_cartao_e_do_plano_do_cartao_e_a_distancia_entre_cartoes_e_12(painel, fila, desktop_app):
    aplicar_tema(desktop_app, "dark", "grafite")
    cores = theme.papeis("dark", "grafite")
    a, b = _tarefa("a", JobStatus.DONE), _tarefa("b", JobStatus.DONE)
    _adicionar(fila, desktop_app, a, b)
    imagem, retangulo = _pintado(painel, desktop_app, 0)
    assert imagem.pixelColor(queue_cards._PAD // 2, queue_cards._PAD + queue_cards._TILE // 2).name().lower() == cores["card"].lower()
    seguinte = painel._list.visualRect(painel._list.model().index(1, 0))
    altura = medir(a, painel._list.delegate.largura(), painel._list.font()).altura
    assert seguinte.top() - retangulo.top() == altura + 12 == altura + queue_cards.ENTRE_CARTOES


def test_o_cartao_que_espera_e_mais_discreto_e_selecionado_volta_a_cor_inteira(painel, fila, desktop_app):
    aplicar_tema(desktop_app, "dark", "grafite")
    _adicionar(fila, desktop_app, _tarefa("a", JobStatus.PENDING), _tarefa("b", JobStatus.RUNNING, progress=Progress(phase="Baixando", percent=5)))
    espera, _ = _pintado(painel, desktop_app, 0)
    ativo, _ = _pintado(painel, desktop_app, 1)
    titulo_y = queue_cards._PAD + 8
    brilho = lambda imagem: max(imagem.pixelColor(x, titulo_y).lightness() for x in range(queue_cards._PAD + queue_cards._TILE + 14, 140))
    assert brilho(espera) < brilho(ativo)
    painel._list.selectionModel().select(painel._list.model().index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    selecionada, _ = _pintado(painel, desktop_app, 0)
    assert brilho(selecionada) >= brilho(ativo) - 2


def test_os_botoes_do_pe_tem_36_px_e_o_de_limpar_nao_tem_fundo(painel, fila, desktop_app):
    aplicar_tema(desktop_app, "dark", "grafite")
    cores = theme.papeis("dark", "grafite")
    _adicionar(fila, desktop_app, _tarefa("a", JobStatus.RUNNING, progress=Progress(phase="Baixando", percent=10)),
               _tarefa("b", JobStatus.DONE))
    assert painel._cancel_all.height() == painel._clear.height() == 36
    quadro = painel.grab().toImage()
    ponto = lambda botao: botao.mapTo(painel, QPoint(botao.width() // 2, 3))
    cor = lambda botao: quadro.pixelColor(ponto(botao)).name().lower()
    assert cor(painel._cancel_all) == cores["raised"].lower()
    assert cor(painel._clear) == cores["panel"].lower()
