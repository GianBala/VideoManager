"""Caracterização da fila de tarefas (``JobQueue``) sem rede nem ffmpeg.

A fila é quem garante a regra RN-07: processamento local tem **uma** vaga, e
o plano de memória da interpolação se apoia nisso ("a memória medida no plano
ainda está lá na execução"); downloads têm as vagas da preferência. Nada disso
tinha teste: um erro de roteamento passaria pela suíte verde.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRunnable

from videomanager.application.jobs.models import Job, JobKind, JobStatus
from videomanager.application.jobs.requests import ConversionRequest
from videomanager.infrastructure.qt.workers import queue as fila
from videomanager.infrastructure.qt.workers.signals import ConvertSignals, emit_safely


class _Trabalho(QRunnable):
    """Dublê de worker: espera ser liberado e registra quantos rodam juntos."""

    def __init__(self, registro, job):
        super().__init__()
        self.job, self.registro = job, registro
        self.signals = ConvertSignals()
        self.liberar = threading.Event()
        self.cancelado = False
        # Guarda só o evento: como os workers de verdade, o dublê é apagado
        # pela pool ao terminar, e o objeto Python deixa de valer.
        registro["criados"].append(self.liberar)
        registro["cancelar"].append(self.cancel)

    def cancel(self):
        self.cancelado = True
        self.liberar.set()

    def run(self):
        local = self.job.kind.runs_ffmpeg_locally
        self.registro["iniciados"].append(self.job.job_id)
        with self.registro["trava"]:
            self.registro["ativos"][local] += 1
            self.registro["pico"][local] = max(self.registro["pico"][local], self.registro["ativos"][local])
        self.liberar.wait(5)
        with self.registro["trava"]:
            self.registro["ativos"][local] -= 1
        if self.cancelado:
            emit_safely(self.signals.cancelled, self.job.job_id)
        else:
            emit_safely(self.signals.finished, self.job.job_id, None)


@pytest.fixture
def registro(monkeypatch):
    dados = {"criados": [], "cancelar": [], "iniciados": [], "trava": threading.Lock(), "ativos": {True: 0, False: 0}, "pico": {True: 0, False: 0}}
    monkeypatch.setattr(fila, "ConvertWorker", lambda job: _Trabalho(dados, job))
    monkeypatch.setattr(fila, "DownloadWorker", lambda job: _Trabalho(dados, job))
    return dados


@pytest.fixture
def queue(desktop_app, registro):
    # Depende de ``registro`` para ser desmontada antes dele: a fila só termina
    # de esperar as pools quando todo dublê foi liberado.
    q = fila.JobQueue(SimpleNamespace(max_concurrent_jobs=3))
    yield q
    _liberar_todos(registro)
    _desmontar(desktop_app, q)


def _desmontar(app, q):
    """Encerra a fila e a apaga agora, e não quando o coletor de lixo quiser.

    Os receptores das tentativas saem por ``deleteLater``, que fora do
    ``exec()`` não é entregue sozinho; deixada para o coletor, a fila de um
    teste era destruída no meio do seguinte e derrubava o processo.
    """
    import gc
    from PySide6.QtCore import QEvent
    q.shutdown(timeout_ms=4000)
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    q.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def _liberar_todos(registro):
    for liberar in registro["criados"]:
        liberar.set()


def test_processamento_local_roda_um_por_vez(queue, registro, wait_until):
    jobs = [queue.submit(Job("a.mp4", "a", "", kind=JobKind.CONVERT)) for _ in range(3)]
    wait_until(lambda: registro["ativos"][True] == 1)
    _liberar_todos(registro)
    wait_until(lambda: all(job.status is JobStatus.DONE for job in jobs))
    _liberar_todos(registro)
    assert registro["pico"][True] == 1


def test_downloads_usam_as_vagas_da_preferencia_sem_esperar_o_local(queue, registro, wait_until):
    local = queue.submit(Job("a.mp4", "a", "", kind=JobKind.EXPORT))
    downloads = [queue.submit(Job(f"https://x/{i}", "v", "")) for i in range(3)]
    wait_until(lambda: registro["ativos"][False] == 3 and registro["ativos"][True] == 1)
    _liberar_todos(registro)
    wait_until(lambda: all(job.status is JobStatus.DONE for job in [local, *downloads]))


def test_falha_ao_montar_o_worker_devolve_a_reserva(desktop_app, monkeypatch):
    devolvidas = []

    class Saidas:
        def abort(self, path, lease=None):
            devolvidas.append((path, lease))

    def quebrar(job):
        raise RuntimeError("sem ffmpeg")

    monkeypatch.setattr(fila, "ConvertWorker", quebrar)
    monkeypatch.setattr(fila, "FileOutputStore", Saidas)
    q = fila.JobQueue(SimpleNamespace(max_concurrent_jobs=1))
    pedido = ConversionRequest(media=None, target="alvo", destination=Path("/saida/x.mp4"), lease="reserva")
    job = q.submit(Job("a.mp4", "a", "", kind=JobKind.CONVERT, request=pedido))
    assert job.status is JobStatus.FAILED
    assert devolvidas == [(Path("/saida/x.mp4"), "reserva")]
    _desmontar(desktop_app, q)


def test_repetir_conversao_reserva_um_nome_novo(queue, registro, monkeypatch, wait_until):
    reservas = []

    class Saidas:
        def reserve(self, source, target, folder, custom_stem=None):
            reservas.append((source, folder, custom_stem))
            return SimpleNamespace(path=folder / f"{custom_stem} (2).mp4")

    monkeypatch.setattr(fila, "FileOutputStore", Saidas)
    pedido = ConversionRequest(media=None, target="alvo", destination=Path("/saida/x.mp4"))
    job = queue.submit(Job("/origem/a.mov", "a", "", kind=JobKind.CONVERT, request=pedido))
    wait_until(lambda: registro["criados"])
    registro["cancelar"][0]()
    wait_until(lambda: job.status is JobStatus.CANCELLED)
    queue.retry(job.job_id)
    assert reservas == [(Path("/origem/a.mov"), Path("/saida"), "x")]
    assert job.request.destination == Path("/saida/x (2).mp4")
    assert job.request.lease.path == job.request.destination
    _liberar_todos(registro)
    wait_until(lambda: job.status is JobStatus.DONE)


def test_cancelar_tarefa_que_espera_vaga_vale_na_hora(queue, registro, monkeypatch, wait_until):
    # Antes, cancelar só marcava o worker: atrás de uma exportação longa na
    # única vaga local, a tarefa seguia "Pendente" (medido: 2,84 s atrás de
    # uma de 3 s; numa exportação interpolada, minutos) e a reserva de 0 byte
    # ficava na pasta do usuário até lá.
    devolvidas = []

    class Saidas:
        def abort(self, path, lease=None):
            devolvidas.append((path, lease))

    monkeypatch.setattr(fila, "FileOutputStore", Saidas)
    primeira = queue.submit(Job("a.mp4", "a", "", kind=JobKind.EXPORT))
    wait_until(lambda: registro["ativos"][True] == 1)
    pedido = ConversionRequest(media=None, target="alvo", destination=Path("/saida/b.mp4"), lease="reserva")
    segunda = queue.submit(Job("b.mp4", "b", "", kind=JobKind.EXPORT, request=pedido))
    queue.cancel(segunda.job_id)
    assert segunda.status is JobStatus.CANCELLED
    assert devolvidas == [(Path("/saida/b.mp4"), "reserva")]
    _liberar_todos(registro)
    wait_until(lambda: primeira.status is JobStatus.DONE)
    assert segunda.job_id not in registro["iniciados"]
