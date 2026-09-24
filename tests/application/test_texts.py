"""Textos da aplicação: o que a tarefa guarda acompanha a troca de idioma."""

from __future__ import annotations

from pathlib import Path

from videomanager.application.errors import ConversionError, error_message
from videomanager.application.jobs.models import Job, JobStatus
from videomanager.application.jobs.service import JobService
from videomanager.application.media.export_description import describe_export
from videomanager.domain import i18n
from videomanager.domain.i18n import Text
from videomanager.domain.project import Clip, MediaKind, MediaRef, new_project

VIDEO = MediaRef(Path("a.mp4"), MediaKind.VIDEO, duration=12.5, width=1920, height=1080, fps=30.0, has_audio=True)


def test_descricao_da_exportacao_nos_dois_idiomas():
    projeto = new_project().with_clip(0, Clip(VIDEO, 0.0, 4.25))
    guardada = Text.of(describe_export, projeto, "mp4")
    assert str(guardada).endswith("4,25 s de duração")
    assert "bloco(s) de imagem" in str(guardada)
    i18n.set_language(i18n.ENGLISH)
    assert str(guardada).endswith("4.25 s long")
    assert "image clip(s)" in str(guardada)


def test_erro_guardado_na_tarefa_segue_o_idioma_da_tela():
    service = JobService()
    job = Job("a.mp4", "a.mp4", Text("DESC_AUDIO_ONLY"))
    service.add(job)
    attempt = service.begin(job)
    job.status = JobStatus.RUNNING
    falha = ConversionError(Text("ERROR_CODEC_NOT_IN_CONTAINER", codec="HEVC", container="webm"))
    assert isinstance(error_message(falha), Text)
    service.fail(job.job_id, attempt, error_message(falha))
    assert str(job.error) == "HEVC não cabe em .webm"
    i18n.set_language(i18n.ENGLISH)
    assert str(job.error) == "HEVC doesn't fit in .webm"
    assert str(job.description) == "audio only"


def test_mensagem_de_excecao_sem_catalogo_continua_texto():
    assert error_message(OSError("disco cheio")) == "disco cheio"
