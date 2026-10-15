"""O aplicativo roda no Fusion puro: nenhum estilo em Python no caminho de toda dica (``PRF-002``).

``EstiloDaAplicacao`` era um ``QProxyStyle`` com ``styleHint`` em Python instalado no ``QApplication``: o Qt perguntava ao
Python 29,7 mil vezes na abertura (71 dos 84 ms que a abertura ganhou) por duas dicas que só importam nos diálogos e na barra de
menus. A ordem "Cancelar | OK" passou ao QSS do tema, e o sublinhado dos atalhos a um estilo só da barra de menus.
"""

from __future__ import annotations

import os
import subprocess
import sys

_ABRIR = '''
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
pedidos = []
original = QApplication.setStyle
QApplication.setStyle = staticmethod(lambda estilo: (pedidos.append(estilo), original(estilo))[1])
from videomanager.app import build_app
app, janela = build_app([], audio_enabled=False)
print("ESTILOS", pedidos)
janela._edit.shutdown()
janela.close()
'''


def test_o_build_app_instala_o_fusion_pelo_nome_e_nao_um_estilo_em_python(tmp_path):
    ambiente = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "c"), "XDG_DATA_HOME": str(tmp_path / "d"),
                "XDG_CACHE_HOME": str(tmp_path / "k")}
    saida = subprocess.run([sys.executable, "-c", _ABRIR], env=ambiente, capture_output=True, text=True, timeout=90)
    assert "ESTILOS ['Fusion']" in saida.stdout, saida.stdout + saida.stderr


_SOLTAR_O_ESTILO = '''
import gc
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QCoreApplication, QEvent
from videomanager.app import build_app
app, janela = build_app([], audio_enabled=False)
janela.show()
for _ in range(3):
    app.processEvents()
janela._edit.shutdown()
janela._menu_style = None  # o Python solta o estilo; só o Qt o segura agora
gc.collect()
janela.deleteLater()  # o QMenuBar é destruído depois, como no encerramento do processo, e ainda pergunta ao estilo
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
print("SOBREVIVEU")
'''


def test_o_estilo_da_barra_de_menus_sobrevive_aos_widgets_que_o_usam(tmp_path):
    """O widget não é dono do estilo que recebe por ``setStyle``: o dono é o ``QApplication``.

    Só com a referência Python, ela era solta antes de a barra ser destruída e o processo caía no encerramento (4 em 12
    aberturas, em ``QMenuBar::eventFilter``, sem erro nenhum). Soltar a referência à mão torna a queda determinística.
    """
    ambiente = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "c"), "XDG_DATA_HOME": str(tmp_path / "d"),
                "XDG_CACHE_HOME": str(tmp_path / "k")}
    saida = subprocess.run([sys.executable, "-c", _SOLTAR_O_ESTILO], env=ambiente, capture_output=True, text=True, timeout=90)
    assert saida.returncode == 0 and "SOBREVIVEU" in saida.stdout, (saida.returncode, saida.stderr[-800:])
