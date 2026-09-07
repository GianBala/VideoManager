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
import os
import re
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import hwaccel
from .binaries import FFmpegTools, subprocess_kwargs
from .downloader import Progress
from .errors import ConversionError, JobCancelled
from .process import ProcessControl
from .composer import Composition, describe_export, export_args
from .parallel_export import ParallelExport, plan_segments
from .thumbnail import embed_thumbnail
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
    # Proporção do pixel (``sample_aspect_ratio``). Quase toda mídia atual tem
    # pixel quadrado e traz 1, mas rip de DVD e filmadora antiga guardam a
    # imagem espremida — 720×480 para exibir em 16:9 — e só este número diz
    # isso. Sem ele, a imagem sai achatada e nada falha. ``None`` quando o
    # arquivo não informa, que o ffmpeg trata como 1.
    sar: float | None = None
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
    hardware: str = hwaccel.SOFTWARE

    @property
    def extension(self) -> str:
        return self.container


# O recorte da aba de edição também é executado pelo :class:`Converter`: o que
# muda é a montagem dos argumentos, e todo o resto — progresso lido do ffmpeg,
# cancelamento, limpeza da saída parcial — vale igual. O módulo ``trimmer``
# depende deste, e nunca o contrário, para a dependência continuar de mão única.
ConversionTarget = AudioTarget | VideoTarget | TrimTarget | Composition


# ---------------------------------------------------------------------------
# Inspeção
# ---------------------------------------------------------------------------


def probe_file(path: Path, tools: FFmpegTools, *, control: ProcessControl | None = None) -> LocalMedia:
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
        proc = (control or ProcessControl()).run(command, timeout=60)
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
                sar=_ratio(raw.get("sample_aspect_ratio")),
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


def _ratio(value: object) -> float | None:
    """Converte a proporção do pixel — "32:27" — no número correspondente.

    O ffprobe escreve razão com dois-pontos, e não com barra como o framerate.
    Desconhecida ele escreve "0:1" ou "N/A": as duas viram ``None``, que é
    diferente de 1 — não se sabe, e não "é quadrado".
    """
    numerator, separator, denominator = str(value or "").partition(":")
    if not separator:
        return None
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
    custom_stem: str | None = None,
) -> Path:
    """Caminho de saída, evitando sobrescrever o arquivo de origem.

    Converter um ``.mp3`` para ``.mp3`` com outro bitrate é um pedido legítimo, e
    sem o sufixo a origem seria destruída no meio da leitura.

    ``suffix`` distingue saídas que nascem do mesmo arquivo — os vários trechos
    de um recorte — sem depender do contador, que só entra em cena quando o nome
    escolhido já existe.

    **O nome é reservado, não apenas consultado.** Esta função é chamada ao
    *enfileirar*, e o ffmpeg só grava minutos depois: "não existe agora" não diz
    nada sobre o instante da gravação. Enquanto era só uma consulta, enfileirar
    duas vezes a mesma origem devolvia o mesmo caminho para as duas tarefas, e a
    segunda sobrescrevia o resultado já pronto da primeira — em silêncio, e com
    o ``-y`` do ffmpeg contra o qual não havia defesa nenhuma. Criar o arquivo
    vazio com ``O_EXCL`` fecha a janela: o nome deixa de estar livre no ato. O
    arquivo de zero byte é sobrescrito pelo próprio ffmpeg, e a limpeza de saída
    parcial em caso de falha ou cancelamento já existia.
    """
    directory = dest_dir or source.parent
    clean_custom = custom_stem.strip() if custom_stem else ""
    stem = clean_custom if clean_custom else f"{source.stem}{suffix}"
    candidate = directory / f"{stem}.{target.extension}"
    if candidate.resolve() == source.resolve():
        candidate = directory / f"{stem} (convertido).{target.extension}"

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConversionError(
            f"Não foi possível usar a pasta de destino {directory}: {exc}"
        ) from exc

    counter = 2
    while True:
        try:
            os.close(os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            return candidate
        except FileExistsError:
            candidate = directory / f"{stem} ({counter}).{target.extension}"
            counter += 1
        except OSError as exc:
            raise ConversionError(
                f"Não foi possível criar o arquivo de saída em {directory}: {exc}"
            ) from exc


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
    device_args: list[str] = []
    video_encoder_args: list[str] = []
    filters: list[str] = []

    if needs_scaling(media, target):
        # -2 mantém a largura par: codecs H.264/HEVC exigem dimensões pares.
        filters.append(f"scale=-2:{target.height}")

    if codec == "copy":
        video_encoder_args = ["-c:v", "copy"]
    else:
        # Se hardware foi solicitado e a família possui acelerador
        if target.hardware != hwaccel.SOFTWARE and codec in ("h264", "hevc"):
            hw_enc = hwaccel.resolve(codec, target.hardware, tools)
            device_args = list(hw_enc.device)
            if hw_enc.filter_suffix:
                filters.append(hw_enc.filter_suffix)
            video_encoder_args = ["-c:v", hw_enc.name, *hw_enc.quality]
        else:
            encoder = _VIDEO_ENCODERS.get(codec)
            if encoder is None:
                raise ConversionError(f"Codec de vídeo não suportado: {codec}")
            video_encoder_args = ["-c:v", encoder, "-crf", str(target.crf)]
            if encoder in ("libx264", "libx265"):
                # yuv420p garante reprodução em reprodutores legados e navegadores
                video_encoder_args += ["-pix_fmt", "yuv420p"]
            if encoder == "libx264":
                video_encoder_args += ["-preset", "medium"]

    args = [
        tools.ffmpeg_str,
        "-nostdin",
        "-hide_banner",
        "-y",
        *device_args,
        "-i", str(media.path),
        "-map", "0:v:0",
    ]
    if media.has_audio:
        args += ["-map", "0:a:0"]

    args += video_encoder_args
    if filters:
        args += ["-vf", ",".join(filters)]
    if codec != "copy" and target.fps:
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
    if isinstance(target, Composition):
        # A composição não tem "arquivo de origem": as mídias estão dentro do
        # projeto, e ``media`` só existe aqui para as outras conversões.
        return export_args(
            target.project,
            destination,
            tools,
            container=target.container,
            family=target.family,
            hardware=target.hardware,
            interpolate=target.interpolate,
            audio_only=target.audio_only,
            audio_codec=target.audio_codec,
            quality=target.quality,
        )
    return build_video_args(media, target, destination, tools)


def output_duration(media: LocalMedia | None, target: ConversionTarget) -> float | None:
    """Duração que a saída vai ter — a régua do percentual de progresso.

    Só um recorte tem duração diferente da origem, e é justamente onde usar a
    duração do arquivo faria a barra parar em 3% numa tarefa concluída.
    """
    if isinstance(target, (TrimTarget, Composition)):
        return target.output_duration or None
    return media.duration if media else None


def describe_target(media: LocalMedia, target: ConversionTarget) -> str:
    """Resumo do que a conversão vai fazer, para exibir antes de começar."""
    if isinstance(target, Composition):
        return describe_export(
            target.project,
            target.container,
            target.hardware,
            target.interpolate,
            family=target.family,
            audio_only=target.audio_only,
            audio_codec=target.audio_codec,
            quality=target.quality,
        )
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
        if target.hardware != hwaccel.SOFTWARE and codec in ("h264", "hevc"):
            parts.append("placa de vídeo, se disponível")
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
# Verbo que a fila mostra enquanto a tarefa corre. Sai daqui, e não de um
# ``if`` no meio do laço de progresso, para acrescentar um alvo novo não exigir
# mexer no código que lê o ffmpeg.
_PHASES = {
    TrimTarget: "Recortando",
    Composition: "Exportando",
}

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
        self._parallel: ParallelExport | None = None
        self._cancelled = False
        self._postprocess = ProcessControl()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancelled = True
        self._postprocess.cancel()
        with self._lock:
            process = self._process
            parallel = self._parallel
        if process and process.poll() is None:
            process.terminate()
        if parallel is not None:
            parallel.cancel()

    def discard_reservation(self) -> None:
        """Devolve o nome reservado por :func:`output_path`, se nada foi gravado.

        Uma tarefa cancelada **antes de começar** nunca chega ao ``run``, e o
        arquivo vazio que segurava o nome dela ficaria na pasta do usuário como
        lixo — de zero byte, com o nome do resultado que ele não vai ter.

        Só remove o que está vazio: um arquivo com conteúdo é resultado de
        alguém e não se apaga por causa de uma reserva.
        """
        try:
            if self._destination.is_file() and self._destination.stat().st_size == 0:
                self._destination.unlink()
        except OSError:
            # Não poder limpar um arquivo vazio não é motivo para transformar um
            # cancelamento em falha.
            pass

    def _run_parallel(self, composition: Composition, segments: int) -> Path:
        """Entrega a exportação ao caminho de trechos paralelos.

        A referência é guardada porque o cancelamento chega por
        :meth:`cancel`, de outra thread, e precisa alcançar os processos de lá.
        """
        export = ParallelExport(
            composition,
            self._destination,
            self._tools,
            segments,
            on_progress=self._on_progress,
        )
        with self._lock:
            self._parallel = export
        if self._cancelled:
            # Cancelado entre a decisão e o registro: sem isto, os trechos
            # começariam depois de o usuário já ter desistido.
            raise JobCancelled("Conversão cancelada.")
        try:
            path = export.run()
        finally:
            with self._lock:
                self._parallel = None
        return path

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
                phase=_PHASES.get(type(self._target), "Convertendo"),
                percent=percent,
                downloaded_bytes=size,
                indeterminate=percent is None,
            )
        )

    def run(self) -> Path:
        # A interpolação é o único trabalho desta aplicação que não usa a máquina
        # inteira: o filtro é de uma thread só. Quando dá para dividi-la em
        # trechos paralelos, quem executa é outro caminho — e ``plan_segments``
        # devolve 1 sempre que dividir não vale ou não é seguro (ver
        # ``core/parallel_export.py``).
        if isinstance(self._target, Composition):
            segments = plan_segments(self._target)
            if segments > 1:
                return self._run_parallel(self._target, segments)

        # Renderiza num arquivo temporário na mesma pasta para evitar que o explorador
        # de arquivos (Nautilus/Nemo) tente gerar miniaturas em cima do arquivo 0-byte ou
        # incompleto e grave uma falha definitiva no cache de thumbnails.
        render_target = self._destination.with_name(f".tmp_{self._destination.name}")
        args = build_args(self._media, self._target, render_target, self._tools)
        self._destination.parent.mkdir(parents=True, exist_ok=True)

        kwargs = subprocess_kwargs()
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE

        try:
            process = subprocess.Popen(args, text=True, bufsize=1, **kwargs)
        except OSError as exc:
            render_target.unlink(missing_ok=True)
            self._destination.unlink(missing_ok=True)
            raise ConversionError(f"Não foi possível iniciar o ffmpeg: {exc}") from exc

        with self._lock:
            self._process = process
        if self._cancelled:
            # A desistência pode ter chegado entre o ``Popen`` e o registro: o
            # ``cancel`` daquele instante leu ``self._process`` como ``None`` e
            # não terminou nada. Sem esta conferência, a recuperação dependeria
            # de o ffmpeg emitir a próxima linha de progresso — o que não
            # acontece enquanto ele analisa uma entrada longa ou de rede, e nesse
            # intervalo ele segue gravando depois de o usuário ter desistido.
            # (Mesma conferência de ``ParallelExport._render``.)
            process.terminate()

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
            render_target.unlink(missing_ok=True)
            self._destination.unlink(missing_ok=True)
            raise JobCancelled("Conversão cancelada.")

        if process.returncode != 0:
            render_target.unlink(missing_ok=True)
            self._destination.unlink(missing_ok=True)
            detail = _last_error_line(stderr)
            raise ConversionError(f"O ffmpeg falhou na conversão: {detail}")

        # Vazio conta como ausente.
        if not render_target.is_file() or render_target.stat().st_size == 0:
            render_target.unlink(missing_ok=True)
            self._destination.unlink(missing_ok=True)
            raise ConversionError(
                "O ffmpeg terminou sem erro mas não gerou o arquivo de saída."
            )

        # Emite o banner (thumbnail) no arquivo exportado antes da substituição atômica.
        _is_video_export = not isinstance(self._target, AudioTarget)
        _audio_only = isinstance(self._target, Composition) and self._target.audio_only
        if _is_video_export and not _audio_only:
            try:
                embed_thumbnail(render_target, self._tools, control=self._postprocess)
            except JobCancelled:
                render_target.unlink(missing_ok=True)
                self.discard_reservation()
                raise
        try:
            self._postprocess.check()
        except JobCancelled:
            render_target.unlink(missing_ok=True)
            self.discard_reservation()
            raise

        import shutil
        shutil.move(str(render_target), str(self._destination))
        try:
            os.utime(str(self._destination), None)
        except OSError:
            pass

        return self._destination


def _last_error_line(stderr: str) -> str:
    """Última linha significativa do stderr — onde o ffmpeg diz a causa."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    return lines[-1] if lines else "erro não informado"
