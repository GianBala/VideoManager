"""A recodificação do download espera a vez: no máximo uma por vez no processo (``downloader._RECODE_SLOT``).

O download roda na fila de rede (3 vagas por padrão), mas o encode de duas passadas usa todos os núcleos e pede de 1,2 GB
(1080p60) a 4 GB (4K): três juntos somavam ~12 GB, fora do limite de uma tarefa pesada por vez que a fila local aplica à
conversão. O que isto pode errar sem exceção: duas recodificações simultâneas, a vaga que não volta depois de uma falha ou
de um cancelamento (a recodificação seguinte espera para sempre), e o cancelamento que não alcança quem espera.

Sem ffmpeg: o ``probe_video`` e o comando são trocados, e ``_run_recode`` só conta quantas rodam ao mesmo tempo.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from videomanager.application.errors import JobCancelled
from videomanager.domain.i18n import Text
from videomanager.infrastructure.ffmpeg import recode
from videomanager.infrastructure.ffmpeg.recode import SourceVideo
from videomanager.infrastructure.yt_dlp import downloader
from videomanager.infrastructure.yt_dlp.downloader import Downloader, RecodePlan


@pytest.fixture(autouse=True)
def sem_ffmpeg(monkeypatch):
    monkeypatch.setattr(recode, "probe_video", lambda path, tools, **kw: SourceVideo("h264", "mp4", 4000.0, 10.0))
    monkeypatch.setattr(recode, "build_args", lambda source, destination, *a, **k: [[str(destination)]])


def _baixador(tmp_path: Path, nome: str, progresso=None) -> Downloader:
    arquivo = tmp_path / f"{nome}.mp4"
    arquivo.write_bytes(b"fonte")
    baixador = Downloader({}, on_progress=progresso, recode_plan=RecodePlan(kbps=800, tools=object()))
    baixador._final_path = arquivo
    return baixador


def _recodificar(baixador: Downloader, prazo: float = 5.0) -> BaseException | None:
    """Roda ``_recode_video`` numa thread com prazo: uma vaga que não volta vira falha do teste, e não travamento."""
    erro: list[BaseException] = []

    def alvo():
        try:
            baixador._recode_video()
        except BaseException as exc:  # noqa: BLE001 - o teste confere qual
            erro.append(exc)

    fio = threading.Thread(target=alvo, daemon=True)
    fio.start()
    fio.join(prazo)
    assert not fio.is_alive(), "a recodificação ficou esperando uma vaga que não voltou"
    return erro[0] if erro else None


def _disputando(monkeypatch, durante=None):
    """``_run_recode`` que registra quantas recodificações correm juntas e grava o "arquivo recodificado"."""
    estado = {"agora": 0, "maximo": 0, "total": 0}
    trava = threading.Lock()

    def falso(self, args, duration, index=0, total=1):
        with trava:
            estado["agora"] += 1
            estado["total"] += 1
            estado["maximo"] = max(estado["maximo"], estado["agora"])
        try:
            if durante is not None:
                durante(self)
            else:
                time.sleep(0.15)
            Path(args[0]).write_bytes(b"recodificado")
        finally:
            with trava:
                estado["agora"] -= 1

    monkeypatch.setattr(Downloader, "_run_recode", falso)
    return estado


def test_tres_downloads_nao_recodificam_ao_mesmo_tempo(monkeypatch, tmp_path):
    estado = _disputando(monkeypatch)
    baixadores = [_baixador(tmp_path, f"v{i}") for i in range(3)]
    fios = [threading.Thread(target=b._recode_video, daemon=True) for b in baixadores]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join(10)
    assert not any(fio.is_alive() for fio in fios)
    assert estado["total"] == 3 and estado["maximo"] == 1, estado
    assert all(b._final_path.read_bytes() == b"recodificado" for b in baixadores)


def test_quem_espera_a_vez_avisa_e_o_cancelamento_o_alcanca(monkeypatch, tmp_path):
    from videomanager.application.events import Progress

    liberar, dentro = threading.Event(), threading.Event()

    def segura(self):
        dentro.set()
        liberar.wait(10)

    _disputando(monkeypatch, durante=segura)
    primeiro = _baixador(tmp_path, "primeiro")
    fio = threading.Thread(target=primeiro._recode_video, daemon=True)
    fio.start()
    assert dentro.wait(5)

    avisos: list[Progress] = []
    segundo = _baixador(tmp_path, "segundo", avisos.append)
    desfecho: dict = {}

    def esperar():
        try:
            segundo._recode_video()
            desfecho["fim"] = "recodificou"
        except JobCancelled:
            desfecho["fim"] = "cancelado"

    espera = threading.Thread(target=esperar, daemon=True)
    espera.start()
    prazo = time.monotonic() + 5
    while not avisos and time.monotonic() < prazo:
        time.sleep(0.02)
    assert [str(a.phase) for a in avisos] == [str(Text("PHASE_WAITING_RECODE"))] and avisos[0].indeterminate
    segundo.cancel()
    espera.join(5)
    assert not espera.is_alive() and desfecho == {"fim": "cancelado"}
    assert segundo._final_path.read_bytes() == b"fonte"  # nunca recodificou

    liberar.set()
    fio.join(10)
    assert primeiro._final_path.read_bytes() == b"recodificado"
    # E a vaga voltou: o cancelamento de quem esperava não a levou consigo.
    terceiro = _baixador(tmp_path, "terceiro")
    assert _recodificar(terceiro) is None
    assert terceiro._final_path.read_bytes() == b"recodificado"


def test_a_vaga_volta_quando_a_recodificacao_falha(monkeypatch, tmp_path):
    def quebra(self):
        raise RuntimeError("o ffmpeg caiu")

    _disputando(monkeypatch, durante=quebra)
    assert isinstance(_recodificar(_baixador(tmp_path, "a")), RuntimeError)
    assert downloader._RECODE_SLOT.acquire(timeout=1), "a vaga ficou presa depois da falha"
    downloader._RECODE_SLOT.release()


def test_cancelar_antes_de_a_vaga_chegar_a_devolve(monkeypatch, tmp_path):
    """A desistência pode chegar entre a vaga livre e a conferência: sem devolver, o próximo espera para sempre."""
    _disputando(monkeypatch)
    baixador = _baixador(tmp_path, "a")
    baixador._cancelled = True
    assert isinstance(_recodificar(baixador), JobCancelled)
    assert downloader._RECODE_SLOT.acquire(timeout=1), "o cancelamento levou a vaga consigo"
    downloader._RECODE_SLOT.release()
