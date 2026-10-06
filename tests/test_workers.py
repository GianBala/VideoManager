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


def test_quadro_parado_monta_o_comando_fora_da_interface(monkeypatch):
    """O comando do quadro parado é montado no worker, não na interface.

    No último quadro de um bloco ele lê o fim do arquivo com o ffprobe (ver
    ``lastframe``): montado na thread da interface, cada arquivo novo custava
    uma espera de processo com a janela parada.
    """
    import threading
    from PySide6.QtCore import QCoreApplication
    from videomanager.bootstrap import build_desktop_runtime
    from videomanager.domain.preview import RawFrame
    from videomanager.domain.project import new_project
    from videomanager.infrastructure.ffmpeg import composer

    montado_em = []

    def frame_command(*args, **kwargs):
        montado_em.append(threading.current_thread())
        return ['ffmpeg']

    monkeypatch.setattr(composer, 'frame_command', frame_command)
    monkeypatch.setattr('videomanager.infrastructure.qt.workers.preview_worker.frame_from_command',
                        lambda *args, register, **kwargs: RawFrame(bytes(12), 2, 2))
    worker = build_desktop_runtime(audio_enabled=False).frame_worker(new_project(), 0.0, (2, 2), TOOLS, 7)
    # Confere a thread, e não a lista inteira: um painel que outro teste deixou
    # vivo pode pedir quadros nas threads dele enquanto este roda.
    assert threading.current_thread() not in montado_em, "o comando foi montado na thread que pediu o quadro"

    quadros = []
    worker.signals.frame.connect(lambda token, frame: quadros.append(token))
    thread = threading.Thread(target=worker.run)
    thread.start()
    thread.join(10)
    QCoreApplication.processEvents()
    assert thread in montado_em
    assert threading.current_thread() not in montado_em
    assert quadros == [7]


def test_atualizacao_do_motor_instala_so_versao_estavel(monkeypatch):
    # Com --pre, o menu instalava build de desenvolvimento do yt-dlp em quem
    # roda do código-fonte; a versão estável é a que o projeto valida.
    import subprocess
    from videomanager.infrastructure.qt.workers import engine_worker
    comandos = []

    def executar(comando, **kwargs):
        comandos.append(comando)
        return subprocess.CompletedProcess(comando, 1, b"", b"sem rede")

    monkeypatch.setattr(engine_worker.subprocess, "run", executar)
    engine_worker.EngineUpdateWorker("2026.01.01").run()
    assert comandos and "yt-dlp" in comandos[0]
    assert "--pre" not in comandos[0]


def test_erro_inesperado_no_worker_deixa_a_pilha_no_log(monkeypatch, caplog):
    # Antes, o except genérico transformava a exceção em texto para a fila e
    # nada ia para o log: um defeito de código num .exe sem console não
    # deixava rastro nenhum para diagnosticar.
    import logging
    from videomanager.infrastructure.qt.workers import function_worker

    def quebrar():
        raise KeyError("chave_que_nao_existe")

    worker = function_worker.FunctionWorker(quebrar)
    with caplog.at_level(logging.ERROR):
        worker.run()
    registro = [r for r in caplog.records if r.exc_info]
    assert registro and registro[0].exc_info[0] is KeyError


def test_falha_esperada_do_dominio_nao_vira_pilha_no_log(caplog):
    # Projeto inválido, arquivo sem vídeo: é resposta, não defeito.
    import logging
    from videomanager.application.errors import ProjectError
    from videomanager.infrastructure.qt.workers import function_worker

    def recusar():
        raise ProjectError("projeto inválido")

    with caplog.at_level(logging.ERROR):
        function_worker.FunctionWorker(recusar).run()
    assert not [r for r in caplog.records if r.exc_info]


def test_tarefa_local_que_falha_oferece_os_detalhes_do_ffmpeg(monkeypatch):
    # A fila só mostra "Ver detalhes técnicos" quando o worker tem ``log``, e
    # só o worker de download tinha: a falha de conversão não deixava ver nada.
    from types import SimpleNamespace
    from videomanager.application.errors import ConversionError
    from videomanager.infrastructure.qt.workers import convert_worker

    class Conversor:
        def __init__(self, **kwargs):
            self.log = ()

        def run(self):
            self.log = ("[libx264 @ 0x1] width not divisible by 2 (3x3)", "Conversion failed!")
            raise ConversionError("falhou")

        def discard_reservation(self):
            pass

    monkeypatch.setattr(convert_worker, "find_tools", lambda: TOOLS)
    monkeypatch.setattr(convert_worker, "Converter", Conversor)
    pedido = SimpleNamespace(media=None, target=None, destination=Path("/x.mp4"), text_assets=(), lease=None, max_bytes=None)
    worker = convert_worker.ConvertWorker(SimpleNamespace(job_id=1, request=pedido))
    worker.run()
    assert "width not divisible" in worker.log[0]


def test_texto_vira_png_no_worker_do_quadro_e_nao_na_interface(monkeypatch):
    # Cada estado novo de um texto grande custava de 24 a 51 ms na thread da
    # interface, a cada tecla: o PNG era feito antes de criar o worker.
    import threading
    from videomanager.infrastructure.qt.runtime import DesktopRuntime
    from videomanager.infrastructure.ffmpeg import composer
    chamadas = []

    def ativos():
        chamadas.append(threading.current_thread() is threading.main_thread())
        return {}

    monkeypatch.setattr(composer, "frame_command", lambda *a, **k: ["ffmpeg"])
    monkeypatch.setattr(composer, "interaction_commands", lambda *a, **k: [])
    runtime = DesktopRuntime(audio_enabled=False)
    from videomanager.domain.project import new_project
    quadro = runtime.frame_worker(new_project(), 0.0, (64, 36), TOOLS, 1, text_assets=ativos)
    camadas = runtime.interaction_worker(object(), (64, 36), TOOLS, 2, text_assets=ativos)
    assert chamadas == []
    quadro._command()
    camadas._commands()
    assert len(chamadas) == 2  # só quando o comando do worker é montado
