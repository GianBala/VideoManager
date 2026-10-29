"""O ``AppRun`` confere a glibc antes de abrir e explica, em vez de deixar o carregador morrer calado.

As bibliotecas do AppImage vêm do sistema que o gerou (Ubuntu 24.04) e pedem a glibc dele: no Ubuntu 22.04 e no Debian 12
o carregador respondia ``version `GLIBC_2.38' not found`, num terminal que quem deu duplo clique nunca abriu. O mínimo é
medido na geração e gravado ao lado do executável; o script o compara com a glibc do sistema.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APP_RUN = Path(__file__).resolve().parents[1] / "packaging" / "appimage" / "AppRun"

pytestmark = pytest.mark.skipif(sys.platform != "linux" or shutil.which("getconf") is None,
                                reason="AppRun é do Linux e usa getconf e sort -V")


def _imagem(tmp_path: Path, minimo: str | None) -> Path:
    raiz = tmp_path / "imagem"
    (raiz / "usr" / "bin").mkdir(parents=True)
    (raiz / "usr" / "share" / "videomanager").mkdir(parents=True)
    shutil.copy(APP_RUN, raiz / "AppRun")
    executavel = raiz / "usr" / "bin" / "VideoManager"
    executavel.write_text("#!/bin/sh\necho ABRIU\n")
    for arquivo in (raiz / "AppRun", executavel):
        arquivo.chmod(0o755)
    if minimo is not None:
        (raiz / "usr" / "share" / "videomanager" / "glibc-minimo").write_text(minimo + "\n")
    return raiz


def _rodar(raiz: Path, idioma: str) -> subprocess.CompletedProcess:
    # Sem DISPLAY: nenhuma janela de erro tenta abrir no teste.
    ambiente = {"PATH": "/usr/bin:/bin", "LANG": idioma, "HOME": str(raiz)}
    return subprocess.run(["sh", str(raiz / "AppRun")], capture_output=True, text=True, env=ambiente, timeout=30)


def test_glibc_mais_velha_que_a_exigida_explica_em_portugues_e_nao_abre(tmp_path):
    resultado = _rodar(_imagem(tmp_path, "99.0"), "pt_BR.UTF-8")
    assert resultado.returncode == 1
    assert "ABRIU" not in resultado.stdout
    assert "precisa da glibc 99.0" in resultado.stderr and "este sistema tem a" in resultado.stderr


def test_a_mesma_mensagem_sai_em_ingles_fora_do_portugues(tmp_path):
    resultado = _rodar(_imagem(tmp_path, "99.0"), "en_US.UTF-8")
    assert resultado.returncode == 1
    assert "needs glibc 99.0 or newer" in resultado.stderr


def test_glibc_suficiente_abre_o_aplicativo(tmp_path):
    resultado = _rodar(_imagem(tmp_path, "2.17"), "pt_BR.UTF-8")
    assert resultado.returncode == 0
    assert resultado.stdout.strip() == "ABRIU"


def test_um_pacote_sem_o_arquivo_do_minimo_abre_como_antes(tmp_path):
    resultado = _rodar(_imagem(tmp_path, None), "pt_BR.UTF-8")
    assert resultado.returncode == 0 and "ABRIU" in resultado.stdout
