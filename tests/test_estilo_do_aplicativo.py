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
