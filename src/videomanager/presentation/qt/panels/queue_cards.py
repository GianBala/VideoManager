"""Cartão de tarefa da fila: a medida e a pintura de uma tarefa como cartão.

A fila deixou de ser uma tabela de cinco colunas — onde o erro saía cortado com "…" na coluna Situação,
e o progresso, a velocidade e o tempo restante dividiam espaço com o título — e virou uma lista de
cartões: o que cada tarefa tem a dizer ocupa a largura inteira, e o erro aparece **na própria tarefa**,
com a saída (Tentar de novo) ao lado.

O cartão é pintado, e não composto de widgets, pelo mesmo motivo de antes: o progresso chega várias vezes
por segundo por tarefa, e um ``QProgressBar`` por linha custaria muito mais que uma barra desenhada.
Medida e pintura saem da mesma conta (:func:`medir`), e é a mesma conta que decide para onde o clique vai
(:meth:`TaskDelegate.regiao_em`): três contas diferentes acabariam discordando sobre onde o botão está.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from videomanager.application.formatting import DASH, format_eta, format_size, format_speed
from videomanager.application.jobs.models import Job, JobKind, JobStatus
from videomanager.domain import i18n
from videomanager.presentation.qt import icons, strings, theme

_PAD = 14
_TILE = 40
_GAP = 12
_ACAO = 28
_BARRA = 6
_RAIO = 12
_ENTRE = 10
_BOTAO = 32
_ERRO_PAD = 10
_ICONE = 20
# Espaço entre um cartão e o seguinte. É a lista que reserva (altura da linha = cartão + isto) e o delegate
# que o respeita ao pintar: ``QListView.setSpacing`` mexe também na largura do item, e a largura é do que depende a quebra de texto.
ENTRE_CARTOES = 10

# Linhas que um título, uma situação e um erro ocupam antes de ganhar reticências: tarefa com texto
# longo não pode decidir sozinha a altura da lista.
_LINHAS_TITULO = 2
_LINHAS_SITUACAO = 2
_LINHAS_ERRO = 4

REGIOES_CLICAVEIS = ("cancelar", "pasta", "repetir", "detalhes")


@dataclass
class Cartao:
    """Onde cada parte da tarefa fica, em coordenadas do cartão (origem no canto dele)."""

    altura: int
    tile: QRect
    titulo: list[str]
    titulo_em: QRect
    situacao: list[str]
    situacao_em: QRect
    acao: QRect | None = None
    acao_nome: str = ""
    barra: QRect | None = None
    rodape: QRect | None = None
    erro: QRect | None = None
    erro_linhas: list[str] = field(default_factory=list)
    repetir: QRect | None = None
    detalhes: QRect | None = None

    def regiao_em(self, ponto: QPoint) -> str:
        if self.acao is not None and self.acao.contains(ponto):
            return self.acao_nome
        if self.repetir is not None and self.repetir.contains(ponto):
            return "repetir"
        if self.detalhes is not None and self.detalhes.contains(ponto):
            return "detalhes"
        if self.erro is not None and self.erro.contains(ponto):
            return "erro"
        return ""


def quebrar(metricas: QFontMetrics, texto: str, largura: int, max_linhas: int) -> list[str]:
    """Quebra em palavras; o que passa de ``max_linhas`` vira reticências na última linha.

    Uma palavra sozinha mais larga que a linha (um endereço, um nome de arquivo sem espaço) também é
    cortada com reticências: não há onde quebrá-la, e deixá-la vazar empurraria o botão de cancelar.
    """
    linhas: list[str] = []
    atual = ""
    for palavra in texto.split():
        tentativa = f"{atual} {palavra}" if atual else palavra
        if metricas.horizontalAdvance(tentativa) <= largura or not atual:
            atual = tentativa
        else:
            linhas.append(atual)
            atual = palavra
    linhas.append(atual)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas - 1] + [" ".join(linhas[max_linhas - 1:])]
    return [metricas.elidedText(linha, Qt.TextElideMode.ElideRight, largura) for linha in linhas]


def velocidade_e_tempo(job: Job) -> list[str]:
    """Os pedaços do lado direito do rodapé: velocidade e tempo restante, os que o extrator informou."""
    progresso = job.progress
    pedacos: list[str] = []
    if progresso is not None:
        if progresso.speed:
            pedacos.append(format_speed(progresso.speed))
        if progresso.eta:
            pedacos.append(strings.QUEUE_ETA.format(eta=format_eta(progresso.eta)))
    return pedacos


def situacao(job: Job) -> str:
    """A linha de baixo do título: situação, o que a tarefa produz e, se houver, parte i/n e tamanho."""
    if job.status.is_active and job.progress is not None:
        rotulo = str(job.progress.phase)
    else:
        rotulo = strings.JOB_STATUS_LABELS[job.status.value]
    partes = [rotulo]
    descricao = str(job.description)
    if descricao and descricao != DASH:
        partes.append(descricao)
    progresso = job.progress
    if job.status.is_active and progresso is not None and progresso.fragment_count:
        partes.append(strings.QUEUE_FRAGMENT.format(index=progresso.fragment_index or 0,
                                                    count=progresso.fragment_count))
    if job.status is JobStatus.DONE and job.result_size:
        partes.append(format_size(job.result_size))
    return " · ".join(partes)


def fontes(base: QFont) -> tuple[QFont, QFont]:
    """Título em negrito no tamanho do texto; o resto, um pouco menor."""
    titulo = QFont(base)
    titulo.setBold(True)
    normal = QFont(base)
    if base.pointSizeF() > 0:
        normal.setPointSizeF(base.pointSizeF() * 0.93)
    elif base.pixelSize() > 0:
        normal.setPixelSize(max(1, round(base.pixelSize() * 0.93)))
    return titulo, normal


def _largura_do_botao(metricas: QFontMetrics, texto: str, com_icone: bool) -> int:
    return 12 + (16 + 6 if com_icone else 0) + metricas.horizontalAdvance(texto) + 12


def medir(job: Job, largura: int, base: QFont) -> Cartao:
    """A geometria do cartão de ``job`` numa linha de ``largura`` px."""
    fonte_titulo, fonte = fontes(base)
    mt, mn = QFontMetrics(fonte_titulo), QFontMetrics(fonte)

    ativa = job.status.is_active
    if not job.status.is_final:
        acao_nome = "cancelar"
    elif job.status is JobStatus.DONE and job.result_path:
        acao_nome = "pasta"
    else:
        acao_nome = ""
    acao = QRect(largura - _PAD - _ACAO, _PAD + (_TILE - _ACAO) // 2, _ACAO, _ACAO) if acao_nome else None

    texto_x = _PAD + _TILE + _GAP
    texto_largura = (acao.left() - _GAP if acao else largura - _PAD) - texto_x
    titulo = quebrar(mt, job.title, texto_largura, _LINHAS_TITULO)
    linhas_situacao = quebrar(mn, situacao(job), texto_largura, _LINHAS_SITUACAO)
    altura_titulo = len(titulo) * mt.lineSpacing()
    altura_situacao = len(linhas_situacao) * mn.lineSpacing()
    bloco = altura_titulo + 2 + altura_situacao
    # O texto se centraliza no ladrilho quando cabe nele; quando passa, o ladrilho fica no topo.
    topo = _PAD + max(0, (_TILE - bloco) // 2)
    cartao = Cartao(
        altura=0,
        tile=QRect(_PAD, _PAD, _TILE, _TILE),
        titulo=titulo,
        titulo_em=QRect(texto_x, topo, texto_largura, altura_titulo),
        situacao=linhas_situacao,
        situacao_em=QRect(texto_x, topo + altura_titulo + 2, texto_largura, altura_situacao),
        acao=acao,
        acao_nome=acao_nome,
    )
    y = _PAD + max(_TILE, bloco)
    inteira = largura - 2 * _PAD

    if ativa:
        y += _ENTRE
        cartao.barra = QRect(_PAD, y, inteira, _BARRA)
        y += _BARRA + 6
        cartao.rodape = QRect(_PAD, y, inteira, mn.height())
        y += mn.height()

    if job.status is JobStatus.FAILED and job.error:
        y += _ENTRE
        interna = inteira - 2 * _ERRO_PAD
        cartao.erro_linhas = quebrar(mn, str(job.error), interna, _LINHAS_ERRO)
        cartao.erro = QRect(_PAD, y, inteira, len(cartao.erro_linhas) * mn.lineSpacing() + 2 * _ERRO_PAD)
        y += cartao.erro.height()

    if job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
        y += _ENTRE
        largura_repetir = _largura_do_botao(mt, strings.QUEUE_RETRY, True)
        cartao.repetir = QRect(_PAD, y, largura_repetir, _BOTAO)
        if job.status is JobStatus.FAILED and job.log:
            largura_detalhes = _largura_do_botao(mt, strings.QUEUE_DETAILS, False)
            cartao.detalhes = QRect(cartao.repetir.right() + 8, y, largura_detalhes, _BOTAO)
        y += _BOTAO

    cartao.altura = y + _PAD
    return cartao


class TaskDelegate(QStyledItemDelegate):
    """Pinta uma tarefa como cartão e entrega os cliques nos botões dele."""

    #: ``(tarefa, região)``: "cancelar", "pasta", "repetir" ou "detalhes".
    acionado = Signal(object, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._largura = 0
        self._cores: dict[str, str] = {}
        self._icones: dict[tuple[str, str, int], object] = {}
        self._hover: tuple[int, str] | None = None
        self._alturas: dict[int, tuple[tuple, int]] = {}
        self._refrescar_cores()
        theme.on_theme_change(self._retheme)

    # -- tema --------------------------------------------------------------

    def _refrescar_cores(self) -> None:
        self._cores = theme.papeis(*theme.atual())
        self._icones.clear()

    def _retheme(self) -> None:
        self._refrescar_cores()
        pai = self.parent()
        if pai is not None and hasattr(pai, "viewport"):
            pai.viewport().update()

    def _icone(self, desenho, cor: str, tamanho: int):
        chave = (desenho.__name__, cor, tamanho)
        if chave not in self._icones:
            self._icones[chave] = desenho(cor, tamanho)
        return self._icones[chave]

    # -- medida ------------------------------------------------------------

    def set_largura(self, largura: int) -> None:
        self._largura = largura

    def largura(self) -> int:
        return self._largura

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        job: Job | None = index.data(Qt.ItemDataRole.UserRole)
        # A largura é a da lista, e não a de ``option.rect``: o Qt a entrega ora zerada, ora a de antes de a
        # barra de rolagem aparecer, e a altura medida numa largura não vale na outra.
        largura = self._largura or 400
        if job is None:
            return QSize(largura, 0)
        return QSize(largura, self._altura(job, largura, option.font) + ENTRE_CARTOES)

    def _altura(self, job: Job, largura: int, base: QFont) -> int:
        """A altura do cartão, guardada enquanto nada que a muda mudar.

        O progresso chega várias vezes por segundo e cada aviso refaz a lista inteira, que pergunta a altura
        de todas as tarefas — 200 delas custavam 23 ms por aviso, doze vezes o que a tabela custava. A altura
        só depende de poucos campos (a assinatura), e o progresso não está entre eles.
        """
        progresso = job.progress
        assinatura = (
            largura, base.key(), i18n.language(), job.status, job.kind, job.title, str(job.description),
            str(progresso.phase) if progresso is not None and job.status.is_active else None,
            (progresso.fragment_index, progresso.fragment_count) if progresso is not None else None,
            job.result_size, str(job.error) if job.error else None, bool(job.log), bool(job.result_path),
        )
        guardado = self._alturas.get(job.job_id)
        if guardado is not None and guardado[0] == assinatura:
            return guardado[1]
        altura = medir(job, largura, base).altura
        self._alturas[job.job_id] = (assinatura, altura)
        return altura

    def mudou_a_altura(self, job: Job, largura: int, base: QFont) -> bool:
        """Se a tarefa agora pede outra altura que a da última medida (ou nunca foi medida)."""
        guardado = self._alturas.get(job.job_id)
        return guardado is None or guardado[1] != self._altura(job, largura, base)

    def altura_minima(self, base: QFont, largura: int = 400) -> int:
        """Altura de uma linha da lista com um cartão sem barra nem botões: o menor que ela mostra."""
        espera = Job("", "", "", status=JobStatus.PENDING)
        return medir(espera, largura, base).altura + ENTRE_CARTOES

    # -- hover e cliques ---------------------------------------------------

    def set_hover(self, job_id: int | None, nome: str = "") -> bool:
        novo = (job_id, nome) if job_id is not None and nome else None
        mudou = novo != self._hover
        self._hover = novo
        return mudou

    def regiao_em(self, job: Job, retangulo: QRect, ponto: QPoint) -> str:
        """A região do cartão sob ``ponto`` (coordenadas da lista), ou ``""``."""
        return medir(job, self._largura, self._fonte_base()).regiao_em(ponto - retangulo.topLeft())

    def _fonte_base(self) -> QFont:
        pai = self.parent()
        return pai.font() if pai is not None else QFont()

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            job: Job | None = index.data(Qt.ItemDataRole.UserRole)
            if job is not None:
                nome = self.regiao_em(job, option.rect, event.position().toPoint())
                if nome in REGIOES_CLICAVEIS:
                    self.acionado.emit(job, nome)
                    return True
        return False

    # -- pintura -----------------------------------------------------------

    def _visual(self, job: Job):
        """``(ícone, cor do ícone, fundo do ladrilho, cor da linha de situação)`` da situação da tarefa."""
        c = self._cores
        status = job.status
        if status is JobStatus.DONE:
            return icons.check, c["ok"], _com_alfa(c["ok"], 38), c["ok"]
        if status is JobStatus.FAILED:
            return icons.warn, c["err"], _com_alfa(c["err"], 38), c["err"]
        if status is JobStatus.CANCELLED:
            return icons.close, c["t2"], c["raised2"], c["t2"]
        if status is JobStatus.PENDING:
            return icons.clock, c["t3"], c["raised2"], c["t3"]
        if status is JobStatus.RUNNING and job.kind is JobKind.DOWNLOAD:
            desenho = icons.nav_download
        elif status is JobStatus.RUNNING and job.kind is JobKind.EXPORT:
            desenho = icons.upload
        else:
            desenho = icons.sync
        return desenho, c["accent"], _com_alfa(c["accent"], 38), c["t2"]

    def paint(self, painter: QPainter, option, index) -> None:
        job: Job | None = index.data(Qt.ItemDataRole.UserRole)
        if job is None:
            return
        c = self._cores
        retangulo = option.rect
        cartao = medir(job, self._largura or retangulo.width(), option.font)
        fonte_titulo, fonte = fontes(option.font)
        mt, mn = QFontMetrics(fonte_titulo), QFontMetrics(fonte)
        icone, cor_icone, fundo_tile, cor_situacao = self._visual(job)
        selecionado = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(retangulo.topLeft())
        corpo = QRectF(0.5, 0.5, self._largura - 1, cartao.altura - 1)
        painter.setPen(QPen(QColor(c["accent"]), 1.5) if selecionado else Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c["raised"]))
        painter.drawRoundedRect(corpo, _RAIO, _RAIO)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(fundo_tile))
        painter.drawRoundedRect(QRectF(cartao.tile), 10, 10)
        lado = _ICONE
        icone_em = QRect(cartao.tile.x() + (_TILE - lado) // 2, cartao.tile.y() + (_TILE - lado) // 2, lado, lado)
        self._icone(icone, cor_icone, lado).paint(painter, icone_em)

        painter.setFont(fonte_titulo)
        painter.setPen(QColor(c["text"]))
        _linhas(painter, mt, cartao.titulo, cartao.titulo_em)
        painter.setFont(fonte)
        painter.setPen(QColor(cor_situacao))
        _linhas(painter, mn, cartao.situacao, cartao.situacao_em)

        if cartao.acao is not None:
            self._pintar_acao(painter, job, cartao)
        if cartao.barra is not None:
            self._pintar_andamento(painter, job, cartao, mn, fonte_titulo)
        if cartao.erro is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c["canvas"]))
            painter.drawRoundedRect(QRectF(cartao.erro), 8, 8)
            painter.setFont(fonte)
            painter.setPen(QColor(c["t2"]))
            interna = cartao.erro.adjusted(_ERRO_PAD, _ERRO_PAD, -_ERRO_PAD, -_ERRO_PAD)
            _linhas(painter, mn, cartao.erro_linhas, interna)
        if cartao.repetir is not None:
            self._pintar_botoes(painter, job, cartao, fonte_titulo)
        painter.restore()

    def _quente(self, job: Job, nome: str) -> bool:
        return self._hover == (job.job_id, nome)

    def _pintar_acao(self, painter: QPainter, job: Job, cartao: Cartao) -> None:
        c = self._cores
        if self._quente(job, cartao.acao_nome):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(c["raised2"]))
            painter.drawRoundedRect(QRectF(cartao.acao), 8, 8)
        desenho = icons.close if cartao.acao_nome == "cancelar" else icons.folder
        lado = 16
        alvo = QRect(cartao.acao.x() + (_ACAO - lado) // 2, cartao.acao.y() + (_ACAO - lado) // 2, lado, lado)
        self._icone(desenho, c["text"] if self._quente(job, cartao.acao_nome) else c["t2"], lado).paint(painter, alvo)

    def _pintar_andamento(self, painter: QPainter, job: Job, cartao: Cartao, mn: QFontMetrics, fonte_forte: QFont) -> None:
        c = self._cores
        barra = cartao.barra
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c["raised2"]))
        painter.drawRoundedRect(QRectF(barra), _BARRA / 2, _BARRA / 2)
        percentual = job.percent
        if percentual is None:
            # Sem percentual honesto (HLS sem tamanho total, pós-processamento): a barra cheia e esmaecida
            # diz "trabalhando" sem prometer um ponto de chegada.
            fracao, texto = 1.0, "…"
            alfa = 90
        else:
            fracao, texto = max(0.0, min(1.0, percentual / 100)), f"{percentual:.0f}%"
            alfa = 255
        if fracao > 0:
            preenchida = QRectF(barra.x(), barra.y(), max(_BARRA, barra.width() * fracao), barra.height())
            degrade = QLinearGradient(preenchida.topLeft(), preenchida.topRight())
            degrade.setColorAt(0, _com_alfa_cor(c["fill_a"], alfa))
            degrade.setColorAt(1, _com_alfa_cor(c["fill_b"], alfa))
            painter.setBrush(degrade)
            painter.drawRoundedRect(preenchida, _BARRA / 2, _BARRA / 2)
        painter.setFont(fonte_forte)
        painter.setPen(QColor(c["text"]))
        rodape = cartao.rodape
        base = rodape.y() + mn.ascent()
        painter.drawText(QPoint(rodape.x(), base), texto)
        direita = " · ".join(velocidade_e_tempo(job))
        if direita:
            fonte = QFont(painter.font())
            fonte.setBold(False)
            painter.setFont(fonte)
            painter.setPen(QColor(c["t2"]))
            largura_texto = QFontMetrics(fonte).horizontalAdvance(direita)
            painter.drawText(QPoint(rodape.right() - largura_texto + 1, base), direita)

    def _pintar_botoes(self, painter: QPainter, job: Job, cartao: Cartao, fonte_titulo: QFont) -> None:
        c = self._cores
        mt = QFontMetrics(fonte_titulo)
        painter.setFont(fonte_titulo)
        repetir = cartao.repetir
        quente = self._quente(job, "repetir")
        painter.setPen(Qt.PenStyle.NoPen)
        if job.status is JobStatus.FAILED:
            degrade = QLinearGradient(repetir.topLeft(), repetir.topRight())
            degrade.setColorAt(0, QColor(c["fill_a"]))
            degrade.setColorAt(1, QColor(c["fill_b"]))
            painter.setBrush(degrade)
            cor_texto = c["on_fill"]
        else:
            painter.setBrush(QColor(c["raised2"]))
            cor_texto = c["text"]
        painter.drawRoundedRect(QRectF(repetir), 8, 8)
        if quente:
            # Um véu na cor do texto do botão: clareia o preenchido de fundo escuro e escurece o de fundo claro.
            painter.setBrush(_com_alfa_cor(cor_texto, 36))
            painter.drawRoundedRect(QRectF(repetir), 8, 8)
        lado = 16
        self._icone(icons.undo, cor_texto, lado).paint(
            painter, QRect(repetir.x() + 12, repetir.y() + (_BOTAO - lado) // 2, lado, lado))
        painter.setPen(QColor(cor_texto))
        painter.drawText(QPoint(repetir.x() + 12 + lado + 6, repetir.y() + (_BOTAO + mt.ascent() - mt.descent()) // 2),
                         strings.QUEUE_RETRY)
        if cartao.detalhes is not None:
            detalhes = cartao.detalhes
            painter.setPen(QColor(c["text"] if self._quente(job, "detalhes") else c["t2"]))
            painter.drawText(QPoint(detalhes.x() + 8, detalhes.y() + (_BOTAO + mt.ascent() - mt.descent()) // 2),
                             strings.QUEUE_DETAILS)


def _linhas(painter: QPainter, metricas: QFontMetrics, linhas: list[str], area: QRect) -> None:
    """Desenha as linhas já quebradas como um texto só, e não uma chamada por linha.

    O texto pintado à mão é conferido inteiro (``validate_language.py``): em pedaços, cada linha de um
    texto traduzido perdia as marcas do começo ou do fim e parecia texto fora do catálogo.
    """
    painter.drawText(QRect(area.x(), area.y(), area.width(), len(linhas) * metricas.lineSpacing()),
                     int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextDontClip),
                     "\n".join(linhas))


def _com_alfa(cor: str, alfa: int) -> str:
    """``#rrggbb`` com ``alfa`` (0–255) como ``#aarrggbb``, que é como o Qt lê cor translúcida em texto."""
    return f"#{alfa:02x}{cor.lstrip('#')}"


def _com_alfa_cor(cor: str, alfa: int) -> QColor:
    resultado = QColor(cor)
    resultado.setAlpha(alfa)
    return resultado
