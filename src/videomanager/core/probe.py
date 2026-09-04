"""Análise de uma URL: descobrir o que existe antes de baixar qualquer coisa.

Faz uma extração sem download (``download=False``) e converte a resposta crua num
:class:`MediaInfo` ou :class:`PlaylistInfo`. Também traduz as exceções do yt-dlp
em erros do domínio com mensagem apresentável — a camada de interface nunca deve
mostrar um traceback nem uma mensagem em inglês vinda do extrator.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError, GeoRestrictedError, UnsupportedError

from .errors import DrmProtectedError, NoFormatsError, ProbeError, UnsupportedUrlError
from .format_matrix import build_matrix
from .models import MediaInfo, PlaylistEntry, PlaylistInfo, SubtitleTrack
from .settings import Settings


class _QuietLogger:
    """Silencia o yt-dlp e guarda as mensagens para diagnóstico.

    Sem isto, o yt-dlp escreve no stdout — que num aplicativo empacotado com
    ``--windowed`` no Windows não existe, e a escrita pode falhar.
    """

    def __init__(self) -> None:
        self.messages: list[str] = []

    def debug(self, msg: str) -> None:
        self.messages.append(msg)

    def info(self, msg: str) -> None:
        self.messages.append(msg)

    def warning(self, msg: str) -> None:
        self.messages.append(f"aviso: {msg}")

    def error(self, msg: str) -> None:
        self.messages.append(f"erro: {msg}")


def _probe_opts(settings: Settings, *, flat_playlist: bool) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "logger": _QuietLogger(),
        # Numa playlist, resolver cada item exigiria uma requisição por vídeo —
        # inviável para um canal com centenas. Listamos superficialmente e só
        # analisamos em detalhe o que o usuário marcar.
        "extract_flat": "in_playlist" if flat_playlist else False,
    }
    if settings.cookies_file and Path(settings.cookies_file).is_file():
        opts["cookiefile"] = str(Path(settings.cookies_file).resolve())
    elif settings.cookies_browser:
        opts["cookiesfrombrowser"] = (settings.cookies_browser, None, None, None)
    return opts


# Trechos de mensagens do yt-dlp que já sabemos traduzir. Casados em minúsculas.
_LOGIN_HINTS = (
    "sign in",
    "log in",
    "login required",
    "private video",
    "members-only",
    "requires authentication",
    "confirm your age",
    "age-restricted",
    # Formas específicas do extrator do Instagram: ele nunca diz "login
    # required" nesses casos, mas o problema é o mesmo — sem cookies, o
    # Instagram redireciona anônimos para a tela de login após poucos pedidos.
    "redirected to the login page",
    "rate-limit for accessing posts anonymously",
    "empty media response",
    "only available for registered users",
)


def _translate_error(exc: Exception) -> ProbeError:
    """Converte um erro do yt-dlp em algo que o usuário consiga agir sobre."""
    message = str(exc)
    lowered = message.lower()

    if isinstance(exc, UnsupportedError) or "unsupported url" in lowered:
        return UnsupportedUrlError(
            "Nenhum extrator reconhece esta URL. Confira o endereço; se o site "
            "for novo, atualizar a engine em Configurações pode resolver."
        )

    if "drm" in lowered:
        return DrmProtectedError(
            "Esta mídia é protegida por DRM e não pode ser baixada."
        )

    if any(hint in lowered for hint in _LOGIN_HINTS):
        return ProbeError(
            "Esta mídia exige conta conectada (privada, de membros ou com "
            "restrição de idade). Em Configurações, escolha o navegador em que "
            "você já está logado para que os cookies sejam usados."
        )

    if isinstance(exc, GeoRestrictedError) or "not available in your country" in lowered:
        return ProbeError(
            "Esta mídia está bloqueada na sua região."
        )

    if "video unavailable" in lowered or "has been removed" in lowered:
        return ProbeError("Esta mídia não está mais disponível.")

    if any(hint in lowered for hint in ("timed out", "timeout", "connection", "network", "resolve")):
        return ProbeError(
            "Não foi possível conectar. Verifique sua conexão e tente novamente."
        )

    # Sem tradução conhecida: entrega a mensagem original, limpa do prefixo que o
    # yt-dlp acrescenta. Uma mensagem técnica é melhor que uma genérica.
    cleaned = re.sub(r"^ERROR:\s*", "", message).strip()
    return ProbeError(f"Falha ao analisar a URL: {cleaned}")


def _subtitle_tracks(info: dict[str, Any]) -> tuple[SubtitleTrack, ...]:
    tracks: list[SubtitleTrack] = []
    for is_auto, key in ((False, "subtitles"), (True, "automatic_captions")):
        container = info.get(key)
        if not isinstance(container, dict):
            continue
        for lang, variants in container.items():
            name = lang
            if isinstance(variants, list) and variants:
                first = variants[0]
                if isinstance(first, dict):
                    name = str(first.get("name") or lang)
            tracks.append(SubtitleTrack(lang=str(lang), name=name, is_auto=is_auto))
    # Manuais antes das automáticas, que são transcrições e têm erros.
    tracks.sort(key=lambda t: (t.is_auto, t.lang))
    return tuple(tracks)


def _as_playlist(info: dict[str, Any], url: str) -> PlaylistInfo:
    entries: list[PlaylistEntry] = []
    raw_entries = info.get("entries") or []
    for index, entry in enumerate(raw_entries, start=1):
        if not isinstance(entry, dict):
            continue
        entry_url = entry.get("url") or entry.get("webpage_url") or entry.get("id")
        if not entry_url:
            continue
        duration = entry.get("duration")
        entries.append(
            PlaylistEntry(
                url=str(entry_url),
                title=str(entry.get("title") or f"Item {index}"),
                index=index,
                media_id=str(entry.get("id") or ""),
                duration=float(duration) if isinstance(duration, (int, float)) else None,
            )
        )
    return PlaylistInfo(
        url=url,
        title=str(info.get("title") or "Playlist"),
        entries=tuple(entries),
        extractor=str(info.get("extractor_key") or info.get("extractor") or ""),
        uploader=str(info.get("uploader") or info.get("channel") or ""),
    )


def media_from_info(info: dict[str, Any], url: str = "") -> MediaInfo:
    """Constrói um :class:`MediaInfo` a partir de uma resposta já extraída.

    Separado de :func:`probe` para que os testes possam usar respostas gravadas
    em arquivo, sem tocar na rede.
    """
    matrix = build_matrix(info.get("formats"))

    # Alguns extratores devolvem uma mídia de formato único sem a lista
    # ``formats``, colocando url/codecs direto na raiz. Nesse caso a própria raiz
    # é o formato.
    if matrix.is_empty and info.get("url"):
        matrix = build_matrix([info])

    duration = info.get("duration")
    return MediaInfo(
        url=str(info.get("webpage_url") or url),
        title=str(info.get("title") or "Sem título"),
        matrix=matrix,
        media_id=str(info.get("id") or ""),
        extractor=str(info.get("extractor_key") or info.get("extractor") or ""),
        uploader=str(info.get("uploader") or info.get("channel") or ""),
        duration=float(duration) if isinstance(duration, (int, float)) else None,
        thumbnail_url=str(info.get("thumbnail") or ""),
        is_live=bool(info.get("is_live")),
        subtitles=_subtitle_tracks(info),
        raw=info,
    )


def probe(
    url: str,
    settings: Settings | None = None,
    *,
    flat_playlist: bool = True,
) -> MediaInfo | PlaylistInfo:
    """Analisa uma URL sem baixar nada.

    Devolve :class:`PlaylistInfo` para playlists e canais, ou :class:`MediaInfo`
    para uma mídia única.
    """
    url = url.strip()
    if not url:
        raise ProbeError("Informe uma URL.")

    settings = settings or Settings()
    try:
        with yt_dlp.YoutubeDL(_probe_opts(settings, flat_playlist=flat_playlist)) as ydl:
            info = ydl.extract_info(url, download=False)
            # sanitize_info remove objetos não serializáveis, o que permite
            # guardar a resposta em disco (gravação de fixtures e diagnóstico).
            info = ydl.sanitize_info(info)
    except (DownloadError, ExtractorError) as exc:
        raise _translate_error(exc) from exc
    except OSError as exc:
        raise ProbeError(f"Falha de rede ao analisar a URL: {exc}") from exc

    if not isinstance(info, dict):
        raise ProbeError("O extrator não devolveu informação utilizável.")

    if info.get("_type") in ("playlist", "multi_video"):
        playlist = _as_playlist(info, url)
        if not playlist.entries:
            raise NoFormatsError("Esta playlist está vazia ou é inacessível.")
        return playlist

    media = media_from_info(info, url)

    if media.matrix.is_empty:
        if media.matrix.drm_blocked:
            raise DrmProtectedError(
                "Todos os formatos desta mídia são protegidos por DRM."
            )
        if media.is_live:
            raise NoFormatsError(
                "Esta transmissão ao vivo ainda não oferece formatos para baixar. "
                "Tente novamente depois que ela começar."
            )
        raise NoFormatsError(
            "A URL foi reconhecida, mas nenhum formato utilizável foi oferecido. "
            "Se a mídia exige login, configure o navegador para leitura de cookies."
        )

    return media
