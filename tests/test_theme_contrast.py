"""Contraste do tema: o foco do teclado e o texto precisam se ler.

Medido pelo que o Qt pinta, e não pelos tokens: o foco depende de como o QSS
combina estados, e foi assim que os botões ficaram com 1,1 a 1,6:1 entre o
estado com e sem foco — e o controle deslizante sem mudar pixel nenhum.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QLineEdit, QPushButton, QRadioButton, QSlider, QTabWidget, QVBoxLayout, QWidget

from videomanager.presentation.qt import paletas
from videomanager.presentation.qt.theme import qpalette, stylesheet


def _luminancia(cor: QColor) -> float:
    canal = lambda v: (v / 255) / 12.92 if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4
    return 0.2126 * canal(cor.red()) + 0.7152 * canal(cor.green()) + 0.0722 * canal(cor.blue())


def contraste(a, b) -> float:
    claro, escuro = sorted((_luminancia(QColor(a)), _luminancia(QColor(b))), reverse=True)
    return (claro + 0.05) / (escuro + 0.05)


@pytest.mark.parametrize("nome", paletas.nomes())
@pytest.mark.parametrize("tema", ["dark", "light"])
def test_foco_do_teclado_tem_pelo_menos_3_para_1_em_cada_controle(desktop_app, tema, nome):
    estilo, paleta = desktop_app.styleSheet(), desktop_app.palette()
    desktop_app.setPalette(qpalette(tema, nome))
    desktop_app.setStyleSheet(stylesheet(tema, nome))
    host = QWidget()
    try:
        layout = QVBoxLayout(host)
        inicio = QLineEdit("x")
        layout.addWidget(inicio)
        primario = QPushButton("Converter")
        primario.setProperty("role", "primary")
        abas = QTabWidget()
        abas.addTab(QWidget(), "Download")
        abas.addTab(QWidget(), "Convert")
        controles = [("botão", QPushButton("Analisar")), ("checkbox", QCheckBox("Loop")),
                     ("rádio", QRadioButton("Comprimir")), ("deslizante", QSlider(Qt.Orientation.Horizontal)),
                     ("primário", primario)]
        for _, widget in controles:
            layout.addWidget(widget)
        layout.addWidget(abas)
        controles.append(("aba", abas.tabBar()))
        host.resize(260, 400)
        host.show()
        host.activateWindow()
        for _ in range(5):
            desktop_app.processEvents()
        inicio.setFocus()
        desktop_app.processEvents()
        antes = {nome: widget.grab().toImage() for nome, widget in controles}
        fracos = []
        for nome, widget in controles:
            QTest.keyClick(desktop_app.focusWidget(), Qt.Key.Key_Tab)
            desktop_app.processEvents()
            assert widget.hasFocus(), nome
            a, b = antes[nome], widget.grab().toImage()
            melhor = max((contraste(a.pixel(x, y), b.pixel(x, y)) for y in range(a.height())
                          for x in range(a.width()) if a.pixel(x, y) != b.pixel(x, y)), default=1.0)
            if melhor < 3.0:
                fracos.append(f"{nome}: {melhor:.2f}:1")
        assert fracos == []
    finally:
        host.close()
        desktop_app.setStyleSheet(estilo)
        desktop_app.setPalette(paleta)


# Pares de texto e fundo que a interface usa, e o contraste mínimo de cada um:
# 4,5:1 para texto (WCAG 1.4.3), 3:1 para indicadores (1.4.11).
_TEXTO = [("text", "bg"), ("text", "surface"), ("text", "surface_alt"), ("text_dim", "bg"),
          ("text_dim", "surface"), ("text_dim", "surface_alt"), ("accent_text", "accent_fill"),
          ("accent_text", "accent_fill_hover"), ("accent_fg", "surface"), ("warn", "bg"),
          ("warn", "surface")]
# O foco do botão primário é o texto dele sobre o preenchimento (ver o QSS), e não ``focus``:
# o branco ou o preto some sobre um preenchimento claro, escuro ou âmbar.
_INDICADOR = [("focus", "border"), ("accent_text", "accent_fill"), ("accent", "surface_alt"), ("accent", "border")]


@pytest.mark.parametrize("nome", paletas.nomes())
@pytest.mark.parametrize("tema", ["dark", "light"])
def test_texto_e_indicadores_tem_o_contraste_minimo(tema, nome):
    from videomanager.presentation.qt.theme import palette
    cores = palette(tema, nome)
    # O selo "ao vivo" tem fundo vermelho fixo e texto sempre branco.
    assert contraste("#ffffff", cores["live"]) >= 4.5
    fracos = [f"{a}/{b}: {contraste(cores[a], cores[b]):.2f}" for a, b in _TEXTO
              if contraste(cores[a], cores[b]) < 4.5]
    fracos += [f"{a}/{b}: {contraste(cores[a], cores[b]):.2f}" for a, b in _INDICADOR
               if contraste(cores[a], cores[b]) < 3.0]
    assert fracos == []


@pytest.mark.parametrize("nome", paletas.nomes())
@pytest.mark.parametrize("tema", ["dark", "light"])
def test_texto_sobre_o_plano_da_previa_se_le_em_cada_paleta_e_modo(tema, nome):
    """O plano ``screen`` é escuro nos dois modos; o texto que cai sobre ele não pode ser o ``t2`` do modo claro (2,3 : 1)."""
    from videomanager.presentation.qt.theme import _cores_do_estilo
    cores = _cores_do_estilo(tema, nome)
    assert contraste(cores["t2_tela"], cores["screen"]) >= 4.5, (
        f"{nome}/{tema}: t2_tela {cores['t2_tela']} sobre screen {cores['screen']}")


@pytest.mark.parametrize("nome", paletas.nomes())
@pytest.mark.parametrize("tema", ["dark", "light"])
def test_o_estado_vazio_e_o_aviso_da_previa_usam_a_cor_de_texto_sobre_o_plano(tema, nome):
    import re
    from videomanager.presentation.qt.theme import _cores_do_estilo
    folha = stylesheet(tema, nome)
    esperada = _cores_do_estilo(tema, nome)["t2_tela"]
    for papel in ("screen-dim", "overlay-note"):
        regra = re.search(r'QLabel\[role="' + papel + r'"\]\s*\{[^}]*?[^-]color:\s*(#[0-9a-fA-F]{6})', folha)
        assert regra is not None and regra.group(1).lower() == esperada.lower(), (papel, regra and regra.group(1), esperada)
