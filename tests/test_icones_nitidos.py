"""Os ícones desenhados saem nítidos em tela de escala maior que 1 (``FRT-004``).

Cada função de ``icons.py`` devolvia um ``QIcon`` com um pixmap de 1×. Numa tela de escala 125% a 200% o Qt ampliava essa
imagem, e todo ícone da interface saía borrado ao lado de texto nítido — sem erro nenhum, só pior. Agora o ícone traz o desenho
em várias escalas, cada uma desenhada **no tamanho físico** com as mesmas funções (que já escalam por ``size``).
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon

from videomanager.presentation.qt import icons

COR = "#336699"
# Toda função pública de desenho: recebe a cor primeiro e devolve um QIcon.
DESENHOS = sorted(
    (nome, funcao) for nome, funcao in inspect.getmembers(icons, inspect.isfunction)
    if not nome.startswith("_") and funcao.__module__ == icons.__name__
    and next(iter(inspect.signature(funcao).parameters), None) == "color"
)


def _lado(funcao) -> int:
    """O tamanho em que a função cria o ícone quando não se pede outro: o do desenho de 1×, e o teto dele."""
    return inspect.signature(funcao).parameters["size"].default


def _imagem(pixmap):
    copia = pixmap.copy()
    copia.setDevicePixelRatio(1.0)
    return copia.toImage()


def test_o_inventario_de_desenhos_nao_esta_vazio():
    # Sem isto, uma mudança na assinatura esvaziaria a lista e os testes abaixo passariam sem medir nada.
    assert len(DESENHOS) >= 60


@pytest.mark.parametrize("nome, funcao", DESENHOS, ids=[nome for nome, _ in DESENHOS])
def test_a_escala_dois_o_icone_e_desenhado_no_dobro_de_pixels_e_nao_ampliado(desktop_app, nome, funcao):
    lado = _lado(funcao)
    pixmap = funcao(COR).pixmap(QSize(lado, lado), 2.0)
    assert pixmap.size() == QSize(2 * lado, 2 * lado) and pixmap.devicePixelRatio() == 2.0
    # É o desenho do dobro de pixels, ponto a ponto: o Qt ampliando o de 1× não dá a mesma imagem.
    assert _imagem(pixmap) == _imagem(icons.desenhar(funcao, COR, 2 * lado))


@pytest.mark.parametrize("nome, funcao", DESENHOS, ids=[nome for nome, _ in DESENHOS])
def test_a_escala_um_o_icone_e_o_desenho_do_tamanho_de_criacao(desktop_app, nome, funcao):
    lado = _lado(funcao)
    pixmap = funcao(COR).pixmap(QSize(lado, lado), 1.0)
    assert pixmap.size() == QSize(lado, lado) and pixmap.devicePixelRatio() == 1.0
    assert _imagem(pixmap) == _imagem(icons.desenhar(funcao, COR, lado))


def _tinta(pixmap) -> float:
    """Quanto o desenho cobre, somando a opacidade de cada ponto: cresce com a área do traço, e não com o contorno."""
    imagem = pixmap.toImage()
    return sum(imagem.pixelColor(x, y).alphaF() for x in range(imagem.width()) for y in range(imagem.height()))


@pytest.mark.parametrize("nome, funcao", DESENHOS, ids=[nome for nome, _ in DESENHOS])
def test_o_traco_engrossa_junto_com_o_desenho_na_escala_dois(desktop_app, nome, funcao):
    """Com o traço de largura fixa em pixels, o desenho dobrava e o traço ficava com metade da espessura relativa."""
    lado = _lado(funcao)
    um, dois = funcao(COR).pixmap(QSize(lado, lado), 1.0), funcao(COR).pixmap(QSize(lado, lado), 2.0)
    proporcao = _tinta(dois) / _tinta(um)
    # A área vai a 4×; o anti-serrilhado e o arredondamento dos pontos deixam uma folga.
    assert 3.3 < proporcao < 4.7, f"{nome}: a tinta foi a {proporcao:.2f}× na escala 2 (esperado ~4×)"


def test_o_icone_nunca_passa_do_tamanho_em_que_foi_pedido_como_o_pixmap_de_antes(desktop_app):
    icone = icons.plus(COR, 16)
    assert icone.actualSize(QSize(32, 32)) == QSize(16, 16)
    assert icone.pixmap(QSize(32, 32), 1.0).size() == QSize(16, 16)
    # Na escala 2 o mesmo teto vale em pixels lógicos: 16 lógicos são 32 físicos, e não 64.
    assert icone.pixmap(QSize(32, 32), 2.0).size() == QSize(32, 32)


def test_o_icone_desabilitado_continua_acinzentado_como_o_do_pixmap(desktop_app):
    normal = icons.plus(COR, 18).pixmap(QSize(18, 18), 1.0)
    desabilitado = icons.plus(COR, 18).pixmap(QSize(18, 18), 1.0, QIcon.Mode.Disabled)
    esperado = QIcon(icons.desenhar(icons.plus, COR, 18)).pixmap(QSize(18, 18), QIcon.Mode.Disabled)
    assert _imagem(desabilitado) != _imagem(normal)
    assert _imagem(desabilitado) == _imagem(esperado)


def test_dois_estados_desenham_cada_um_na_sua_cor_e_no_tamanho_fisico(desktop_app):
    icone = icons.two_states(icons.plus, "#112233", "#aabbcc", 18)
    repouso = icone.pixmap(QSize(18, 18), 2.0, QIcon.Mode.Normal, QIcon.State.Off)
    marcado = icone.pixmap(QSize(18, 18), 2.0, QIcon.Mode.Normal, QIcon.State.On)
    assert repouso.size() == marcado.size() == QSize(36, 36)
    assert _imagem(repouso) == _imagem(icons.desenhar(icons.plus, "#112233", 36))
    assert _imagem(marcado) == _imagem(icons.desenhar(icons.plus, "#aabbcc", 36))


def test_o_icone_se_copia_e_continua_desenhando(desktop_app):
    original = icons.check(COR)
    copia = QIcon(original)
    assert _imagem(copia.pixmap(QSize(18, 18), 2.0)) == _imagem(original.pixmap(QSize(18, 18), 2.0))


_ESCALA_DOIS = '''
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "2"
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QToolButton
from videomanager.presentation.qt import icons

app = QApplication([])
pixmap = icons.plus("#336699", 18).pixmap(18, 18)  # como o QLabel.setPixmap(icone.pixmap(18, 18)) dos painéis
botao = QToolButton()
botao.setIcon(icons.plus("#336699", 18))
botao.setIconSize(QSize(18, 18))
botao.show()
app.processEvents()
print("PIXMAP", pixmap.width(), pixmap.height(), pixmap.devicePixelRatio())
print("BOTAO", botao.grab().devicePixelRatio())
'''


def test_numa_tela_de_escala_dois_o_pixmap_pedido_sem_escala_ja_vem_no_dobro(tmp_path):
    """Os rótulos dos painéis fazem ``setPixmap(icone.pixmap(18, 18))``: sem escala explícita, vale a da tela."""
    ambiente = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "c"), "XDG_DATA_HOME": str(tmp_path / "d"),
                "XDG_CACHE_HOME": str(tmp_path / "k")}
    saida = subprocess.run([sys.executable, "-c", _ESCALA_DOIS], env=ambiente, capture_output=True, text=True, timeout=60)
    assert "PIXMAP 36 36 2.0" in saida.stdout, saida.stdout + saida.stderr
    assert "BOTAO 2.0" in saida.stdout
