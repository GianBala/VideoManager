"""Testes da resolução e da execução dos binários externos.

O que se guarda aqui é o **ambiente** entregue a cada processo filho. É um
defeito que não levanta exceção nenhuma: o ffmpeg abre, roda, termina com código
zero — e por dentro está usando outra biblioteca, com outros codecs. Por isso o
teste afirma o conteúdo do ambiente, e não que a chamada funcionou.
"""

from __future__ import annotations

import os
import pytest

from videomanager.infrastructure.system.binaries import clean_env
from videomanager.infrastructure.system.binaries import subprocess_kwargs


@pytest.mark.network
@pytest.mark.parametrize('platform', ['win64', 'linux64', 'linuxarm64'])
def test_publicacao_de_ffmpeg_configurada_existe(platform, monkeypatch):
    from urllib.request import Request, urlopen
    from videomanager.infrastructure.system import binaries
    monkeypatch.setattr(binaries, 'platform_key', lambda: platform)
    request = Request(binaries.download_url(), method='HEAD',
                      headers={'User-Agent': 'VideoManager/validacao'})
    with urlopen(request, timeout=30) as response:
        assert response.status == 200
        assert response.url.startswith('https://')


class TestAmbienteDosProcessosFilhos:
    """O ``LD_LIBRARY_PATH`` que o bootloader do PyInstaller injeta.

    Ele aponta para a pasta interna do pacote, e todo filho o herda. Lá dentro
    está a ``libavcodec`` do QtMultimedia, com o mesmo ``SONAME`` da do ffmpeg:
    um ffmpeg ligado dinamicamente carregava a do Qt e **perdia os codecs que
    ela não tem**. Medido: de 230 encoders para 190, sem ``libx264``,
    ``libx265`` nem ``libmp3lame`` — e o banner de configuração, que é compilado
    no executável e não na biblioteca, continuava anunciando os três.
    """

    def test_o_caminho_do_empacotador_nao_vai_para_o_filho(self, monkeypatch) -> None:
        monkeypatch.setenv("LD_LIBRARY_PATH", "/pacote/_internal")
        monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

        assert "LD_LIBRARY_PATH" not in clean_env()

    def test_o_valor_de_antes_do_empacotamento_e_devolvido(self, monkeypatch) -> None:
        # Quando havia um valor antes, o bootloader o guarda em *_ORIG — e é ele
        # que vale para o filho, não o do pacote.
        monkeypatch.setenv("LD_LIBRARY_PATH", "/pacote/_internal")
        monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/opt/meu/lib")

        ambiente = clean_env()

        assert ambiente["LD_LIBRARY_PATH"] == "/opt/meu/lib"
        assert "LD_LIBRARY_PATH_ORIG" not in ambiente

    def test_fora_do_pacote_nada_muda(self, monkeypatch) -> None:
        monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
        monkeypatch.setenv("PATH", "/usr/bin")

        ambiente = clean_env()

        assert "LD_LIBRARY_PATH" not in ambiente
        assert ambiente["PATH"] == "/usr/bin", "o resto do ambiente passa intacto"

    def test_vale_para_todo_processo_externo(self, monkeypatch) -> None:
        # A limpeza mora no funil por onde passam ffmpeg, ffprobe e pip: uma
        # chamada que montasse os argumentos por fora escaparia dela.
        monkeypatch.setenv("LD_LIBRARY_PATH", "/pacote/_internal")
        monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

        kwargs = subprocess_kwargs()

        assert "LD_LIBRARY_PATH" not in kwargs["env"]
        assert kwargs["stdin"] == -3, "DEVNULL continua obrigatório"

    def test_o_ambiente_do_processo_nao_e_alterado(self, monkeypatch) -> None:
        # Limpar por cópia, e não mexendo em os.environ: o caminho do pacote é
        # justamente o que faz o **próprio** aplicativo achar as bibliotecas
        # dele, e apagá-lo daqui derrubaria a janela no primeiro import tardio.
        monkeypatch.setenv("LD_LIBRARY_PATH", "/pacote/_internal")

        clean_env()

        assert os.environ["LD_LIBRARY_PATH"] == "/pacote/_internal"


def test_patch_runtime_universal_extract_and_run(tmp_path) -> None:
    import sys
    from pathlib import Path
    pkg_dir = Path(__file__).resolve().parents[1] / "packaging"
    if str(pkg_dir) not in sys.path:
        sys.path.insert(0, str(pkg_dir))
    from patch_runtime import patch_runtime

    target_str = b"APPIMAGE_EXTRACT_AND_RUN\0"
    header = bytearray(0x2000)
    str_offset = 0x1500
    header[str_offset : str_offset + len(target_str)] = target_str

    lea_offset = 0x800
    disp = str_offset - (lea_offset + 7)
    header[lea_offset : lea_offset + 3] = b"\x48\x8d\x3d"
    header[lea_offset + 3 : lea_offset + 7] = disp.to_bytes(4, "little", signed=True)

    after_call = lea_offset + 7 + 5
    header[after_call : after_call + 3] = b"\x48\x85\xc0"
    jne_idx = after_call + 3
    header[jne_idx : jne_idx + 2] = b"\x0f\x85"
    header[jne_idx + 2 : jne_idx + 6] = (0x100).to_bytes(4, "little", signed=True)

    test_file = tmp_path / "mock_runtime"
    test_file.write_bytes(header)

    assert patch_runtime(test_file) is True
    patched = test_file.read_bytes()
    assert patched[jne_idx] == 0xE9
    assert patched[jne_idx + 1 : jne_idx + 5] == (0x101).to_bytes(4, "little", signed=True)
    assert patched[jne_idx + 5] == 0x90

    # Segunda chamada deve reconhecer que já está patcheado
    assert patch_runtime(test_file) is True


class TestRuntimeJavaScript:
    """O yt-dlp precisa de Deno ou Node para liberar os formatos do YouTube."""

    def _vendor(self, tmp_path, monkeypatch):
        from videomanager.infrastructure.system import binaries
        monkeypatch.setattr(binaries, "vendor_dir", lambda: tmp_path)
        return binaries

    def test_deno_empacotado_vem_antes_do_sistema(self, tmp_path, monkeypatch) -> None:
        binaries = self._vendor(tmp_path, monkeypatch)
        deno = tmp_path / binaries.exe_name("deno")
        deno.write_bytes(b"")
        deno.chmod(0o755)
        monkeypatch.setattr(binaries.shutil, "which", lambda name: f"/sistema/{name}")
        assert binaries.find_js_runtime() == ("deno", deno)

    def test_node_do_sistema_serve_quando_nao_ha_deno(self, tmp_path, monkeypatch) -> None:
        binaries = self._vendor(tmp_path, monkeypatch)
        monkeypatch.setattr(binaries.shutil, "which", lambda name: "/sistema/node" if name == "node" else None)
        name, path = binaries.find_js_runtime()
        assert name == "node" and path.name == "node"

    def test_sem_runtime_nenhum(self, tmp_path, monkeypatch) -> None:
        binaries = self._vendor(tmp_path, monkeypatch)
        monkeypatch.setattr(binaries.shutil, "which", lambda name: None)
        assert binaries.find_js_runtime() is None


class TestIntegridadeDoFfmpegBaixado:
    """O ffmpeg baixado só é instalado se o SHA-256 conferir com a publicação.

    Ele roda com os privilégios do usuário; sem o resumo, a integridade
    dependia só do TLS e da conta do fornecedor.
    """

    def _arquivo(self):
        import io
        import tarfile
        from videomanager.infrastructure.system.binaries import exe_name
        dados = io.BytesIO()
        with tarfile.open(fileobj=dados, mode="w:xz") as tar:
            for nome in (exe_name("ffmpeg"), exe_name("ffprobe")):
                corpo = b"#!/bin/sh\necho ffmpeg version teste\n"
                info = tarfile.TarInfo(f"ffmpeg-build/bin/{nome}")
                info.size, info.mode = len(corpo), 0o755
                tar.addfile(info, io.BytesIO(corpo))
        return dados.getvalue()

    def _preparar(self, tmp_path, monkeypatch, conteudo, resumo):
        import io
        from videomanager.infrastructure.system import binaries

        class Resposta(io.BytesIO):
            headers = {}

            def geturl(self):
                return "https://github.com/BtbN/arquivo.tar.xz"

        monkeypatch.setattr(binaries, "platform_key", lambda: "linux64")
        monkeypatch.setattr(binaries, "managed_dir", lambda: tmp_path / "ger")
        monkeypatch.setattr(binaries, "urlopen", lambda *a, **k: Resposta(conteudo))
        monkeypatch.setattr(binaries, "probe_version", lambda path: "ffmpeg version teste")
        monkeypatch.setitem(binaries._ARCHIVES, "linux64", ("arquivo.tar.xz", resumo))
        return binaries

    def test_resumo_divergente_nao_instala_nada(self, tmp_path, monkeypatch):
        conteudo = self._arquivo()
        binaries = self._preparar(tmp_path, monkeypatch, conteudo, "0" * 64)
        with pytest.raises(binaries.BinaryDownloadError):
            binaries.download_tools()
        assert list((tmp_path / "ger").iterdir()) == []

    def test_resumo_igual_instala(self, tmp_path, monkeypatch):
        import hashlib
        conteudo = self._arquivo()
        binaries = self._preparar(tmp_path, monkeypatch, conteudo, hashlib.sha256(conteudo).hexdigest())
        tools = binaries.download_tools()
        assert tools.ffmpeg.is_file() and tools.ffprobe.is_file()


@pytest.mark.network
def test_resumos_fixados_conferem_com_a_publicacao():
    """Os resumos do código são os que o GitHub publica para cada arquivo."""
    import json
    from urllib.request import Request, urlopen
    from videomanager.infrastructure.system import binaries
    tag = binaries._RELEASE_BASE.rstrip("/").rsplit("/", 1)[1]
    request = Request(f"https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/{tag}",
                      headers={"User-Agent": "VideoManager/validacao"})
    with urlopen(request, timeout=30) as response:
        publicados = {a["name"]: a.get("digest") for a in json.load(response)["assets"]}
    for nome, resumo in binaries._ARCHIVES.values():
        assert publicados[nome] == f"sha256:{resumo}"
