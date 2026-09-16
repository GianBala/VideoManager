"""Testes do ciclo de vida dos workers — o que precisa parar quando se fecha.

Nada aqui instancia ``QApplication``: um ``QRunnable`` e o ``QObject`` de sinais
existem sem janela, e o que se afirma é a mecânica de cancelamento, não o
desenho.

**O defeito que estes testes impedem de voltar:** o destrutor do
``QThreadPool`` chama ``waitForDone()`` sem prazo. Enquanto a onda (120 s) e os
keyframes (180 s) não sabiam ser interrompidos, fechar a aba de edição logo
depois de importar um arquivo longo deixava o processo pendurado até o prazo
acabar — com a janela já fora da tela e nada explicando a espera.
"""

from __future__ import annotations

import pytest

from pathlib import Path

from videomanager.application.capabilities import FFmpegTools
from videomanager.infrastructure.qt.workers.engine_worker import is_packaged
from videomanager.infrastructure.qt.workers.preview_worker import FilmstripWorker
from videomanager.infrastructure.qt.workers.preview_worker import FrameWorker
from videomanager.infrastructure.qt.workers.preview_worker import KeyframeWorker
from videomanager.infrastructure.qt.workers.preview_worker import WaveformWorker
from videomanager.infrastructure.qt.workers.preview_worker import _Interruption
from videomanager.presentation.qt.tasks import WorkerRunner
from videomanager.infrastructure.qt.workers.thumbnail_worker import ThumbnailWorker

TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")


class ProcessoDeMentira:
    def __init__(self, vivo: bool = True) -> None:
        self._vivo = vivo
        self.terminado = False

    def poll(self) -> int | None:
        return None if self._vivo else 0

    def terminate(self) -> None:
        self.terminado = True
        self._vivo = False


class TestTravaDeInterrupcao:
    def test_cancelar_termina_o_processo_registrado(self) -> None:
        trava = _Interruption()
        processo = ProcessoDeMentira()
        trava.register(processo)

        trava.cancel()

        assert processo.terminado is True

    def test_cancelamento_entre_abrir_e_registrar_nao_se_perde(self) -> None:
        # A janela existe de verdade: o ffmpeg é aberto antes de ser registrado,
        # e um cancelamento nesse intervalo deixaria o processo rodando sozinho.
        trava = _Interruption()
        trava.cancel()

        processo = ProcessoDeMentira()
        trava.register(processo)

        assert processo.terminado is True

    def test_processo_ja_encerrado_nao_e_terminado_de_novo(self) -> None:
        trava = _Interruption()
        processo = ProcessoDeMentira(vivo=False)
        trava.register(processo)

        trava.cancel()

        assert processo.terminado is False


class TestWorkersSabemParar:
    """Todo worker de fundo da aba de edição precisa saber ser interrompido.

    A lista é literal de propósito: um worker novo que esqueça o ``cancel``
    volta a segurar o fechamento da janela, e o esquecimento não falha em
    lugar nenhum — o aplicativo só demora a sair.
    """

    def test_todos_expoem_cancel(self) -> None:
        workers = [
            FrameWorker(["ffmpeg"], (16, 16), 0.0, 1),
            FilmstripWorker(Path("/m/a.mp4"), 0.0, 1.0, 4, (16, 16), TOOLS, 1),
            WaveformWorker(Path("/m/a.mp4"), 0.0, 1.0, (16, 16), "#ffffff", TOOLS, 1),
            KeyframeWorker(Path("/m/a.mp4"), TOOLS),
        ]
        for worker in workers:
            assert callable(getattr(worker, "cancel", None)), type(worker).__name__


class TestRunnerCancelaTodos:
    def test_cancela_quem_sabe_e_ignora_quem_nao_sabe(self) -> None:
        class SabeParar:
            def __init__(self) -> None:
                self.cancelado = False

            def cancel(self) -> None:
                self.cancelado = True

        class NaoSabe:
            pass

        runner = WorkerRunner()
        sabe, nao_sabe = SabeParar(), NaoSabe()
        runner._alive.update({sabe, nao_sabe})

        runner.cancel_all()  # não pode levantar por causa do que não sabe parar

        assert sabe.cancelado is True


class TestAtualizacaoDaEngine:
    def test_fora_do_pacote_a_atualizacao_e_oferecida(self) -> None:
        # A suíte roda do código-fonte, onde ``sys.executable`` é o Python de
        # verdade e o pip existe.
        assert is_packaged() is False

    def test_no_pacote_ela_e_recusada(self, monkeypatch) -> None:
        # Num pacote, ``sys.executable`` é o próprio Video Manager: o comando
        # viraria "VideoManager -m pip install …", cujos argumentos o bootloader
        # repassa como sys.argv — e o que acontece é uma **segunda janela** do
        # aplicativo, enquanto a primeira espera dez minutos de prazo.
        monkeypatch.setattr("videomanager.infrastructure.qt.workers.engine_worker.sys.frozen", True, raising=False)
        assert is_packaged() is True


class TestCapaDaMidia:
    """A URL da capa vem dos metadados do site, ou seja, de fora."""

    def test_esquemas_locais_sao_recusados(self) -> None:
        # ``urlopen`` atende file:, ftp: e data: além de http(s). Sem a lista,
        # uma capa apontando para "file:///proc/self/environ" faria o aplicativo
        # ler disco a mando de quem publicou a mídia.
        recebido: list[bytes] = []
        for endereco in (
            "file:///etc/passwd",
            "ftp://exemplo/capa.jpg",
            "data:image/png;base64,AAAA",
        ):
            worker = ThumbnailWorker(endereco)
            worker.signals.loaded.connect(recebido.append)
            worker.run()

        assert recebido == []

    def test_https_continua_valendo(self, monkeypatch) -> None:
        # A recusa é pelo esquema, e não por desconfiar de tudo: a capa comum
        # tem de continuar carregando.
        class Resposta:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, _limite):
                return b"PNG"

        monkeypatch.setattr(
            "videomanager.infrastructure.qt.workers.thumbnail_worker.urlopen", lambda *a, **k: Resposta()
        )
        recebido: list[bytes] = []
        worker = ThumbnailWorker("https://exemplo/capa.jpg")
        worker.signals.loaded.connect(recebido.append)
        worker.run()

        assert recebido == [b"PNG"]


# Estes cenários exercitam adaptadores ou apresentação Qt.
pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")


@pytest.mark.usefixtures('desktop_app')
def test_falha_de_frame_tem_diagnostico_e_cancelamento_nao_e_erro(monkeypatch):
    from videomanager.application.errors import VideoManagerError
    def fail(*args, **kwargs):
        raise VideoManagerError('Não foi possível ler uma mídia da prévia.')
    monkeypatch.setattr('videomanager.infrastructure.qt.workers.preview_worker.frame_from_command', fail)
    worker = FrameWorker(['ffmpeg'], (2, 2), 0, 42)
    failures, done, cancelled = [], [], []
    worker.signals.failed.connect(lambda token, msg: failures.append((token, msg)))
    worker.signals.done.connect(lambda: done.append(True))
    worker.signals.cancelled.connect(cancelled.append)
    worker.run()
    assert failures == [(42, 'Não foi possível ler uma mídia da prévia.')]
    assert len(done) == 1
    worker.cancel()
    worker.run()
    assert len(failures) == 1
    assert cancelled == [42]
    assert len(done) == 2


def test_worker_concluido_libera_processo_e_buffers(monkeypatch):
    from types import SimpleNamespace
    from videomanager.domain.preview import RawFrame
    process = SimpleNamespace(stdout=b'buffer retido', poll=lambda: 0)
    def render(*args, register, **kwargs):
        register(process)
        return RawFrame(bytes(12), 2, 2)
    monkeypatch.setattr('videomanager.infrastructure.qt.workers.preview_worker.frame_from_command', render)
    worker = FrameWorker(['ffmpeg'], (2, 2), 0, 1)
    worker.run()
    assert worker._guard._process is None
