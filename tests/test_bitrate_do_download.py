"""Bitrate de vídeo nas opções de download: "igual ao da fonte" ou um valor (``QualityPanel`` e ``VideoRequest``).

Pedir um valor é o consentimento de recodificar, e o painel precisa dizer isso antes de baixar: o aviso da recodificação, o
aviso de que recodificar para cima só aumenta o arquivo, e o tamanho estimado que acompanha o valor. O que isto pode errar
sem exceção: o pedido que sai sem o valor escolhido, o tamanho que continua o da fonte, o perfil rápido que herda o bitrate
de uma escolha anterior, o valor pronto que fica com o separador decimal do idioma antigo.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from conftest import fixture_formats
from videomanager.application.formatting import format_bitrate, format_size
from videomanager.domain import i18n
from videomanager.domain.estimator import estimate_download_size
from videomanager.domain.formats import Mode
from videomanager.domain.selection import VIDEO_BITRATE_PRESETS
from videomanager.infrastructure.storage.settings import Settings
from videomanager.infrastructure.yt_dlp.formats import build_matrix
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.i18n import apply_language
from videomanager.presentation.qt.panels.quality_panel import QualityPanel

DURACAO = 600.0


@pytest.fixture
def painel(desktop_app):
    instancia = QualityPanel(Settings())
    instancia.set_matrix(build_matrix(fixture_formats("youtube_dash")), DURACAO)
    instancia.show()
    for _ in range(3):
        desktop_app.processEvents()
    yield instancia
    instancia.close()
    apply_language(i18n.PORTUGUESE)


def _escolher(painel, dado) -> None:
    painel._bitrate.setCurrentIndex(painel._bitrate.findData(dado))


def test_por_padrao_o_bitrate_e_igual_ao_da_fonte_e_o_pedido_nao_recodifica(painel):
    assert painel.current_video_kbps() is None
    assert painel.build_request().video_kbps is None
    fonte = painel._source_video_kbps()
    assert fonte and painel._bitrate.itemText(0) == strings.VIDEO_BITRATE_SOURCE_WITH.format(bitrate=format_bitrate(fonte))
    assert not painel._bitrate_custom_box.isVisibleTo(painel)
    assert [painel._bitrate.itemData(i) for i in range(painel._bitrate.count())][1:-1] == list(VIDEO_BITRATE_PRESETS)


def test_um_valor_pronto_entra_no_pedido_e_no_resumo(painel):
    _escolher(painel, 1000)
    assert painel.current_video_kbps() == 1000 and painel.build_request().video_kbps == 1000
    assert format_bitrate(1000) in painel.summary()


def test_personalizado_mostra_o_campo_livre_e_o_valor_dele_vai_no_pedido(painel):
    _escolher(painel, "custom")
    assert painel._bitrate_custom_box.isVisibleTo(painel)
    painel._bitrate_custom.setValue(3300)
    assert painel.current_video_kbps() == 3300 and painel.build_request().video_kbps == 3300
    _escolher(painel, None)
    assert not painel._bitrate_custom_box.isVisibleTo(painel) and painel.build_request().video_kbps is None


def test_bitrate_fica_na_segunda_fileira_e_a_trilha_de_audio_e_uma_coluna_so(painel):
    """Seis combos em duas fileiras de três colunas iguais: o bitrate entre o container e a trilha, e o valor livre sob ele."""
    def caixa(widget):
        topo = widget.mapTo(painel, widget.rect().topLeft())
        return topo.x(), topo.y(), widget.width()

    assert painel._audio_track.isVisibleTo(painel)  # o YouTube separa vídeo e áudio
    (cx, cy, cw), (bx, by, bw), (tx, ty, tw) = caixa(painel._container), caixa(painel._bitrate), caixa(painel._audio_track)
    assert cy == by == ty and cx < bx < tx
    assert cw == bw == tw  # a trilha de áudio já ocupou duas colunas, e o bitrate ficava sozinho numa terceira fileira
    _escolher(painel, "custom")
    for _ in range(3):
        QApplication.processEvents()
    vx, vy, _ = caixa(painel._bitrate_custom)
    assert vx == bx and vy > by


def test_com_o_audio_mesclado_a_segunda_fileira_nao_deixa_vao(desktop_app):
    instancia = QualityPanel(Settings())
    instancia.set_matrix(build_matrix(fixture_formats("archive_muxed")), DURACAO)
    instancia.show()
    for _ in range(3):
        desktop_app.processEvents()
    try:
        assert not instancia._audio_track.isVisibleTo(instancia)
        container = instancia._container.mapTo(instancia, instancia._container.rect().topLeft())
        bitrate = instancia._bitrate.mapTo(instancia, instancia._bitrate.rect().topLeft())
        # O bitrate fica na coluna do meio, junto do container: o vão é à direita, e não entre os dois.
        assert bitrate.y() == container.y() and bitrate.x() > container.x()
    finally:
        instancia.close()
        apply_language(i18n.PORTUGUESE)


def test_o_pedido_de_lote_leva_o_bitrate_tambem(painel):
    _escolher(painel, 2500)
    assert painel.build_batch_request(720).video_kbps == 2500


def test_o_tamanho_estimado_acompanha_o_bitrate_pedido(painel):
    matriz = painel._matrix
    fonte = painel.estimated_size()
    _escolher(painel, 500)
    esperado = estimate_download_size(matriz, Mode.VIDEO, painel.current_video_choice(), painel.current_audio_choice(),
                                      duration=DURACAO, video_kbps=500)
    assert painel.estimated_size() == format_size(esperado, estimated=True) != fonte
    # Vídeo a 500 kbps por 600 s são 37,5 MB, mais o áudio que fica como está.
    assert 37_500_000 < esperado < 37_500_000 + 20_000_000


def test_o_aviso_diz_que_o_video_sera_recodificado_e_some_com_a_fonte(painel):
    _escolher(painel, 1000)
    assert "recodificado" in painel._warning.text() and format_bitrate(1000) in painel._warning.text()
    _escolher(painel, None)
    assert "recodificado" not in painel._warning.text()


def test_um_bitrate_acima_da_fonte_avisa_que_so_aumentaria_e_a_estimativa_e_a_da_fonte(painel):
    fonte = painel.estimated_size()
    _escolher(painel, "custom")
    painel._bitrate_custom.setValue(int(painel._source_video_kbps() * 2))
    assert "só aumentaria" in painel._warning.text() and "mantido" in painel._warning.text()
    assert painel.estimated_size() == fonte


def test_um_perfil_rapido_volta_o_bitrate_ao_da_fonte(painel):
    _escolher(painel, 1000)
    painel.apply_profile(mode=Mode.VIDEO, height=720)
    assert painel.current_video_kbps() is None and painel._bitrate.currentIndex() == 0


def test_os_valores_prontos_seguem_o_separador_decimal_do_idioma(painel):
    indice = painel._bitrate.findData(2500)
    assert painel._bitrate.itemText(indice) == "2,5 Mbps"
    apply_language(i18n.ENGLISH)
    assert painel._bitrate.itemText(indice) == "2.5 Mbps"
    assert painel._bitrate.itemText(0).startswith("Same as the source")
    assert painel._bitrate.currentData() is None  # a escolha não muda com o texto


def test_o_estimador_nao_recodifica_para_cima(painel):
    matriz, escolha = painel._matrix, painel.current_video_choice()
    base = estimate_download_size(matriz, Mode.VIDEO, escolha, painel.current_audio_choice(), duration=DURACAO)
    acima = estimate_download_size(matriz, Mode.VIDEO, escolha, painel.current_audio_choice(), duration=DURACAO,
                                   video_kbps=int(painel._source_video_kbps() * 1.5))
    assert acima == base


def _worker(monkeypatch, tmp_path, selecao):
    from dataclasses import dataclass
    from pathlib import Path

    from videomanager.infrastructure.qt.workers import download_worker

    visto: dict = {}

    class _Dubla:
        def __init__(self, opts, on_progress=None, recode_plan=None):
            visto["plano"] = recode_plan
            self.log = ()

    @dataclass
    class _Pedido:
        temporary: Path
        selection: object
        media: object = None
        destination: Path = Path("destino")
        preferences: object = None

    @dataclass
    class _Tarefa:
        job_id: int
        request: _Pedido
        url: str = "https://exemplo.invalido/v"

    ferramentas = object()
    monkeypatch.setattr(download_worker, "Downloader", _Dubla)
    monkeypatch.setattr(download_worker, "find_tools", lambda: ferramentas)
    monkeypatch.setattr(download_worker, "build_opts", lambda *args: ({}, None))
    download_worker.DownloadWorker(_Tarefa(1, _Pedido(tmp_path, selecao)))
    return visto["plano"], ferramentas


def test_o_worker_so_planeja_recodificar_quando_o_pedido_traz_o_bitrate(monkeypatch, tmp_path):
    from videomanager.domain.selection import AudioRequest, VideoRequest
    plano, ferramentas = _worker(monkeypatch, tmp_path, VideoRequest(video_kbps=1800))
    assert plano is not None and plano.kbps == 1800 and plano.tools is ferramentas
    assert _worker(monkeypatch, tmp_path, VideoRequest())[0] is None  # igual à fonte: nada de recodificar
    assert _worker(monkeypatch, tmp_path, AudioRequest())[0] is None  # áudio não tem bitrate de vídeo
