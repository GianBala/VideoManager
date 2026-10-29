"""O que o pacote precisa embutir está declarado: o ``curl_cffi`` do yt-dlp.

Sem ele, sites que exigem a impressão digital TLS de um navegador (o Dailymotion, medido) respondiam "none of these impersonate
targets are available", e o pacote abria igual: o defeito só aparecia na primeira URL desses sites. A prova de verdade é o
``--smoke-test`` do pacote gerado (``app._smoke_check``); aqui fica o que impede a declaração de sumir sem ninguém ver.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def test_o_yt_dlp_e_pedido_com_o_extra_curl_cffi():
    pyproject = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    pedido = re.search(r'"yt-dlp\[([^\]]+)\]', pyproject)
    assert pedido is not None
    assert "curl-cffi" in pedido.group(1).split(","), pedido.group(0)


def test_o_pyinstaller_coleta_o_curl_cffi_que_nao_tem_hook():
    spec = (RAIZ / "packaging" / "videomanager.spec").read_text(encoding="utf-8")
    assert 'collect_all("curl_cffi")' in spec
    assert "_CFFI_BINARIES" in spec and "_CFFI_DATAS" in spec and "_CFFI_HIDDEN" in spec


def test_o_diagnostico_do_pacote_falha_sem_o_curl_cffi():
    app = (RAIZ / "src" / "videomanager" / "app.py").read_text(encoding="utf-8")
    assert "_get_available_impersonate_targets" in app and "curl_cffi ausente do pacote" in app
