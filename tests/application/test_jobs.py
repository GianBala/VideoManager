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


def test_download_concluido_com_aviso_guarda_o_aviso_e_o_diz_na_descricao():
    """O arquivo foi entregue, mas algo do que foi pedido não foi aplicado (ex.: o bitrate): o cartão diz."""
    from videomanager.application.events import DownloadResult
    from videomanager.domain.i18n import Text

    service, job = prepared()
    aviso = Text("RECODE_FALLBACK", error="sem encoder")
    service.finish(job.job_id, 1, DownloadResult(Path('final.mp4'), 'Título', (), (aviso,)), size=20)
    assert job.status is JobStatus.DONE and job.warnings == (aviso,)
    assert str(job.description).startswith('Descrição') and 'aviso' in str(job.description)

    sem_aviso = Job('url2', 'Outro', 'Outra')
    service.add(sem_aviso)
    service.begin(sem_aviso)
    service.finish(sem_aviso.job_id, 1, DownloadResult(Path('x.mp4'), 'Outro', ()), size=1)
    assert sem_aviso.warnings == () and str(sem_aviso.description) == 'Outra'
