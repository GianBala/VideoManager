"""Preparação de processamento, download e prévia com portas em memória."""
from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.application.errors import ConversionError, ProbeError
from videomanager.application.jobs.models import JobKind
from videomanager.application.jobs.requests import DownloadRequest
from videomanager.application.media.downloads import DownloadService
from videomanager.application.media.preview import prepare_preview
from videomanager.application.media.processing import ExportOptions, ProcessingService
from videomanager.application.ports.downloads import DownloadPlan
from videomanager.application.ports.output import OutputLease
from videomanager.application.preferences import Preferences
from videomanager.domain.composition import Composition
from videomanager.domain.formats import FormatMatrix, MediaInfo
from videomanager.domain.media import AudioTarget, LocalMedia, LocalStream, VideoTarget
from videomanager.domain.project import Clip, MediaKind, MediaRef, media_ref, new_project
from videomanager.domain.selection import VideoRequest
from videomanager.domain.timing import CutMode


MEDIA = LocalMedia(Path('/origem/video.mp4'), 10, 'mp4', 100,
                   (LocalStream(0, 'video', 'h264', width=640, height=360, fps=30),))


class Catalog:
    def __init__(self):
        self.inspected = []
    def exists(self, path):
        return path == MEDIA.path
    def inspect(self, path):
        self.inspected.append(path)
        return MEDIA
    def writable(self, directory):
        return directory != MEDIA.path.parent


class Outputs:
    def __init__(self):
        self.calls = []
    def reserve(self, source, target, directory, suffix='', custom_stem=None):
        self.calls.append((source, target, directory, suffix, custom_stem))
        return OutputLease(directory / ((custom_stem or 'saida') + '.' + target.extension), 1, 2)


def test_exportacao_vazia_falha_antes_de_reservar_destino():
    outputs = Outputs()
    with pytest.raises(ConversionError):
        ProcessingService(Catalog(), outputs).export(new_project(), ExportOptions(), fallback=Path('/tmp'))
    assert outputs.calls == []


def test_corte_rapido_preserva_container_e_usa_probe_em_cache():
    catalog, outputs = Catalog(), Outputs()
    project = new_project(media_ref(MEDIA))
    job = ProcessingService(catalog, outputs).export(
        project, ExportOptions(fast=True, container='webm', custom_name='final.mp4'),
        fallback=Path('/tmp'), probed={MEDIA.path: MEDIA})
    assert job.kind is JobKind.TRIM
    assert job.request.target.mode is CutMode.FAST
    assert job.request.target.container == 'mp4'
    assert job.request.destination == Path('/origem/final.mp4')
    assert job.request.lease.path == job.request.destination
    assert not catalog.inspected


def test_tela_explicita_exige_composicao_mesmo_com_corte_rapido():
    job = ProcessingService(Catalog(), Outputs()).export(
        new_project(media_ref(MEDIA)), ExportOptions(fast=True, canvas_explicit=True), fallback=Path('/tmp'))
    assert job.kind is JobKind.EXPORT
    assert isinstance(job.request.target, Composition)


def test_texto_usa_recurso_injetado_e_falha_nao_reserva_saida():
    outputs = Outputs()
    clip = Clip(media=MediaRef(Path('Texto'), MediaKind.IMAGE), start=0, duration=2,
                overlay_type='text', text_content='Olá')
    project = new_project().with_clip(0, clip)
    service = ProcessingService(Catalog(), outputs)
    with pytest.raises(ValueError, match='renderizador'):
        service.export(project, ExportOptions(), fallback=Path('/tmp'))
    assert not outputs.calls
    class Rasterizer:
        def render(self, requested):
            assert requested.clip_id == clip.clip_id
            return Path('/cache/texto.png')
    service.rasterizer = Rasterizer()
    job = service.export(project, ExportOptions(), fallback=Path('/tmp'))
    assert job.request.text_assets == ((clip.clip_id, Path('/cache/texto.png')),)
    assert job.request.media is None


def test_conversao_sem_stream_falha_e_destino_sem_permissao_usa_fallback():
    outputs = Outputs()
    service = ProcessingService(Catalog(), outputs)
    with pytest.raises(ConversionError, match='áudio'):
        service.convert(MEDIA, AudioTarget('mp3'), same_folder=True, fallback=Path('/destino'))
    assert not outputs.calls
    job, used = service.convert(MEDIA, VideoTarget('mkv'), same_folder=True, fallback=Path('/destino'))
    assert used and job.request.destination.parent == Path('/destino')


def test_gateway_recebe_url_normalizada_e_plano_preserva_avisos():
    media = MediaInfo('https://example.org/video', 'Vídeo', FormatMatrix())
    class Gateway:
        def analyze(self, url, preferences):
            assert url == media.url
            return media
        def plan(self, received, selection):
            assert received is media and isinstance(selection, VideoRequest)
            return DownloadPlan('MKV', ('Aviso de compatibilidade',))
    service = DownloadService(Gateway())
    preferences = Preferences()
    with pytest.raises(ProbeError):
        service.analyze('  ', preferences)
    assert service.analyze('  ' + media.url + '  ', preferences) is media
    request = DownloadRequest(VideoRequest(), media, Path('/saida'), Path('/tmp'), preferences)
    job = service.prepare(request)
    assert job.request is request and job.description == 'MKV'
    assert job.warnings == ('Aviso de compatibilidade',)


def test_preview_normaliza_limites_e_captura_recursos():
    project = replace(new_project(), fps=120)
    assets = {1: Path('/texto.png')}
    request = prepare_preview(project, -1, (320, 180), 4, text_assets=assets)
    assets.clear()
    assert request.seconds == 0 and request.fps == 60 and request.token == 4
    assert request.project is project and request.text_assets == ((1, Path('/texto.png')),)
    with pytest.raises(ValueError):
        prepare_preview(project, 0, (0, 180), 5)
