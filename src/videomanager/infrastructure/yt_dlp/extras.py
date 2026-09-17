"""Ajustes do yt-dlp que dependem do ambiente e não do pedido.

Ficam separados de ``selector`` e ``probe`` porque os dois precisam deles, e
porque tratam de peças externas ao yt-dlp — o runtime JavaScript e a capa, que
depende do mutagen — cuja ausência não pode derrubar a tarefa.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from yt_dlp.postprocessor.embedthumbnail import EmbedThumbnailPP
from yt_dlp.utils import PostProcessingError, prepend_extension, replace_extension

from videomanager.infrastructure.system.binaries import find_js_runtime

_LOG = logging.getLogger(__name__)

THUMBNAIL_KEY = "EmbedThumbnail"


def js_runtime_opts() -> dict[str, Any]:
    """``js_runtimes`` para o runtime disponível, ou nada se não houver.

    Sem esta opção o yt-dlp só tenta o Deno do ``PATH``: o Deno empacotado e o
    Node instalado ficavam de fora, e o YouTube perdia formatos.
    """
    found = find_js_runtime()
    if found is None:
        return {}
    name, path = found
    return {"js_runtimes": {name: {"path": str(path)}}}


class TolerantEmbedThumbnailPP(EmbedThumbnailPP):
    """Embute a capa quando dá; quando não dá, o download continua valendo.

    O ``EmbedThumbnail`` do yt-dlp levanta erro para container sem suporte
    (webm, wav) e para ogg/opus/flac sem o mutagen. Como ele roda depois de o
    arquivo estar pronto, o erro transformava um download bem-sucedido em
    tarefa falha — com o arquivo esquecido na pasta temporária. A capa é
    cosmética; perder o vídeo por ela, não.
    """

    @classmethod
    def pp_key(cls) -> str:
        # Mesmo nome do original: é por ele que a fila mostra "Embutindo a capa".
        return THUMBNAIL_KEY

    def run(self, info):
        try:
            return super().run(info)
        except PostProcessingError as exc:
            self.report_warning(f"A capa não foi embutida: {exc}")
            _LOG.warning("Capa não embutida em %s: %s", info.get("filepath"), exc)
            leftovers = []
            filepath = info.get("filepath")
            if filepath:
                temporary = prepend_extension(filepath, "temp")
                if os.path.exists(temporary):
                    leftovers.append(temporary)
            if not self._already_have_thumbnail:
                for thumb in info.get("thumbnails") or ():
                    original = thumb.get("filepath")
                    if not original:
                        continue
                    # Antes de recusar o container, o yt-dlp já converteu a
                    # capa (webp → png); a cópia convertida não fica registrada
                    # em ``thumbnails`` e sobrava na pasta temporária.
                    candidates = {original, *(replace_extension(original, ext) for ext in ("png", "jpg"))}
                    leftovers.extend(path for path in sorted(candidates) if os.path.exists(path))
            return leftovers, info


def split_thumbnail_postprocessor(opts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Tira o ``EmbedThumbnail`` das opções para registrá-lo tolerante.

    O yt-dlp só instancia postprocessors pelo nome; a versão tolerante precisa
    ser acrescentada à instância. Ela entra por último, que é também a ordem da
    linha de comando do yt-dlp: a capa depois de legendas e metadados, que
    reescrevem o container.
    """
    processors = list(opts.get("postprocessors") or ())
    found = next((pp for pp in processors if pp.get("key") == THUMBNAIL_KEY), None)
    if found is None:
        return opts, None
    remaining = dict(opts)
    remaining["postprocessors"] = [pp for pp in processors if pp is not found]
    arguments = {key: value for key, value in found.items() if key not in ("key", "when")}
    return remaining, arguments
