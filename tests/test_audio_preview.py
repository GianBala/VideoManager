"""Testes do abastecimento da placa de som na prévia.

O laço que despeja o PCM no ``QAudioSink`` é testado sem Qt nenhum: ele só
precisa de um objeto que diga quanto espaço tem e aceite bytes, então os testes
passam um dublê no lugar do sink. É o que permite guardar aqui um defeito que só
aparecia no ouvido.

**O defeito que estes testes impedem de voltar:** o ``write`` de um
``QAudioSink`` grava no máximo ``bytesFree()`` e **descarta o excedente em
silêncio**. Escrever sem conferir o retorno fazia a prévia perder quase metade
do som — e áudio perdido não soa como falha, soa como som acelerado, porque o
conteúdo corre à frente do relógio. Medido no defeito: 8,19 s de conteúdo
entregues em 4 s, som ao dobro da velocidade.
"""

from __future__ import annotations

import pytest

import queue
import subprocess
import threading

from videomanager.infrastructure.qt.audio import AudioPreview
from videomanager.infrastructure.qt.audio import _reap


class SinkDeMentira:
    """Aceita no máximo ``limite`` bytes por escrita, como o Qt faz."""

    def __init__(self, limite: int) -> None:
        self.limite = limite
        self.recebido = bytearray()

    def bytesFree(self) -> int:  # noqa: N802 - assinatura do Qt
        return self.limite

    def write(self, data: bytes) -> int:
        aceito = data[: self.limite]
        self.recebido += aceito
        self.limite -= len(aceito)
        return len(aceito)


class Painel:
    """O mínimo de que ``_pump`` precisa, sem instanciar Qt."""

    def __init__(self, sink: SinkDeMentira, pedacos: list[bytes | None]) -> None:
        self._sink = sink
        self._device = sink
        self._chunks: queue.Queue[bytes | None] = queue.Queue()
        for pedaco in pedacos:
            self._chunks.put(pedaco)
        self._pending: bytes | None = None
        self._written = 0
        self._next = None
        self.terminou = False

    def _finish(self) -> None:
        self.terminou = True

    def pump(self) -> None:
        AudioPreview._pump(self)  # type: ignore[arg-type]


def test_nada_e_descartado_quando_a_placa_aceita_menos() -> None:
    sink = SinkDeMentira(limite=1000)
    painel = Painel(sink, [b"a" * 800, b"b" * 800])
    painel.pump()

    assert len(sink.recebido) == 1000, "escreveu só o que cabia"
    assert painel._pending == b"b" * 600, "o resto ficou guardado, não perdido"


def test_a_sobra_sai_no_tique_seguinte() -> None:
    sink = SinkDeMentira(limite=1000)
    painel = Painel(sink, [b"a" * 800, b"b" * 800])
    painel.pump()
    sink.limite = 5000  # a placa esvaziou
    painel.pump()

    assert len(sink.recebido) == 1600, "todo o conteúdo chegou, na ordem"
    assert sink.recebido == b"a" * 800 + b"b" * 800
    assert painel._pending is None


def test_placa_cheia_nao_consome_a_fila() -> None:
    sink = SinkDeMentira(limite=0)
    painel = Painel(sink, [b"a" * 800])
    painel.pump()

    assert not sink.recebido
    assert painel._chunks.qsize() == 1, "o pedaço continua na fila para depois"


def test_fim_do_fluxo_so_e_anunciado_depois_de_esvaziar_a_sobra() -> None:
    # Anunciar o fim com áudio ainda por escrever cortaria a última palavra.
    sink = SinkDeMentira(limite=500)
    painel = Painel(sink, [b"a" * 800, None])
    painel.pump()
    assert not painel.terminou, "ainda há sobra para entregar"

    sink.limite = 5000
    painel.pump()
    assert painel.terminou
    assert len(sink.recebido) == 800


def test_fila_vazia_apenas_devolve() -> None:
    sink = SinkDeMentira(limite=5000)
    painel = Painel(sink, [])
    painel.pump()  # não pode levantar nem bloquear
    assert not sink.recebido


class Avisador:
    """O mínimo para exercitar a guarda de geração de ``_emit_stopped``."""

    def __init__(self) -> None:
        self._generation = 7
        self.parou = False
        self.avisou = False

    def stop(self) -> None:
        self.parou = True

    class _Sinal:
        def __init__(self, dono: Avisador) -> None:
            self._dono = dono

        def emit(self) -> None:
            self._dono.avisou = True

    @property
    def stopped(self) -> _Sinal:  # noqa: F821 - referência à classe interna
        return Avisador._Sinal(self)

    def emitir(self, geracao: int) -> None:
        AudioPreview._emit_stopped(self, geracao)  # type: ignore[arg-type]


def test_fim_de_uma_reproducao_antiga_nao_derruba_a_atual() -> None:
    # O aviso de fim é agendado com atraso, para a placa terminar de tocar o
    # que já recebeu. Quem parasse e voltasse a tocar nesse intervalo via a
    # reprodução nova ser encerrada pelo aviso da anterior.
    avisador = Avisador()
    avisador.emitir(3)  # geração antiga
    assert not avisador.parou and not avisador.avisou


def test_fim_da_reproducao_corrente_avisa() -> None:
    avisador = Avisador()
    avisador.emitir(7)  # geração corrente
    assert avisador.parou and avisador.avisou


class ProcessoDeMentira:
    """Um ffmpeg que ignora o SIGTERM, como o de verdade faz com o cano cheio."""

    def __init__(self, *, atende_terminate: bool) -> None:
        self._atende = atende_terminate
        self.vivo = True
        self.pediram_terminate = False
        self.mataram = False

    def poll(self) -> int | None:
        return None if self.vivo else 0

    def terminate(self) -> None:
        self.pediram_terminate = True
        self.vivo = not self._atende

    def kill(self) -> None:
        self.mataram = True
        self.vivo = False

    def wait(self, timeout: float | None = None) -> int:
        if self.vivo:
            raise subprocess.TimeoutExpired("ffmpeg", timeout or 0)
        return 0


def test_ffmpeg_que_ignora_o_terminate_e_morto() -> None:
    # Bloqueado escrevendo num cano que ninguém lê, o ffmpeg só nota o pedido de
    # parada entre pacotes — e não chega lá. Medido: o ``wait(timeout=2)`` ia
    # até o fim todas as vezes, e ele rodava na interface: dois segundos de
    # janela congelada em cada pausa.
    processo = ProcessoDeMentira(atende_terminate=False)
    _reap(processo)  # type: ignore[arg-type]
    assert processo.pediram_terminate
    assert processo.mataram, "não adianta pedir com jeito e desistir"
    assert not processo.vivo


def test_ffmpeg_que_atende_nao_precisa_ser_morto() -> None:
    processo = ProcessoDeMentira(atende_terminate=True)
    _reap(processo)  # type: ignore[arg-type]
    assert processo.pediram_terminate and not processo.mataram


def test_processo_ja_encerrado_nao_recebe_sinal() -> None:
    processo = ProcessoDeMentira(atende_terminate=True)
    processo.vivo = False
    _reap(processo)  # type: ignore[arg-type]
    assert not processo.pediram_terminate and not processo.mataram


class CanoDeMentira:
    def __init__(self, pedacos: list[bytes]) -> None:
        self._pedacos = list(pedacos)

    def read(self, _tamanho: int) -> bytes:
        return self._pedacos.pop(0) if self._pedacos else b""


class ProcessoComCano:
    def __init__(self, pedacos: list[bytes]) -> None:
        self.stdout = CanoDeMentira(pedacos)


class Tocador:
    """Um objeto com a fila da reprodução **nova**, como fica depois do start."""

    def __init__(self) -> None:
        self._chunks: queue.Queue[bytes | None] = queue.Queue()
        self._stopping = threading.Event()


def test_leitor_antigo_nao_alimenta_a_reproducao_nova() -> None:
    # Parar não espera mais o ffmpeg morrer, então o leitor da reprodução
    # anterior ainda pode estar de pé quando a próxima começa. Enquanto os dois
    # compartilhavam os atributos do objeto, esse leitor atrasado despejava o som
    # antigo na fila da reprodução nova — som de outro trecho, no meio deste.
    antiga: queue.Queue[bytes | None] = queue.Queue()
    parada = threading.Event()
    tocador = Tocador()

    AudioPreview._read(  # type: ignore[arg-type]
        tocador, ProcessoComCano([b"velho"]), antiga, parada
    )

    assert antiga.get_nowait() == b"velho"
    assert tocador._chunks.empty(), "a fila da reprodução nova ficou intacta"


def test_o_sinal_de_parada_do_leitor_e_o_dele() -> None:
    # O ``start`` cria um sinal novo em vez de limpar o antigo: limpando, o
    # leitor já mandado parar voltava a ler e não parava mais.
    tocador = Tocador()
    parada = threading.Event()
    parada.set()
    fila: queue.Queue[bytes | None] = queue.Queue()

    AudioPreview._read(  # type: ignore[arg-type]
        tocador, ProcessoComCano([b"velho"]), fila, parada
    )

    assert fila.get_nowait() is None, "só o fim do fluxo, nenhum áudio"


# Estes cenários exercitam adaptadores ou apresentação Qt.
def test_fim_do_audio_nao_se_perde_quando_o_ultimo_pedaco_enche_a_fila():
    fila = queue.Queue(1)
    stopping = threading.Event()
    thread = threading.Thread(target=AudioPreview._read, args=(
        Tocador(), ProcessoComCano([b"fim"]), fila, stopping,
    ))
    thread.start()
    try:
        # Deixa o produtor chegar ao EOF antes de consumir o último pedaço.
        thread.join(0.1)
        assert fila.get(timeout=1) == b"fim"
        assert fila.get(timeout=1) is None
    finally:
        stopping.set()
        thread.join(1)
    assert not thread.is_alive()


def test_leitor_com_fila_cheia_responde_ao_cancelamento():
    fila = queue.Queue(1)
    stopping = threading.Event()
    thread = threading.Thread(target=AudioPreview._read, args=(
        Tocador(), ProcessoComCano([b"fim"]), fila, stopping,
    ))
    thread.start()
    stopping.set()
    thread.join(1)
    assert not thread.is_alive()


pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")


def test_runtime_produz_pcm_no_mesmo_formato_negociado_com_a_placa(monkeypatch):
    from types import SimpleNamespace
    from videomanager.infrastructure.qt.runtime import DesktopRuntime
    from videomanager.infrastructure.qt import runtime
    requested = []
    started = []
    def command(*args, **kwargs):
        requested.append(kwargs)
        return ['ffmpeg', 'pcm']
    monkeypatch.setattr(runtime.composer, 'audio_command', command)
    output = SimpleNamespace(
        available=True, target_format=(44100, 1),
        start=lambda *args, **kwargs: started.append((args, kwargs)),
    )
    DesktopRuntime.play_audio(None, output, object(), 2.5, object())
    assert requested[0]['sample_rate'] == 44100
    assert requested[0]['channels'] == 1
    assert started == [((['ffmpeg', 'pcm'], 2.5), {'pcm_format': (44100, 1)})]


def test_audio_continua_sendo_relogio_enquanto_a_placa_drena_o_final():
    from types import SimpleNamespace
    output = SimpleNamespace(_sink=object(), _finished=True)
    assert AudioPreview.playing.fget(output)
    output._sink = None
    assert not AudioPreview.playing.fget(output)


def test_formato_incompativel_nao_inicia_ffmpeg(monkeypatch):
    from types import SimpleNamespace
    from videomanager.infrastructure.qt import audio
    monkeypatch.setattr(AudioPreview, 'available', property(lambda self: True))
    monkeypatch.setattr(audio, 'QMediaDevices', SimpleNamespace(
        defaultAudioOutput=lambda: SimpleNamespace(isFormatSupported=lambda fmt: False),
    ))
    def unexpected(*args, **kwargs):
        pytest.fail('formato incompatível não deve iniciar processo')
    monkeypatch.setattr(audio.subprocess, 'Popen', unexpected)
    output = AudioPreview()
    assert not output.start(['ffmpeg'], 0, pcm_format=(44100, 1))
    assert not output.playing


def test_falha_na_abertura_da_placa_encerra_o_produtor(monkeypatch):
    from types import SimpleNamespace
    from videomanager.infrastructure.qt import audio
    monkeypatch.setattr(AudioPreview, 'available', property(lambda self: True))
    monkeypatch.setattr(audio, 'QMediaDevices', SimpleNamespace(
        defaultAudioOutput=lambda: SimpleNamespace(isFormatSupported=lambda fmt: True),
    ))
    process = ProcessoDeMentira(atende_terminate=True)
    process.stdout = CanoDeMentira([])
    monkeypatch.setattr(audio.subprocess, 'Popen', lambda *args, **kwargs: process)
    monkeypatch.setattr(audio, '_dispose', _reap)
    monkeypatch.setattr(audio, 'QAudioSink', lambda *args: SimpleNamespace(
        start=lambda: None, stop=lambda: None, deleteLater=lambda: None,
        setVolume=lambda volume: None,
    ))
    output = AudioPreview()
    assert not output.start(['ffmpeg'], 0)
    assert not process.vivo
    assert not output.playing
    assert output._process is None
