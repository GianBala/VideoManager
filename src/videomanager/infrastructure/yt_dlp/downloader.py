"""Execução de um download, com progresso e cancelamento.

Cada download roda numa instância nova de ``YoutubeDL``. Não é desperdício: as
opções (formato, container, postprocessors) variam por tarefa, e compartilhar uma
instância entre downloads simultâneos misturaria estado.

O download refaz a extração pela URL em vez de reaproveitar a análise já feita na
interface. Isso é deliberado: muitas plataformas assinam as URLs de mídia com
validade curta, então reaproveitar uma análise de dez minutos atrás falharia com
403. Uma requisição extra é preço barato por um download que funciona.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadCancelled, DownloadError, ExtractorError

from videomanager.application.errors import DownloadFailedError
from videomanager.application.errors import JobCancelled
from videomanager.application.errors import error_message
from videomanager.domain.i18n import Text, t
from videomanager.infrastructure.yt_dlp.extras import TolerantEmbedThumbnailPP
from videomanager.infrastructure.yt_dlp.extras import split_thumbnail_postprocessor
from videomanager.infrastructure.yt_dlp.probe import _translate_error

from videomanager.application.events import Progress as Progress
from videomanager.application.events import ProgressStage
from videomanager.application.events import DownloadResult as DownloadResult


ProgressCallback = Callable[[Progress], None]

_PHASE_LABELS = {
    "FFmpegMerger": "PHASE_MERGING",
    "FFmpegExtractAudio": "PHASE_EXTRACTING_AUDIO",
    "FFmpegVideoConvertor": "PHASE_CONVERTING_VIDEO",
    "FFmpegVideoRemuxer": "PHASE_REMUXING",
    "FFmpegMetadata": "PHASE_METADATA",
    "EmbedThumbnail": "PHASE_THUMBNAIL",
    "FFmpegEmbedSubtitle": "PHASE_SUBTITLES",
    "MoveFiles": "PHASE_MOVING",
}


class _JobLogger:
    """Captura as mensagens do yt-dlp para a aba de detalhes da tarefa."""

    def __init__(self, limit: int = 400) -> None:
        self.lines: list[str] = []
        self._limit = limit

    def _add(self, text: str) -> None:
        self.lines.append(text)
        if len(self.lines) > self._limit:
            # Mantém as últimas linhas: o fim de um log de erro é onde está a causa.
            del self.lines[: len(self.lines) - self._limit]

    def debug(self, msg: str) -> None:
        # O yt-dlp manda mensagens de info por debug() com prefixo "[debug] ".
        if not msg.startswith("[debug] "):
            self._add(msg)

    def info(self, msg: str) -> None:
        self._add(msg)

    # O log é registro do que aconteceu: a linha sai no idioma do momento.
    def warning(self, msg: str) -> None:
        self._add(t("LOG_WARNING", message=msg))

    def error(self, msg: str) -> None:
        self._add(t("LOG_ERROR", message=msg))


def _percent(downloaded: int | None, total: int | None) -> float | None:
    if not downloaded or not total or total <= 0:
        return None
    return min(100.0, downloaded * 100.0 / total)


class Downloader:
    """Um download cancelável.

    Uso típico, dentro de uma thread de trabalho::

        downloader = Downloader(opts, on_progress=emitir_sinal)
        try:
            resultado = downloader.run(url)
        except JobCancelled:
            ...
    """

    def __init__(
        self,
        opts: dict[str, Any],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._opts = dict(opts)
        self._on_progress = on_progress
        self._cancelled = False
        self._logger = _JobLogger()
        self._final_path: Path | None = None

    # -- controle ---------------------------------------------------------

    def cancel(self) -> None:
        """Pede o cancelamento.

        O efeito é assíncrono: o download para no próximo hook de progresso,
        onde a exceção pode ser levantada de dentro do yt-dlp com segurança.
        Interromper de fora deixaria arquivos temporários órfãos.
        """
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def log(self) -> tuple[str, ...]:
        return tuple(self._logger.lines)

    # -- hooks ------------------------------------------------------------

    def _check_cancel(self) -> None:
        if self._cancelled:
            # Exceção reconhecida pelo yt-dlp, que então limpa os temporários.
            raise DownloadCancelled("cancelado pelo usuário")

    def _progress_hook(self, data: dict[str, Any]) -> None:
        self._check_cancel()
        if self._on_progress is None:
            return

        status = data.get("status")
        if status == "finished":
            self._on_progress(
                Progress(phase=Text("PHASE_DOWNLOADED"), percent=100.0, indeterminate=True)
            )
            return
        if status == "error":
            return  # a exceção vem por outro caminho; nada a reportar aqui
        if status != "downloading":
            return

        downloaded = data.get("downloaded_bytes")
        total = data.get("total_bytes")
        estimate = False
        if not total:
            total = data.get("total_bytes_estimate")
            estimate = bool(total)

        fragment_index = data.get("fragment_index")
        fragment_count = data.get("fragment_count")

        percent = _percent(downloaded, total)
        # Em HLS/DASH sem tamanho total, a contagem de fragmentos é o único
        # sinal de progresso confiável que existe.
        if percent is None and fragment_index and fragment_count:
            percent = min(100.0, fragment_index * 100.0 / fragment_count)

        self._on_progress(
            Progress(
                phase=Text("PHASE_DOWNLOADING"),
                stage=ProgressStage.DOWNLOAD,
                percent=percent,
                downloaded_bytes=downloaded if isinstance(downloaded, int) else None,
                total_bytes=total if isinstance(total, int) else None,
                total_is_estimate=estimate,
                speed=data.get("speed"),
                eta=data.get("eta"),
                fragment_index=fragment_index if isinstance(fragment_index, int) else None,
                fragment_count=fragment_count if isinstance(fragment_count, int) else None,
                indeterminate=percent is None,
            )
        )

    def _postprocessor_hook(self, data: dict[str, Any]) -> None:
        """Reporta as etapas de pós-processamento.

        Sem isto a barra fica parada em 100% durante o ffmpeg — que num vídeo
        longo leva minutos e passa a impressão de travamento.
        """
        self._check_cancel()
        if self._on_progress is None or data.get("status") != "started":
            return
        name = str(data.get("postprocessor") or "")
        label = Text(_PHASE_LABELS.get(name, "PHASE_PROCESSING"))
        self._on_progress(Progress(phase=label, percent=None, indeterminate=True))

    # -- execução ---------------------------------------------------------

    def _capture_path(self, info: dict[str, Any]) -> None:
        """Descobre o caminho final do arquivo produzido.

        ``requested_downloads[0]['filepath']`` é atualizado pelo yt-dlp após os
        postprocessors, então reflete a extensão final — e não a do stream
        baixado, que muda quando o áudio é extraído ou o container é trocado.
        """
        requested = info.get("requested_downloads")
        if isinstance(requested, list) and requested:
            entry = requested[0]
            if isinstance(entry, dict):
                path = entry.get("filepath") or entry.get("_filename")
                if path:
                    self._final_path = Path(str(path))
                    return
        path = info.get("filepath") or info.get("_filename")
        if path:
            self._final_path = Path(str(path))

    def run(self, url: str) -> DownloadResult:
        """Baixa a URL. Levanta :class:`JobCancelled` se cancelado."""
        opts, thumbnail = split_thumbnail_postprocessor(dict(self._opts))
        opts["logger"] = self._logger
        opts["progress_hooks"] = [self._progress_hook]
        opts["postprocessor_hooks"] = [self._postprocessor_hook]

        title = url
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                if thumbnail is not None:
                    ydl.add_post_processor(TolerantEmbedThumbnailPP(ydl, **thumbnail), when="post_process")
                info = ydl.extract_info(url, download=True)
                if isinstance(info, dict):
                    title = str(info.get("title") or url)
                    self._capture_path(info)
        except DownloadCancelled as exc:
            raise JobCancelled("Download cancelado.") from exc
        except (DownloadError, ExtractorError) as exc:
            # Cancelar durante o pós-processamento chega embrulhado em
            # DownloadError, então a checagem de cancelamento vem primeiro.
            if self._cancelled:
                raise JobCancelled("Download cancelado.") from exc
            translated = _translate_error(exc, Text("ACTION_DOWNLOAD"))
            raise DownloadFailedError(error_message(translated)) from exc
        except OSError as exc:
            raise DownloadFailedError(Text("DOWNLOAD_WRITE_FAILED", error=str(exc))) from exc

        if self._cancelled:
            raise JobCancelled("Download cancelado.")

        return DownloadResult(path=self._final_path, title=title, log=self.log)

__all__ = [
    'DownloadFailedError',
    'JobCancelled',
    'Progress',
    'ProgressStage',
    'DownloadResult',
]
