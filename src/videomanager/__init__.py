"""Video Manager — baixa, converte e edita vídeo e áudio, e ajusta metadados."""

import sys
from pathlib import Path

__version__ = "3.1"
APP_NAME = "VideoManager"
APP_DISPLAY_NAME = "Video Manager"
APP_TITLE = f"{APP_DISPLAY_NAME} {__version__}"
# Onde o usuário do pacote busca versão nova: no pacote o yt-dlp vem congelado,
# e quando um site muda, só uma versão nova do aplicativo traz o extrator novo.
RELEASES_URL = "https://github.com/GianBala/VideoManager/releases"
ISSUES_URL = "https://github.com/GianBala/VideoManager/issues"


def build_commit() -> str | None:
    """O ``git describe`` que o build gravou no pacote; ``None`` no código-fonte.

    "3.1" vale para vários commits: sem isto, um relato de campo não diz qual
    o usuário roda. O Sobre e a linha de partida do log o mostram.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        return None
    try:
        return (Path(base) / "resources" / "build_commit.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None
