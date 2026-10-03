"""Caracterização do ``Downloader`` com um ``YoutubeDL`` falso, sem rede.

O yt-dlp é atualizado em campo (``pip``, ou outro pacote), e o que o
``Downloader`` usa dele é interno: os ganchos de progresso e de
pós-processamento, ``DownloadCancelled``, o cancelamento que chega embrulhado em
``DownloadError`` e ``requested_downloads[0]['filepath']``. Antes, isso só
rodava nos testes de rede, fora da execução padrão e da CI.
"""

from __future__ import annotations


import pytest
from yt_dlp.utils import DownloadCancelled, DownloadError

from videomanager.application.errors import DownloadFailedError, JobCancelled
from videomanager.infrastructure.yt_dlp import downloader as modulo


class _YoutubeDL:
    """Dublê: chama os ganchos que recebeu e devolve um info como o do yt-dlp."""

    roteiro = None

    def __init__(self, params):
        self.params = params

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def add_post_processor(self, pp, when=None):
        pass

    def extract_info(self, url, download=True):
        return type(self).roteiro(self)

    def gancho(self, **dados):
        for hook in self.params["progress_hooks"]:
            hook(dados)

    def pos(self, **dados):
        for hook in self.params["postprocessor_hooks"]:
            hook(dados)


@pytest.fixture
def ydl(monkeypatch):
    monkeypatch.setattr(modulo.yt_dlp, "YoutubeDL", _YoutubeDL)
    return _YoutubeDL


def test_progresso_e_caminho_final_depois_do_pos_processamento(ydl, tmp_path):
    def roteiro(self):
        self.gancho(status="downloading", downloaded_bytes=50, total_bytes=200, speed=10.0, eta=15)
        self.gancho(status="finished")
        self.pos(status="started", postprocessor="FFmpegMerger")
        # O filepath reflete a extensão final, não a do stream baixado.
        return {"title": "Vídeo", "requested_downloads": [{"filepath": str(tmp_path / "Vídeo [x].mkv")}]}

    ydl.roteiro = roteiro
    progresso = []
    resultado = modulo.Downloader({}, on_progress=progresso.append).run("https://x/v")
    assert resultado.path == tmp_path / "Vídeo [x].mkv"
    assert resultado.title == "Vídeo"
    assert progresso[0].percent == pytest.approx(25.0)
    assert progresso[0].eta == 15
    assert progresso[-1].indeterminate


def test_hls_sem_tamanho_usa_a_contagem_de_fragmentos(ydl):
    def roteiro(self):
        self.gancho(status="downloading", downloaded_bytes=10, fragment_index=3, fragment_count=12)
        return {"title": "t"}

    ydl.roteiro = roteiro
    progresso = []
    modulo.Downloader({}, on_progress=progresso.append).run("https://x/v")
    assert progresso[0].percent == pytest.approx(25.0)


def test_cancelar_no_meio_do_download_vira_tarefa_cancelada(ydl):
    baixador = modulo.Downloader({})

    def roteiro(self):
        baixador.cancel()
        self.gancho(status="downloading", downloaded_bytes=1, total_bytes=2)  # o gancho levanta
        raise AssertionError("o gancho deveria ter interrompido")

    ydl.roteiro = roteiro
    with pytest.raises(JobCancelled):
        baixador.run("https://x/v")


def test_cancelar_no_pos_processamento_chega_embrulhado_e_vira_cancelada(ydl):
    baixador = modulo.Downloader({})

    def roteiro(self):
        baixador.cancel()
        try:
            self.pos(status="started", postprocessor="FFmpegMerger")
        except DownloadCancelled as exc:
            raise DownloadError("ERROR: Postprocessing: cancelado") from exc

    ydl.roteiro = roteiro
    with pytest.raises(JobCancelled):
        baixador.run("https://x/v")


def test_erro_do_yt_dlp_sem_cancelamento_vira_falha_traduzida(ydl):
    def roteiro(self):
        raise DownloadError("ERROR: [generic] Unable to download webpage: HTTP Error 404: Not Found")

    ydl.roteiro = roteiro
    with pytest.raises(DownloadFailedError):
        modulo.Downloader({}).run("https://x/v")


def test_o_yt_dlp_ainda_abre_processos_pela_classe_popen():
    # O cancelamento do pós-processamento depende disto: se o yt-dlp mudar a
    # forma de abrir o ffmpeg, cancelar volta a não alcançá-lo.
    import inspect
    import yt_dlp.postprocessor.ffmpeg as pos
    import yt_dlp.utils as utilidades
    assert pos.Popen is utilidades.Popen
    assert inspect.ismethod(utilidades.Popen.run)  # classmethod: instancia ``cls``
    assert utilidades.Popen.__init__ is modulo._registering_init


def test_cancelar_termina_o_processo_do_pos_processamento(ydl):
    # Antes: cancelar durante "Juntando" só valia quando o ffmpeg acabasse
    # sozinho, e fechar a janela deixava o processo vivo.
    import sys
    import threading
    import time
    from yt_dlp.utils import Popen

    baixador = modulo.Downloader({})
    duracao = []

    def roteiro(self):
        inicio = time.monotonic()
        _, _, codigo = Popen.run([sys.executable, "-c", "import time; time.sleep(20)"])
        duracao.append(time.monotonic() - inicio)
        raise DownloadError(f"ERROR: Postprocessing: ffmpeg saiu com {codigo}")

    ydl.roteiro = roteiro
    threading.Timer(0.5, baixador.cancel).start()
    with pytest.raises(JobCancelled):
        baixador.run("https://x/v")
    assert duracao[0] < 5
