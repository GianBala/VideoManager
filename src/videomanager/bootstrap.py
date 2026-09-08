"""Montagem explícita dos serviços; nenhum caso de uso constrói adaptadores."""
from videomanager.application.editor.service import EditorService
from videomanager.infrastructure.storage.projects import JsonProjectRepository


def load_preferences():
    from dataclasses import asdict
    from videomanager.application.preferences import Preferences
    from videomanager.infrastructure.storage.settings import Settings
    return Preferences.from_dict(asdict(Settings.load()))


def build_editor_service() -> EditorService:
    return EditorService(JsonProjectRepository(), rasterizer=build_text_rasterizer())


def build_processing_service():
    from videomanager.application.media.processing import ProcessingService
    from videomanager.infrastructure.ffmpeg.catalog import FFmpegCatalog
    from videomanager.infrastructure.storage.outputs import FileOutputStore
    return ProcessingService(FFmpegCatalog(), FileOutputStore(), build_text_rasterizer())


def build_download_service():
    from videomanager.application.media.downloads import DownloadService
    from videomanager.infrastructure.yt_dlp.gateway import YtDlpGateway
    return DownloadService(YtDlpGateway())


def build_text_rasterizer():
    from videomanager.infrastructure.qt.text import QtTextRasterizer
    return QtTextRasterizer()


def build_desktop_runtime(*, audio_enabled=True):
    from videomanager.infrastructure.qt.runtime import DesktopRuntime
    return DesktopRuntime(audio_enabled=audio_enabled)
