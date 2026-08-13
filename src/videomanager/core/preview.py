"""Imagens da aba de edição: quadro, tira de miniaturas, forma de onda e prévia.

**Por que o próprio ffmpeg desenha a prévia, e não um player do Qt.** Um player
pede um instante e entrega o quadro que conseguir, normalmente o keyframe mais
próximo. O ffmpeg entrega **o quadro pedido**, que é a única forma de o que está
na tela ser exatamente o que o corte vai produzir. E ele já está garantido — é o
mesmo binário que junta vídeo e áudio de todo download.

O som é o oposto: precisa sair contínuo, não exato, e por isso quem toca é o
``QMediaPlayer`` (ver ``ui/audio_preview.py``). Enquanto a prévia roda, é o
relógio dele que manda, e os quadros daqui correm atrás.

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
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .binaries import FFmpegTools, subprocess_kwargs

# Quadros por segundo da reprodução de prévia. Cada quadro é um arquivo de
# imagem cru atravessando um cano: 15 é fluido o suficiente para acompanhar uma
# ação e barato o bastante para não disputar CPU com um download em andamento.
PREVIEW_FPS = 15

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
    if count <= 0 or end <= start:
        return ()
    step = (end - start) / count
    return tuple(start + step * (index + 0.5) for index in range(count))


def _run(command: list[str], timeout: int) -> bytes:
    """Executa o ffmpeg e devolve o que ele escreveu na saída.

    Falha silenciosa de propósito: imagem de prévia é cosmética. Quando não sai
    nada — arquivo protegido, instante além do fim, ffmpeg antigo demais para um
    filtro — a interface mantém o que já estava na tela, o que é bem melhor que
    um diálogo de erro no meio de uma navegação.
    """
    try:
        proc = subprocess.run(command, timeout=timeout, check=False, **subprocess_kwargs())
    except (OSError, subprocess.SubprocessError):
        return b""
    return proc.stdout or b"" if proc.returncode == 0 else b""


def render_frame(
    path: Path,
    seconds: float,
    size: tuple[int, int],
    tools: FFmpegTools,
    *,
    timeout: int = 30,
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
        "-ss", f"{max(0.0, seconds):.6f}",
        "-i", str(path),
        "-frames:v", "1",
        "-vf", f"scale={width}:{height}",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "pipe:1",
    ]
    data = _run(command, timeout)
    frame = RawFrame(data, width, height, seconds)
    return frame if frame.is_complete else None


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
    return _run(command, timeout)


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
        path: Path,
        start: float,
        size: tuple[int, int],
        tools: FFmpegTools,
        *,
        fps: int = PREVIEW_FPS,
    ) -> None:
        self._path = path
        self._start = max(0.0, start)
        self._size = size
        self._tools = tools
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

    def _command(self) -> list[str]:
        width, height = self._size
        return [
            self._tools.ffmpeg_str,
            "-nostdin",
            "-hide_banner",
            "-v", "error",
            "-ss", f"{self._start:.6f}",
            "-i", str(self._path),
            # A taxa vem antes da escala: descartar quadros primeiro é mais
            # barato que redimensionar quadros que serão descartados.
            "-vf", f"fps={self._fps},scale={width}:{height}",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "pipe:1",
        ]

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
            process = subprocess.Popen(self._command(), **kwargs)
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
