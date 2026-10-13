"""A fonte da interface: embutida, em pixels, e as imagens que o QSS usa no lugar do que ele não desenha.

O que uma troca de fonte perde em silêncio é a medida: código que calcula "um pouco menor" a partir de ``pointSizeF``
(que numa fonte em pixels vale -1) devolve um tamanho fixo ou zero, sem erro nenhum, e a linha do tempo ficava com
7 pt onde devia haver 11 px.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QImage

from videomanager.presentation.qt import fonts, paletas, theme

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "src" / "videomanager" / "resources" / "fonts"


def test_as_fontes_estao_no_pacote_e_carregam(desktop_app):
    for nome in ("Inter-Regular", "Inter-Medium", "Inter-SemiBold", "Inter-Bold",
                 "JetBrainsMono-Regular", "JetBrainsMono-Medium", "JetBrainsMono-Bold"):
        assert (PASTA / f"{nome}.ttf").is_file(), nome
    familias = QFontDatabase.families()
    assert fonts.INTERFACE_FAMILY in familias and fonts.MONO_FAMILY in familias
    # Os quatro pesos que o QSS pede (400, 500, 600, 700) existem de verdade, e não são sintetizados.
    estilos = QFontDatabase.styles(fonts.INTERFACE_FAMILY)
    assert {"Regular", "Medium", "SemiBold", "Bold"} <= set(estilos)


def test_a_interface_usa_a_inter_em_13_px(desktop_app):
    fonts.ensure_application_fonts()
    fonte = desktop_app.font()
    assert (fonte.family(), fonte.pixelSize()) == ("Inter", 13)
    # Não é uma substituição: o Qt resolve para a Inter mesma, e não para a "Sans Serif" do sistema.
    assert QFontInfo(fonte).family() == "Inter"


def test_a_monoespacada_e_a_embutida_e_tem_largura_fixa(desktop_app):
    mono = fonts.mono()
    assert QFontInfo(mono).family() == "JetBrains Mono" and QFontInfo(mono).fixedPitch()
    assert fonts.mono(20).pixelSize() == 20


def test_resized_trabalha_em_pixels_e_respeita_o_piso(desktop_app):
    base = fonts.interface_font()
    assert fonts.resized(base, delta=-2).pixelSize() == 11
    assert fonts.resized(base, factor=0.9).pixelSize() == 12
    assert fonts.resized(base, delta=-10, minimum=9).pixelSize() == 9
    # Uma fonte em pontos (a de um diálogo antigo, ou a de um widget de fora) também sai em pixels.
    em_pontos = QFont("Inter")
    em_pontos.setPointSize(10)
    saida = fonts.resized(em_pontos, delta=-1)
    assert saida.pixelSize() == QFontInfo(em_pontos).pixelSize() - 1 and saida.pointSizeF() < 0


def test_nenhum_codigo_da_interface_calcula_tamanho_a_partir_de_pontos():
    # ``pointSizeF()`` de uma fonte em pixels é -1: quem soma ou multiplica por ele devolve um tamanho que nada tem a
    # ver com o texto (7 pt fixo na régua da linha do tempo; ``setPointSize(0)`` no título das Propriedades).
    quem = []
    for caminho in sorted((RAIZ / "src" / "videomanager" / "presentation").rglob("*.py")):
        if caminho.name == "fonts.py":
            continue
        for numero, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\.(pointSizeF|pointSize|setPointSizeF|setPointSize)\(", linha) and "QFont(" not in linha:
                quem.append(f"{caminho.relative_to(RAIZ)}:{numero}: {linha.strip()}")
    assert not quem, quem


def test_as_licencas_das_fontes_acompanham_o_pacote():
    texto = (RAIZ / "packaging" / "licenses" / "OFL-1.1.txt").read_text(encoding="utf-8")
    for fonte in ("Inter", "JetBrains Mono", "Carlito"):
        assert fonte in texto
    assert "SIL OPEN FONT LICENSE Version 1.1" in texto
    avisos = (RAIZ / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert all(fonte in avisos for fonte in ("**Inter**", "**JetBrains Mono**", "**Carlito**")) and "OFL-1.1.txt" in avisos
    # O build recusa empacotar sem o texto da licença.
    assert "OFL-1.1.txt" in (RAIZ / "packaging" / "build_linux.sh").read_text(encoding="utf-8")


# -- imagens do QSS -------------------------------------------------------------------------------------------

def _caminhos(qss: str, chave: str) -> list[str]:
    # Dentro de uma regra só: ``[^}]`` não deixa a busca atravessar para a regra seguinte.
    return re.findall(rf'{chave}[^}}]*?url\("([^"]+)"\)', qss)


def test_o_qss_aponta_para_imagens_que_existem_e_tem_o_desenho(desktop_app):
    qss = theme.stylesheet("dark", "grafite")
    for chave in ("QComboBox::down-arrow", "QCheckBox::indicator:checked"):
        caminhos = _caminhos(qss, chave)
        assert caminhos, chave
        for caminho in caminhos:
            assert Path(caminho).is_file(), caminho
            assert Path(caminho.replace(".png", "@2x.png")).is_file(), caminho
            imagem = QImage(caminho)
            assert not imagem.isNull() and imagem.width() == 12
            assert any(imagem.pixelColor(x, y).alpha() > 200 for x in range(12) for y in range(12)), caminho


def test_cada_paleta_tem_a_sua_seta_e_o_visto_na_cor_certa(desktop_app):
    setas = set()
    for nome in paletas.nomes():
        for modo in ("dark", "light"):
            qss = theme.stylesheet(modo, nome)
            seta = _caminhos(qss, "QComboBox::down-arrow")[0]
            setas.add(seta)
            cores = theme.papeis(modo, nome)
            assert cores["t2"].lstrip("#").lower() in seta.lower()
            imagem = QImage(seta)
            mais_opaco = max(((imagem.pixelColor(x, y).alpha(), x, y) for x in range(12) for y in range(12)))
            assert imagem.pixelColor(mais_opaco[1], mais_opaco[2]).name().lower() == cores["t2"].lower()
    assert len(setas) > 1  # paletas com t2 diferentes não dividem o mesmo arquivo
