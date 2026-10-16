"""O tamanho que a aba Converter anuncia: medido em todo o que recodifica, e honesto quando não deu para medir.

A conta por pixels errava de −66% a +1500% e anunciava que o arquivo cresceria quando ele encolhia. Fora do modo
Comprimir ela ainda era a única coisa que a aba mostrava; agora vira "medindo…" até a amostra chegar, e só volta como
aproximação marcada quando a medida falha.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.estimator import estimate_convert_size
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import LocalStream
from videomanager.domain.media import VideoTarget
from videomanager.presentation.qt.panels import convert_rows

TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")


class _AmostrasFalsas:
    """O runtime de verdade, com a medida trocada por uma que só termina quando liberada (ou que falha)."""

    def __init__(self, runtime, kbps: float = 3000.0, falha: bool = False) -> None:
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
        audio = isinstance(target, AudioTarget)
        self.pedidos.append((media.path.name, target.codec if audio else target.video_codec))

        def medir():
            while not self.liberar.wait(0.005):
                control.check()
            control.check()
            if self.falha:
                raise ConversionError(Text("CONVERT_SAMPLE_FAILED"))
            return 100.0 if audio else self.kbps

        return FunctionWorker(medir, control.cancel)


def _painel(desktop_app, tmp_path, kbps=3000.0, falha=False):
    from videomanager.application.preferences import Preferences
    from videomanager.bootstrap import build_desktop_runtime, build_processing_service
    from videomanager.presentation.qt.panels.convert_panel import ConvertPanel

    runtime = _AmostrasFalsas(build_desktop_runtime(audio_enabled=False), kbps, falha)
    video = LocalMedia(tmp_path / "video.mp4", 60.0, "mov,mp4", 80_000_000,
                       (LocalStream(0, "video", "h264", height=1080, width=1920, fps=30.0),
                        LocalStream(1, "audio", "aac", bitrate=128.0, sample_rate=48000, channels=2)))
    musica = LocalMedia(tmp_path / "musica.flac", 180.0, "flac", 20_000_000,
                        (LocalStream(0, "audio", "flac", bitrate=900.0, sample_rate=44100, channels=2),))
    panel = ConvertPanel(Preferences(), lambda: TOOLS, processing=build_processing_service(), runtime=runtime)
    panel._tools = TOOLS
    panel._on_inspected(panel._inspection_token, SimpleNamespace(probed={m.path: m for m in (video, musica)}, rejected=[]))
    return panel, runtime, video, musica


def _codec(panel, codec: str) -> None:
    panel._to_video.setChecked(True)  # a aba abre em áudio
    panel._video_codec.setCurrentIndex(panel._video_codec.findData(codec))


def _fechar(panel) -> None:
    panel.shutdown()
    panel.deleteLater()


def test_copiar_nao_pede_medida(desktop_app, tmp_path) -> None:
    panel, runtime, *_ = _painel(desktop_app, tmp_path)
    try:
        _codec(panel, "copy")
        assert runtime.pedidos == []
        assert "video.mp4" in panel._list.item(0).text()
        assert panel._list.item(0).data(convert_rows.ROLE_AFTER)["size"] is not None
    finally:
        _fechar(panel)


def test_copiar_que_recodifica_de_fato_tambem_e_medido(desktop_app, wait_until, tmp_path) -> None:
    """A aba nasce em "Cópia": redimensionar recodifica do mesmo jeito, e a conta por pixels errou de −39% a +609% aí."""
    from videomanager.domain.compatibility import needs_video_reencode
    from videomanager.presentation.qt import strings

    panel, runtime, video, _ = _painel(desktop_app, tmp_path)
    try:
        _codec(panel, "copy")
        assert runtime.pedidos == []  # copiar de verdade continua sem medida
        panel._resize.setCurrentIndex(panel._resize.findData(720))
        alvo = panel._build_target(video)
        assert alvo.video_codec == "copy" and needs_video_reencode(video, alvo)
        assert runtime.pedidos == [("video.mp4", "copy")]
        assert panel._list.item(0).data(convert_rows.ROLE_AFTER)["size"] is None
        assert strings.CONVERT_MEASURING in panel._plan.text()

        runtime.liberar.set()
        wait_until(lambda: not panel._sampling and panel._sampling_runner.active == 0, timeout=10)
        dado = panel._list.item(0).data(convert_rows.ROLE_AFTER)
        assert dado["size"] == estimate_convert_size(video, alvo, 3000.0) and dado["approximate"] is False
    finally:
        _fechar(panel)


def test_recodificar_fora_da_compressao_espera_a_amostra_e_usa_o_que_ela_mediu(desktop_app, wait_until, tmp_path) -> None:
    from videomanager.presentation.qt import strings

    panel, runtime, video, _ = _painel(desktop_app, tmp_path)
    try:
        _codec(panel, "h264")
        assert runtime.pedidos == [("video.mp4", "h264")]
        assert panel._list.item(0).data(convert_rows.ROLE_AFTER) == {"size": None, "approximate": False, "skipped": False}
        assert strings.CONVERT_MEASURING in panel._plan.text()

        runtime.liberar.set()
        wait_until(lambda: not panel._sampling and panel._sampling_runner.active == 0, timeout=10)
        alvo = panel._build_target(video)
        assert isinstance(alvo, VideoTarget)
        dado = panel._list.item(0).data(convert_rows.ROLE_AFTER)
        assert dado == {"size": estimate_convert_size(video, alvo, 3000.0), "approximate": False, "skipped": False}
        assert strings.CONVERT_MEASURING not in panel._plan.text()
    finally:
        _fechar(panel)


def test_trocar_de_codec_abandona_a_medida_que_ninguem_pede(desktop_app, wait_until, tmp_path) -> None:
    panel, runtime, *_ = _painel(desktop_app, tmp_path)
    try:
        _codec(panel, "h264")
        antigo = panel._sampling_token
        _codec(panel, "hevc")
        assert panel._sampling_token != antigo
        assert runtime.pedidos == [("video.mp4", "h264"), ("video.mp4", "hevc")]
        runtime.liberar.set()
        wait_until(lambda: not panel._sampling and panel._sampling_runner.active == 0, timeout=10)
        assert {chave[2] for chave in panel._samples} == {"hevc"}  # a do h264 nunca entrou
    finally:
        _fechar(panel)


def test_mesma_escolha_nao_mede_duas_vezes(desktop_app, wait_until, tmp_path) -> None:
    panel, runtime, *_ = _painel(desktop_app, tmp_path)
    try:
        runtime.liberar.set()
        _codec(panel, "h264")
        wait_until(lambda: not panel._sampling and panel._sampling_runner.active == 0, timeout=10)
        _codec(panel, "hevc")
        wait_until(lambda: not panel._sampling and panel._sampling_runner.active == 0, timeout=10)
        _codec(panel, "h264")  # voltar a uma escolha já medida não mede de novo
        assert runtime.pedidos == [("video.mp4", "h264"), ("video.mp4", "hevc")]
    finally:
        _fechar(panel)


def test_conversao_so_de_audio_mede_o_codec_de_taxa_variavel(desktop_app, tmp_path) -> None:
    panel, runtime, *_ = _painel(desktop_app, tmp_path)
    try:
        panel._to_audio.setChecked(True)
        panel._audio_codec.setCurrentIndex(panel._audio_codec.findData("opus"))
        assert ("musica.flac", "opus") in runtime.pedidos and ("video.mp4", "opus") in runtime.pedidos
        runtime.pedidos.clear()
        panel._audio_codec.setCurrentIndex(panel._audio_codec.findData("mp3"))  # taxa constante: a conta acerta
        assert runtime.pedidos == []
    finally:
        _fechar(panel)


def test_medida_que_falha_vira_aproximacao_marcada_e_nao_afirma_variacao(desktop_app, wait_until, tmp_path) -> None:
    from videomanager.presentation.qt import strings

    panel, runtime, video, _ = _painel(desktop_app, tmp_path, falha=True)
    try:
        _codec(panel, "h264")
        runtime.liberar.set()
        wait_until(lambda: not panel._sampling and panel._sampling_runner.active == 0, timeout=10)
        dado = panel._list.item(0).data(convert_rows.ROLE_AFTER)
        assert dado["approximate"] is True and dado["size"] == estimate_convert_size(video, panel._build_target(video))
        assert convert_rows.change_label(video, dado) is None
        assert strings.CONVERT_SIZE_APPROXIMATE in panel._plan.text()
    finally:
        _fechar(panel)


def test_arquivo_que_a_conversao_ignora_nao_tem_tamanho_nem_variacao(desktop_app, tmp_path) -> None:
    """Um áudio na conversão de vídeo é ignorado: a conta por pixels dava "+37%" a um arquivo que nem é gravado."""
    panel, runtime, video, musica = _painel(desktop_app, tmp_path)
    try:
        _codec(panel, "copy")
        linha = panel._list.item(1)
        assert linha.text().endswith("→ —")
        dado = linha.data(convert_rows.ROLE_AFTER)
        assert dado["skipped"] is True and dado["size"] == 0
        assert convert_rows.change_label(musica, dado) is None
        # Fora o ignorado, o total é a soma do que é gravado.
        assert panel._estimate(video, panel._build_target(video)) == panel._list.item(0).data(convert_rows.ROLE_AFTER)["size"]
        assert panel._estimate(musica, panel._build_target(musica)) == 0
        # No áudio, é o vídeo sem trilha de som que sai da lista de gravações.
        panel._to_audio.setChecked(True)
        assert panel._list.item(1).data(convert_rows.ROLE_AFTER)["skipped"] is False
    finally:
        _fechar(panel)


class TestVariacaoNaLinha:
    MEDIA = LocalMedia(Path("v.mp4"), 60.0, "mov,mp4", 100_000_000, ())

    def test_variacao_clara_escolhe_lado_e_cor(self) -> None:
        assert convert_rows.change_label(self.MEDIA, {"size": 130_000_000}) == ("+30%", "warn")
        assert convert_rows.change_label(self.MEDIA, {"size": 60_000_000}) == ("−40%", "ok")

    def test_dentro_do_erro_da_medida_nao_escolhe_lado(self) -> None:
        for size in (97_000_000, 100_000_000, 103_000_000):
            assert convert_rows.change_label(self.MEDIA, {"size": size}) == ("≈0%", "t2")
        assert convert_rows.change_label(self.MEDIA, {"size": 104_000_000}) == ("+4%", "warn")

    def test_sem_medida_ou_sem_tamanho_nao_ha_o_que_afirmar(self) -> None:
        assert convert_rows.change_label(self.MEDIA, {"size": None}) is None
        assert convert_rows.change_label(self.MEDIA, {"size": 50_000_000, "approximate": True}) is None
        sem_tamanho = LocalMedia(Path("v.mp4"), 60.0, "mov,mp4", None, ())
        assert convert_rows.change_label(sem_tamanho, {"size": 50_000_000}) is None
