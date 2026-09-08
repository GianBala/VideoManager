"""Contrato do provedor de análise e planejamento de downloads."""
from dataclasses import dataclass
from typing import Protocol
from videomanager.domain.formats import MediaInfo
from videomanager.domain.formats import PlaylistInfo
from videomanager.domain.selection import Request
from videomanager.application.preferences import Preferences


@dataclass(frozen=True)
class DownloadPlan:
    description: str
    warnings: tuple[str, ...] = ()


class DownloadGateway(Protocol):
    def analyze(self, url: str, preferences: Preferences) -> MediaInfo | PlaylistInfo: ...
    def plan(self, media: MediaInfo, selection: Request) -> DownloadPlan: ...
