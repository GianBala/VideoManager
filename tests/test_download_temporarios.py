"""Temporários de download: uma pasta por sessão e uma por tarefa.

**O defeito que estes testes impedem de voltar:** a pasta temporária era uma
só para todas as tarefas, e o yt-dlp retoma o ``.part`` que encontra com o nome
esperado. O resto de uma tarefa cancelada (formato A) era continuado por outra
de mesmo título e id (formato B): o arquivo saía com o tamanho de B, conteúdo
misturado — medido, 749 erros de decodificação — e a tarefa "Concluída". Um
clique duplo em "Adicionar à fila" fazia o mesmo com duas tarefas ao mesmo
tempo. E os ``.part`` de quem cancelava nunca eram apagados.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from videomanager.application.errors import DownloadFailedError
from videomanager.application.errors import JobCancelled
from videomanager.application.events import DownloadResult
from videomanager.infrastructure.qt import sessions
from videomanager.infrastructure.qt.workers import download_worker


@dataclass
class _Pedido:
    temporary: Path
    selection: object = None
    media: object = None
    destination: Path = Path("destino")
    preferences: object = None


@dataclass
class _Tarefa:
    job_id: int
    request: _Pedido
    url: str = "https://exemplo.invalido/v"


class _Downloader:
    """Dublê do Downloader: grava um .part na pasta que recebeu e termina como pedido."""

    desfecho = "ok"

    def __init__(self, opts, on_progress=None):
        self.temp = Path(opts["paths"]["temp"])
        self.log = ()

    def cancel(self):
        pass

    def run(self, url):
        self.temp.mkdir(parents=True, exist_ok=True)
        (self.temp / "video [id].mp4.part").write_bytes(b"x" * 10)
        if self.desfecho == "cancelado":
            raise JobCancelled("cancelado")
        if self.desfecho == "falha":
            raise DownloadFailedError("rede")
        return DownloadResult(path=None, title="t", log=())


@pytest.fixture
def worker(monkeypatch, tmp_path):
    monkeypatch.setattr(download_worker, "find_tools", lambda: object())
    monkeypatch.setattr(download_worker, "build_opts",
                        lambda sel, media, prefs, tools, dest, temp: ({"paths": {"temp": str(temp)}}, None))
    monkeypatch.setattr(download_worker, "Downloader", _Downloader)

    def criar(job_id, desfecho="ok"):
        _Downloader.desfecho = desfecho
        return download_worker.DownloadWorker(_Tarefa(job_id, _Pedido(tmp_path / "sessao")))
    return criar


def test_cada_tarefa_tem_a_propria_pasta(worker):
    a, b = worker(1), worker(2)
    assert a._downloader.temp != b._downloader.temp
    assert a._downloader.temp.parent == b._downloader.temp.parent


def test_cancelar_apaga_os_temporarios_da_tarefa(worker):
    w = worker(1, "cancelado")
    w.run()
    assert not w._downloader.temp.exists()


def test_falha_guarda_o_part_para_repetir_e_repetir_usa_a_mesma_pasta(worker):
    w = worker(1, "falha")
    w.run()
    assert (w._downloader.temp / "video [id].mp4.part").is_file()
    assert worker(1)._downloader.temp == w._downloader.temp


def test_concluir_apaga_os_temporarios_da_tarefa(worker):
    w = worker(1, "ok")
    w.run()
    assert not w._downloader.temp.exists()


def _travar_em_outro_processo(pasta: Path, viver: bool):
    codigo = (
        "import sys,time,os\n"
        "from PySide6.QtCore import QLockFile\n"
        f"l=QLockFile({str(pasta / '.trava')!r}); l.setStaleLockTime(0); print(l.tryLock(0), flush=True)\n"
        + ("time.sleep(30)\n" if viver else "os._exit(0)\n")
    )
    proc = subprocess.Popen([sys.executable, "-c", codigo], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "True"
    return proc


def test_varredura_apaga_so_sessoes_de_processos_mortos(tmp_path):
    morta, viva = tmp_path / "sessao-1-a", tmp_path / "sessao-2-b"
    for pasta in (morta, viva):
        pasta.mkdir()
        (pasta / "tarefa-1").mkdir()
    _travar_em_outro_processo(morta, viver=False).wait()
    processo = _travar_em_outro_processo(viva, viver=True)
    try:
        sessions.sweep(tmp_path)
        assert not morta.exists()
        assert viva.exists()
    finally:
        processo.kill()
        processo.wait()


def test_varredura_apaga_restos_antigos_da_raiz_e_poupa_os_recentes(tmp_path):
    import os
    import time
    antigo, recente = tmp_path / "antigo.mp4.part", tmp_path / "recente.mp4.part"
    antigo.write_bytes(b"x")
    recente.write_bytes(b"x")
    dois_dias = time.time() - 2 * 24 * 3600
    os.utime(antigo, (dois_dias, dois_dias))
    sessions.sweep(tmp_path)
    assert not antigo.exists()
    assert recente.exists()


def test_limpar_encerradas_apaga_o_part_guardado_para_repetir(desktop_app, worker, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from videomanager.application.jobs.models import Job, JobStatus
    from videomanager.application.jobs.requests import DownloadRequest
    from videomanager.infrastructure.qt.workers import queue as fila
    pedido = DownloadRequest(None, None, tmp_path / "destino", tmp_path / "sessao", None)
    job = Job("https://x/v", "v", "", request=pedido)
    q = fila.JobQueue(SimpleNamespace(max_concurrent_jobs=1))
    q.service.add(job)
    job.status = JobStatus.FAILED
    pasta = download_worker.task_dir(job)
    pasta.mkdir(parents=True)
    (pasta / "video.mp4.part").write_bytes(b"x")
    q.remove_finished()
    assert not pasta.exists()
    q.shutdown()


def test_sessao_nasce_no_primeiro_uso_e_fechar_apaga(tmp_path):
    sessao = sessions.Session(tmp_path / "temp")
    assert not (tmp_path / "temp").exists()
    pasta = sessao.path
    assert pasta.is_dir() and pasta.parent == tmp_path / "temp"
    assert sessao.path == pasta
    sessao.close()
    assert not pasta.exists()


class _YtDlpNoDestino:
    """Dublê com a semântica do yt-dlp no destino final (``paths.home``).

    Vídeo: se o arquivo final já existe, devolve-o sem baixar ("has already
    been downloaded"). Áudio extraído: o ``MoveFiles`` substitui o que houver.
    """

    modo = "video"

    def __init__(self, opts, on_progress=None):
        self.home = Path(opts["paths"]["home"])
        self.log = ()

    def cancel(self):
        pass

    def run(self, url):
        final = self.home / "video [id].mp4"
        if self.modo == "video" and final.exists():
            return DownloadResult(path=final, title="t", log=())
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"NOVO")
        return DownloadResult(path=final, title="t", log=())


@pytest.mark.parametrize("modo", ["video", "audio"])
def test_nome_ja_existente_no_destino_vira_um_arquivo_novo(modo, monkeypatch, tmp_path):
    # Antes: o vídeo "baixado" era o arquivo antigo, entregue como resultado
    # sem aviso; o áudio extraído apagava o arquivo antigo de mesmo nome.
    destino = tmp_path / "destino"
    destino.mkdir()
    antigo = destino / "video [id].mp4"
    antigo.write_bytes(b"ARQUIVO ANTERIOR")
    monkeypatch.setattr(download_worker, "find_tools", lambda: object())
    monkeypatch.setattr(download_worker, "build_opts",
                        lambda sel, media, prefs, tools, dest, temp: ({"paths": {"home": str(dest), "temp": str(temp)}}, None))
    monkeypatch.setattr(_YtDlpNoDestino, "modo", modo)
    monkeypatch.setattr(download_worker, "Downloader", _YtDlpNoDestino)
    w = download_worker.DownloadWorker(_Tarefa(1, _Pedido(tmp_path / "sessao", destination=destino)))
    resultados = []
    w.signals.finished.connect(lambda job_id, resultado: resultados.append(resultado))
    w.run()
    assert antigo.read_bytes() == b"ARQUIVO ANTERIOR"
    assert resultados[0].path == destino / "video [id] (2).mp4"
    assert resultados[0].path.read_bytes() == b"NOVO"
    assert not download_worker.task_dir(w._job).exists()


def test_publicar_entre_volumes_copia_antes_de_trocar(tmp_path):
    # O cache do usuário e a pasta de downloads podem estar em volumes
    # diferentes; a troca atômica só existe dentro de um volume.
    import os
    import tempfile
    from videomanager.infrastructure.yt_dlp.downloader import publish
    outro = Path("/dev/shm")
    if not outro.is_dir() or os.stat(outro).st_dev == os.stat(tmp_path).st_dev:
        pytest.skip("sem um segundo volume gravável")
    with tempfile.TemporaryDirectory(dir=outro) as pasta:
        staging = Path(pasta) / "pronto"
        (staging / "Site").mkdir(parents=True)
        pronto = staging / "Site" / "video [id].mp4"
        pronto.write_bytes(b"NOVO")
        final = publish(pronto, staging, tmp_path)
    assert final == tmp_path / "Site" / "video [id].mp4"
    assert final.read_bytes() == b"NOVO"
    assert [p.name for p in final.parent.iterdir()] == ["video [id].mp4"]


def test_sessao_morta_tem_reserva_e_temporarios_desfeitos_e_arquivo_do_usuario_poupado(tmp_path, monkeypatch):
    # Uma queda no meio de uma exportação deixava na pasta do usuário a
    # reserva de 0 byte com o nome do resultado (a seguinte virava "nome (2)")
    # e o render parcial, e nada os apagava.
    from videomanager.infrastructure.storage import outputs
    from types import SimpleNamespace

    raiz, saida = tmp_path / "temp", tmp_path / "Videos"
    saida.mkdir()
    morta = sessions.Session(raiz)
    monkeypatch.setattr(outputs, "_journal", None)
    monkeypatch.setattr(outputs, "_token", "")
    morta.start()
    alvo = SimpleNamespace(extension="mp4")
    reserva = outputs.FileOutputStore().reserve(Path("a.mov"), alvo, saida)
    publicada = outputs.FileOutputStore().reserve(Path("b.mov"), alvo, saida)
    render = saida / f"{outputs.temp_prefix()}abc.mp4"
    render.write_bytes(b"meio arquivo")
    pasta_render = saida / f"{outputs.temp_prefix()}trechos"
    pasta_render.mkdir()
    pronto = saida / "pronto.mp4"
    pronto.write_bytes(b"conteudo")
    outputs.FileOutputStore().commit(pronto, publicada.path, lease=publicada)
    alheio = saida / ".videomanager-outra-sessao.mp4"
    alheio.write_bytes(b"de outra janela aberta")
    pasta_sessao = morta.path
    morta._lock.unlock()  # o processo "morreu" sem fechar a sessão

    sessions.Session(raiz).start()

    assert not reserva.path.exists()
    assert not render.exists() and not pasta_render.exists()
    assert publicada.path.read_bytes() == b"conteudo"
    assert alheio.exists()
    assert not pasta_sessao.exists()
