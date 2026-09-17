"""Prepara pedidos de conversão/exportação e reserva seus destinos por uma porta."""
from dataclasses import dataclass
from pathlib import Path
from videomanager.domain.composition import Composition
from videomanager.domain.export_policy import simple_trim
from videomanager.domain.export_policy import can_interpolate
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import VideoTarget
from videomanager.domain.media import LocalMedia
from videomanager.domain.project import Project
from videomanager.domain.timing import CutMode
from videomanager.domain.timing import TrimTarget
from videomanager.domain.timing import keyframe_at_or_before
from videomanager.application.errors import ConversionError
from videomanager.application.errors import VideoManagerError
from videomanager.application.jobs.models import Job
from videomanager.application.jobs.models import JobKind
from videomanager.application.jobs.requests import ConversionRequest
from videomanager.application.ports.rendering import collect_text_assets
from videomanager.application.ports.rendering import TextRasterizer
from videomanager.application.ports.processing import MediaCatalog
from videomanager.application.ports.processing import OutputStore
from videomanager.domain.compatibility import container_accepts_video


@dataclass(frozen=True)
class ExportOptions:
    container: str = 'mp4'
    family: str | None = None
    quality: str = 'balanced'
    hardware: str = 'software'
    interpolate: bool = False
    audio_only: bool = False
    audio_codec: str = 'mp3'
    fast: bool = False
    canvas_explicit: bool = False
    keyframes: tuple[float, ...] = ()
    same_folder: bool = True
    directory: Path | None = None
    custom_name: str = ''
    fast_suffix: str = ''
    export_suffix: str = ''


class ProcessingService:
    def __init__(self, catalog: MediaCatalog, outputs: OutputStore, rasterizer: TextRasterizer | None = None):
        self.catalog, self.outputs = catalog, outputs
        self.rasterizer = rasterizer

    def export(self, project: Project, options: ExportOptions, *, fallback: Path,
               project_path: Path | None = None, probed: dict[Path, LocalMedia] | None = None) -> Job:
        project = project.for_export()
        if project.is_empty:
            raise ConversionError('O projeto não tem clipes para exportar.')
        cache = probed or {}
        # A trilha de vídeo inferior define a referência principal da montagem.
        ordered = [c for t in reversed(project.video_tracks) if t.visible for c in t.sorted_clips()]
        # Fotos agora estão nas trilhas de vídeo; o nome da saída continua vindo
        # de um vídeo quando há algum.
        ordered = [c for c in ordered if not c.is_image] + [c for c in ordered if c.is_image]
        ordered += list(project.clips)
        source = next((c.media.path for c in ordered if c.overlay_type not in ('text', 'filter', 'transition')
                       and self.catalog.exists(c.media.path)), None)
        local = cache.get(source)
        if source is not None and not isinstance(local, LocalMedia):
            try:
                local = self.catalog.inspect(source)
            except VideoManagerError:
                local = None
        segments = simple_trim(project)
        fast = (options.fast and not options.audio_only and not options.canvas_explicit
                and local is not None and bool(segments) and len(segments) == 1)
        if fast:
            target = TrimTarget(segments, container=source.suffix.lstrip('.').lower() or 'mp4',
                                mode=CutMode.FAST, anchor=keyframe_at_or_before(options.keyframes, segments[0].start),
                                hardware=options.hardware)
        else:
            container = options.audio_codec if options.audio_only else options.container
            target = Composition(project, container=container, family=options.family,
                                 hardware=options.hardware, quality=options.quality,
                                 interpolate=options.interpolate and can_interpolate(project) and not options.audio_only,
                                 audio_only=options.audio_only,
                                 audio_codec=options.audio_codec if options.audio_only else None)
        if source is None:
            source = project_path.with_suffix('.' + target.extension) if project_path else fallback / ('edicao.' + target.extension)
        directory = source.parent if options.same_folder else options.directory or fallback
        name = options.custom_name.strip()
        extension = '.' + target.extension.lower()
        if name.lower().endswith(extension):
            name = name[:-len(extension)].strip()
        assets = collect_text_assets(project, self.rasterizer)
        lease = self.outputs.reserve(source, target, directory,
                                           options.fast_suffix if fast else options.export_suffix, name or None)
        return Job(str(source), lease.path.name, '', kind=JobKind.TRIM if fast else JobKind.EXPORT,
                   request=ConversionRequest(local, target, lease.path, tuple(assets.items()), lease))

    def convert(self, media: LocalMedia, target: AudioTarget | VideoTarget, *,
                same_folder: bool, fallback: Path) -> tuple[Job, bool]:
        if isinstance(target, VideoTarget) and (not media.has_video or media.video_is_cover):
            # Uma capa embutida (MP3, M4A, FLAC) aparece como trilha de vídeo,
            # mas convertê-la gerava um "vídeo" de um quadro só.
            raise ConversionError('não tem trilha de vídeo')
        if isinstance(target, VideoTarget) and not container_accepts_video(target.container, target.video_codec):
            raise ConversionError(f'{target.video_codec.upper()} não cabe em .{target.container}')
        if isinstance(target, AudioTarget) and not media.has_audio:
            raise ConversionError('não tem trilha de áudio')
        directory = media.path.parent if same_folder else fallback
        fallback_used = not self.catalog.writable(directory)
        if fallback_used:
            directory = fallback
        lease = self.outputs.reserve(media.path, target, directory)
        return Job(str(media.path), media.path.name, '', kind=JobKind.CONVERT,
                   request=ConversionRequest(media, target, lease.path, lease=lease)), fallback_used
