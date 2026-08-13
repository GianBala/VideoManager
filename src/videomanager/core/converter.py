"""Conversão de arquivos que o usuário já tem no disco, via ffmpeg.

Três decisões sustentam este módulo.

**Cópia direta quando dá.** Se o áudio de origem já está no codec pedido e só o
container muda, usamos ``-c copy``: é instantâneo e sem perda nenhuma.
Recodificar nesse caso desperdiçaria minutos e degradaria o som sem motivo. A
detecção está em :func:`can_copy_audio`.

**Progresso por ``-progress pipe:1``.** O ffmpeg escreve pares ``chave=valor`` em
stdout, em formato estável e independente de idioma. A alternativa comum —
raspar o texto do stderr — quebra quando a versão do ffmpeg muda o formato, e
depende do locale.

**``-nostdin`` sempre.** Sem isso o ffmpeg herda o stdin do processo pai, consome
a entrada e pode travar esperando por dados que nunca chegam.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .binaries import FFmpegTools, subprocess_kwargs
from .downloader import Progress
from .errors import ConversionError, JobCancelled
from .trimmer import TrimTarget, build_trim_args, describe_trim

# --- alvos de áudio ---------------------------------------------------------
# Codec pedido -> encoder do ffmpeg. "copy" não aparece aqui: é tratado à parte.
_AUDIO_ENCODERS = {
    "mp3": "libmp3lame",
    "aac": "aac",
    "m4a": "aac",
    "opus": "libopus",
    "vorbis": "libvorbis",
    "ogg": "libvorbis",
    "flac": "flac",
    "alac": "alac",
    "wav": "pcm_s16le",
}

# Extensão do arquivo de saída para cada codec pedido.
_AUDIO_EXTENSIONS = {
    "mp3": "mp3",
    "aac": "m4a",
    "m4a": "m4a",
    "opus": "opus",
    "vorbis": "ogg",
    "ogg": "ogg",
    "flac": "flac",
    "alac": "m4a",
    "wav": "wav",
}

# Formatos sem perda: pedir bitrate não faz sentido.
_LOSSLESS = {"flac", "alac", "wav"}

# Nomes de codec que o ffprobe reporta, por codec pedido. Usado para decidir se
# a cópia direta é possível.
_EQUIVALENT_SOURCE_CODECS = {
    "mp3": {"mp3"},
    "aac": {"aac"},
    "m4a": {"aac"},
    "opus": {"opus"},
    "vorbis": {"vorbis"},
    "ogg": {"vorbis"},
    "flac": {"flac"},
    "alac": {"alac"},
    "wav": {"pcm_s16le", "pcm_s16be", "pcm_u8"},
}

_VIDEO_ENCODERS = {
    "h264": "libx264",
    "hevc": "libx265",
    "vp9": "libvpx-vp9",
    "av1": "libsvtav1",
}

AUDIO_TARGETS = ("mp3", "m4a", "opus", "vorbis", "flac", "wav")
VIDEO_CONTAINERS = ("mp4", "mkv", "webm")

# O que cada container aceita guardar. ``None`` = aceita qualquer coisa, que é o
# caso do MKV. Os nomes são os que o ffprobe reporta em ``codec_name``.
# Sem esta tabela, "copiar sem recodificar" para .webm produzia um erro cru do
# ffmpeg ("Only VP8/VP9/AV1 video and Vorbis/Opus audio are supported") depois de
# a tarefa já estar na fila — quando dava para saber antes de começar.
_CONTAINER_VIDEO_OK: dict[str, set[str] | None] = {
    "mp4": {"h264", "hevc", "av1", "mpeg4"},
    "mkv": None,
    "webm": {"vp8", "vp9", "av1"},
}
_CONTAINER_AUDIO_OK: dict[str, set[str] | None] = {
    "mp4": {"aac", "mp3", "alac", "ac3", "eac3"},
    "mkv": None,
    "webm": {"opus", "vorbis"},
}
# Para onde recodificar quando a cópia não cabe no container pedido.
_CONTAINER_VIDEO_FALLBACK = {"mp4": "h264", "mkv": "h264", "webm": "vp9"}
_CONTAINER_AUDIO_FALLBACK = {"mp4": "aac", "mkv": "aac", "webm": "opus"}


@dataclass(frozen=True)
class LocalStream:
    index: int
    kind: str  # "video" | "audio" | "subtitle" | outro
    codec: str
    height: int | None = None
    width: int | None = None
    fps: float | None = None
    bitrate: float | None = None  # kbps
    sample_rate: int | None = None
    channels: int | None = None
    language: str | None = None


@dataclass(frozen=True)
class LocalMedia:
    """Um arquivo local já inspecionado pelo ffprobe."""

    path: Path
    duration: float | None
    format_name: str
    size: int | None
    streams: tuple[LocalStream, ...]

    @property
    def video(self) -> LocalStream | None:
        return next((s for s in self.streams if s.kind == "video"), None)

    @property
    def audio(self) -> LocalStream | None:
        return next((s for s in self.streams if s.kind == "audio"), None)

    @property
    def has_video(self) -> bool:
        return self.video is not None

    @property
    def has_audio(self) -> bool:
        return self.audio is not None


@dataclass(frozen=True)
class AudioTarget:
    """Pedido de conversão para áudio."""

    codec: str = "mp3"
    bitrate: str = "192"

    @property
    def extension(self) -> str:
        return _AUDIO_EXTENSIONS.get(self.codec, self.codec)

    @property
    def is_lossless(self) -> bool:
        return self.codec in _LOSSLESS


@dataclass(frozen=True)
class VideoTarget:
    """Pedido de conversão para vídeo.

    ``video_codec="copy"`` troca só o container: rápido e sem perda. É o padrão
    por isso mesmo.
    """

    container: str = "mp4"
    video_codec: str = "copy"
    audio_codec: str = "copy"
    audio_bitrate: str = "192"
    height: int | None = None
    fps: float | None = None
    crf: int = 20

    @property
    def extension(self) -> str:
        return self.container


# O recorte da aba de edição também é executado pelo :class:`Converter`: o que
# muda é a montagem dos argumentos, e todo o resto — progresso lido do ffmpeg,
# cancelamento, limpeza da saída parcial — vale igual. O módulo ``trimmer``
# depende deste, e nunca o contrário, para a dependência continuar de mão única.
ConversionTarget = AudioTarget | VideoTarget | TrimTarget


# ---------------------------------------------------------------------------
# Inspeção
# ---------------------------------------------------------------------------


def probe_file(path: Path, tools: FFmpegTools) -> LocalMedia:
    """Inspeciona um arquivo local com ffprobe."""
    if not path.is_file():
        raise ConversionError(f"Arquivo não encontrado: {path}")

    command = [
        tools.ffprobe_str,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(command, timeout=60, check=False, **subprocess_kwargs())
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConversionError(f"Falha ao inspecionar o arquivo: {exc}") from exc

    if proc.returncode != 0:
        raise ConversionError(
            f"O ffprobe não reconheceu “{path.name}” como arquivo de mídia."
        )

    try:
        data = json.loads(proc.stdout or b"{}")
    except json.JSONDecodeError as exc:
        raise ConversionError("Resposta do ffprobe ilegível.") from exc

    container = data.get("format") or {}
    streams: list[LocalStream] = []
    for raw in data.get("streams") or []:
        if not isinstance(raw, dict):
            continue
        streams.append(
            LocalStream(
                index=_int(raw.get("index")) or 0,
                kind=str(raw.get("codec_type") or "desconhecido"),
                codec=str(raw.get("codec_name") or "desconhecido"),
                height=_int(raw.get("height")),
                width=_int(raw.get("width")),
                fps=_fraction(raw.get("r_frame_rate")),
                bitrate=_kbps(raw.get("bit_rate")),
                sample_rate=_int(raw.get("sample_rate")),
                channels=_int(raw.get("channels")),
                language=(raw.get("tags") or {}).get("language"),
            )
        )

    return LocalMedia(
        path=path,
        duration=_float(container.get("duration")),
        format_name=str(container.get("format_name") or "desconhecido"),
        size=_int(container.get("size")),
        streams=tuple(streams),
    )


def _int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _float(value: object) -> float | None:
    try:
        result = float(str(value))
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _kbps(value: object) -> float | None:
    raw = _float(value)
    return raw / 1000 if raw else None


def _fraction(value: object) -> float | None:
    """Converte "30000/1001" no framerate real."""
    text = str(value or "")
    if "/" not in text:
        return _float(text)
    numerator, _, denominator = text.partition("/")
    num, den = _float(numerator), _float(denominator)
    return num / den if num and den else None


# ---------------------------------------------------------------------------
# Montagem dos argumentos (funções puras, testáveis sem ffmpeg)
# ---------------------------------------------------------------------------


def can_copy_audio(media: LocalMedia, codec: str) -> bool:
    """Se o áudio pode ser copiado em vez de recodificado.

    Vale quando o codec de origem já é o pedido: aí a conversão é só troca de
    container, feita em segundos e sem perda.
    """
    stream = media.audio
    if stream is None or codec == "copy":
        return codec == "copy" and stream is not None
    return stream.codec.lower() in _EQUIVALENT_SOURCE_CODECS.get(codec, set())


def output_path(
    source: Path,
    target: ConversionTarget,
    dest_dir: Path | None = None,
    suffix: str = "",
) -> Path:
    """Caminho de saída, evitando sobrescrever o arquivo de origem.

    Converter um ``.mp3`` para ``.mp3`` com outro bitrate é um pedido legítimo, e
    sem o sufixo a origem seria destruída no meio da leitura.

    ``suffix`` distingue saídas que nascem do mesmo arquivo — os vários trechos
    de um recorte — sem depender do contador, que só entra em cena quando o nome
    escolhido já existe.
    """
    directory = dest_dir or source.parent
    stem = f"{source.stem}{suffix}"
    candidate = directory / f"{stem}.{target.extension}"
    if candidate.resolve() == source.resolve():
        candidate = directory / f"{stem} (convertido).{target.extension}"
    # Não sobrescreve arquivos já existentes.
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}).{target.extension}"
        counter += 1
    return candidate


def build_audio_args(
    media: LocalMedia, target: AudioTarget, destination: Path, tools: FFmpegTools
) -> list[str]:
    """Argumentos do ffmpeg para extrair/converter o áudio."""
    if not media.has_audio:
        raise ConversionError(
            f"“{media.path.name}” não tem trilha de áudio para converter."
        )

    args = [
        tools.ffmpeg_str,
        "-nostdin",
        "-hide_banner",
        "-y",
        "-i", str(media.path),
        # Descarta vídeo, capas e legendas: a saída é só áudio.
        "-vn",
        "-sn",
        "-map", "0:a:0",
    ]

    if can_copy_audio(media, target.codec):
        args += ["-c:a", "copy"]
    else:
        encoder = _AUDIO_ENCODERS.get(target.codec)
        if encoder is None:
            raise ConversionError(f"Formato de áudio não suportado: {target.codec}")
        args += ["-c:a", encoder]
        if not target.is_lossless:
            args += ["-b:a", f"{target.bitrate}k"]

    if target.codec == "mp3":
        # Sem ID3v2.3 o Windows Explorer não mostra título nem artista.
        args += ["-id3v2_version", "3"]

    args += ["-map_metadata", "0", "-progress", "pipe:1", "-nostats", str(destination)]
    return args


def needs_scaling(media: LocalMedia, target: VideoTarget) -> bool:
    return bool(target.height and media.video and media.video.height != target.height)


def _container_accepts(table: dict[str, set[str] | None], container: str, codec: str) -> bool:
    allowed = table.get(container, None)
    return allowed is None or codec.lower() in allowed


def needs_video_reencode(media: LocalMedia, target: VideoTarget) -> bool:
    """Se a conversão vai ter de recodificar o vídeo.

    Existe para que :func:`build_video_args` e :func:`describe_target` decidam
    pela mesma regra. Quando essa decisão estava duplicada, a interface anunciava
    "vídeo copiado" numa conversão que recodificava — porque redimensionar ou
    mudar o framerate torna a cópia impossível, independentemente do que o
    usuário pediu.
    """
    if target.video_codec != "copy":
        return True
    if needs_scaling(media, target) or target.fps:
        return True
    # Copiar só é possível se o container de destino aceitar o codec de origem.
    stream = media.video
    return stream is not None and not _container_accepts(
        _CONTAINER_VIDEO_OK, target.container, stream.codec
    )


def needs_audio_reencode(media: LocalMedia, target: VideoTarget) -> bool:
    """Mesma pergunta, para a trilha de áudio de uma conversão de vídeo."""
    if not media.has_audio:
        return False
    if target.audio_codec != "copy":
        return True
    stream = media.audio
    return stream is not None and not _container_accepts(
        _CONTAINER_AUDIO_OK, target.container, stream.codec
    )


def resolved_video_codec(media: LocalMedia, target: VideoTarget) -> str:
    """Codec de vídeo que a conversão vai realmente produzir."""
    if not needs_video_reencode(media, target):
        return "copy"
    if target.video_codec != "copy":
        return target.video_codec
    # O usuário pediu cópia, mas ela não cabe: escolhe o codec natural do
    # container em vez de falhar.
    stream = media.video
    if stream is not None and _container_accepts(
        _CONTAINER_VIDEO_OK, target.container, stream.codec
    ):
        return "h264" if target.container != "webm" else "vp9"
    return _CONTAINER_VIDEO_FALLBACK.get(target.container, "h264")


def resolved_audio_codec(media: LocalMedia, target: VideoTarget) -> str:
    """Codec de áudio que a conversão vai realmente produzir."""
    if not needs_audio_reencode(media, target):
        return "copy"
    if target.audio_codec != "copy":
        return target.audio_codec
    return _CONTAINER_AUDIO_FALLBACK.get(target.container, "aac")


def build_video_args(
    media: LocalMedia, target: VideoTarget, destination: Path, tools: FFmpegTools
) -> list[str]:
    """Argumentos do ffmpeg para converter vídeo."""
    if not media.has_video:
        raise ConversionError(
            f"“{media.path.name}” não tem trilha de vídeo. Use a conversão para áudio."
        )

    args = [
        tools.ffmpeg_str,
        "-nostdin",
        "-hide_banner",
        "-y",
        "-i", str(media.path),
        "-map", "0:v:0",
    ]
    if media.has_audio:
        args += ["-map", "0:a:0"]

    codec = resolved_video_codec(media, target)
    if codec == "copy":
        args += ["-c:v", "copy"]
    else:
        encoder = _VIDEO_ENCODERS.get(codec)
        if encoder is None:
            raise ConversionError(f"Codec de vídeo não suportado: {codec}")
        args += ["-c:v", encoder, "-crf", str(target.crf)]
        if encoder == "libx264":
            # yuv420p é o único formato de pixel que reproduz em qualquer lugar.
            args += ["-pix_fmt", "yuv420p", "-preset", "medium"]
        if needs_scaling(media, target):
            # -2 mantém a largura par: codecs H.264/HEVC exigem dimensões pares.
            args += ["-vf", f"scale=-2:{target.height}"]
        if target.fps:
            args += ["-r", str(target.fps)]

    if media.has_audio:
        audio_codec = resolved_audio_codec(media, target)
        if audio_codec == "copy":
            args += ["-c:a", "copy"]
        else:
            encoder = _AUDIO_ENCODERS.get(audio_codec)
            if encoder is None:
                raise ConversionError(f"Codec de áudio não suportado: {audio_codec}")
            args += ["-c:a", encoder, "-b:a", f"{target.audio_bitrate}k"]

    if target.container == "mp4":
        # Coloca o índice no começo: permite começar a assistir antes de baixar
        # o arquivo todo, e é o que players web esperam.
        args += ["-movflags", "+faststart"]

    args += ["-map_metadata", "0", "-progress", "pipe:1", "-nostats", str(destination)]
    return args


def build_args(
    media: LocalMedia, target: ConversionTarget, destination: Path, tools: FFmpegTools
) -> list[str]:
    if isinstance(target, AudioTarget):
        return build_audio_args(media, target, destination, tools)
    if isinstance(target, TrimTarget):
        return build_trim_args(media, target, destination, tools)
    return build_video_args(media, target, destination, tools)


def output_duration(media: LocalMedia, target: ConversionTarget) -> float | None:
    """Duração que a saída vai ter — a régua do percentual de progresso.

    Só um recorte tem duração diferente da origem, e é justamente onde usar a
    duração do arquivo faria a barra parar em 3% numa tarefa concluída.
    """
    if isinstance(target, TrimTarget):
        return target.output_duration or None
    return media.duration


def describe_target(media: LocalMedia, target: ConversionTarget) -> str:
    """Resumo do que a conversão vai fazer, para exibir antes de começar."""
    if isinstance(target, TrimTarget):
        return describe_trim(media, target)
    if isinstance(target, AudioTarget):
        if can_copy_audio(media, target.codec):
            return f"{target.codec.upper()} · cópia direta (sem recodificar)"
        if target.is_lossless:
            return f"{target.codec.upper()} · sem perda"
        return f"{target.codec.upper()} · {target.bitrate} kbps"

    parts = [f".{target.container}"]
    codec = resolved_video_codec(media, target)
    if codec == "copy":
        parts.append("vídeo copiado (sem recodificar)")
    else:
        parts.append(f"recodifica em {codec.upper()}")
    audio_codec = resolved_audio_codec(media, target)
    if media.has_audio and audio_codec != "copy":
        # Só se diz quando há custo: "áudio copiado" seria ruído em toda linha.
        parts.append(f"áudio em {audio_codec.upper()}")
    if target.height:
        parts.append(f"{target.height}p")
    if target.fps:
        parts.append(f"{target.fps:g} fps")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

# Linhas do -progress: "chave=valor". out_time_us é preferido a out_time_ms
# porque em várias versões do ffmpeg o campo "ms" é reportado em microssegundos
# — uma inconsistência antiga que já causou barras de progresso 1000x erradas.
_PROGRESS_LINE = re.compile(r"^(\w+)=(.*)$")
_TIMESTAMP = re.compile(r"^(\d+):(\d{2}):(\d{2})(?:\.(\d+))?$")


def _parse_timestamp(text: str) -> float | None:
    match = _TIMESTAMP.match(text.strip())
    if not match:
        return None
    hours, minutes, seconds, fraction = match.groups()
    total = int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    if fraction:
        total += float(f"0.{fraction}")
    return float(total)


class Converter:
    """Uma conversão cancelável de um arquivo local."""

    def __init__(
        self,
        media: LocalMedia,
        target: ConversionTarget,
        destination: Path,
        tools: FFmpegTools,
        *,
        on_progress: Callable[[Progress], None] | None = None,
    ) -> None:
        self._media = media
        self._target = target
        self._destination = destination
        self._tools = tools
        self._on_progress = on_progress
        self._process: subprocess.Popen | None = None
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancelled = True
        with self._lock:
            process = self._process
        if process and process.poll() is None:
            process.terminate()

    @staticmethod
    def _drain(stream, into: deque[str]) -> None:
        """Consome o stderr do ffmpeg, guardando só o fim — onde está a causa."""
        if stream is None:
            return
        try:
            for line in stream:
                text = line.strip()
                if text:
                    into.append(text)
        except (OSError, ValueError):
            # Cano fechado por causa de terminate(): nada a relatar.
            pass

    def _emit(self, seconds: float | None, size: int | None) -> None:
        if self._on_progress is None:
            return
        duration = output_duration(self._media, self._target)
        percent = None
        if seconds is not None and duration:
            percent = min(100.0, seconds * 100.0 / duration)
        self._on_progress(
            Progress(
                phase="Recortando" if isinstance(self._target, TrimTarget) else "Convertendo",
                percent=percent,
                downloaded_bytes=size,
                indeterminate=percent is None,
            )
        )

    def run(self) -> Path:
        args = build_args(self._media, self._target, self._destination, self._tools)
        self._destination.parent.mkdir(parents=True, exist_ok=True)

        kwargs = subprocess_kwargs()
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE

        try:
            process = subprocess.Popen(args, text=True, bufsize=1, **kwargs)
        except OSError as exc:
            raise ConversionError(f"Não foi possível iniciar o ffmpeg: {exc}") from exc

        with self._lock:
            self._process = process

        # O stderr é drenado em paralelo, e não depois do stdout: os dois são
        # canos de capacidade limitada, e um ffmpeg que enchesse o de stderr
        # ficaria bloqueado esperando alguém ler — enquanto nós esperávamos o
        # stdout que ele não teria como continuar escrevendo. Travamento mútuo,
        # tanto mais provável quanto mais longa a conversão.
        stderr_tail: deque[str] = deque(maxlen=40)
        drain = threading.Thread(
            target=self._drain, args=(process.stderr, stderr_tail), daemon=True
        )
        drain.start()

        size: int | None = None
        try:
            assert process.stdout is not None
            for line in process.stdout:
                if self._cancelled:
                    process.terminate()
                    break
                match = _PROGRESS_LINE.match(line.strip())
                if not match:
                    continue
                key, value = match.group(1), match.group(2).strip()
                if key == "total_size" and value.isdigit():
                    size = int(value)
                elif key == "out_time_us" and value.isdigit():
                    self._emit(int(value) / 1_000_000, size)
                elif key == "out_time":
                    self._emit(_parse_timestamp(value), size)
            process.wait()
            drain.join(timeout=5)
            stderr = "\n".join(stderr_tail)
        finally:
            with self._lock:
                self._process = None

        if self._cancelled:
            # Saída parcial é lixo: um arquivo truncado ludibriaria o usuário.
            self._destination.unlink(missing_ok=True)
            raise JobCancelled("Conversão cancelada.")

        if process.returncode != 0:
            self._destination.unlink(missing_ok=True)
            detail = _last_error_line(stderr)
            raise ConversionError(f"O ffmpeg falhou na conversão: {detail}")

        if not self._destination.exists():
            raise ConversionError(
                "O ffmpeg terminou sem erro mas não gerou o arquivo de saída."
            )
        return self._destination


def _last_error_line(stderr: str) -> str:
    """Última linha significativa do stderr — onde o ffmpeg diz a causa."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    return lines[-1] if lines else "erro não informado"
