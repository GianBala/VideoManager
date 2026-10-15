"""O tamanho que a janela de exportação anuncia: medido numa amostra da mídia principal, não adivinhado por pixels.

A conta por pixels não enxerga o conteúdo (errou de −66% a +1500% em gravações reais). A janela passa a medir a mídia
principal codificada como a exportação a codificaria, mostra "medindo…" até a amostra chegar e só volta à conta quando a
medida falha.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.formatting import format_size
from videomanager.bootstrap import build_desktop_runtime, build_processing_service
from videomanager.domain.estimator import estimate_export_size
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import LocalStream
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import TrackKind
from videomanager.domain.project import new_project
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.export_dialog import ExportDialog

TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")


@pytest.fixture
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


class _AmostrasFalsas:
    """O runtime de verdade, com a medida trocada por uma que só termina quando liberada (ou que falha)."""

    def __init__(self, runtime, kbps: float = 4000.0, falha: bool = False) -> None:
        self._runtime = runtime
        self.pedidos: list[tuple] = []
        self.liberar = threading.Event()
        self.kbps = kbps
        self.falha = falha

    def __getattr__(self, nome):
        return getattr(self._runtime, nome)

    def sample_worker(self, media, target, tools):
        from videomanager.application.errors import ConversionError
        from videomanager.domain.i18n import Text
        from videomanager.infrastructure.qt.workers.function_worker import FunctionWorker
        from videomanager.infrastructure.system.process import ProcessControl

        control = ProcessControl()
        self.pedidos.append((target.container, target.video_codec, target.quality, target.height, target.fps))

        def medir():
            while not self.liberar.wait(0.005):
                control.check()
            control.check()
            if self.falha:
                raise ConversionError(Text("CONVERT_SAMPLE_FAILED"))
            return self.kbps

        return FunctionWorker(medir, control.cancel)


def _dialogo(tmp_path: Path, **kwargs):
    caminho = tmp_path / "orig.mp4"
    caminho.write_bytes(b"data")
    ref = MediaRef(path=caminho, kind=MediaKind.VIDEO, duration=120.0, width=1920, height=1080, fps=30.0, has_audio=True)
    local = LocalMedia(path=caminho, duration=120.0, format_name="mp4", size=40 * 1024 * 1024, streams=(
        LocalStream(index=0, kind="video", codec="h264", width=1920, height=1080, fps=30.0),
        LocalStream(index=1, kind="audio", codec="aac")))
    projeto = new_project().with_track(TrackKind.VIDEO, name="Vídeo 1").with_clip(0, Clip(media=ref, start=0.0, duration=120.0))
    runtime = _AmostrasFalsas(build_desktop_runtime(), **kwargs)
    dialogo = ExportDialog(project=projeto, settings=Settings(), pool=[ref], probed={caminho: local},
                           ensure_tools=lambda: TOOLS, processing=build_processing_service(), runtime=runtime)
    return dialogo, runtime, projeto


def _esperar(app, dialogo) -> None:
    prazo = time.monotonic() + 10
    while (dialogo._sampling or dialogo._sampling_runner.active) and time.monotonic() < prazo:
        app.processEvents()
        time.sleep(0.005)
    assert not dialogo._sampling


def test_a_janela_mede_e_depois_mostra_o_que_a_amostra_mediu(qapp, tmp_path) -> None:
    dialogo, runtime, projeto = _dialogo(tmp_path)
    try:
        assert dialogo._size_label.text() == strings.CONVERT_MEASURING
        assert len(runtime.pedidos) == 1 and runtime.pedidos[0][1] == "h264"
        runtime.liberar.set()
        _esperar(qapp, dialogo)
        esperado = estimate_export_size(
            duration=projeto.export_duration, width=projeto.width, height=projeto.height, fps=projeto.fps,
            video_codec="h264", quality=dialogo._quality_choice, video_kbps=4000.0, container="mp4")
        assert dialogo._size_label.text() == format_size(esperado, estimated=True)
        # Um quarto do que a conta por pixels anunciava para uma tela de 1080p (a fonte é leve): é a amostra que manda.
        assert esperado < estimate_export_size(
            duration=projeto.export_duration, width=projeto.width, height=projeto.height, fps=projeto.fps,
            video_codec="h264", quality=dialogo._quality_choice)
    finally:
        dialogo.close()


def test_trocar_a_qualidade_abandona_a_medida_antiga_e_pede_a_nova(qapp, tmp_path) -> None:
    dialogo, runtime, _ = _dialogo(tmp_path)
    try:
        antigo = dialogo._sampling_token
        indice = dialogo._quality_box.findData("high")
        assert indice >= 0
        dialogo._quality_box.setCurrentIndex(indice)
        assert dialogo._sampling_token != antigo
        assert [pedido[2] for pedido in runtime.pedidos][-1] == "high" and len(runtime.pedidos) == 2
        runtime.liberar.set()
        _esperar(qapp, dialogo)
        assert {chave[3] for chave in dialogo._samples} == {"high"}  # a de antes nunca entrou
    finally:
        dialogo.close()


def test_so_audio_e_corte_rapido_nao_pedem_medida_de_video(qapp, tmp_path) -> None:
    dialogo, runtime, _ = _dialogo(tmp_path)
    try:
        runtime.liberar.set()
        _esperar(qapp, dialogo)
        pedidos = len(runtime.pedidos)
        dialogo._audio_only_check.setChecked(True)
        assert len(runtime.pedidos) == pedidos and "~" in dialogo._size_label.text()
    finally:
        dialogo.close()


def test_medida_que_falha_volta_para_a_conta_marcada(qapp, tmp_path) -> None:
    dialogo, runtime, projeto = _dialogo(tmp_path, falha=True)
    try:
        runtime.liberar.set()
        _esperar(qapp, dialogo)
        formula = estimate_export_size(
            duration=projeto.export_duration, width=projeto.width, height=projeto.height, fps=projeto.fps,
            video_codec="h264", quality=dialogo._quality_choice)
        assert dialogo._size_label.text() == format_size(formula, estimated=True)
    finally:
        dialogo.close()


def test_fechar_a_janela_interrompe_a_medida(qapp, tmp_path) -> None:
    dialogo, runtime, _ = _dialogo(tmp_path)
    assert dialogo._sampling
    dialogo.reject()  # o que o usuário faz ao fechar a janela modal; ``close()`` de uma janela nunca exibida não chega aqui
    assert not dialogo._sampling
    _esperar(qapp, dialogo)
    assert dialogo._sampling_runner.active == 0
