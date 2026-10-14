"""A gaveta de tarefas no lugar da fila embaixo e da barra de status.

O que a barra de status fazia (contar as tarefas, dizer de onde veio o ffmpeg, avisar que algo entrou na fila)
foi para três lugares: o selo do item Tarefas, a aba Geral das configurações e o aviso flutuante. Um deles
perdido não levanta exceção nenhuma — o editor ficaria com a gaveta recolhida e o "Adicionar à fila" sem
resposta na tela —, e é isso que os testes abaixo conferem pelo que aparece.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QStatusBar

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.jobs.models import Job, JobKind, JobStatus
from videomanager.bootstrap import (build_desktop_runtime, build_download_service, build_editor_service,
                                    build_processing_service)
from videomanager.domain import i18n
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.i18n import apply_language
from videomanager.presentation.qt.main_window import _TAB_CONVERT, _TAB_DOWNLOAD, _TAB_EDIT, _TAB_METADATA, MainWindow
from videomanager.presentation.qt.panels.queue_panel import DRAWER_WIDTH, QueuePanel
from videomanager.presentation.qt.settings_dialog import SettingsDialog


@pytest.fixture
def janela(desktop_app, monkeypatch):
    monkeypatch.setattr("videomanager.presentation.qt.main_window.ensure_ffmpeg", lambda parent, **kw: None)
    w = MainWindow(Settings(), editor=build_editor_service(), processing=build_processing_service(),
                   downloads=build_download_service(), runtime=build_desktop_runtime(audio_enabled=False))
    w.show()
    for _ in range(5):
        desktop_app.processEvents()
    yield w
    w._edit._project_actions.confirm_replace = lambda: True
    # Tarefa em andamento faz o ``closeEvent`` abrir a pergunta "sair mesmo?", e ela espera uma resposta que ninguém dá.
    for job in w._queue.jobs:
        job.status = JobStatus.DONE
    w._edit.shutdown()
    w.close()
    apply_language(i18n.PORTUGUESE)


def _ir(janela, desktop_app, indice: int) -> None:
    janela._tabs.setCurrentIndex(indice)
    for _ in range(3):
        desktop_app.processEvents()


# -- onde a gaveta aparece ------------------------------------------------------------------------------------

def test_a_gaveta_acompanha_a_aba_como_a_fila_acompanhava(janela, desktop_app):
    visivel = {}
    for indice in (_TAB_DOWNLOAD, _TAB_CONVERT, _TAB_EDIT, _TAB_METADATA, _TAB_DOWNLOAD):
        _ir(janela, desktop_app, indice)
        visivel[indice] = janela._queue_panel.isVisible()
        # O item do menu mostra o que a gaveta mostra: marcado = gaveta à vista.
        assert janela._nav_tasks.isChecked() == janela._queue_panel.isVisible()
    assert visivel == {_TAB_DOWNLOAD: True, _TAB_CONVERT: True, _TAB_EDIT: False, _TAB_METADATA: False}
    assert janela._queue_panel.width() == DRAWER_WIDTH


def test_recolher_vale_nas_abas_que_a_mostram_e_volta_do_editor_como_estava(janela, desktop_app):
    janela._queue_panel._hide_button.click()
    assert not janela._queue_panel.isVisible() and not janela._nav_tasks.isChecked()
    for indice in (_TAB_CONVERT, _TAB_EDIT, _TAB_DOWNLOAD):
        _ir(janela, desktop_app, indice)
        assert not janela._queue_panel.isVisible()
    janela._nav_tasks.click()
    assert janela._queue_panel.isVisible() and janela._nav_tasks.isChecked()
    _ir(janela, desktop_app, _TAB_EDIT)
    assert not janela._queue_panel.isVisible()
    _ir(janela, desktop_app, _TAB_CONVERT)
    assert janela._queue_panel.isVisible()


def test_o_item_tarefas_abre_a_gaveta_no_editor(janela, desktop_app):
    _ir(janela, desktop_app, _TAB_EDIT)
    janela._nav_tasks.click()
    assert janela._queue_panel.isVisible()
    janela._nav_tasks.click()
    assert not janela._queue_panel.isVisible()


def test_o_aviso_ver_tarefas_abre_a_gaveta_com_o_editor_aberto(janela, desktop_app, monkeypatch):
    monkeypatch.setattr(janela._queue, "submit", lambda job: None)
    _ir(janela, desktop_app, _TAB_EDIT)
    assert not janela._queue_panel.isVisible()
    janela._submit_jobs([Job("", "a", "", kind=JobKind.EXPORT)])
    aviso = janela._toasts.ativos[0]
    assert aviso.mensagem.text() == strings.STATUS_ENQUEUED.format(count=1)
    assert aviso.acao.text() == strings.TOAST_VIEW_TASKS
    aviso.acao.click()
    assert janela._queue_panel.isVisible() and janela._nav_tasks.isChecked()


def test_nao_ha_barra_de_status(janela):
    assert janela.findChildren(QStatusBar) == []


# -- o selo do item Tarefas -----------------------------------------------------------------------------------

def test_o_selo_conta_as_tarefas_em_aberto_em_qualquer_aba_e_a_dica_diz_o_resto(janela, desktop_app):
    fila = janela._queue
    for status in (JobStatus.RUNNING, JobStatus.PROCESSING, JobStatus.PENDING, JobStatus.DONE, JobStatus.FAILED):
        fila.service.add(Job("", status.value, "", status=status))
    fila.counts_changed.emit()
    for indice in (_TAB_DOWNLOAD, _TAB_EDIT, _TAB_METADATA):
        _ir(janela, desktop_app, indice)
        assert janela._nav_tasks._selo == 3, indice
    assert janela._nav_tasks.toolTip() == strings.STATUS_COUNTS.format(active=2, pending=1, done=1)
    # E o selo se pinta: sem ele o item é o mesmo desenho.
    com = janela._nav_tasks.grab().toImage()
    janela._nav_tasks.set_selo(0)
    assert janela._nav_tasks.grab().toImage() != com


def test_a_troca_de_idioma_retraduz_o_item_e_a_dica_do_selo(janela, desktop_app):
    janela._queue.service.add(Job("", "a", "", status=JobStatus.RUNNING))
    janela._queue.counts_changed.emit()
    apply_language(i18n.ENGLISH)
    assert janela._nav_tasks.text() == "Tasks"
    assert janela._nav_tasks.toolTip() == strings.STATUS_COUNTS.format(active=1, pending=0, done=0)
    assert "in progress" in janela._nav_tasks.toolTip()


# -- os selos do cabeçalho da gaveta --------------------------------------------------------------------------

class _Fila(QObject):
    job_added = Signal(object)
    job_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.jobs: list[Job] = []


@pytest.fixture
def gaveta(desktop_app):
    fila = _Fila()
    painel = QueuePanel(fila, runtime=None)
    painel.show()
    yield fila, painel
    painel.close()
    painel.deleteLater()


def _com(fila, desktop_app, *status: JobStatus) -> None:
    for situacao in status:
        job = Job("", situacao.value, "", status=situacao)
        fila.jobs.append(job)
        fila.job_added.emit(job)
    desktop_app.processEvents()


def _selos(painel) -> dict[str, str]:
    return {nome: chip.text() for nome, chip in painel._chips.items() if chip.isVisibleTo(painel)}


def test_sem_tarefas_nao_ha_selos_e_a_linha_some(gaveta):
    _, painel = gaveta
    assert _selos(painel) == {} and not painel._chip_row.isVisibleTo(painel)


def test_cada_selo_conta_a_sua_situacao_no_singular_e_no_plural(gaveta, desktop_app):
    fila, painel = gaveta
    _com(fila, desktop_app, JobStatus.RUNNING, JobStatus.PROCESSING, JobStatus.PENDING, JobStatus.FAILED,
         JobStatus.CANCELLED, JobStatus.DONE)
    assert _selos(painel) == {"active": "2 ativas", "pending": "1 na fila", "failed": "1 falhou",
                              "cancelled": "1 cancelada"}
    _com(fila, desktop_app, JobStatus.FAILED, JobStatus.CANCELLED)
    assert _selos(painel)["failed"] == "2 falharam" and _selos(painel)["cancelled"] == "2 canceladas"
    # Tarefa concluída não ganha selo: "concluídos" está na dica do item do menu.
    assert "done" not in _selos(painel)


def test_o_selo_acompanha_a_mudanca_de_situacao_e_o_idioma(gaveta, desktop_app):
    fila, painel = gaveta
    _com(fila, desktop_app, JobStatus.RUNNING)
    fila.jobs[0].status = JobStatus.FAILED
    fila.job_changed.emit(fila.jobs[0])
    assert _selos(painel) == {"failed": "1 falhou"}
    apply_language(i18n.ENGLISH)
    assert _selos(painel) == {"failed": "1 failed"}


def test_todos_os_selos_cabem_ao_lado_um_do_outro_na_gaveta(gaveta, desktop_app):
    fila, painel = gaveta
    _com(fila, desktop_app, *([JobStatus.RUNNING] * 12 + [JobStatus.PENDING] * 12 + [JobStatus.FAILED] * 12
                              + [JobStatus.CANCELLED] * 12))
    for idioma in (i18n.PORTUGUESE, i18n.ENGLISH):
        apply_language(idioma)
        desktop_app.processEvents()
        selos = [c for c in painel._chips.values() if c.isVisibleTo(painel)]
        assert len(selos) == 4
        assert max(c.geometry().right() for c in selos) < painel._chip_row.width(), idioma


# -- a origem do ffmpeg em Ajustes ----------------------------------------------------------------------------

class _SemFerramentas:
    """Runtime sem ffmpeg: o diálogo de configurações não sonda a placa."""

    def __init__(self, runtime):
        self._runtime = runtime

    def __getattr__(self, nome):
        return getattr(self._runtime, nome)

    def find_tools(self):
        return None


@pytest.fixture
def abrir(desktop_app):
    abertos = []

    def _abrir(tools):
        dialogo = SettingsDialog(Settings(), runtime=_SemFerramentas(build_desktop_runtime(audio_enabled=False)),
                                 tools=tools)
        abertos.append(dialogo)
        return dialogo

    yield _abrir
    for dialogo in abertos:
        dialogo.deleteLater()


@pytest.mark.parametrize("origem", ["empacotado", "gerenciado", "sistema"])
def test_ajustes_mostra_de_onde_veio_o_ffmpeg_e_o_caminho(abrir, origem):
    dialogo = abrir(FFmpegTools(Path("/opt/vm/ffmpeg"), Path("/opt/vm/ffprobe"), origem))
    # A origem é uma pastilha (o nome) com a nota ao lado, e o caminho vem embaixo.
    nome, nota = strings.FFMPEG_SOURCES[origem]
    assert dialogo._ffmpeg_source.text() == nome and not dialogo._ffmpeg_source.isHidden()
    assert dialogo._ffmpeg_note.text() == nota
    assert dialogo._ffmpeg_path.text() == "/opt/vm/ffmpeg"
    assert not dialogo._ffmpeg_path.isHidden()


def test_ajustes_sem_ffmpeg_localizado_diz_que_ainda_nao_achou(abrir):
    dialogo = abrir(None)
    assert dialogo._ffmpeg_note.text() == strings.SETTINGS_FFMPEG_UNKNOWN
    assert dialogo._ffmpeg_source.isHidden() and dialogo._ffmpeg_path.text() == ""


def test_as_tres_origens_tem_frase_nos_dois_idiomas(desktop_app):
    from videomanager.presentation.qt import strings_en
    assert set(strings.FFMPEG_SOURCES) == set(strings_en.FFMPEG_SOURCES) == {"empacotado", "gerenciado", "sistema"}
    assert all(strings.FFMPEG_SOURCES[k] != strings_en.FFMPEG_SOURCES[k] for k in strings.FFMPEG_SOURCES)
