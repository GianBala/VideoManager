"""Gateway de análise e negociação; dicionários de provedor ficam neste lado."""
from videomanager.application.ports.downloads import DownloadPlan
from videomanager.infrastructure.yt_dlp.probe import probe
from videomanager.application.media.download_policy import plan_container
from videomanager.application.media.download_policy import describe_request
from videomanager.domain.selection import VideoRequest
from videomanager.domain.i18n import Text


class YtDlpGateway:
    def analyze(self, url, preferences):
        return probe(url, preferences)

    def plan(self, media, selection):
        plan = plan_container(media.matrix, selection.video, selection.audio, selection.container) if isinstance(selection, VideoRequest) else None
        # A descrição vai para a fila e é refeita a cada exibição, no idioma dela.
        return DownloadPlan(Text.of(describe_request, selection, plan), plan.warnings if plan else ())

__all__ = [
    'DownloadPlan',
    'plan_container',
    'describe_request',
    'VideoRequest',
]
