"""Testes do contrato da prévia: taxa e tamanho fiéis ao material.

O caminho da prévia tem um acoplamento que não falha alto quando se rompe: o
fluxo de quadros é **gerado** numa taxa e **entregue** noutra, e se as duas se
separarem a reprodução sai em velocidade errada sem erro nenhum — foi assim que
o som já saiu ao dobro. Estes testes fixam as duas pontas.
"""

from __future__ import annotations

import io
import inspect
import threading
import time
from pathlib import Path

import pytest

from videomanager.application.capabilities import FFmpegTools
from videomanager.infrastructure.system.binaries import decode_threads
from videomanager.domain.preview import MAX_PREVIEW_FPS
from videomanager.infrastructure.ffmpeg.preview import FramePump
from videomanager.infrastructure.ffmpeg.preview import _one_pass_worth_it
from videomanager.infrastructure.ffmpeg.preview import _strip_command
from videomanager.domain.preview import filmstrip_times
from videomanager.domain.preview import fit_size
from videomanager.domain.preview import preview_fps
from videomanager.infrastructure.qt.workers.preview_worker import PlaybackWorker

TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")


class TestTaxaDaPrevia:
    @pytest.mark.parametrize("nativo", [24.0, 25.0, 29.97, 30.0, 50.0, 60.0])
    def test_segue_a_taxa_do_material(self, nativo: float) -> None:
        # Uma taxa fixa mais baixa deixa a imagem aos trancos num vídeo de 30 ou
        # 60 fps — foi o que se via com os 15 fps de antes.
        assert preview_fps(nativo) == nativo

    def test_teto_para_material_muito_rapido(self) -> None:
        assert preview_fps(240.0) == MAX_PREVIEW_FPS

    def test_sem_taxa_conhecida_usa_um_padrao_utilizavel(self) -> None:
        assert preview_fps(None) == 30
        assert preview_fps(0.0) == 30


class TestAcoplamentoDaTaxa:
    """A taxa não pode ter valor padrão em nenhuma das duas pontas.

    Um padrão faz o descuido passar calado: o comando é montado a 30 fps, o
    fluxo é entregue a 15, e a reprodução roda pela metade da velocidade sem
    levantar nada.
    """

    @pytest.mark.parametrize("alvo", [FramePump.__init__, PlaybackWorker.__init__])
    def test_fps_e_obrigatorio(self, alvo) -> None:
        parametro = inspect.signature(alvo).parameters["fps"]
        assert parametro.default is inspect.Parameter.empty
        assert parametro.kind is inspect.Parameter.KEYWORD_ONLY


class TestInicioDaReproducao:
    def test_cancelamento_durante_abertura_encerra_processo_sem_ler(self, monkeypatch):
        from types import SimpleNamespace
        terminated = []
        class Stream(io.BytesIO):
            def read(self, *args):
                pytest.fail('Cancelamento não pode aguardar o primeiro quadro')
        stream = Stream(b'abc')
        process = SimpleNamespace(stdout=stream, stderr=None, poll=lambda: None,
                                  terminate=lambda: terminated.append(True), wait=lambda **kw: 0)
        pump = FramePump(['ffmpeg'], 0, (1, 1), fps=30)
        def launch(*args, **kwargs):
            pump.stop()
            return process
        monkeypatch.setattr('videomanager.infrastructure.ffmpeg.preview.subprocess.Popen', launch)
        assert list(pump.frames()) == []
        assert terminated
        assert stream.closed

    def test_carregamento_nao_consume_o_relogio(self, monkeypatch) -> None:
        """Depois da pré-carga, os quadros continuam espaçados normalmente.

        Antes o relógio começava na abertura do processo. Segurar a prévia por
        alguns décimos fazia o segundo quadro sair colado ao primeiro para
        tentar recuperar o atraso, que era a engasgada vista após clicar play.
        """

        class Processo:
            def __init__(self) -> None:
                self.stdout = io.BytesIO(b"abc" + b"def")
                self.returncode = 0
                self.terminated = False

            def poll(self):
                return 0 if self.terminated else None

            def terminate(self) -> None:
                self.terminated = True

            def kill(self) -> None:
                self.terminated = True

            def wait(self, timeout=None):
                self.terminated = True
                return 0

        monkeypatch.setattr(
            "videomanager.infrastructure.ffmpeg.preview.subprocess.Popen",
            lambda *args, **kwargs: Processo(),
        )
        gate = threading.Event()
        primed = threading.Event()
        moments: list[float] = []
        pump = FramePump(["ffmpeg"], 2.0, (1, 1), fps=20)

        def consume() -> None:
            frames = pump.frames(gate=gate, on_primed=primed.set)
            for _ in range(2):
                next(frames)
                moments.append(time.monotonic())
            frames.close()

        thread = threading.Thread(target=consume)
        thread.start()
        assert primed.wait(0.5)
        time.sleep(0.12)  # maior que dois passos de 20 fps
        assert not moments, "nenhum quadro deve escapar antes do play"
        released = time.monotonic()
        gate.set()
        thread.join(1.0)

        assert not thread.is_alive()
        assert moments[0] - released < 0.03
        assert moments[1] - moments[0] >= 0.035

    def test_worker_pode_ser_preparado_sem_iniciar(self) -> None:
        worker = PlaybackWorker(
            ["ffmpeg"], 0.0, (2, 2), 1, fps=30, autostart=False
        )
        assert not worker._gate.is_set()
        worker.start_playback()
        assert worker._gate.is_set()

    def test_ui_ocupada_retem_so_quadro_mais_recente(self, desktop_app, monkeypatch):
        from PySide6.QtCore import Qt
        from videomanager.domain.preview import RawFrame
        worker = PlaybackWorker(['ffmpeg'], 0, (1, 1), 17, fps=30)
        monkeypatch.setattr(worker._pump, 'frames', lambda **kw: (
            RawFrame(bytes([index % 256]) * 3, 1, 1, index / 30) for index in range(300)))
        notifications = []
        worker.signals.frame.connect(lambda token, inbox: notifications.append((token, inbox)),
                                     Qt.ConnectionType.QueuedConnection)
        worker.run()
        assert not notifications
        desktop_app.processEvents()
        assert len(notifications) == 1
        token, inbox = notifications[0]
        assert token == 17
        assert inbox.take().seconds == pytest.approx(299 / 30)
        assert inbox.take() is None
        assert inbox.publish(RawFrame(b'abc', 1, 1, 10))


class TestTamanho:
    def test_cabe_na_area_preservando_a_proporcao(self) -> None:
        assert fit_size(1920, 1080, 1920, 1080) == (1920, 1080)
        assert fit_size(1920, 1080, 960, 1080) == (960, 540)
        # Vertical de celular numa área larga: limita pela altura.
        assert fit_size(1080, 1920, 1920, 540) == (302, 540)

    def test_dimensoes_sempre_pares(self) -> None:
        # Escaladores e codificadores trabalham em blocos de dois pixels.
        largura, altura = fit_size(1919, 1079, 777, 777)
        assert largura % 2 == 0 and altura % 2 == 0


class TestTiraDeMiniaturas:
    """Uma tira é uma chamada ao ffmpeg, não doze.

    Cada miniatura custava um processo, uma abertura de arquivo e a montagem de
    um decodificador para devolver um quadro. Medido: 1,32 s contra 0,21 s a
    1080p e 3,08 s contra 0,29 s a 4K.

    O passe único decodifica o trecho **inteiro**, então a escolha entre os dois
    caminhos é o que impede a otimização de virar regressão numa tira sobre um
    vídeo de horas.
    """

    def tempos(self, inicio: float, fim: float, quantas: int) -> tuple[float, ...]:
        return filmstrip_times(inicio, fim, quantas)

    def test_trecho_curto_sai_num_passe_so(self) -> None:
        assert _one_pass_worth_it(self.tempos(0.0, 12.0, 12))

    def test_trecho_longo_continua_buscando_cada_uma(self) -> None:
        # Duas horas visíveis: decodificar reto até a última miniatura custaria
        # as duas horas, contra doze saltos de um décimo de segundo.
        assert not _one_pass_worth_it(self.tempos(0.0, 7200.0, 12))

    def test_uma_miniatura_so_nao_tem_passo(self) -> None:
        # É o caso da imagem parada, que não tem trecho a percorrer.
        assert not _one_pass_worth_it(self.tempos(3.0, 3.0, 1))

    def test_a_busca_cai_na_primeira_miniatura(self) -> None:
        tempos = self.tempos(10.0, 22.0, 12)
        comando = _strip_command(Path("/m/v.mp4"), tempos, (160, 90), TOOLS)
        assert comando[comando.index("-ss") + 1] == f"{tempos[0]:.6f}"

    def test_a_taxa_pedida_e_o_inverso_do_passo(self) -> None:
        # É o que faz os quadros do filtro (0, passo, 2×passo…) caírem
        # exatamente nos instantes de filmstrip_times, sem escolher nada.
        tempos = self.tempos(0.0, 24.0, 12)
        passo = tempos[1] - tempos[0]
        comando = _strip_command(Path("/m/v.mp4"), tempos, (160, 90), TOOLS)
        filtro = comando[comando.index("-filter_complex") + 1]
        assert filtro.startswith(f"[0:v]fps={1.0 / passo:.9f}")

    def test_arredonda_para_cima_como_o_ss_faz(self) -> None:
        # O padrão do filtro é "near", e com ele a tira inteira saía meio passo
        # adiantada em relação a uma busca direta — completa, em ordem e no
        # instante errado. "up" é a mesma regra do -ss: o primeiro quadro com
        # pts maior ou igual ao pedido.
        comando = _strip_command(
            Path("/m/v.mp4"), self.tempos(0.0, 12.0, 12), (160, 90), TOOLS
        )
        assert "round=up" in comando[comando.index("-filter_complex") + 1]

    def test_escala_depois_de_escolher_os_quadros(self) -> None:
        # Escalar antes seria escalar todo quadro decodificado para jogar fora a
        # esmagadora maioria deles.
        comando = _strip_command(
            Path("/m/v.mp4"), self.tempos(0.0, 12.0, 12), (160, 90), TOOLS
        )
        filtro = comando[comando.index("-filter_complex") + 1]
        assert filtro.index("fps=") < filtro.index("scale=160:90")

    def test_pede_exatamente_a_quantidade_de_miniaturas(self) -> None:
        comando = _strip_command(
            Path("/m/v.mp4"), self.tempos(0.0, 12.0, 12), (160, 90), TOOLS
        )
        assert comando[comando.index("-frames:v") + 1] == "12"

    def test_o_teto_de_threads_vem_antes_da_entrada(self) -> None:
        # Depois do ``-i`` o argumento valeria para o codificador da saída, que
        # aqui nem existe — e a decodificação ficaria no padrão em silêncio.
        comando = _strip_command(
            Path("/m/v.mp4"), self.tempos(0.0, 12.0, 12), (160, 90), TOOLS
        )
        assert comando.index("-threads") < comando.index("-i")
        assert comando[comando.index("-threads") + 1] == str(decode_threads())


# Estes cenários exercitam adaptadores ou apresentação Qt.
pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")
