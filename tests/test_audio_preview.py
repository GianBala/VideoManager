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

import queue

from videomanager.ui.audio_preview import AudioPreview


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
