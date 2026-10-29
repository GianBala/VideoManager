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


# -- O que a QtGui pede ao sistema, em qualquer plataforma ---------------------------------------------------------

def _sem_as_bibliotecas(monkeypatch, *ausentes: str) -> None:
    def carregar(nome, *args, **kwargs):
        if nome in ausentes:
            raise OSError(f"{nome}: cannot open shared object file")
        return object()

    monkeypatch.setattr(preflight, "sys", types.SimpleNamespace(platform="linux"))
    monkeypatch.setattr(preflight.ctypes, "CDLL", carregar)


def test_sem_libgl_o_aviso_vale_ate_no_offscreen(monkeypatch):
    """Sem ``libGL.so.1`` o ``import`` do PySide6 falhava com um traceback de Python, que ninguém via ao abrir pelo ícone."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _sem_as_bibliotecas(monkeypatch, "libGL.so.1")
    assert preflight.missing_system_libraries() == ["libgl1"]
    assert "libgl1" in preflight.format_instructions(["libgl1"])


def test_com_tudo_instalado_nao_acusa_nada_nem_no_xcb(monkeypatch):
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    _sem_as_bibliotecas(monkeypatch)
    assert preflight.missing_system_libraries() == []


def test_no_xcb_acusa_o_que_falta_da_qtgui_e_do_plugin(monkeypatch):
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    _sem_as_bibliotecas(monkeypatch, "libEGL.so.1", "libxcb-xinerama.so.0")
    assert preflight.missing_system_libraries() == ["libegl1", "libxcb-xinerama0"]


def test_numa_sessao_wayland_pura_so_vale_o_que_a_qtgui_pede(monkeypatch):
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    _sem_as_bibliotecas(monkeypatch, "libxcb-xinerama.so.0", "libGL.so.1")
    assert preflight.missing_system_libraries() == ["libgl1"]


def test_a_falta_da_libgl_e_explicada_antes_de_o_qt_ser_importado(tmp_path):
    """O aviso vale mesmo quando o próprio ``import`` do PySide6 não funciona.

    A ``libGL`` é pedida pela ``QtGui`` ao ser importada: com ela ausente, o aplicativo morria num ``ImportError`` de Python
    antes de o ``main`` conferir (visto num Ubuntu 24.04 enxuto, com o pacote do Linux), e os testes de
    ``missing_system_libraries`` passavam o tempo todo porque nenhum deles passava pelo ponto de entrada. Aqui o PySide6
    é bloqueado e a ``libGL`` "falta": só chega à mensagem quem confere antes do import.
    """
    import subprocess

    codigo = (
        "import sys; sys.modules['PySide6'] = None\n"
        "from videomanager import preflight\n"
        "preflight._absent = lambda libs: ['libgl1'] if ('libGL.so.1', 'libgl1') in libs else []\n"
        "import videomanager.__main__ as entrada\n"
        "raise SystemExit(entrada.main())\n"
    )
    ambiente = {**os.environ, "PYTHONPATH": str(Path(preflight.__file__).resolve().parents[1]),
                "XDG_CONFIG_HOME": str(tmp_path), "XDG_CACHE_HOME": str(tmp_path), "APPDATA": str(tmp_path)}
    resultado = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, env=ambiente, timeout=60)
    if sys.platform != "linux":
        pytest.skip("a conferência das bibliotecas só vale no Linux")
    assert resultado.returncode == 1, resultado.stderr
    assert "libgl1" in resultado.stderr and "Traceback" not in resultado.stderr, resultado.stderr
