"""Tema da aplicação.

O QSS fica embutido como string em vez de num arquivo ``.qss`` separado para não
precisar empacotar arquivo de dados: o PyInstaller exigiria uma regra extra e uma
resolução de caminho que falha silenciosamente quando o app roda congelado.

As cores estão declaradas uma vez no dicionário de paleta e interpoladas no QSS,
para que trocar de tema não implique reescrever o estilo inteiro. O mesmo
dicionário alimenta a ``QPalette`` da aplicação (ver :func:`qpalette`), porque o
QSS não cobre tudo: o que é desenhado por um delegate — como a barra de progresso
da fila — pergunta a cor à paleta, e sem isso aparece um retângulo branco no meio
do tema escuro.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

# Largura dos campos de escolha, igual nas duas abas. Sem o teto, um formulário
# estica o combo por toda a coluna: 800 px para escolher "1080p" fica
# desproporcional e joga o rótulo para longe do campo que ele descreve.
FIELD_WIDTH = 280

DARK = {
    "bg": "#1e2128",
    "surface": "#272b34",
    "surface_alt": "#2f3440",
    "border": "#3a404e",
    "text": "#e6e8ec",
    "text_dim": "#9aa3b2",
    "accent": "#4c8bf5",
    "accent_hover": "#6ba0f7",
    "accent_text": "#ffffff",
    "ok": "#3fb950",
    "warn": "#d99b28",
    "error": "#e5534b",
    "track": "#353b47",
}

LIGHT = {
    "bg": "#f4f5f7",
    "surface": "#ffffff",
    "surface_alt": "#eceef2",
    "border": "#d3d7de",
    "text": "#1d2128",
    "text_dim": "#616b7a",
    "accent": "#2f6fd0",
    "accent_hover": "#3f80e0",
    "accent_text": "#ffffff",
    "ok": "#1a7f37",
    "warn": "#9a6700",
    "error": "#cf222e",
    "track": "#dfe3e9",
}

_QSS = """
QWidget {{
    background: {bg};
    color: {text};
    font-size: 10pt;
}}
/* O título fica dentro da moldura, e não montado sobre ela.
   Fora, a linha da borda cortava as letras — o texto é mais alto que a margem
   que sobrava para ele — e um título solto entre dois painéis não deixava claro
   a qual dos dois pertencia. O recuo de 19 px (padding 10 + margem padrão do
   layout, 9) põe o título na mesma coluna em que começa o conteúdo abaixo. */
QGroupBox {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 8px;
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
    color: {text_dim};
}}
/* O card da mídia é o único painel sem título, então não pode ser um QGroupBox.
   O recuo interno (borda + padding + margem do layout) é o mesmo dos grupos,
   para que a miniatura comece na mesma coluna dos rótulos abaixo dela. */
QFrame#mediaCard {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 10px;
}}

/* Contêiner que só agrupa outros widgets, sem pintura própria. Sem isto ele
   herda o fundo da janela e desenha um retângulo escuro por cima da superfície
   do grupo em que está. */
QWidget[role="plain"] {{ background: transparent; }}

QLabel {{ background: transparent; }}
QLabel[role="dim"] {{ color: {text_dim}; }}
QLabel[role="title"] {{ font-size: 13pt; font-weight: 600; }}
QLabel[role="live"] {{ color: {accent_text}; background: {error};
    border-radius: 4px; padding: 2px 6px; font-weight: 700; font-size: 8pt; }}
QLabel[role="warn"] {{ color: {warn}; }}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QListWidget, QTreeWidget {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {accent};
    selection-color: {accent_text};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {accent}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {text_dim}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {surface_alt};
    border: 1px solid {border};
    selection-background-color: {accent};
    selection-color: {accent_text};
    outline: none;
}}

QPushButton {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:disabled {{ color: {text_dim}; border-color: {border}; }}
QPushButton[role="primary"] {{
    background: {accent};
    color: {accent_text};
    /* Borda da mesma cor do fundo em vez de "none": mantém a altura idêntica à
       do botão comum, senão o botão primário fica 2 px mais alto e desalinha a
       linha inteira em que estiver. */
    border: 1px solid {accent};
    font-weight: 600;
    padding: 7px 16px;
}}
QPushButton[role="primary"]:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton[role="primary"]:disabled {{
    background: {track}; color: {text_dim}; border-color: {track};
}}
QPushButton[role="profile"] {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 10px;
    text-align: left;
}}
QPushButton[role="profile"]:hover {{ border-color: {accent}; background: {surface}; }}

QPushButton[role="transport"] {{
    background: {surface_alt};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 2px 6px;
    font-size: 13px;
}}
QPushButton[role="transport"]:hover {{ border-color: {accent}; }}
QPushButton[role="transport"]:checked {{ background: {accent}; color: {accent_text}; border-color: {accent}; }}
QPushButton[role="transport"]:disabled {{ color: {text_dim}; border-color: {border}; }}

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
    background: {surface_alt};
    border: 1px solid {text_dim};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator:checked {{
    /* Anel grosso da cor de destaque em volta do miolo escuro: é o ponto do
       botão de rádio, sem depender de imagem embutida. */
    width: 8px;
    height: 8px;
    background: {surface_alt};
    border: 4px solid {accent};
}}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
QRadioButton::indicator:hover, QCheckBox::indicator:hover {{ border-color: {accent}; }}
QRadioButton:disabled, QCheckBox:disabled {{ color: {text_dim}; }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{
    border-color: {border};
}}

QTableView {{
    background: {surface};
    alternate-background-color: {surface_alt};
    border: 1px solid {border};
    border-radius: 8px;
    gridline-color: {border};
    selection-background-color: {accent};
    selection-color: {accent_text};
}}
QHeaderView::section {{
    background: {surface_alt};
    color: {text_dim};
    border: none;
    border-bottom: 1px solid {border};
    padding: 7px;
    font-weight: 600;
}}
QTableView::item {{ padding: 4px; }}

QProgressBar {{
    background: {track};
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
    background: {track};
    height: 4px;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {accent};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {text};
    border: 1px solid {border};
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{
    background: {accent_hover};
    border-color: {accent_hover};
}}
QSlider::handle:horizontal:disabled {{
    background: {text_dim};
}}

/* Alça larga e transparente: quem separa os painéis são as bordas dos grupos, e
   uma alça de 1 px colava o título do grupo de baixo no conteúdo do de cima. */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 12px; }}
QSplitter::handle:vertical {{ height: 8px; }}
QSplitter::handle:hover {{ background: {border}; }}

QMenuBar, QMenu {{ background: {surface}; }}
QMenuBar::item:selected, QMenu::item:selected {{
    background: {accent}; color: {accent_text};
}}
QMenu {{ border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}

QStatusBar {{ background: {surface}; color: {text_dim}; }}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {text_dim}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 5px; min-width: 24px; }}

QToolTip {{
    background: {surface_alt};
    color: {text};
    border: 1px solid {accent};
    border-radius: 4px;
    padding: 6px;
}}

/* Sem moldura em volta da página: quem delimita o conteúdo são os painéis lá
   dentro, e uma moldura por fora deles só duplicaria a borda. */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; color: {text_dim};
    padding: 8px 16px; margin-right: 4px;
    border: 1px solid transparent; border-radius: 6px;
}}
QTabBar::tab:hover {{ color: {text}; }}
QTabBar::tab:selected {{
    background: {surface}; border-color: {border};
    color: {accent}; font-weight: 600;
}}
"""


def palette(theme: str) -> dict[str, str]:
    return LIGHT if theme == "light" else DARK


def stylesheet(theme: str) -> str:
    return _QSS.format(**palette(theme))


def qpalette(theme: str) -> QPalette:
    """Paleta Qt equivalente ao QSS, para o que o QSS não alcança.

    Um ``QStyledItemDelegate`` desenha pelo estilo, que consulta a paleta e não a
    folha de estilo. Sem esta paleta a barra de progresso da fila sai com as
    cores padrão — branca sobre o tema escuro.
    """
    colors = palette(theme)
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
        QPalette.ColorRole.Highlight: colors["accent"],
        QPalette.ColorRole.HighlightedText: colors["accent_text"],
        QPalette.ColorRole.ToolTipBase: colors["surface_alt"],
        QPalette.ColorRole.ToolTipText: colors["text"],
        QPalette.ColorRole.Link: colors["accent"],
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
