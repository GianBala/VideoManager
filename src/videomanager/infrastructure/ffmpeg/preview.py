"""Imagens da aba de edição: quadro, tira de miniaturas, forma de onda e prévia.

**Por que o próprio ffmpeg desenha a prévia, e não um player do Qt.** Um player
pede um instante e entrega o quadro que conseguir, normalmente o keyframe mais
próximo. O ffmpeg entrega **o quadro pedido**, que é a única forma de o que está
na tela ser exatamente o que o corte vai produzir. E ele já está garantido — é o
mesmo binário que junta vídeo e áudio de todo download.

O som é o oposto: precisa sair contínuo, não exato, e por isso ele sai da
mixagem do compositor direto para a placa (ver ``infrastructure/qt/audio.py``).
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
from pathlib import Path

from videomanager.infrastructure.ffmpeg.command_assets import filter_script
from videomanager.application.capabilities import FFmpegTools
from videomanager.application.errors import VideoManagerError
from videomanager.infrastructure.system.binaries import decode_thread_args
from videomanager.infrastructure.system.binaries import subprocess_kwargs

from videomanager.domain.preview import MAX_PREVIEW_FPS as MAX_PREVIEW_FPS
from videomanager.domain.preview import preview_fps as preview_fps
from videomanager.domain.preview import BYTES_PER_PIXEL as BYTES_PER_PIXEL
from videomanager.domain.preview import RawFrame as RawFrame
from videomanager.domain.preview import fit_size as fit_size
from videomanager.domain.preview import filmstrip_times as filmstrip_times

# Teto da taxa da prévia. Abaixo dele a reprodução usa **a taxa do próprio
# projeto**: pedir ao ffmpeg a mesma taxa da origem faz o filtro ``fps`` não ter
# o que duplicar nem descartar, e o movimento na tela é o do arquivo. Uma taxa
# fixa mais baixa — havia 15 aqui — deixa a imagem visivelmente aos trancos num
# vídeo de 30 ou 60 fps.
#
# O teto existe para material acima de 60 fps, onde o ganho é imperceptível e o
# custo não é: cada quadro é uma imagem crua atravessando um cano. Medido nesta
# máquina, 1920×1080 a 60 fps sustenta 355 MB/s sem atrasar.


# Recebe o processo recém-aberto, para quem chamou poder interrompê-lo. Ver
# :func:`_run`.
Register = Callable[[subprocess.Popen], None]


def _run(command: list[str], timeout: int, register: Register | None = None, *, strict: bool = False) -> bytes:
    with filter_script(command) as prepared:
        return _run_raw(prepared, timeout, register, strict=strict)


def _run_raw(command: list[str], timeout: int, register: Register | None = None, *, strict: bool = False) -> bytes:
    """Executa um pedido curto; quadros do editor reportam falhas explicitamente."""
    try:
        proc = subprocess.Popen(command, **subprocess_kwargs())
    except OSError as exc:
        if strict:
            raise VideoManagerError("Não foi possível iniciar o FFmpeg para atualizar a prévia.") from exc
        return b""
    if register is not None:
        register(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        # Nos dois casos o processo pode continuar de pé, e sair daqui sem matá-lo
        # deixaria um ffmpeg decodificando para ninguém até o fim do arquivo.
        proc.kill()
        proc.communicate()
        if strict:
            raise VideoManagerError("A atualização da prévia excedeu o prazo. Tente novamente.")
        return b""
    if strict and proc.returncode != 0:
        raise VideoManagerError(_preview_error(stderr or b""))
    return stdout or b"" if proc.returncode == 0 else b""


def _preview_error(stderr: bytes) -> str:
    # Nunca publicar caminhos, comandos ou URLs da mídia no diagnóstico.
    detail = stderr[-8192:].lower()
    if b"no such file" in detail or b"error opening input" in detail:
        return "Não foi possível ler uma mídia da prévia. Confira os arquivos do projeto."
    if b"no such filter" in detail or b"error initializing filter" in detail:
        return "O FFmpeg não conseguiu aplicar um efeito da prévia. Confira a versão instalada."
    return "Não foi possível renderizar a prévia. Confira as mídias e os efeitos do projeto."


class _DiagnosticTail:
    """Drena stderr continuamente e guarda no máximo 8 KiB, sem bloquear stdout."""
    def __init__(self, stream) -> None:
        self.data = b""
        self._stream = stream
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        try:
            while self._stream is not None:
                chunk = self._stream.read(4096)
                if not chunk:
                    break
                self.data = (self.data + chunk)[-8192:]
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        self._thread.join(timeout=1)
        if self._stream is not None:
            self._stream.close()


def frame_from_command(
    command: list[str],
    size: tuple[int, int],
    *,
    timeout: int = 60,
    register: Register | None = None,
    strict: bool = False,
) -> RawFrame | None:
    """Um quadro cru produzido por um comando já montado.

    É por aqui que entra a composição da linha do tempo (ver ``infrastructure/ffmpeg/composer``):
    o mesmo grafo que exporta o arquivo desenha o quadro da prévia, e por isso o
    que está na tela é a montagem de verdade, com as trilhas sobrepostas na
    ordem certa.
    """
    width, height = size
    frame = RawFrame(_run(command, timeout, register, strict=strict), width, height)
    if strict and not frame.is_complete:
        raise VideoManagerError("A prévia não retornou um quadro completo. Confira a mídia nesse instante.")
    return frame if frame.is_complete else None


def _fit_filter(width: int, height: int, *, prefix: str = "") -> str:
    """Encaixa na célula sem deformar, preto de verdade sob transparência.

    A saída é rawvideo: o tamanho precisa ser exatamente o pedido, senão o
    buffer não fecha e o quadro é descartado como incompleto. Por isso encolher
    não basta — o que sobra vira tarja. Pedir ``scale=w:h`` cru esticava a
    imagem para o formato da célula, e uma foto em pé aparecia achatada na
    largura de um quadro 16:9.

    ``pad`` sozinho só preenche a moldura nova; o que já estava transparente
    **dentro** da imagem escalada continua com o RGB que o decodificador
    guardou sob alfa=0 — não é necessariamente preto, é lixo do codificador.
    Medido num WebP real com canal alfa: a borda transparente saía
    (255,255,255) em vez de preta, um risco branco visível na miniatura. O
    ``geq`` multiplica cada canal pelo próprio alfa (0 a 1): onde alfa é zero,
    a cor vai a zero junto, sem depender do que o codificador deixou ali.

    A primeira versão disto compunha com ``overlay`` sobre uma segunda fonte
    ``color``, que É a forma canônica de compor sobre um fundo — mas exige
    sincronizar duas correntes de quadros, e a tira de miniaturas pede várias
    de uma vez pelo mesmo ``fps``. Medido: a partir da segunda miniatura o
    brilho saía cada vez mais errado, a base ficando para trás da frente sem
    avisar nada. O ``geq`` opera quadro a quadro, sem segunda corrente para
    dessincronizar, e por isso serve aos dois caminhos igual. ``prefix`` entra
    antes do ``scale`` para filtros que precisam do quadro cru primeiro, como
    o ``fps`` da tira.
    """
    return (
        f"[0:v]{prefix}scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"format=rgba,"
        f"geq=r='r(X,Y)*alpha(X,Y)/255':g='g(X,Y)*alpha(X,Y)/255':b='b(X,Y)*alpha(X,Y)/255',"
        f"format=yuv420p,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black[__fit]"
    )


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

    ``seconds <= 0`` omite o ``-ss`` inteiro em vez de pedir ``0.000000``:
    buscar o início é sempre um no-op, e para uma imagem única que o ffprobe
    detectou como ``image2`` (comum em JPEG baixado da internet, por
    conteúdo, não pela extensão) o demuxer trata ``-ss`` como "avance para a
    próxima imagem da sequência" — que não existe. Medido: o mesmo arquivo,
    mesmo filtro, sem ``-ss`` sai 15552 bytes; com ``-ss 0.000000`` o ffmpeg
    devolve zero bytes e nenhum aviso, porque ``-v error`` não imprime o
    "No filtered frames for output stream" que explicaria o motivo.
    """
    width, height = size
    command = [
        tools.ffmpeg_str,
        "-nostdin",
        "-hide_banner",
        "-v", "error",
        *decode_thread_args(),
    ]
    if seconds > 0:
        command += ["-ss", f"{seconds:.6f}"]
    command += [
        "-i", str(path),
        "-frames:v", "1",
        "-filter_complex", _fit_filter(width, height),
        "-map", "[__fit]",
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
        "-filter_complex", _fit_filter(width, height, prefix=f"fps={1.0 / step:.9f}:round=up,"),
        "-map", "[__fit]",
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
        fps: float,
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

    def frames(
        self,
        *,
        gate: threading.Event | None = None,
        on_primed: Callable[[], None] | None = None,
    ) -> Iterator[RawFrame]:
        """Gera quadros no ritmo real, com pré-carga opcional do primeiro.

        O relógio começa quando a reprodução é liberada, não quando o FFmpeg é
        aberto. Caso contrário, os décimos gastos montando uma transição deixam
        o fluxo atrasado antes do primeiro quadro e ele dispara vários quadros
        de uma vez para tentar alcançar o tempo perdido.
        """
        with filter_script(self._command) as prepared:
            yield from self._frames(prepared, gate=gate, on_primed=on_primed)

    def _frames(self, command, *, gate=None, on_primed=None) -> Iterator[RawFrame]:
        width, height = self._size
        frame_bytes = width * height * BYTES_PER_PIXEL

        if self._stopped:
            return
        try:
            process = subprocess.Popen(command, **subprocess_kwargs())
        except OSError as exc:
            raise VideoManagerError("Não foi possível iniciar a reprodução da prévia.") from exc
        diagnostic = _DiagnosticTail(getattr(process, "stderr", None))

        with self._lock:
            self._process = process

        try:
            # stop pode ter ocorrido durante Popen, antes de haver um processo
            # registrado. Não entrar numa leitura bloqueante nessa situação.
            if self._stopped:
                return
            assert process.stdout is not None
            first = process.stdout.read(frame_bytes)
            if not first or len(first) < frame_bytes:
                if not self._stopped:
                    process.wait(timeout=5)
                    diagnostic.close()
                    raise VideoManagerError(_preview_error(diagnostic.data))
                return
            if on_primed is not None:
                on_primed()
            if gate is not None:
                while not gate.wait(0.05):
                    if self._stopped:
                        return
            if self._stopped:
                return

            began = time.monotonic()
            yield RawFrame(first, width, height, self._start)
            index = 1
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
                    if not self._stopped:
                        process.wait(timeout=5)
                        diagnostic.close()
                        if process.returncode != 0 or data:
                            raise VideoManagerError(_preview_error(diagnostic.data))
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
            diagnostic.close()
            with self._lock:
                self._process = None

__all__ = [
    'FFmpegTools',
    'MAX_PREVIEW_FPS',
    'preview_fps',
    'BYTES_PER_PIXEL',
    'RawFrame',
    'fit_size',
    'filmstrip_times',
]
