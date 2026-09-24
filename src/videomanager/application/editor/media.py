"""Leitura e importação: coordenação sem conhecimento de workers ou ferramentas."""
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from videomanager.domain.media import LocalMedia
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import Project
from videomanager.domain.project import media_ref
from videomanager.domain.i18n import Text
from videomanager.application.errors import JobCancelled
from videomanager.application.errors import VideoManagerError
from videomanager.application.ports.editor import Cancellation
from videomanager.application.ports.editor import MediaProbe
from videomanager.application.ports.editor import ProjectRepository


@dataclass
class MediaResult:
    project: Project | None = None
    references: list[MediaRef] = field(default_factory=list)
    probed: dict[Path, LocalMedia] = field(default_factory=dict)
    missing: list[Path] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


class ReadMedia:
    def __init__(self, repository: ProjectRepository, probe: MediaProbe | None):
        self.repository = repository
        self.probe = probe

    def execute(self, paths: list[Path], cancellation: Cancellation, *,
                project_path: Path | None = None,
                known: dict[Path, MediaRef] | None = None,
                require_duration: bool = True,
                on_progress: Callable[[int, int], None] = lambda done, total: None) -> MediaResult:
        cancellation.check()
        result = MediaResult()
        known = known or {}
        paths = list(dict.fromkeys(paths))
        if project_path is not None:
            result.project, result.missing = self.repository.load(project_path)
            refs = {c.media.path: c.media for c in result.project.clips
                    if c.overlay_type not in ('text', 'filter', 'transition')}
            result.references = list(refs.values())
            paths = list(refs)
        for index, path in enumerate(paths):
            cancellation.check()
            try:
                if project_path is None and path in known:
                    result.references.append(known[path])
                elif self.probe is not None:
                    local = self.probe.inspect(path, cancellation)
                    reference = media_ref(local)
                    if project_path is None:
                        if require_duration and reference.kind is not MediaKind.IMAGE and not reference.duration:
                            raise VideoManagerError(Text('ERROR_MEDIA_NO_DURATION'))
                        result.references.append(reference)
                    result.probed[path] = local
            except JobCancelled:
                raise
            except VideoManagerError as exc:
                if project_path is None:
                    result.rejected.append(f'{path.name}: {exc}')
            on_progress(index + 1, len(paths))
        cancellation.check()
        return result
