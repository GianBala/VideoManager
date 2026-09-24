"""Análise e preparação de downloads sobre um gateway substituível."""
from videomanager.application.errors import ProbeError
from videomanager.application.jobs.models import Job
from videomanager.application.jobs.requests import DownloadRequest
from videomanager.application.ports.downloads import DownloadGateway
from videomanager.application.preferences import Preferences
from videomanager.domain.i18n import Text


class DownloadService:
    def __init__(self, gateway: DownloadGateway):
        self.gateway = gateway

    def analyze(self, url: str, preferences: Preferences):
        url = url.strip()
        if not url:
            raise ProbeError(Text('ERROR_URL_EMPTY'))
        return self.gateway.analyze(url, preferences)

    def prepare(self, request: DownloadRequest) -> Job:
        plan = self.gateway.plan(request.media, request.selection)
        return Job(request.media.url, request.media.title, plan.description,
                   request=request, warnings=plan.warnings)
