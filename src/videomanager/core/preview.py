"""Imagens da aba de edição: quadro, tira de miniaturas, forma de onda e prévia.

**Por que o próprio ffmpeg desenha a prévia, e não um player do Qt.** Um player
pede um instante e entrega o quadro que conseguir, normalmente o keyframe mais
próximo. O ffmpeg entrega **o quadro pedido**, que é a única forma de o que está
na tela ser exatamente o que o corte vai produzir. E ele já está garantido — é o
mesmo binário que junta vídeo e áudio de todo download.

O som é o oposto: precisa sair contínuo, não exato, e por isso ele sai da
mixagem do compositor direto para a placa (ver ``ui/audio_preview.py``).
Enquanto a prévia roda, é o relógio da placa que manda, e os quadros daqui
correm atrás.

**Os quadros vêm em rgb24 cru, sem passar por PNG ou JPEG.** Um quadro cru vira
``QImage`` por cópia direta de memória, sem codificar de um lado e decodificar do
outro, e sem depender de nenhum plugin de imagem estar presente no pacote. Em
troca é preciso saber o tamanho exato de cada quadro — daí :func:`fit_size`
calcular a escala aqui e passá-la ao ffmpeg em vez de deixá-lo escolher.

A forma de onda é a exceção: ela é uma imagem com transparência, desenhada pelo
filtro ``showwavespic``, e sai em PNG.
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .binaries import FFmpegTools, decode_thread_args, subprocess_kwargs

# Teto da taxa da prévia. Abaixo dele a reprodução usa **a taxa do próprio
# projeto**: pedir ao ffmpeg a mesma taxa da origem faz o filtro ``fps`` não ter
# o que duplicar nem descartar, e o movimento na tela é o do arquivo. Uma taxa
# fixa mais baixa — havia 15 aqui — deixa a imagem visivelmente aos trancos num
# vídeo de 30 ou 60 fps.
#
# O teto existe para material acima de 60 fps, onde o ganho é imperceptível e o
# custo não é: cada quadro é uma imagem crua atravessando um cano. Medido nesta
# máquina, 1920×1080 a 60 fps sustenta 355 MB/s sem atrasar.
MAX_PREVIEW_FPS = 60


def preview_fps(project_fps: float | None) -> int:
    """Taxa da reprodução de prévia para um projeto."""
    if not project_fps or project_fps <= 0:
        return 30
    return max(1, min(MAX_PREVIEW_FPS, round(project_fps)))


BYTES_PER_PIXEL = 3  # rgb24


@dataclass(frozen=True)
class RawFrame:
    """Um quadro em rgb24, pronto para virar ``QImage`` sem conversão."""

    data: bytes
    width: int
    height: int
    seconds: float = 0.0

    @property
    def is_complete(self) -> bool:
        return len(self.data) == self.width * self.height * BYTES_PER_PIXEL


def fit_size(
    source_width: int | None,
    source_height: int | None,
    max_width: int,
    max_height: int,
) -> tuple[int, int]:
    """Tamanho de exibição que cabe na área, preservando a proporção.

    Sempre par: escaladores e codificadores de vídeo trabalham em blocos de dois
    pixels e recusam dimensões ímpares.
    """
    width = source_width or 16
    height = source_height or 9
    scale = min(max_width / width, max_height / height)
    return (
        max(2, int(width * scale) // 2 * 2),
        max(2, int(height * scale) // 2 * 2),
    )


def filmstrip_times(start: float, end: float, count: int) -> tuple[float, ...]:
    """Instantes das miniaturas que cobrem um trecho da linha do tempo.

    Cada miniatura representa uma fatia, e o instante escolhido é o **meio** da
    fatia: pegar o começo faria a primeira miniatura ser sempre o primeiro
    quadro do arquivo, que costuma ser preto.
    """
    if count <= 0:
        return ()
    if end <= start:
        # Trecho de duração zero — uma imagem, que só tem o instante zero.
        # Devolver a fatia média de um intervalo vazio pediria ao ffmpeg um
        # quadro depois do fim do arquivo, e ele não devolveria nada.
        return (start,)
    step = (end - start) / count
    return tuple(start + step * (index + 0.5) for index in range(count))


# Recebe o processo recém-aberto, para quem chamou poder interrompê-lo. Ver
# :func:`_run`.
Register = Callable[[subprocess.Popen], None]


def _run(command: list[str], timeout: int, register: Register | None = None) -> bytes:
    """Executa o ffmpeg e devolve o que ele escreveu na saída.

    Falha silenciosa de propósito: imagem de prévia é cosmética. Quando não sai
    nada — arquivo protegido, instante além do fim, ffmpeg antigo demais para um
    filtro — a interface mantém o que já estava na tela, o que é bem melhor que
    um diálogo de erro no meio de uma navegação.

    ``register`` existe porque estes processos precisam morrer quando a janela
    fecha. O ``QThreadPool`` espera as threads dele no destrutor, então um
    ffmpeg de prazo longo aqui segurava o fechamento do aplicativo pelo prazo
    inteiro, com a janela já fora da tela e nada explicando a espera.
    """
    try:
        proc = subprocess.Popen(command, **subprocess_kwargs())
    except OSError:
        return b""
    if register is not None:
        register(proc)
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        # Nos dois casos o processo pode continuar de pé, e sair daqui sem matá-lo
        # deixaria um ffmpeg decodificando para ninguém até o fim do arquivo.
        proc.kill()
        proc.communicate()
        return b""
    return stdout or b"" if proc.returncode == 0 else b""


def frame_from_command(
    command: list[str],
    size: tuple[int, int],
    *,
    timeout: int = 60,
    register: Register | None = None,
) -> RawFrame | None:
    """Um quadro cru produzido por um comando já montado.

    É por aqui que entra a composição da linha do tempo (ver ``core/composer``):
    o mesmo grafo que exporta o arquivo desenha o quadro da prévia, e por isso o
    que está na tela é a montagem de verdade, com as trilhas sobrepostas na
    ordem certa.
    """
    width, height = size
    frame = RawFrame(_run(command, timeout, register), width, height)
    return frame if frame.is_complete else None


def render_frame(
    path: Path,
    seconds: float,
    size: tuple[int, int],
    tools: FFmpegTools,
    *,
    timeout: int = 30,
    register: Register | None = None,
) -> RawFrame | None:
    """O quadro exibido no instante ``seconds``, escalado para ``size``.

    ``-ss`` antes do ``-i`` salta direto para o ponto em vez de decodificar o
    arquivo desde o começo: é o que mantém a navegação instantânea mesmo num
    vídeo de horas. Quem chama já recuou o instante um quarto de quadro (ver
    ``trimmer.seek_time``), o que garante que o quadro devolvido seja o que
    contém ``seconds``, e não o seguinte.
    """
    width, height = size
    command = [
        tools.ffmpeg_str,
        "-nostdin",
        "-hide_banner",
        "-v", "error",
        *decode_thread_args(),
        "-ss", f"{max(0.0, seconds):.6f}",
        "-i", str(path),
        "-frames:v", "1",
        "-vf", f"scale={width}:{height}",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "pipe:1",
    ]
    data = _run(command, timeout, register)
    frame = RawFrame(data, width, height, seconds)
    return frame if frame.is_complete else None


# Passo entre miniaturas a partir do qual sai mais barato **buscar** cada uma do
# que decodificar reto até ela. Buscar custa um processo, uma abertura e um salto
# (medido: ~0,11 s por miniatura); decodificar reto custa o tempo do trecho
# dividido pela velocidade de decodificação (medido: ~20× o tempo real em 4K).
# Os dois se igualam perto de 2 s de passo, e o valor é conservador de propósito:
# errar para o lado da busca custa alguns décimos, errar para o outro faz uma
# tira sobre um vídeo de duas horas decodificar as duas horas.
_STRIP_ONE_PASS_STEP = 2.0


def _one_pass_worth_it(times: tuple[float, ...]) -> bool:
    """Se a tira inteira sai de um ffmpeg só, em vez de um por miniatura."""
    if len(times) < 2:
        return False
    return times[1] - times[0] <= _STRIP_ONE_PASS_STEP


def _strip_command(
    path: Path, times: tuple[float, ...], size: tuple[int, int], tools: FFmpegTools
) -> list[str]:
    """Comando que devolve a tira inteira, em ordem, num fluxo só.

    O ``fps`` do filtro é o inverso do passo entre miniaturas, e o ``-ss`` cai na
    **primeira** delas — que é meia fatia depois do começo do trecho. Assim os
    quadros gerados pelo filtro (0, passo, 2×passo…) caem exatamente nos
    instantes de :func:`filmstrip_times`, sem precisar escolher nada.

    ``round=up`` é a parte que não se adivinha. O padrão do filtro é ``near``, e
    com ele a tira saía inteira **meio passo adiantada** em relação ao caminho de
    uma busca por miniatura: medido nesta fonte, 19 de brilho onde o outro
    caminho dá 9, e assim nas doze. Nada falhava — a tira aparecia completa, em
    ordem e bonita, mostrando os instantes errados. ``up`` é a mesma regra do
    ``-ss``: o primeiro quadro com pts **maior ou igual** ao pedido.

    O ``scale`` vem depois do ``fps``: escalar antes seria escalar todos os
    quadros decodificados para jogar fora a esmagadora maioria deles.
    """
    width, height = size
    step = times[1] - times[0]
    return [
        tools.ffmpeg_str,
        "-nostdin",
        "-hide_banner",
        "-v", "error",
        *decode_thread_args(),
        "-ss", f"{max(0.0, times[0]):.6f}",
        "-i", str(path),
        "-vf", f"fps={1.0 / step:.9f}:round=up,scale={width}:{height}",
        "-frames:v", str(len(times)),
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "pipe:1",
    ]


def filmstrip_frames(
    path: Path,
    start: float,
    end: float,
    count: int,
    size: tuple[int, int],
    tools: FFmpegTools,
    *,
    timeout: int = 120,
    register: Register | None = None,
) -> Iterator[tuple[int, RawFrame]]:
    """As miniaturas de um trecho, na ordem, cada uma assim que sai.

    Um ffmpeg por miniatura é o caminho óbvio e era o que havia aqui, mas cada
    uma custava um processo, uma abertura de arquivo e a montagem de um
    decodificador — para devolver um quadro. Num passe só, medido: 1,32 s contra
    0,21 s a 1080p (6,3×) e 3,08 s contra 0,29 s a 4K (10,6×).

    O passe único **não** vale sempre: ele decodifica o trecho inteiro, então uma
    tira sobre duas horas de vídeo decodificaria duas horas. Ver
    :func:`_one_pass_worth_it`.

    Quem chama continua recebendo as miniaturas uma a uma, e é o que faz a tira
    aparecer preenchendo da esquerda para a direita em vez de tudo no fim.
    """
    times = filmstrip_times(start, end, count)
    if not times:
        return

    vistos: set[int] = set()
    if _one_pass_worth_it(times):
        for index, frame in _stream_strip(path, times, size, tools, timeout, register):
            vistos.add(index)
            yield index, frame

    # O que o passe único não entregou sai uma a uma. Cobre desde o caso em que
    # ele nem vale a pena até o arquivo que termina antes do fim do trecho — sem
    # isso, um defeito no fluxo deixaria a tira pela metade em silêncio.
    for index, moment in enumerate(times):
        if index in vistos:
            continue
        frame = render_frame(path, moment, size, tools, register=register)
        if frame is not None:
            yield index, frame


def _stream_strip(
    path: Path,
    times: tuple[float, ...],
    size: tuple[int, int],
    tools: FFmpegTools,
    timeout: int,
    register: Register | None = None,
) -> Iterator[tuple[int, RawFrame]]:
    """Lê a tira do cano, um quadro por vez, e encerra o ffmpeg ao sair.

    O ``finally`` é o que sustenta o cancelamento: quem consome fecha o gerador
    ao desistir, e o processo morre junto em vez de continuar decodificando um
    trecho que ninguém vai mais ver.
    """
    width, height = size
    frame_bytes = width * height * BYTES_PER_PIXEL
    kwargs = subprocess_kwargs()
    kwargs["stderr"] = subprocess.DEVNULL
    try:
        process = subprocess.Popen(_strip_command(path, times, size, tools), **kwargs)
    except OSError:
        return
    if register is not None:
        register(process)
    try:
        assert process.stdout is not None
        for index, moment in enumerate(times):
            data = process.stdout.read(frame_bytes)
            if not data or len(data) < frame_bytes:
                return
            yield index, RawFrame(data, width, height, moment)
    finally:
        if process.poll() is None:
            process.terminate()
        if process.stdout is not None:
            process.stdout.close()
        try:
            process.wait(timeout=timeout)
        except subprocess.SubprocessError:
            process.kill()


def render_waveform(
    path: Path,
    tools: FFmpegTools,
    *,
    width: int,
    height: int,
    color: str,
    start: float = 0.0,
    duration: float | None = None,
    timeout: int = 120,
    register: Register | None = None,
) -> bytes:
    """Forma de onda do áudio, em PNG com fundo transparente.

    Desenhada só do trecho visível (``start``/``duration``): o filtro precisa
    decodificar todo o áudio que recebe, e recortar a janela antes é o que
    permite redesenhar a onda a cada aproximação sem custo proporcional à
    duração do arquivo.

    ``aformat=channel_layouts=mono`` deixa uma faixa só; sem isso um arquivo
    estéreo desenha dois canais empilhados, cada um com metade da altura e
    metade da legibilidade.

    ``scale=sqrt`` levanta as amplitudes baixas. Material comum — voz gravada,
    áudio de celular — passa longe do volume máximo, e na escala linear a onda
    vira um fio de um ou dois pixels numa faixa de vinte: some justamente onde
    ela serviria para achar o começo de uma fala.
    """
    command = [
        tools.ffmpeg_str,
        "-nostdin",
        "-hide_banner",
        "-v", "error",
        "-ss", f"{max(0.0, start):.6f}",
    ]
    if duration:
        command += ["-t", f"{duration:.6f}"]
    # O ffmpeg escreve cor em 0xRRGGBB; o tema guarda em #RRGGBB (a forma do
    # CSS, que é onde a mesma cor é usada no resto da interface).
    tint = color.replace("#", "0x")
    command += [
        "-i", str(path),
        "-filter_complex",
        f"aformat=channel_layouts=mono,"
        f"showwavespic=s={width}x{height}:colors={tint}:scale=sqrt",
        "-frames:v", "1",
        "-f", "image2pipe",
        "-vcodec", "png",
        "pipe:1",
    ]
    return _run(command, timeout, register)


class FramePump:
    """Fluxo contínuo de quadros para a reprodução, com ritmo de tempo real.

    Um processo só do ffmpeg decodifica e escala; nós lemos quadro a quadro e
    seguramos a leitura até a hora de cada um. Segurar é o ponto: o cano tem
    capacidade limitada, então o ffmpeg fica bloqueado esperando espaço em vez de
    decodificar o vídeo inteiro para a memória — a mesma pressão de volta que um
    player de verdade usa.
    """

    def __init__(
        self,
        command: list[str],
        start: float,
        size: tuple[int, int],
        *,
        fps: int,
    ) -> None:
        self._command = command
        self._start = max(0.0, start)
        self._size = size
        self._fps = max(1, fps)
        self._process: subprocess.Popen | None = None
        self._stopped = False
        self._lock = threading.Lock()

    def stop(self) -> None:
        self._stopped = True
        with self._lock:
            process = self._process
        if process and process.poll() is None:
            process.terminate()

    def frames(self) -> Iterator[RawFrame]:
        """Gera os quadros a partir de ``start``, no ritmo do relógio."""
        width, height = self._size
        frame_bytes = width * height * BYTES_PER_PIXEL

        kwargs = subprocess_kwargs()
        # O stderr vai para o vazio, e não para um cano: ninguém o lê aqui, e um
        # arquivo com defeito que resolvesse reclamar a cada quadro encheria o
        # cano e travaria o ffmpeg — a prévia congelaria sem explicação.
        kwargs["stderr"] = subprocess.DEVNULL
        try:
            process = subprocess.Popen(self._command, **kwargs)
        except OSError:
            return

        with self._lock:
            self._process = process

        began = time.monotonic()
        index = 0
        try:
            assert process.stdout is not None
            while not self._stopped:
                # A espera acontece antes da leitura: enquanto dormimos, o cano
                # enche e o ffmpeg para sozinho.
                due = index / self._fps
                behind = due - (time.monotonic() - began)
                if behind > 0:
                    time.sleep(behind)
                    if self._stopped:
                        break
                data = process.stdout.read(frame_bytes)
                if not data or len(data) < frame_bytes:
                    break
                yield RawFrame(data, width, height, self._start + due)
                index += 1
        finally:
            self.stop()
            if process.stdout is not None:
                process.stdout.close()
            try:
                process.wait(timeout=5)
            except subprocess.SubprocessError:
                process.kill()
            with self._lock:
                self._process = None
