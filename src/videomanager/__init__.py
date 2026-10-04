"""Video Manager — downloader e conversor de vídeo/áudio multiplataforma."""

__version__ = "3.1"
APP_NAME = "VideoManager"
APP_DISPLAY_NAME = "Video Manager"
APP_TITLE = f"{APP_DISPLAY_NAME} {__version__}"
# Onde o usuário do pacote busca versão nova: no pacote o yt-dlp vem congelado,
# e quando um site muda, só uma versão nova do aplicativo traz o extrator novo.
RELEASES_URL = "https://github.com/GianBala/VideoManager/releases"
ISSUES_URL = "https://github.com/GianBala/VideoManager/issues"
