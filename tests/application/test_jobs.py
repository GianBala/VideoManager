"""Eventos atrasados e repetição não podem reabrir tentativas encerradas."""
from pathlib import Path
import pytest
from videomanager.application.events import Progress
from videomanager.application.events import ProgressStage
from videomanager.application.jobs.models import Job
from videomanager.application.jobs.models import JobStatus
from videomanager.application.jobs.service import JobService


def prepared():
    service = JobService()
    job = Job('url', 'Título', 'Descrição')
    service.add(job)
    service.begin(job)
    return service, job


def test_estado_usa_categoria_e_nao_texto_de_interface():
    service, job = prepared()
    service.progress(job.job_id, 1, Progress('Texto traduzido', stage=ProgressStage.DOWNLOAD))
    assert job.status is JobStatus.RUNNING


@pytest.mark.parametrize('terminal', ['cancelled', 'failed', 'done'])
def test_tentativa_so_termina_uma_vez(terminal):
    service, job = prepared()
    if terminal == 'cancelled':
        service.cancelled(job.job_id, 1)
    elif terminal == 'failed':
        service.fail(job.job_id, 1, 'Falhou')
    else:
        service.finish(job.job_id, 1, Path('final.mp4'), size=20)
    status = job.status
    assert service.progress(job.job_id, 1, Progress('Atrasado')) is None
    assert service.finish(job.job_id, 1, Path('outro.mp4')) is None
    assert job.status is status


def test_eventos_da_tentativa_anterior_nao_modificam_repeticao():
    service, job = prepared()
    service.fail(job.job_id, 1, 'Rede indisponível')
    service.begin(job)
    assert job.attempt_id == 2
    assert service.cancelled(job.job_id, 1) is None
    assert service.finish(job.job_id, 1, Path('antigo')) is None
    assert job.status is JobStatus.PENDING
    service.finish(job.job_id, 2, Path('novo'), size=123)
    assert job.result_path == Path('novo') and job.result_size == 123


def test_submeter_mesmo_id_duas_vezes_falha():
    service, job = prepared()
    with pytest.raises(ValueError):
        service.add(job)
    assert service.jobs == [job]
