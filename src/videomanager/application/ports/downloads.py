"""Contrato do provedor de análise e planejamento de downloads."""
from dataclasses import dataclass
from typing import Protocol
from videomanager.domain.formats import MediaInfo
from videomanager.domain.formats import PlaylistInfo
from videomanager.domain.selection import Request
from videomanager.domain.i18n import Text
from videomanager.application.preferences import Preferences


@dataclass(frozen=True)
class DownloadPlan:
    description: Text
    warnings: tuple[Text, ...] = ()


class DownloadGateway(Protocol):
    def analyze(self, url: str, preferences: Preferences) -> MediaInfo | PlaylistInfo: ...
    def plan(self, media: MediaInfo, selection: Request) -> DownloadPlan: ...
