"""Tema da aplicação.

O QSS fica embutido como string em vez de num arquivo ``.qss`` separado para não
precisar empacotar arquivo de dados: o PyInstaller exigiria uma regra extra e uma
resolução de caminho que falha silenciosamente quando o app roda congelado.

As cores estão declaradas uma vez, em ``paletas`` (seis paletas, cada uma em escuro e
claro), e interpoladas no QSS, para que trocar de tema não implique reescrever o estilo
inteiro. O mesmo dicionário alimenta a ``QPalette`` da aplicação (ver :func:`qpalette`), porque o
QSS não cobre tudo: o que é desenhado por um delegate — como a barra de progresso
da fila — pergunta a cor à paleta, e sem isso aparece um retângulo branco no meio
do tema escuro.
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Callable
from pathlib import Path

import shiboken6
from PySide6.QtCore import QPointF, QStandardPaths, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QProxyStyle, QStyle

from videomanager.presentation.qt import paletas



class EstiloDaAplicacao(QProxyStyle):
    """O Fusion, que é o único estilo idêntico no Windows e no Linux, sem o sublinhado fixo dos atalhos.

    O Qt sublinha a letra de atalho ("A̲rquivo") sempre que o estilo manda; com a dica desligada ela só aparece
    enquanto Alt está apertado, e o atalho continua funcionando. Os protótipos têm a barra de menus sem sublinhado.
    """

    def __init__(self) -> None:
        super().__init__("Fusion")

    def styleHint(self, hint, option=None, widget=None, returnData=None) -> int:  # noqa: N802
        if hint == QStyle.StyleHint.SH_UnderlineShortcut:
            return 0
        return super().styleHint(hint, option, widget, returnData)


# Largura dos campos de escolha, igual nas duas abas. Sem o teto, um formulário
# estica o combo por toda a coluna: 800 px para escolher "1080p" fica
# desproporcional e joga o rótulo para longe do campo que ele descreve.
FIELD_WIDTH = 280

# As chaves antigas da paleta "atual": o que o QSS e os painéis que se pintam sozinhos ainda leem
# (e vários testes importam). Os valores moram em ``paletas``; estes nomes continuam existindo até
# nenhum código precisar deles.
DARK = paletas.legado(paletas.PADRAO, "dark")
LIGHT = paletas.legado(paletas.PADRAO, "light")

_QSS = """
QWidget {{
    background: {canvas};
    color: {text};
    font-size: 13px;
}}
/* O título fica dentro da moldura, e não montado sobre ela.
   Fora, a linha da borda cortava as letras — o texto é mais alto que a margem
   que sobrava para ele — e um título solto entre dois painéis não deixava claro
   a qual dos dois pertencia. O recuo de 19 px (padding 10 + margem padrão do
   layout, 9) põe o título na mesma coluna em que começa o conteúdo abaixo. */
QGroupBox {{
    background: {card};
    border: 1px solid {card};
    border-radius: 12px;
    margin-top: 0;
    padding: 28px 10px 10px 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: padding;
    subcontrol-position: top left;
    left: 19px;
    top: 4px;
    padding: 0;
    color: {text};
}}
/* O card da mídia é o único painel sem título, então não pode ser um QGroupBox.
   O recuo interno (borda + padding + margem do layout) é o mesmo dos grupos,
   para que a miniatura comece na mesma coluna dos rótulos abaixo dela. */
QFrame#mediaCard {{
    background: {card};
    border: none;
    border-radius: 14px;
}}
QLabel[role="doc-title"] {{ font-size: 15px; font-weight: 600; }}
QFrame[role="divider"] {{ background: {raised2}; border: none; }}
QLabel[role="media-title"] {{ font-size: 19px; font-weight: 600; }}
QLabel[role="media-meta"], QLabel[role="media-empty"] {{ font-size: 13px; color: {t2}; }}

/* Contêiner que só agrupa outros widgets, sem pintura própria. Sem isto ele
   herda o fundo da janela e desenha um retângulo escuro por cima da superfície
   do grupo em que está. */
QWidget[role="plain"] {{ background: transparent; }}
/* Colunas do editor como cartões: o plano do cartão, cantos de 16 px, e tudo o que só agrupa (abas, páginas, áreas de
   rolagem) transparente por cima dele — os campos e botões continuam com o fundo deles. */
QWidget[role="pane"] {{ background: {card}; border-radius: 16px; }}
QWidget[role="pane"] QTabWidget::pane {{ background: transparent; border: none; }}
QWidget[role="pane"] QStackedWidget {{ background: transparent; }}
QWidget[role="pane"] QScrollArea {{ background: transparent; border: none; }}
QWidget[role="pane"] QScrollArea > QWidget, QWidget[role="pane"] QScrollArea > QWidget > QWidget {{ background: transparent; }}
QListWidget[role="media"] {{ background: transparent; border: none; padding: 0px; }}

QLabel {{ background: transparent; }}
QLabel[role="dim"] {{ color: {t2}; }}
/* Nota ao pé de uma coluna estreita (aba Transições): menor que o texto dos
   controles, para a coluna não pedir altura que a prévia ao lado perderia. */
QLabel[role="note"] {{ color: {t2}; font-size: 11px; }}
QLabel[role="title"] {{ font-size: 13pt; font-weight: 600; }}
QLabel[role="live"] {{ color: {live_text}; background: {live};
    border-radius: 4px; padding: 2px 6px; font-weight: 700; font-size: 8pt; }}
QLabel[role="warn"] {{ color: {warn}; }}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QListWidget, QTreeWidget {{
    background: {raised};
    border: 1px solid {raised};
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: {fill_a};
    selection-color: {on_fill};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {accent}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {t2}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{img_chevron}"); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url("{img_chevron_dim}"); }}
QComboBox QAbstractItemView {{
    background: {raised};
    border: 1px solid {raised2};
    selection-background-color: {fill_a};
    selection-color: {on_fill};
    outline: none;
}}

QPushButton {{
    background: {raised};
    border: 1px solid {raised};
    border-radius: 8px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: {raised2}; border-color: {raised2}; }}
QPushButton:disabled {{ color: {t2}; border-color: {raised}; }}
QPushButton[role="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {fill_a}, stop:1 {fill_b});
    color: {on_fill};
    /* Borda da mesma cor do fundo em vez de "none": mantém a altura idêntica à
       do botão comum, senão o botão primário fica 2 px mais alto e desalinha a
       linha inteira em que estiver. */
    border: 1px solid {fill_a};
    font-weight: 600;
    padding: 7px 16px;
}}
QPushButton[role="primary"]:hover {{ border-color: {on_fill}; }}
QPushButton[role="primary"]:disabled {{
    background: {raised2}; color: {t2}; border-color: {raised2};
}}
/* Aba Download: o endereço é o que ela pede primeiro (campo, "Colar e analisar" e "Analisar" na mesma altura,
   por isso o ``min-height``), as seções são cartões, e o rodapé leva o resultado e a ação. */
/* A barra de endereço é um quadro só (``AddressBar``): o campo de dentro perde a moldura, e o anel de foco é do quadro. */
QFrame[role="address-bar"] {{ background: {card}; border: 1px solid {raised}; border-radius: 12px; }}
QFrame[role="address-bar"][focused="true"] {{ border: 1px solid {ring}; }}
QLineEdit[role="address-edit"], QLineEdit[role="address-edit"]:focus {{ background: transparent; border: none; border-radius: 0px; padding: 0px; font-size: 15px; min-height: 26px; }}
QPushButton[role="btn"] {{ padding: 9px 14px; border-radius: 9px; }}
QPushButton[role="ghost"] {{ background: transparent; border: 1px solid transparent; color: {t2}; padding: 9px 12px; }}
QPushButton[role="ghost"]:hover {{ background: {raised}; border-color: {raised}; color: {text}; }}
QPushButton[role="ghost"]:focus {{ border-color: {focus}; }}
QComboBox[role="field"], QLineEdit[role="field"] {{ min-height: 36px; padding: 0px 12px; border-radius: 9px; }}
QLabel[role="caption"] {{ font-size: 12px; font-weight: 500; color: {t2}; }}
QPushButton[role="primary"][emphasis="field"] {{ padding: 0px 22px; min-height: 36px; border-radius: 9px; font-size: 14px; }}
/* Destino em linha corrida: o caminho é um campo sem moldura, e "Alterar" é um link no tom do acento. */
QLineEdit[role="field"][compact="true"] {{ min-height: 32px; }}
QLineEdit[role="path"], QLineEdit[role="path"]:focus {{ background: transparent; border: none; border-radius: 0px; padding: 0px; }}
QPushButton[role="link"] {{ background: transparent; border: none; color: {accent}; padding: 0px 2px; }}
QPushButton[role="link"]:hover {{ background: transparent; border: none; color: {text}; }}
QPushButton[role="link"]:focus {{ text-decoration: underline; }}
QPushButton[role="primary"][emphasis="large"] {{ padding: 0px 22px; font-size: 14px; min-height: 42px; border-radius: 11px; }}
QLabel[role="section-title"] {{ font-size: 15px; font-weight: 600; color: {text}; }}
QLabel[role="hint"] {{ font-size: 12px; color: {t3}; }}
/* O cartão de seção é o plano do cartão; o rodapé, que carrega a ação, é um plano acima. */
QFrame[role="section"] {{ background: {card}; border: none; border-radius: 14px; }}
QFrame[role="footer"] {{ background: {raised}; border: none; border-radius: 14px; }}
QToolButton[role="section-header"] {{ background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 2px 8px 2px 2px; font-size: 15px; font-weight: 600; color: {text}; }}
QToolButton[role="section-header"][tight="true"] {{ padding: 0px 0px 0px 0px; background: transparent; }}
QToolButton[role="section-header"]:hover {{ background: {raised}; }}
QToolButton[role="section-header"][tight="true"]:hover {{ background: transparent; }}
QToolButton[role="section-header"]:focus {{ border-color: {focus}; }}
QLabel[role="result"] {{ font-size: 13px; font-weight: 500; color: {text}; }}
QLabel[role="micro"] {{ font-size: 11px; color: {t3}; }}
QLabel[role="result-size"] {{ font-size: 22px; font-weight: 700; color: {text}; }}
/* Cartão de paleta (aba Tema): miniatura e nome dentro do botão. A borda é sempre de 2 px, para
   o cartão marcado não crescer e empurrar os vizinhos. */
QPushButton[role="palette"] {{ background: {raised}; border: 2px solid {raised}; border-radius: 10px; padding: 0px; text-align: left; }}
QPushButton[role="palette"]:hover {{ border-color: {raised2}; }}
/* Aba Convert: a lista de arquivos se pinta sozinha sobre o cartão; os três modos são um controle segmentado
   (três botões de rádio de desenho próprio, ver ``segmented.py``); o resumo é um destaque com moldura no tom do acento. */
QListWidget[role="files"] {{ background: transparent; border: none; padding: 0px; }}
QFrame[role="segments"] {{ background: {raised}; border: none; border-radius: 11px; }}
QFrame[role="callout"] {{ background: {soft16}; border: 1px solid {soft16}; border-radius: 12px; }}
QFrame[role="callout-warn"] {{ background: {warn16}; border: 1px solid {warn16}; border-radius: 10px; }}
QLabel[role="callout-title"] {{ color: {accent}; font-size: 11px; font-weight: 700; }}
QLabel[role="plan"] {{ font-size: 13px; font-weight: 500; color: {text}; }}

/* Janela de configurações: abas sublinhadas e títulos de grupo em caixa alta. */
QTabBar[role="underline"]::tab {{ background: transparent; color: {t2}; padding: 9px 12px; margin-right: 8px;
    border: none; border-bottom: 2px solid transparent; border-radius: 0px; }}
QTabBar[role="underline"]::tab:hover {{ color: {text}; }}
QTabBar[role="underline"]::tab:selected {{ background: transparent; color: {accent}; font-weight: 600;
    border-bottom: 2px solid {accent}; }}
QTabBar[role="underline"]::tab:focus {{ border: 1px solid {focus}; border-bottom: 2px solid {accent}; }}
/* Abas estreitas (a coluna de adicionais do editor): sem margem entre elas e com o preenchimento menor. */
QTabBar[role="underline"][compact="true"]::tab {{ padding: 8px 5px; margin-right: 0px; font-size: 11px; }}
QPushButton[compact="true"] {{ padding-left: 8px; padding-right: 8px; }}
/* Aba Propriedades: o fio entre as seções é pintado pela própria seção (``Section.paintEvent``), o cabeçalho tem 14 px e
   o × fica vermelho ao passar o mouse. Os campos são caixas com o rótulo e a unidade dentro (``FieldBox``): o controle
   de dentro perde a moldura, e o anel de foco é da caixa. */
QFrame[role="prop-section"] {{ background: transparent; border: none; }}
QToolButton[role="section-header"][compact="true"] {{ font-size: 14px; }}
QFrame[role="field-box"] {{ background: {raised}; border: 1px solid {raised}; border-radius: 10px; }}
QFrame[role="field-box"][focused="true"] {{ border-color: {ring}; }}
QAbstractSpinBox[role="bare"] {{ background: transparent; border: none; padding: 0px; color: {text};
    selection-background-color: {fill_a}; selection-color: {on_fill}; }}
QAbstractSpinBox[role="bare"]:disabled {{ color: {t2}; }}
QLabel[role="lead"] {{ color: {t2}; }}
QLabel[role="unit"] {{ color: {t3}; }}
QPushButton[role="tile"] {{ background: {raised}; border: 1px solid {raised}; border-radius: 10px; padding: 0px; }}
QPushButton[role="tile"]:hover {{ background: {raised2}; border-color: {raised2}; }}
QPushButton[role="tile"]:focus {{ border-color: {focus}; }}
QPushButton[role="tile"][active="true"] {{ background: {soft16}; border-color: {accent}; }}
QPushButton[role="tile"]:checked {{ background: {seg_on}; border-color: {seg_ring}; color: {accent}; }}
/* Transporte do editor: botões de ícone sem fundo (o ligado leva o tom suave), o play de 46 px em degradê, o tempo em tipo
   monoespaçado (a família vem do código, e o tamanho daqui: o QSS de ``QWidget`` mandaria no que o código pedisse) e o aviso que fica sobre o canto da prévia. */
QPushButton[role="tool"] {{ background: transparent; border: 1px solid transparent; border-radius: 10px; padding: 0px; }}
QPushButton[role="tool"]:hover {{ background: {raised}; }}
QPushButton[role="tool"]:checked {{ background: {soft16}; }}
QPushButton[role="tool"]:focus {{ border-color: {focus}; }}
QPushButton[role="play"] {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {fill_a}, stop:1 {fill_b});
    border: 1px solid {fill_a}; border-radius: 23px; padding: 0px; }}
QPushButton[role="play"]:hover {{ border-color: {on_fill}; }}
QPushButton[role="play"]:focus {{ border-color: {focus}; }}
QLabel[role="clock"] {{ color: {text}; font-size: 22px; font-weight: 500; }}
QLabel[role="clock-total"] {{ color: {t2}; font-size: 13px; }}
QLabel[role="overlay-note"] {{ background: {screen82}; color: {t2}; border-radius: 8px; padding: 3px 10px; }}
QComboBox[role="field"][compact="true"] {{ min-height: 32px; border-radius: 10px; }}
QFrame[role="segments"][compact="true"] {{ border-radius: 10px; }}
QToolButton[role="icon"][danger="true"]:hover {{ background: {err16}; }}
QLabel[role="group-heading"] {{ color: {t3}; font-size: 11px; font-weight: 700; padding-top: 6px; }}

/* Aba Metadados: o ícone do arquivo e os botões que só pedem atenção quando se chega a eles. */
QLabel[role="tile"] {{ background: {raised2}; border-radius: 10px; }}
QLabel[role="tile"][kind="video"] {{ background: {soft16}; }}
QLabel[role="tile"][kind="audio"] {{ background: {audio16}; }}
QLabel[role="cover"] {{ background: {raised}; color: {t2}; border-radius: 12px; padding: 8px; }}
QPushButton[role="flat"] {{ background: transparent; border: 1px solid transparent; color: {t2}; }}
QPushButton[role="flat"]:hover {{ background: {raised}; border-color: {raised}; color: {text}; }}
QPushButton[role="flat"]:disabled {{ color: {t3}; }}
QPushButton[role="flat"]:focus {{ border-color: {focus}; }}

/* Gaveta de tarefas: coluna à direita, no tom do menu lateral, separada do conteúdo por um fio. */
QFrame[role="drawer"] {{ background: {panel}; border: none; border-left: 1px solid {raised}; }}
QLabel[role="drawer-title"] {{ font-size: 16px; font-weight: 600; color: {text}; background: transparent; }}
QLabel[role="chip"] {{ background: {raised2}; color: {t2}; border-radius: 11px; padding: 2px 9px; min-height: 18px; font-size: 11px; font-weight: 500; }}
QLabel[role="chip"][tone="accent"] {{ background: {soft16}; color: {accent}; }}
QLabel[role="chip"][tone="err"] {{ background: {err16}; color: {err}; }}
QToolButton[role="icon"] {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 4px; }}
QToolButton[role="icon"]:hover {{ background: {raised}; }}
QToolButton[role="icon"]:focus {{ border-color: {focus}; }}
/* Barra superior do editor: o seletor de tela é um botão no tom dos campos, com a seta pintada à direita (a reserva
   do ``padding`` é a de ``canvas_selector._RESERVE``); o painel que ele abre é um menu de campos, sem canto
   arredondado porque é uma janela própria e o canto cairia sobre o fundo da janela. */
QToolButton[role="selector"] {{ background: {raised}; border: 1px solid {raised}; border-radius: 8px; padding: 7px 34px 7px 12px; color: {text}; }}
QToolButton[role="selector"]:hover {{ background: {raised2}; border-color: {raised2}; }}
QToolButton[role="selector"]:focus {{ border-color: {accent}; }}
QFrame[role="popover"] {{ background: {panel}; border: 1px solid {raised2}; }}
QFrame[role="popover"] QLabel {{ background: transparent; }}
QLabel[role="dirty-dot"] {{ background: {warn}; border-radius: 4px; }}
/* Fila de tarefas: os cartões se pintam sozinhos, sobre o fundo do painel. */
QListView[role="queue"] {{ background: transparent; border: none; }}
/* Menu lateral: itens de ícone e texto embaixo; o marcado leva o tom do acento, e a faixa de seleção é pintada pelo
   próprio menu rente à borda da janela (``NavRail.paintEvent``), fora do item. A borda existe sempre (transparente)
   para o item focado não mudar de medida. O item que só liga e desliga (a gaveta) não ganha fundo: aberto, só o ícone
   vai para o acento. */
QWidget[role="rail"] {{ background: {panel}; }}
QToolButton[role="rail-item"] {{ background: transparent; color: {t2}; border: 1px solid transparent; border-radius: 11px; padding: 6px 0px 5px 0px; font-size: 11px; font-weight: 500; }}
QToolButton[role="rail-item"]:hover {{ background: {raised}; color: {text}; }}
QToolButton[role="rail-item"]:checked {{ background: {soft16}; color: {text}; }}
QToolButton[role="rail-item"][toggle="true"]:checked {{ background: transparent; color: {t2}; }}
QToolButton[role="rail-item"][toggle="true"]:checked:hover {{ background: {raised}; color: {text}; }}
QToolButton[role="rail-item"]:focus {{ border-color: {focus}; }}
/* Aviso flutuante: sobre a janela, no plano elevado, com a ação e o fechar sem moldura. */
QFrame[role="toast"] {{ background: {raised2}; border: 1px solid {raised2}; border-radius: 13px; }}
QFrame[role="toast"] QLabel {{ background: transparent; }}
QPushButton[role="toast-action"] {{ background: transparent; border: 1px solid transparent; color: {accent}; font-weight: 600; padding: 4px 10px; }}
QPushButton[role="toast-action"]:hover {{ background: {raised}; border-color: {raised}; }}
QPushButton[role="toast-close"] {{ background: transparent; border: 1px solid transparent; padding: 4px; }}
QPushButton[role="toast-close"]:hover {{ background: {raised}; border-color: {raised}; }}
QPushButton[role="palette"]:checked {{ background: {soft16}; border-color: {accent}; }}

QPushButton[role="transport"] {{
    background: {raised};
    border: 1px solid {raised};
    border-radius: 6px;
    padding: 2px 6px;
    font-size: 13px;
}}
QPushButton[role="transport"]:hover {{ background: {raised2}; border-color: {raised2}; }}
QPushButton[role="transport"]:checked {{ background: {fill_a}; color: {on_fill}; border-color: {fill_a}; }}
QPushButton[role="transport"]:disabled {{ color: {t2}; border-color: {raised}; }}

QPushButton[role="spin-tool"] {{
    background: {raised};
    border: 1px solid {raised};
    border-radius: 4px;
    padding: 0px;
    margin: 0px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    font-size: 16px;
    font-weight: bold;
}}
QPushButton[role="spin-tool"]:hover {{ background: {raised2}; border-color: {raised2}; }}
QPushButton[role="spin-tool"]:pressed {{ background: {fill_a}; color: {on_fill}; }}

/* Escolha entre opções (filtros, transições, fonte): texto à esquerda e a
   marcada com a borda da cor de destaque. Letra de 12 px: com a do resto da
   aplicação, as oito transições pediam 18 px a mais, tirados da prévia. */
/* Opção de uma lista de escolha (filtro, transição): linha de 36 px, e a marcada leva o tom do segmento marcado com o
   anel de metade do acento — a mesma borda de 1 px nos dois estados, para a linha não mudar de medida ao marcar. */
QPushButton[role="option"] {{ text-align: left; padding: 0px 14px; min-height: 34px; border-radius: 10px; }}
QPushButton[role="option"]:checked {{ background: {seg_on}; border: 1px solid {seg_ring}; font-weight: 600; }}
/* Lista de escolha aberta dentro de um painel (fontes): sem moldura própria,
   a do painel já separa, e linhas com folga — sem o padding de item, a lista
   espremia oito nomes no espaço de cinco e a escolhida não se destacava. */
QListWidget[role="picker"] {{ background: transparent; border: none; }}
QListWidget[role="picker"]::item {{ padding: 4px 6px; border-radius: 3px; }}
QListWidget[role="picker"]::item:hover {{ background: {raised}; }}
QListWidget[role="picker"]::item:selected {{ background: {fill_a}; color: {on_fill}; }}
QLineEdit[role="picker"] {{ padding: 4px 6px; font-size: 11px; }}
/* Botão curto de atalho de valor (predefinições dos pop-ups de volume e velocidade). */
QPushButton[role="chip"] {{ padding: 2px 4px; font-size: 11px; }}
/* Atalho de valor da coluna de texto (tamanhos de fonte): células iguais, e a do valor de agora marcada pelo painel. */
QPushButton[role="pill"] {{ padding: 0px; min-height: 26px; border-radius: 8px; }}
QPushButton[role="pill"][active="true"] {{ background: {seg_on}; border-color: {seg_ring}; color: {accent}; font-weight: 600; }}
/* Título da escolha de uma coluna de adicionais, o seletor de fonte (com o desenho do "Aa" e da seta feito por ele
   mesmo, ver ``FontButton``) e o fio horizontal entre os grupos. */
QLabel[role="heading"] {{ font-size: 14px; font-weight: 600; color: {text}; }}
QPushButton[role="select"] {{ text-align: left; padding: 0px 34px 0px 42px; min-height: 32px; border-radius: 10px; }}
QFrame[role="hline"] {{ background: {raised}; border: none; min-height: 1px; max-height: 1px; }}
QPushButton[role="primary"][emphasis="large"][compact="true"] {{ padding: 0px 10px; }}
/* Painel suspenso sem moldura de janela (volume e velocidade do bloco). */
QDialog[role="popup"] {{ background: {card}; border: 1px solid {raised2}; border-radius: 8px; }}

/* O indicador precisa ser desenhado aqui: assim que o QSS toca no QRadioButton,
   o estilo deixa de pintar o círculo nativo e sobra um marcador quase invisível
   — não dava para ver qual das duas opções estava escolhida. */
QRadioButton, QCheckBox {{ background: transparent; spacing: 8px; }}
/* As medidas são do miolo: a borda soma por fora. Os dois estados somam 16 px
   (14+1+1 e 8+4+4), com raio 8, para que o marcador seja sempre o mesmo
   círculo e o texto ao lado não dance ao trocar de opção. */
QRadioButton::indicator, QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    background: {raised};
    border: 1px solid {t2};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; }}
/* Foco do teclado: anel de 2 px na cor de foco, com o miolo 2 px menor — os
   mesmos 16 px. Mudar só a cor da borda fina não chegava a 3:1 contra o
   cinza do indicador sem foco. Fica antes de :checked, que manda no tamanho
   do marcado. */
QRadioButton::indicator:focus, QCheckBox::indicator:focus {{
    width: 12px; height: 12px; border: 2px solid {focus};
}}
QRadioButton::indicator:checked {{
    /* Anel grosso da cor de destaque em volta do miolo escuro: é o ponto do
       botão de rádio, sem depender de imagem embutida. */
    width: 8px;
    height: 8px;
    background: {raised};
    border: 4px solid {accent};
}}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: url("{img_check}"); }}
QRadioButton::indicator:hover, QCheckBox::indicator:hover {{ border-color: {accent}; }}
QRadioButton::indicator:checked:focus, QCheckBox::indicator:checked:focus {{ border-color: {focus}; }}
QRadioButton:disabled, QCheckBox:disabled {{ color: {t2}; }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{
    border-color: {raised2};
}}

QTableView {{
    background: {card};
    alternate-background-color: {raised};
    border: 1px solid {raised};
    border-radius: 8px;
    gridline-color: {raised};
    selection-background-color: {soft16};
    selection-color: {text};
}}
QHeaderView::section {{
    background: {raised};
    color: {t2};
    border: none;
    border-bottom: 1px solid {raised2};
    padding: 7px 10px;
    font-size: 12px;
    font-weight: 500;
}}
QTableView::item {{ padding: 4px; }}

QProgressBar {{
    background: {raised2};
    border: none;
    border-radius: 5px;
    text-align: center;
    color: {text};
    height: 16px;
}}
QProgressBar::chunk {{ background: {accent}; border-radius: 5px; }}

QSlider {{
    background: transparent;
    height: 22px;
}}
QSlider::groove:horizontal {{
    background: {raised2};
    height: 4px;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {accent};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {text};
    border: 1px solid {raised2};
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{
    background: {accent};
    border-color: {accent};
}}
QSlider::handle:horizontal:disabled {{
    background: {t2};
}}
QSlider::handle:horizontal:focus {{ border: 2px solid {focus}; margin: -5px 0; }}

/* Alça larga e transparente: quem separa os painéis são as bordas dos grupos, e
   uma alça de 1 px colava o título do grupo de baixo no conteúdo do de cima. */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 12px; }}
QSplitter::handle:vertical {{ height: 8px; }}
QSplitter::handle:hover {{ background: {raised2}; }}

QMenuBar, QMenu {{ background: {panel}; }}
/* Barra de menus: 28 px, com um fio embaixo, e texto discreto de 12 px. */
QMenuBar {{ border-bottom: 1px solid {raised}; padding: 0px 8px; }}
QMenuBar::item {{ background: transparent; color: {t2}; font-size: 12px; padding: 6px 10px; border-radius: 6px; }}
QMenuBar::item:selected {{ background: {raised}; color: {text}; }}
QMenu::item:selected {{
    background: {fill_a}; color: {on_fill};
}}
QMenu {{ border: 1px solid {raised2}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}

QStatusBar {{ background: {panel}; color: {t2}; }}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {raised2}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {t2}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {raised2}; border-radius: 5px; min-width: 24px; }}

QToolTip {{
    background: {raised};
    color: {text};
    border: 1px solid {accent};
    border-radius: 4px;
    padding: 6px;
}}

/* Sem moldura em volta da página: quem delimita o conteúdo são os painéis lá
   dentro, e uma moldura por fora deles só duplicaria a borda. */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; color: {t2};
    padding: 8px 16px; margin-right: 4px;
    border: 1px solid transparent; border-radius: 6px;
}}
QTabBar::tab:hover {{ color: {text}; }}
QTabBar::tab:selected {{
    background: {card}; border-color: {raised2};
    color: {accent}; font-weight: 600;
}}
QTabBar::tab:focus {{ border-color: {focus}; }}

/* Foco do teclado nos botões: só a cor da borda muda, para a geometria não
   pular. Antes só os campos de texto mostravam foco: medido, 1,1 a 1,6:1
   entre o botão com e sem foco, onde a referência pede 3:1, e quem navega
   por Tab não sabia em que botão o Enter ia cair. No fim do estilo para
   valer sobre o :hover e os papéis. */
QPushButton:focus, QPushButton[role="transport"]:focus,
QPushButton[role="spin-tool"]:focus, QPushButton[role="palette"]:focus {{ border-color: {focus}; }}
/* O anel de foco do botão primário é a cor do texto dele: o foco branco ou preto some sobre um
   preenchimento claro, escuro ou âmbar (medido nas paletas Estúdio e Cinema). */
QPushButton[role="primary"]:focus {{ border-color: {on_fill}; }}
"""


# O modo e a paleta em vigor, e quem quer saber quando mudarem. Fica aqui, e não em cada painel,
# porque a troca com a janela aberta precisa alcançar quem pintou uma cor na construção — o
# dicionário da linha do tempo, os ícones da barra, a onda sonora já renderizada — e ``setStyleSheet``
# não chega a nenhum deles.
_atual: tuple[str, str] = ("dark", paletas.PADRAO)
_ouvintes: list[Callable[[], Callable[[], None] | None]] = []
_registro = logging.getLogger(__name__)


# Cor de cada espécie de bloco da linha do tempo. É semântica e não muda com a paleta: o que o olho procura
# (o áudio, o texto, a transição) tem de ter a mesma cor em qualquer tema. Mora aqui, a casa das cores, e não
# na linha do tempo.
TIPOS_DE_BLOCO = {
    "video": "#4f8ef7", "audio": "#34b27b", "text": "#8b6df5", "image": "#22b8cf", "filter": "#6c7bf0",
    "transition": "#f59e0b",
}


def atual() -> tuple[str, str]:
    """``(modo, paleta)`` em vigor, na forma que :func:`palette` e :func:`papeis` aceitam."""
    return _atual


def on_theme_change(callback: Callable[[], None]) -> None:
    """Chama ``callback`` sempre que :func:`apply` trocar o modo ou a paleta.

    Método de objeto fica por referência **fraca** (como em ``on_language_change``): o painel
    que se registra pode ser fechado sem avisar ninguém, e o registro não o segura vivo.
    O ``callback`` lê o que precisa de :func:`atual`.
    """
    if hasattr(callback, "__self__"):
        _ouvintes.append(weakref.WeakMethod(callback))
    else:
        _ouvintes.append(lambda: callback)


def apply(app, theme: str, nome: str = paletas.PADRAO) -> None:
    """Aplica o modo e a paleta à aplicação e avisa quem pintou cor por conta própria."""
    global _atual
    _atual = (theme, nome)
    app.setPalette(qpalette(theme, nome))
    app.setStyleSheet(stylesheet(theme, nome))
    for ouvinte in list(_ouvintes):
        funcao = ouvinte()
        dono = getattr(funcao, "__self__", None)
        # Fechar uma janela destrói o objeto C++ e deixa o Python vivo enquanto algo o referencia:
        # chamá-lo levanta "Internal C++ object already deleted" (mesma regra de ``i18n``).
        if funcao is None or (dono is not None and not shiboken6.isValid(dono)):
            _ouvintes.remove(ouvinte)
            continue
        try:
            funcao()
        except Exception:  # um painel com defeito não pode deixar o resto na paleta antiga
            _registro.exception("falha ao aplicar o tema em %s", getattr(funcao, "__qualname__", "?"))


def palette(theme: str, nome: str = paletas.PADRAO) -> dict[str, str]:
    """As chaves antigas do tema (``bg``, ``surface``...) da paleta ``nome`` no modo ``theme``.

    Um dicionário novo a cada chamada. Os papéis novos (``canvas``, ``card``...) saem de
    :func:`papeis`; os dois não se fundem porque ``accent``, ``ok`` e ``warn`` existem nos
    dois com valores diferentes na paleta ``atual`` (ver ``paletas``).
    """
    return paletas.legado(nome, theme)


def papeis(theme: str, nome: str = paletas.PADRAO) -> dict[str, str]:
    """Os papéis de cor da paleta ``nome`` no modo ``theme``."""
    return paletas.papeis(nome, theme)


def _misturar(frente: str, fundo: str, peso: float) -> str:
    """``frente`` com ``peso`` de presença sobre ``fundo``, como cor opaca."""
    a, b = QColor(frente), QColor(fundo)
    canal = lambda x, y: round(x * peso + y * (1 - peso))  # noqa: E731
    return QColor(canal(a.red(), b.red()), canal(a.green(), b.green()), canal(a.blue(), b.blue())).name()


def derivadas(cores: dict[str, str]) -> dict[str, str]:
    """Os tons que o protótipo usa e nenhum papel guarda: o anel de foco, o cartão sob o mouse e o segmento marcado.

    O anel é o acento a 50% sobre o cartão; o cartão "quente" é o cartão com 4% do tom suave.
    """
    seg_on = _misturar(cores["soft"], cores["raised"], 0.15)
    return {
        "ring": _misturar(cores["accent"], cores["card"], 0.5),
        "hot": _misturar(cores["soft"], cores["card"], 0.04),
        # O botão marcado de um controle segmentado: o tom suave sobre o fundo elevado, com um anel de metade do acento.
        "seg_on": seg_on,
        "seg_ring": _misturar(cores["accent"], seg_on, 0.5),
    }


def _chevron(p: QPainter, lado: float) -> None:
    u = lado / 12.0
    p.drawPolyline(QPolygonF([QPointF(2.6 * u, 4.4 * u), QPointF(6 * u, 7.8 * u), QPointF(9.4 * u, 4.4 * u)]))


def _visto(p: QPainter, lado: float) -> None:
    u = lado / 12.0
    p.drawPolyline(QPolygonF([QPointF(2.6 * u, 6.4 * u), QPointF(5 * u, 8.8 * u), QPointF(9.4 * u, 3.6 * u)]))


def _imagem(nome: str, cor: str, desenho, espessura: float = 1.6) -> str:
    """O PNG de ``desenho`` na ``cor``, escrito uma vez na pasta de cache, e o caminho para o ``url()`` do QSS.

    O QSS só aceita arquivo de imagem, e o ícone desenhado à mão (``icons``) não é arquivo: a seta do combo e o
    visto da caixa de seleção saem daqui, em 12 px e em 24 px (``@2x``, que o Qt escolhe sozinho em tela densa).
    O nome leva a cor, então trocar de paleta não reaproveita a imagem da outra.
    """
    pasta = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)) / "estilo"
    pasta.mkdir(parents=True, exist_ok=True)
    base = pasta / f"{nome}-{cor.lstrip('#')}"
    for escala, sufixo in ((1, ""), (2, "@2x")):
        alvo = Path(f"{base}{sufixo}.png")
        if alvo.exists():
            continue
        lado = 12 * escala
        imagem = QImage(lado, lado, QImage.Format.Format_ARGB32)
        imagem.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(imagem)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caneta = QPen(QColor(cor), espessura * escala)
        caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
        caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pintor.setPen(caneta)
        desenho(pintor, lado)
        pintor.end()
        imagem.save(str(alvo))
    return f"{base}.png".replace("\\", "/")


def _cores_do_estilo(theme: str, nome: str) -> dict[str, str]:
    """O que o QSS interpola: os papéis, o foco e o selo, e o acento a 16% de opacidade."""
    cores = {**papeis(theme, nome), **{k: palette(theme, nome)[k] for k in ("focus", "live")}}
    vermelho, verde, azul = (int(cores["soft"][i:i + 2], 16) for i in (1, 3, 5))
    cores["soft16"] = f"rgba({vermelho}, {verde}, {azul}, 0.16)"
    erro_r, erro_g, erro_b = (int(cores["err"][i:i + 2], 16) for i in (1, 3, 5))
    cores["err16"] = f"rgba({erro_r}, {erro_g}, {erro_b}, 0.16)"
    aviso_r, aviso_g, aviso_b = (int(cores["warn"][i:i + 2], 16) for i in (1, 3, 5))
    cores["warn16"] = f"rgba({aviso_r}, {aviso_g}, {aviso_b}, 0.16)"
    # O selo "ao vivo" tem fundo vermelho fixo nos dois modos; o texto dele é sempre branco, e não o
    # texto do botão primário, que nas paletas de botão claro ou âmbar é escuro.
    cores["live_text"] = "#ffffff"
    # O plano da prévia a 82%: o aviso que fica sobre o quadro ("Carregando quadro…") precisa ler-se sobre qualquer imagem.
    tela = QColor(cores["screen"])
    cores["screen82"] = f"rgba({tela.red()}, {tela.green()}, {tela.blue()}, 0.82)"
    # O ladrilho do arquivo de áudio: o verde de áudio da linha do tempo, a 16%.
    verde = QColor(TIPOS_DE_BLOCO["audio"])
    cores["audio16"] = f"rgba({verde.red()}, {verde.green()}, {verde.blue()}, 0.16)"
    # O anel de foco do protótipo é o acento a 50% sobre o cartão, e o cartão "quente" (sob o mouse) é o cartão com 4%
    # do tom suave: nenhum dos dois é um papel, são derivados.
    cores.update(derivadas(cores))
    # As imagens do QSS (o QSS não desenha): seta do combo, na cor do texto discreto, e o visto sobre o acento.
    cores["img_chevron"] = _imagem("chevron", cores["t2"], _chevron)
    cores["img_chevron_dim"] = _imagem("chevron", cores["t3"], _chevron)
    cores["img_check"] = _imagem("check", cores["canvas"], _visto, 1.9)
    return cores


def stylesheet(theme: str, nome: str = paletas.PADRAO) -> str:
    return _QSS.format(**_cores_do_estilo(theme, nome))


def qpalette(theme: str, nome: str = paletas.PADRAO) -> QPalette:
    """Paleta Qt equivalente ao QSS, para o que o QSS não alcança.

    Um ``QStyledItemDelegate`` desenha pelo estilo, que consulta a paleta e não a
    folha de estilo. Sem esta paleta a barra de progresso da fila sai com as
    cores padrão — branca sobre o tema escuro.
    """
    colors = palette(theme, nome)
    result = QPalette()
    groups = (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    )
    roles = {
        QPalette.ColorRole.Window: colors["bg"],
        QPalette.ColorRole.WindowText: colors["text"],
        QPalette.ColorRole.Base: colors["surface_alt"],
        QPalette.ColorRole.AlternateBase: colors["surface"],
        QPalette.ColorRole.Text: colors["text"],
        QPalette.ColorRole.PlaceholderText: colors["text_dim"],
        QPalette.ColorRole.Button: colors["surface_alt"],
        QPalette.ColorRole.ButtonText: colors["text"],
        QPalette.ColorRole.Highlight: colors["accent_fill"],
        QPalette.ColorRole.HighlightedText: colors["accent_text"],
        QPalette.ColorRole.ToolTipBase: colors["surface_alt"],
        QPalette.ColorRole.ToolTipText: colors["text"],
        QPalette.ColorRole.Link: colors["accent_fg"],
    }
    for group in groups:
        for role, value in roles.items():
            result.setColor(group, role, QColor(value))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        result.setColor(
            QPalette.ColorGroup.Disabled, role, QColor(colors["text_dim"])
        )
    return result
