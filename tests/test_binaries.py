"""Testes da resolução e da execução dos binários externos.

O que se guarda aqui é o **ambiente** entregue a cada processo filho. É um
defeito que não levanta exceção nenhuma: o ffmpeg abre, roda, termina com código
zero — e por dentro está usando outra biblioteca, com outros codecs. Por isso o
teste afirma o conteúdo do ambiente, e não que a chamada funcionou.
"""

from __future__ import annotations

import os

from videomanager.core.binaries import clean_env, subprocess_kwargs


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
