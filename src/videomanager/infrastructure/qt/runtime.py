"""Fábrica dos adaptadores desktop injetada na apresentação pelo bootstrap.

Não guarda sessão nem estado de tarefas. Conecta pedidos da aplicação às
implementações Qt/ffmpeg e concentra consultas ao ambiente desktop.
"""
from pathlib import Path
import subprocess
import sys
from dataclasses import asdict
from platformdirs import user_cache_dir
from videomanager import APP_NAME
from videomanager.application.media.preview import prepare_preview
from videomanager.infrastructure.ffmpeg import hardware, composer
from videomanager.infrastructure.system import binaries
from videomanager.infrastructure.storage.settings import Settings
from .audio import AudioPreview
from .workers.queue import JobQueue
from .workers.media_worker import MediaWorker
from .workers.function_worker import FunctionWorker
from .workers.preview_worker import FrameWorker, PlaybackWorker, FilmstripWorker, WaveformWorker, KeyframeWorker
from .workers.engine_worker import FFmpegSetupWorker, EngineUpdateWorker, is_packaged
from .workers.hwaccel_worker import HardwareProbeWorker
from .workers.probe_worker import ProbeWorker
from .workers.thumbnail_worker import ThumbnailWorker


class DesktopRuntime:
    def __init__(self, *, audio_enabled=True):
        self._audio_enabled = audio_enabled

    def queue(self, settings, parent=None):
        return JobQueue(settings, parent)

    def media_worker(self, *args, **kwargs):
        return MediaWorker(*args, **kwargs)

    def function_worker(self, operation):
        return FunctionWorker(operation)

    def probe_worker(self, *args, **kwargs):
        return ProbeWorker(*args, **kwargs)

    def hardware_worker(self, tools):
        return HardwareProbeWorker(tools)

    def setup_worker(self):
        return FFmpegSetupWorker()

    def engine_worker(self, version):
        return EngineUpdateWorker(version)

    def thumbnail_worker(self, *args, **kwargs):
        return ThumbnailWorker(*args, **kwargs)

    def filmstrip_worker(self, *args, **kwargs):
        return FilmstripWorker(*args, **kwargs)

    def waveform_worker(self, *args, **kwargs):
        return WaveformWorker(*args, **kwargs)

    def keyframe_worker(self, *args, **kwargs):
        return KeyframeWorker(*args, **kwargs)

    def frame_worker(
        self,
        project,
        seconds,
        size,
        tools,
        token,
        *,
        text_assets = None,
    ):
        request = prepare_preview(project, seconds, size, token, text_assets=text_assets)
        command = composer.frame_command(request.project, request.seconds, request.size, tools,
                                         text_assets=dict(request.text_assets))
        return FrameWorker(command, request.size, request.seconds, request.token)

    def playback_worker(
        self,
        project,
        seconds,
        size,
        tools,
        token,
        *,
        fps,
        text_assets = None,
        autostart = True,
    ):
        request = prepare_preview(project, seconds, size, token, fps=fps, text_assets=text_assets)
        command = composer.playback_command(request.project, request.seconds, request.size, tools,
                                            fps=request.fps, text_assets=dict(request.text_assets))
        return PlaybackWorker(
            command,
            request.seconds,
            request.size,
            request.token,
            fps=request.fps,
            autostart=autostart,
        )

    def audio_output(self, parent=None):
        return AudioPreview(parent, enabled=self._audio_enabled)

    def play_audio(
        self,
        output,
        project,
        seconds,
        tools,
        *,
        text_assets = None,
    ):
        if not output.available:
            output.stop()
            return
        rate, channels = output.target_format
        command = composer.audio_command(project, seconds, tools, sample_rate=rate,
                                         channels=channels, text_assets=text_assets)
        if command is not None:
            output.start(command, seconds, pcm_format=(rate, channels))
        else:
            output.stop()

    def find_tools(self):
        return binaries.find_tools()

    def hardware_ready(self, tools):
        return hardware.probes_ready(tools)

    def hardware_description(self, preference, tools):
        return hardware.describe(preference, tools)

    def reset_hardware(self):
        hardware.forget_probes()

    @property
    def cookie_browsers(self):
        from yt_dlp.cookies import SUPPORTED_BROWSERS
        return tuple(sorted(SUPPORTED_BROWSERS))

    @property
    def engine_version(self):
        from yt_dlp.version import __version__
        return __version__

    def is_packaged(self):
        return is_packaged()

    @property
    def download_cache(self):
        return Path(user_cache_dir(APP_NAME, appauthor=False)) / 'temp'

    def download_directory(self, settings):
        return Settings.from_dict(asdict(settings)).resolved_download_dir()

    def save_settings(self, settings):
        Settings.from_dict(asdict(settings)).save()

    def reveal_file(self, path):
        if not path or not path.exists():
            return
        command = ['explorer', '/select,', str(path)] if sys.platform == 'win32' else (
            ['open', '-R', str(path)] if sys.platform == 'darwin' else ['xdg-open', str(path.parent)])
        subprocess.Popen(command, **binaries.subprocess_kwargs())

__all__ = [
    'prepare_preview',
]
