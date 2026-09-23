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
import tempfile
from collections import deque
from collections.abc import Callable
from pathlib import Path

from videomanager.infrastructure.ffmpeg.command_assets import filter_script
from videomanager.infrastructure.storage.outputs import FileOutputStore
from videomanager.application.ports.output import OutputLease

from videomanager.infrastructure.ffmpeg import hardware as hwaccel
from videomanager.application.capabilities import FFmpegTools
from videomanager.infrastructure.system.binaries import subprocess_kwargs
from videomanager.application.events import Progress
from videomanager.application.errors import ConversionError
from videomanager.infrastructure.system.process import ProcessControl, terminate_and_wait, terminate_async
from videomanager.domain.composition import Composition
from videomanager.infrastructure.ffmpeg.composer import export_args
from videomanager.infrastructure.ffmpeg.parallel import ParallelExport
from videomanager.infrastructure.ffmpeg.parallel import plan_segments
from videomanager.infrastructure.ffmpeg.thumbnail import embed_thumbnail
from videomanager.domain.timing import TrimTarget
from videomanager.infrastructure.ffmpeg.trimmer import build_trim_args

from videomanager.domain.media import LocalStream
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import VideoTarget

from videomanager.domain.compatibility import can_copy_audio
from videomanager.domain.compatibility import needs_scaling
from videomanager.domain.compatibility import is_portrait
from videomanager.domain.compatibility import resolved_video_codec
from videomanager.domain.compatibility import resolved_audio_codec


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

# Formatos sem perda: pedir bitrate não faz sentido.

# Nomes de codec que o ffprobe reporta, por codec pedido. Usado para decidir se
# a cópia direta é possível.

# PCM de origem com mais de 16 bits: o WAV de saída sobe para 24.
_HIGH_RES_PCM = ("pcm_s24", "pcm_s32", "pcm_f32", "pcm_f64")

_VIDEO_ENCODERS = {
    "h264": "libx264",
    "hevc": "libx265",
    "vp9": "libvpx-vp9",
    "av1": "libsvtav1",
}


# O que cada container aceita guardar. ``None`` = aceita qualquer coisa, que é o
# caso do MKV. Os nomes são os que o ffprobe reporta em ``codec_name``.
# Sem esta tabela, "copiar sem recodificar" para .webm produzia um erro cru do
# ffmpeg ("Only VP8/VP9/AV1 video and Vorbis/Opus audio are supported") depois de
# a tarefa já estar na fila — quando dava para saber antes de começar.
# Para onde recodificar quando a cópia não cabe no container pedido.


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
                rotation=_display_rotation(raw),
                attached_picture=bool((raw.get('disposition') or {}).get('attached_pic')),
                duration=_stream_duration(raw),
            )
        )

    return LocalMedia(
        path=path,
        duration=_float(container.get("duration")),
        format_name=str(container.get("format_name") or "desconhecido"),
        size=_int(container.get("size")),
        streams=tuple(streams),
    )


def _stream_duration(raw: dict) -> float | None:
    """Duração da trilha: o campo do MP4 ou, no MKV, a etiqueta DURATION."""
    value = _float(raw.get("duration"))
    if value:
        return value
    tag = next((v for k, v in (raw.get("tags") or {}).items() if str(k).upper() == "DURATION"), None)
    try:
        hours, minutes, seconds = str(tag).split(":")
        total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (ValueError, TypeError):
        return None
    return total if total > 0 else None


def _display_rotation(raw: dict) -> float:
    """FFmpeg aplica autorotate; os metadados só orientam a geometria da UI."""
    import math
    value = next((item.get('rotation') for item in raw.get('side_data_list', [])
                  if isinstance(item, dict) and item.get('rotation') is not None),
                 (raw.get('tags') or {}).get('rotate', 0))
    try:
        angle = float(value)
    except (ValueError, TypeError, OverflowError):
        return 0.0
    return angle if math.isfinite(angle) else 0.0


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
        if encoder == "pcm_s16le" and media.audio and media.audio.codec.lower().startswith(_HIGH_RES_PCM):
            # WAV é anunciado como "sem perda": uma origem de 24 bits ou
            # ponto flutuante reduzida a 16 bits perdia resolução em silêncio.
            encoder = "pcm_s24le"
        args += ["-c:a", encoder]
        if not target.is_lossless:
            args += ["-b:a", f"{target.bitrate}k"]

    if target.codec == "mp3":
        # Sem ID3v2.3 o Windows Explorer não mostra título nem artista.
        args += ["-id3v2_version", "3"]

    args += ["-map_metadata", "0", "-progress", "pipe:1", "-nostats", str(destination)]
    return args


# Legendas que o MKV aceita copiadas. ``mov_text`` (a legenda do MP4) fica de
# fora: copiá-la para MKV é recusado pelo muxer, e convertê-la mudaria o que o
# usuário pediu como cópia.
_MKV_COPYABLE_SUBTITLES = {
    "subrip", "srt", "ass", "ssa", "webvtt", "hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle",
}


def _count(media: LocalMedia, kind: str) -> int:
    return sum(1 for stream in media.streams if stream.kind == kind)


def _mkv_extra_streams(media: LocalMedia) -> tuple[str, ...]:
    """Legendas e anexos (fontes do ASS) que uma saída MKV pode manter."""
    extras: list[str] = []
    subtitles = [s for s in media.streams if s.kind == "subtitle"]
    if subtitles and all(s.codec.lower() in _MKV_COPYABLE_SUBTITLES for s in subtitles):
        extras.append("s")
    if _count(media, "attachment"):
        extras.append("t")
    return tuple(extras)


def build_video_args(
    media: LocalMedia, target: VideoTarget, destination: Path, tools: FFmpegTools
) -> list[str]:
    """Argumentos do ffmpeg para converter vídeo."""
    if not media.has_video:
        raise ConversionError(
            f"“{media.path.name}” não tem trilha de vídeo. Use a conversão para áudio."
        )

    codec = resolved_video_codec(media, target)
    device_args: list[str] = []
    video_encoder_args: list[str] = []
    filters: list[str] = []

    if needs_scaling(media, target):
        # -2 mantém o outro lado par: codecs H.264/HEVC exigem dimensões pares.
        # A resolução pedida é o lado curto, que num retrato é a largura.
        if is_portrait(media):
            filters.append(f"scale={target.height}:-2")
        else:
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
        # "V" maiúsculo exclui capas (attached_pic): com "v", um arquivo cuja
        # capa vinha antes do vídeo virava um vídeo de um quadro só.
        "-map", "0:V:0",
    ]
    extras = _mkv_extra_streams(media) if target.container == "mkv" else ()
    if media.has_audio:
        # O MKV guarda qualquer faixa: todas as de áudio seguem. Os outros
        # containers ficam com a primeira, e a descrição avisa.
        args += ["-map", "0:a?" if target.container == "mkv" and _count(media, "audio") > 1 else "0:a:0"]
    for kind in extras:
        args += ["-map", f"0:{kind}?"]

    args += video_encoder_args
    if filters:
        args += ["-vf", ",".join(filters)]
    if codec != "copy" and target.fps:
        args += ["-r", str(target.fps)]
    if target.container in ("mp4", "mov") and (codec == "hevc" or (
            codec == "copy" and media.video is not None and media.video.codec.lower() == "hevc")):
        # Sem a etiqueta hvc1 o HEVC em MP4 não abre no QuickTime, em aparelhos
        # Apple nem no app Filmes e TV do Windows; o ffmpeg grava hev1.
        args += ["-tag:v", "hvc1"]
    for kind in extras:
        args += [f"-c:{kind}", "copy"]

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
    media: LocalMedia,
    target: ConversionTarget,
    destination: Path,
    tools: FFmpegTools,
    *,
    text_assets: dict[int, Path] | None = None,
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
         text_assets=text_assets)
    return build_video_args(media, target, destination, tools)


def output_duration(media: LocalMedia | None, target: ConversionTarget) -> float | None:
    """Duração que a saída vai ter — a régua do percentual de progresso.

    Só um recorte tem duração diferente da origem, e é justamente onde usar a
    duração do arquivo faria a barra parar em 3% numa tarefa concluída.
    """
    if isinstance(target, (TrimTarget, Composition)):
        return target.output_duration or None
    return media.duration if media else None


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
        text_assets: dict[int, Path] | None = None,
        lease: OutputLease | None = None,
    ) -> None:
        self._text_assets = text_assets
        self._media = media
        self._target = target
        self._destination = destination
        self._outputs = FileOutputStore()
        self._lease = lease
        self._tools = tools
        self._on_progress = on_progress
        self._process: subprocess.Popen | None = None
        self._parallel: ParallelExport | None = None
        self._cancelled = False
        self._postprocess = ProcessControl()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            self._postprocess.cancel()
            process = self._process
            parallel = self._parallel
        if process and process.poll() is None:
            terminate_async(process)
        if parallel is not None:
            parallel.cancel()

    def discard_reservation(self) -> None:
        """Devolve somente a reserva ainda pertencente à tentativa."""
        self._outputs.abort(self._destination, lease=self._lease)

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
         text_assets=self._text_assets, lease=self._lease)
        with self._lock:
            self._parallel = export
        try:
            self._postprocess.check()
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
        render_target: Path | None = None
        try:
            self._postprocess.check()
            if isinstance(self._target, Composition):
                segments = plan_segments(self._target)
                if segments > 1:
                    return self._run_parallel(self._target, segments)

            # Exclusivo e no mesmo volume: não colide com outra tarefa e a
            # publicação continua sendo uma substituição atômica.
            self._destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(
                prefix=".videomanager-", suffix=self._destination.suffix,
                dir=self._destination.parent,
            )
            os.close(descriptor)
            render_target = Path(name)
            return self._run_serial(render_target)
        except BaseException:
            self.discard_reservation()
            raise
        finally:
            if render_target is not None:
                render_target.unlink(missing_ok=True)

    def _run_serial(self, render_target: Path) -> Path:
        args = build_args(self._media, self._target, render_target, self._tools,
                          text_assets=self._text_assets)
        with filter_script(args, render_target.parent) as prepared:
            return self._execute_serial(prepared, render_target)

    def _execute_serial(self, args: list[str], render_target: Path) -> Path:
        self._postprocess.check()
        kwargs = subprocess_kwargs()
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE

        try:
            # UTF-8 explícito: o padrão do Windows é cp1252, e o ffmpeg imprime
            # título e descrição em UTF-8. Um caractere fora da tabela matava a
            # thread que drena o stderr; o cano enchia e o ffmpeg parava para
            # sempre, segurando a fila de processamento, que tem uma vaga só.
            process = subprocess.Popen(args, text=True, bufsize=1, encoding="utf-8",
                                       errors="replace", **kwargs)
        except OSError as exc:
            render_target.unlink(missing_ok=True)
            self._outputs.abort(self._destination, lease=self._lease)
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
            terminate_async(process)

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
                    terminate_async(process)
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
            # Também cobre falhas no leitor e no callback de progresso. Um
            # filho vivo não pode ficar gravando depois da limpeza da saída.
            terminate_and_wait(process)
            drain.join(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            with self._lock:
                self._process = None

        self._postprocess.check()
        if process.returncode != 0:
            detail = _last_error_line(stderr)
            raise ConversionError(f"O ffmpeg falhou na conversão: {detail}")
        if not render_target.is_file() or render_target.stat().st_size == 0:
            raise ConversionError(
                "O ffmpeg terminou sem erro mas não gerou o arquivo de saída."
            )

        is_video = not isinstance(self._target, AudioTarget)
        audio_only = isinstance(self._target, Composition) and self._target.audio_only
        if is_video and not audio_only:
            embed_thumbnail(render_target, self._tools, control=self._postprocess)
        with self._lock:
            self._postprocess.check()
            self._outputs.commit(render_target, self._destination, lease=self._lease)
        try:
            os.utime(str(self._destination), None)
        except OSError:
            pass

        return self._destination


def _last_error_line(stderr: str) -> str:
    """Última linha significativa do stderr — onde o ffmpeg diz a causa."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    return lines[-1] if lines else "erro não informado"
