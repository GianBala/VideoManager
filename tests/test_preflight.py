"""Defesa contra o cache de fontes envenenado (``preflight.font_cache_isolation``).

O defeito que isto cobre não levanta exceção: o processo cai com SIGSEGV na
primeira vez que o Qt monta texto com fonte de reserva. Aqui se confere o que
dá para conferir sem o veneno de verdade — a detecção, o desvio e a ordem das
chamadas; a queda em si foi medida com o cache que o Brave grava (ver CLAUDE.md).
"""
from __future__ import annotations

import os
import struct
import sys
import types
from pathlib import Path

import pytest

from videomanager import preflight

_MAGIC = b"\x04\xfc\x02\xfc"

# Criar link simbólico no Windows exige privilégio; os testes do desvio não
# precisam dele (o cabeçalho pega uma cópia igual a um link), e só os que são
# sobre links ficam de fora lá.
com_link = pytest.mark.skipif(sys.platform == "win32", reason="symlink exige privilégio no Windows")


def _cache(caminho: Path, versao: int, corpo: bytes = b"\0" * 8) -> Path:
    caminho.write_bytes(_MAGIC + struct.pack("<I", versao) + corpo)
    return caminho


@pytest.fixture
def pasta(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(preflight, "sys", types.SimpleNamespace(platform="linux"))
    destino = tmp_path / "fontconfig"
    destino.mkdir()
    return destino


def _envenenar(pasta: Path) -> list[str]:
    """O estrago do Brave: um cache-12 e os nomes cache-9/10/11 com o conteúdo dele."""
    _cache(pasta / "A-le64.cache-12", 12)
    nomes = []
    for versao in (9, 10, 11):
        nomes.append(_cache(pasta / f"A-le64.cache-{versao}", 12).name)
    return nomes


def test_nome_antigo_com_formato_novo_e_envenenado(pasta):
    nomes = _envenenar(pasta)
    achados = [p.name for p in preflight.poisoned_font_caches(pasta)]
    assert sorted(achados) == sorted(nomes)  # o cache-12 em si é inofensivo


@com_link
def test_link_para_formato_novo_e_envenenado(pasta):
    # É assim que o Brave os cria: cache-9/10/11 como links para o cache-12.
    alvo = _cache(pasta / "A-le64.cache-12", 12)
    for versao in (9, 10, 11):
        (pasta / f"A-le64.cache-{versao}").symlink_to(alvo.name)
    achados = sorted(p.name for p in preflight.poisoned_font_caches(pasta))
    assert achados == [f"A-le64.cache-{v}" for v in (10, 11, 9)]


def test_cache_saudavel_nao_e_envenenado(pasta):
    _cache(pasta / "A-le64.cache-9", 9)
    _cache(pasta / "A-le64.cache-12", 12)
    (pasta / "E-le64.cache-9").write_bytes(b"nao e fontconfig")    # sem a assinatura
    _cache(pasta / "F-le64.cache-reindex1-10", 9)                  # nome fora do padrão
    assert preflight.poisoned_font_caches(pasta) == []


@com_link
def test_links_inofensivos_nao_sao_envenenados(pasta):
    _cache(pasta / "A-le64.cache-9", 9)
    (pasta / "C-le64.cache-9").symlink_to("A-le64.cache-9")        # mesma versão
    (pasta / "D-le64.cache-9").symlink_to("D-le64.cache-12")       # quebrado: o fontconfig o ignora
    assert preflight.poisoned_font_caches(pasta) == []


def test_pasta_inexistente_nao_e_erro(tmp_path):
    assert preflight.poisoned_font_caches(tmp_path / "nao-existe") == []


def test_sem_veneno_nada_muda(pasta, tmp_path):
    _cache(pasta / "A-le64.cache-9", 9)
    antes = os.environ["XDG_CACHE_HOME"]
    with preflight.font_cache_isolation() as isolado:
        assert isolado is False
        assert os.environ["XDG_CACHE_HOME"] == antes
    assert not (tmp_path / "VideoManager").exists()  # nem a pasta própria nasce


def test_com_veneno_desvia_o_cache_e_devolve_o_ambiente(pasta, tmp_path):
    _envenenar(pasta)
    with preflight.font_cache_isolation() as isolado:
        assert isolado is True
        proprio = tmp_path / "VideoManager" / "xdg"
        assert os.environ["XDG_CACHE_HOME"] == str(proprio) and proprio.is_dir()
    assert os.environ["XDG_CACHE_HOME"] == str(tmp_path)
    assert len(preflight.poisoned_font_caches(pasta)) == 3  # o cache do usuário não é tocado


def test_sem_xdg_na_origem_a_variavel_some_ao_sair(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    # Path.home e não HOME: no Windows o Python lê USERPROFILE.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(preflight, "sys", types.SimpleNamespace(platform="linux"))
    destino = tmp_path / ".cache" / "fontconfig"
    destino.mkdir(parents=True)
    _envenenar(destino)
    with preflight.font_cache_isolation() as isolado:
        assert isolado is True
        assert os.environ["XDG_CACHE_HOME"] == str(tmp_path / ".cache" / "VideoManager" / "xdg")
    assert "XDG_CACHE_HOME" not in os.environ


def test_o_ambiente_volta_mesmo_se_o_bloco_falhar(pasta, tmp_path):
    _envenenar(pasta)
    with pytest.raises(RuntimeError):
        with preflight.font_cache_isolation():
            raise RuntimeError("falha na criação do QApplication")
    assert os.environ["XDG_CACHE_HOME"] == str(tmp_path)


def test_fora_do_linux_nao_age(pasta, monkeypatch):
    _envenenar(pasta)
    monkeypatch.setattr(preflight, "sys", types.SimpleNamespace(platform="win32"))
    with preflight.font_cache_isolation() as isolado:
        assert isolado is False


def test_sem_onde_gravar_segue_como_antes(pasta, tmp_path):
    _envenenar(pasta)
    (tmp_path / "VideoManager").write_text("arquivo no lugar da pasta")
    with preflight.font_cache_isolation() as isolado:
        assert isolado is False
        assert os.environ["XDG_CACHE_HOME"] == str(tmp_path)


def test_a_lista_de_fontes_e_lida_dentro_do_desvio(pasta, tmp_path, monkeypatch):
    """O Qt só carrega o cache quando a lista é pedida: pedida depois, iria ao cache envenenado."""
    from videomanager import app as janela

    visto: dict[str, str | None] = {}

    class FalsoApp:
        def __init__(self, argv):
            visto["criacao"] = os.environ.get("XDG_CACHE_HOME")

    class FalsoBanco:
        @staticmethod
        def families():
            visto["lista"] = os.environ.get("XDG_CACHE_HOME")
            return []

    monkeypatch.setattr(janela, "QApplication", FalsoApp)
    monkeypatch.setattr(janela, "QFontDatabase", FalsoBanco)

    janela._create_application([])  # sem veneno: não pede a lista, não muda nada
    assert visto == {"criacao": str(tmp_path)}

    visto.clear()
    _envenenar(pasta)
    janela._create_application([])
    proprio = str(tmp_path / "VideoManager" / "xdg")
    assert visto == {"criacao": proprio, "lista": proprio}
