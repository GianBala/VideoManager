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

from videomanager.presentation.qt.theme import qpalette, stylesheet


def _luminancia(cor: QColor) -> float:
    canal = lambda v: (v / 255) / 12.92 if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4
    return 0.2126 * canal(cor.red()) + 0.7152 * canal(cor.green()) + 0.0722 * canal(cor.blue())


def contraste(a, b) -> float:
    claro, escuro = sorted((_luminancia(QColor(a)), _luminancia(QColor(b))), reverse=True)
    return (claro + 0.05) / (escuro + 0.05)


@pytest.mark.parametrize("tema", ["dark", "light"])
def test_foco_do_teclado_tem_pelo_menos_3_para_1_em_cada_controle(desktop_app, tema):
    estilo, paleta = desktop_app.styleSheet(), desktop_app.palette()
    desktop_app.setPalette(qpalette(tema))
    desktop_app.setStyleSheet(stylesheet(tema))
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
          ("warn", "surface"), ("accent_text", "live")]
_INDICADOR = [("focus", "border"), ("focus", "accent_fill"), ("accent", "surface_alt"), ("accent", "border")]


@pytest.mark.parametrize("tema", ["dark", "light"])
def test_texto_e_indicadores_tem_o_contraste_minimo(tema):
    from videomanager.presentation.qt.theme import palette
    cores = palette(tema)
    fracos = [f"{a}/{b}: {contraste(cores[a], cores[b]):.2f}" for a, b in _TEXTO
              if contraste(cores[a], cores[b]) < 4.5]
    fracos += [f"{a}/{b}: {contraste(cores[a], cores[b]):.2f}" for a, b in _INDICADOR
               if contraste(cores[a], cores[b]) < 3.0]
    assert fracos == []
