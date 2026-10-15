"""Testes do módulo de estimativa de tamanho e sua integração na interface."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from videomanager.application.capabilities import FFmpegTools
from videomanager.domain.media import AudioTarget
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import LocalStream
from videomanager.domain.media import VideoTarget
from videomanager.domain.estimator import estimate_audio_bitrate
from videomanager.domain.estimator import estimate_convert_size
from videomanager.domain.estimator import estimate_download_size
from videomanager.domain.estimator import estimate_export_size
from videomanager.domain.estimator import estimate_video_bitrate
from videomanager.domain.formats import AudioChoice
from videomanager.domain.formats import Fmt
from videomanager.domain.formats import FormatMatrix
from videomanager.domain.formats import Kind
from videomanager.domain.formats import Mode
from videomanager.domain.formats import VideoChoice
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import TrackKind
from videomanager.domain.project import new_project
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt.export_dialog import ExportDialog
from videomanager.presentation.qt.panels.convert_panel import ConvertPanel
from videomanager.presentation.qt.panels.quality_panel import QualityPanel
from videomanager.bootstrap import build_processing_service
from videomanager.bootstrap import build_desktop_runtime


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def dummy_tools(tmp_path: Path) -> FFmpegTools:
    ff = tmp_path / "ffmpeg"
    fp = tmp_path / "ffprobe"
    ff.write_text("#!/bin/sh\nexit 0\n")
    fp.write_text("#!/bin/sh\nexit 0\n")
    ff.chmod(0o755)
    fp.chmod(0o755)
    return FFmpegTools(ffmpeg=ff, ffprobe=fp, source="sistema")


class TestBitrateEstimates:
    def test_video_bitrate_resolution_scaling(self) -> None:
        rate_480 = estimate_video_bitrate(854, 480, 30.0, "h264")
        rate_720 = estimate_video_bitrate(1280, 720, 30.0, "h264")
        rate_1080 = estimate_video_bitrate(1920, 1080, 30.0, "h264")
        rate_4k = estimate_video_bitrate(3840, 2160, 30.0, "h264")

        assert rate_480 < rate_720 < rate_1080 < rate_4k
        assert 3500 < rate_1080 < 5500

    def test_video_bitrate_codec_efficiency(self) -> None:
        rate_h264 = estimate_video_bitrate(1920, 1080, 30.0, "h264")
        rate_hevc = estimate_video_bitrate(1920, 1080, 30.0, "hevc")
        rate_vp9 = estimate_video_bitrate(1920, 1080, 30.0, "vp9")
        rate_av1 = estimate_video_bitrate(1920, 1080, 30.0, "av1")

        assert rate_av1 < rate_hevc < rate_h264
        assert rate_vp9 < rate_h264
        assert abs(rate_hevc / rate_h264 - 0.60) < 0.05
        assert abs(rate_av1 / rate_h264 - 0.50) < 0.05

    def test_video_bitrate_fps_scaling(self) -> None:
        rate_30 = estimate_video_bitrate(1920, 1080, 30.0, "h264")
        rate_60 = estimate_video_bitrate(1920, 1080, 60.0, "h264")
        assert rate_60 > rate_30
        assert abs(rate_60 / rate_30 - (2.0 ** 0.5)) < 0.05

    def test_audio_bitrate_standards(self) -> None:
        assert estimate_audio_bitrate("mp3") == 192.0
        assert estimate_audio_bitrate("mp3", "320") == 320.0
        assert estimate_audio_bitrate("opus") == 128.0
        assert estimate_audio_bitrate("flac") == 800.0
        assert estimate_audio_bitrate("wav") == 1411.2


class TestDownloadSizeEstimation:
    def test_download_muxed_stream_with_filesize(self) -> None:
        fmt = Fmt(
            format_id="18",
            ext="mp4",
            kind=Kind.MUXED,
            height=360,
            filesize=15 * 1024 * 1024,
        )
        v_choice = VideoChoice(height=360, fps=30, family="h264", dynamic_range=None, formats=(fmt,))
        matrix = FormatMatrix(video=(v_choice,))

        size = estimate_download_size(matrix, Mode.VIDEO, v_choice, None, duration=60.0)
        assert size == 15 * 1024 * 1024

    def test_download_separate_video_and_audio_streams(self) -> None:
        v_fmt = Fmt(
            format_id="137",
            ext="mp4",
            kind=Kind.VIDEO_ONLY,
            height=1080,
            filesize=50 * 1024 * 1024,
        )
        a_fmt = Fmt(
            format_id="140",
            ext="m4a",
            kind=Kind.AUDIO_ONLY,
            abr=128.0,
            filesize=5 * 1024 * 1024,
        )
        v_choice = VideoChoice(height=1080, fps=30, family="h264", dynamic_range=None, formats=(v_fmt,))
        a_choice = AudioChoice(family="aac", bitrate=128.0, language=None, formats=(a_fmt,))
        matrix = FormatMatrix(video=(v_choice,), audio=(a_choice,))

        size = estimate_download_size(matrix, Mode.VIDEO, v_choice, a_choice, duration=60.0)
        assert size == (50 + 5) * 1024 * 1024

    def test_download_audio_only_reencode(self) -> None:
        a_fmt = Fmt(
            format_id="140",
            ext="m4a",
            kind=Kind.AUDIO_ONLY,
            abr=128.0,
            filesize=5 * 1024 * 1024,
        )
        a_choice = AudioChoice(family="aac", bitrate=128.0, language=None, formats=(a_fmt,))
        matrix = FormatMatrix(audio=(a_choice,))

        # 320 kbps por 100 segundos = 320_000 / 8 * 100 = 4_000_000 bytes
        size = estimate_download_size(
            matrix,
            Mode.AUDIO_ONLY,
            None,
            a_choice,
            audio_codec="mp3",
            audio_quality="320",
            duration=100.0,
        )
        assert size == int((320 * 1000 / 8) * 100.0)


class TestProfileSizeEstimation:
    """O tamanho de um perfil rápido é a conta do rodapé aplicada ao perfil: mesmo vídeo, mesma trilha de áudio."""

    @staticmethod
    def _matrix() -> FormatMatrix:
        def video(fid: str, height: int, mb: int) -> VideoChoice:
            fmt = Fmt(format_id=fid, ext="mp4", kind=Kind.VIDEO_ONLY, height=height, filesize=mb * 1024 * 1024)
            return VideoChoice(height=height, fps=30, family="h264", dynamic_range=None, formats=(fmt,))

        a_fmt = Fmt(format_id="140", ext="m4a", kind=Kind.AUDIO_ONLY, abr=128.0, filesize=5 * 1024 * 1024)
        audio = AudioChoice(family="aac", bitrate=128.0, language=None, formats=(a_fmt,))
        # Da melhor para a pior, como a matriz de verdade.
        return FormatMatrix(video=(video("313", 2160, 400), video("137", 1080, 50), video("135", 480, 12)), audio=(audio,))

    def test_o_limite_de_altura_escolhe_o_melhor_video_que_o_respeita(self) -> None:
        from videomanager.domain.estimator import estimate_profile_size
        matrix = self._matrix()
        assert estimate_profile_size(matrix, Mode.VIDEO, max_height=1080, duration=60.0) == (50 + 5) * 1024 * 1024
        assert estimate_profile_size(matrix, Mode.VIDEO, max_height=None, duration=60.0) == (400 + 5) * 1024 * 1024
        assert estimate_profile_size(matrix, Mode.VIDEO, max_height=500, duration=60.0) == (12 + 5) * 1024 * 1024

    def test_o_perfil_de_audio_usa_o_codec_e_a_qualidade_do_perfil(self) -> None:
        from videomanager.domain.estimator import estimate_profile_size
        matrix = self._matrix()
        mp3 = estimate_profile_size(matrix, Mode.AUDIO_ONLY, audio_codec="mp3", audio_quality="320", duration=100.0)
        assert mp3 == int((320 * 1000 / 8) * 100.0)
        # "Áudio original" copia a trilha: o tamanho é o dela, e não o de uma conta por bitrate.
        assert estimate_profile_size(matrix, Mode.AUDIO_ONLY, audio_codec="best", duration=100.0) == 5 * 1024 * 1024

    def test_sem_formato_nao_ha_o_que_estimar(self) -> None:
        from videomanager.domain.estimator import estimate_profile_size
        assert estimate_profile_size(FormatMatrix(), Mode.VIDEO, max_height=1080, duration=60.0) is None


class TestConvertSizeEstimation:
    def test_convert_copy_preserves_size(self, tmp_path: Path) -> None:
        media = LocalMedia(
            path=tmp_path / "video.mp4",
            duration=60.0,
            format_name="mov,mp4",
            size=20 * 1024 * 1024,
            streams=(
                LocalStream(index=0, kind="video", codec="h264", width=1920, height=1080),
                LocalStream(index=1, kind="audio", codec="aac"),
            ),
        )
        target = VideoTarget(container="mp4", video_codec="copy", audio_codec="copy")
        size = estimate_convert_size(media, target)
        assert size == 20 * 1024 * 1024

    def test_convert_reencode_hevc_is_smaller(self, tmp_path: Path) -> None:
        media = LocalMedia(
            path=tmp_path / "video.mp4",
            duration=60.0,
            format_name="mov,mp4",
            size=100 * 1024 * 1024,
            streams=(
                LocalStream(index=0, kind="video", codec="h264", width=1920, height=1080),
                LocalStream(index=1, kind="audio", codec="aac"),
            ),
        )
        target_h264 = VideoTarget(container="mp4", video_codec="h264", audio_codec="copy")
        target_hevc = VideoTarget(container="mp4", video_codec="hevc", audio_codec="copy")

        size_h264 = estimate_convert_size(media, target_h264)
        size_hevc = estimate_convert_size(media, target_hevc)

        assert size_hevc < size_h264

    def test_retrato_reduz_o_lado_curto_como_a_conversao(self, tmp_path: Path) -> None:
        # "720p" é o lado curto (ver ``needs_scaling``): o retrato sai 720×1280,
        # a mesma área da paisagem 1280×720, e não 405×720.
        def midia(largura: int, altura: int) -> LocalMedia:
            return LocalMedia(
                path=tmp_path / "video.mp4", duration=60.0, format_name="mov,mp4", size=None,
                streams=(LocalStream(index=0, kind="video", codec="h264", width=largura, height=altura),),
            )

        alvo = VideoTarget(container="mp4", video_codec="h264", height=720)
        assert estimate_convert_size(midia(1080, 1920), alvo) == estimate_convert_size(midia(1920, 1080), alvo)

    def test_convert_to_audio(self, tmp_path: Path) -> None:
        media = LocalMedia(
            path=tmp_path / "video.mp4",
            duration=100.0,
            format_name="mov,mp4",
            size=50 * 1024 * 1024,
            streams=(
                LocalStream(index=0, kind="video", codec="h264", width=1920, height=1080),
                LocalStream(index=1, kind="audio", codec="aac"),
            ),
        )
        target = AudioTarget(codec="mp3", bitrate="192")
        size = estimate_convert_size(media, target)
        # 192 kbps * 100s = 2.4 MB
        expected = int((192 * 1000 / 8) * 100.0)
        assert size == expected


class TestConvertSizeMeasuredAndAudio:
    """O que a amostra mede entra na conta sem o 1,5% fixo, e o áudio deixa de ser o bitrate pedido quando não é."""

    @staticmethod
    def _video(tmp_path: Path, audio_kbps: float | None = 191.0) -> LocalMedia:
        return LocalMedia(
            path=tmp_path / "video.mp4", duration=100.0, format_name="mov,mp4", size=80_000_000,
            streams=(LocalStream(index=0, kind="video", codec="h264", width=1920, height=1080, fps=30.0),
                     LocalStream(index=1, kind="audio", codec="aac", bitrate=audio_kbps, sample_rate=48000, channels=2)),
        )

    def test_audio_copiado_de_um_video_tem_o_bitrate_da_trilha_e_nao_o_pedido(self, tmp_path: Path) -> None:
        # AAC de 191 kbps copiado: o pedido de 128 kbps anunciava 34% a menos do que saía.
        size = estimate_convert_size(self._video(tmp_path), AudioTarget(codec="m4a", bitrate="128"))
        assert size == int(191.0 * 1000 / 8 * 100.0)

    def test_audio_copiado_sem_bitrate_da_trilha_usa_o_arquivo_se_for_so_audio(self, tmp_path: Path) -> None:
        music = LocalMedia(path=tmp_path / "a.m4a", duration=100.0, format_name="mov,mp4", size=3_000_000,
                           streams=(LocalStream(index=0, kind="audio", codec="aac"),))
        assert estimate_convert_size(music, AudioTarget(codec="m4a", bitrate="128")) == 3_000_000

    def test_audio_medido_vale_o_que_o_encoder_gravou_mais_o_container(self, tmp_path: Path) -> None:
        # O Opus de 128 kbps gravou 176: a amostra manda, não o pedido.
        alvo = AudioTarget(codec="opus", bitrate="128", reencode=True)
        size = estimate_convert_size(self._video(tmp_path), alvo, 176.0)
        assert size == pytest.approx(176.0 * 1000 / 8 * 100.0 * 1.008, rel=0.01)

    def test_sem_perda_sem_medida_parte_do_pcm_da_propria_trilha(self, tmp_path: Path) -> None:
        # 48 kHz estéreo de 16 bits são 1536 kbps; o 800 fixo errava −50% a −55% em áudios reais.
        size = estimate_convert_size(self._video(tmp_path), AudioTarget(codec="flac", bitrate="0"))
        assert size == pytest.approx(1536.0 * 0.85 * 1000 / 8 * 100.0)
        wav = estimate_convert_size(self._video(tmp_path), AudioTarget(codec="wav", bitrate="0"))
        assert wav == pytest.approx(1536.0 * 1000 / 8 * 100.0)

    def test_video_medido_paga_so_o_container_e_nao_um_e_meio_por_cento(self, tmp_path: Path) -> None:
        alvo = VideoTarget(container="mp4", video_codec="h264", audio_codec="aac", audio_bitrate="128")
        sem_medida = estimate_convert_size(self._video(tmp_path), alvo)
        medido = estimate_convert_size(self._video(tmp_path), alvo, 5000.0)
        carga = (5000.0 + 128.0) * 1000 / 8 * 100.0
        assert carga < medido < carga * 1.006  # 0,2–0,4% medido em 1080p
        assert sem_medida != medido


class TestExportSizeEstimation:
    def test_export_medido_soma_so_o_container_ao_bitrate_da_amostra(self) -> None:
        sem = estimate_export_size(duration=100.0, width=1920, height=1080, fps=30.0, video_codec="h264")
        medido = estimate_export_size(duration=100.0, width=1920, height=1080, fps=30.0, video_codec="h264",
                                      video_kbps=3000.0)
        carga = (3000.0 + 192.0) * 1000 / 8 * 100.0
        assert carga < medido < carga * 1.006
        assert medido < sem  # a conta por pixels anunciava mais que o dobro para esta fonte leve

    def test_export_medido_de_gif_nao_soma_audio(self) -> None:
        gif = estimate_export_size(duration=10.0, width=640, height=360, fps=15.0, video_codec="gif", video_kbps=800.0)
        assert gif < 800.0 * 1000 / 8 * 10.0 * 1.01

    def test_export_so_audio_sem_perda_parte_do_pcm_do_compositor(self) -> None:
        # O compositor mistura a 48 kHz estéreo: 1536 kbps de PCM. O 800 fixo do FLAC errava −39%.
        wav = estimate_export_size(duration=60.0, width=1, height=1, fps=30.0, video_codec="h264",
                                   audio_only=True, audio_codec="wav")
        flac = estimate_export_size(duration=60.0, width=1, height=1, fps=30.0, video_codec="h264",
                                    audio_only=True, audio_codec="flac")
        assert wav == int(1536.0 * 1000 / 8 * 60.0)
        assert flac == pytest.approx(wav * 0.85, rel=0.001)

    def test_export_normal_vs_audio_only(self) -> None:
        size_video = estimate_export_size(
            duration=60.0,
            width=1920,
            height=1080,
            fps=30.0,
            video_codec="h264",
        )
        size_audio = estimate_export_size(
            duration=60.0,
            width=1920,
            height=1080,
            fps=30.0,
            video_codec="h264",
            audio_only=True,
            audio_codec="mp3",
        )
        assert size_video > size_audio
        assert size_video > 10 * 1024 * 1024

    def test_export_fast_trim_proportional(self) -> None:
        size_fast = estimate_export_size(
            duration=30.0,
            width=1920,
            height=1080,
            fps=30.0,
            video_codec="h264",
            is_fast=True,
            source_size=100 * 1024 * 1024,
            source_duration=60.0,
        )
        assert size_fast == 50 * 1024 * 1024

    def test_export_quality_presets_affect_size(self) -> None:
        size_high = estimate_export_size(
            duration=60.0,
            width=1920,
            height=1080,
            fps=30.0,
            video_codec="h264",
            quality="high",
        )
        size_balanced = estimate_export_size(
            duration=60.0,
            width=1920,
            height=1080,
            fps=30.0,
            video_codec="h264",
            quality="balanced",
        )
        size_economy = estimate_export_size(
            duration=60.0,
            width=1920,
            height=1080,
            fps=30.0,
            video_codec="h264",
            quality="economy",
        )
        assert size_high > size_balanced > size_economy
        # Alta deve ser ~70-80% maior que equilibrada
        assert size_high > size_balanced * 1.5
        # Econômica deve ser ~40-50% menor que equilibrada
        assert size_economy < size_balanced * 0.7


class TestUIIntegration:
    def test_quality_panel_estimated_size_display(self, qapp: QApplication) -> None:
        settings = Settings()
        panel = QualityPanel(settings)

        # Sem mídia analisada
        assert panel._video_size_label.text() == "—"
        assert panel._audio_size_label.text() == "—"

        # Com mídia analisada de 60s
        v_fmt = Fmt(
            format_id="137",
            ext="mp4",
            kind=Kind.VIDEO_ONLY,
            height=1080,
            filesize=30 * 1024 * 1024,
        )
        a_fmt = Fmt(
            format_id="140",
            ext="m4a",
            kind=Kind.AUDIO_ONLY,
            abr=128.0,
            filesize=3 * 1024 * 1024,
        )
        v_choice = VideoChoice(height=1080, fps=30, family="h264", dynamic_range=None, formats=(v_fmt,))
        a_choice = AudioChoice(family="aac", bitrate=128.0, language=None, formats=(a_fmt,))
        matrix = FormatMatrix(video=(v_choice,), audio=(a_choice,))

        panel.set_matrix(matrix, duration=60.0)

        assert "MB" in panel._video_size_label.text() or "GB" in panel._video_size_label.text()
        assert "~" in panel._video_size_label.text()
        assert "MB" in panel._audio_size_label.text() or "GB" in panel._audio_size_label.text()

    def test_convert_panel_shows_estimated_size(
        self, qapp: QApplication, dummy_tools: FFmpegTools, tmp_path: Path
    ) -> None:
        settings = Settings()
        panel = ConvertPanel(settings, ensure_tools=lambda: dummy_tools, processing=build_processing_service(), runtime=build_desktop_runtime())

        v_file = tmp_path / "clip.mp4"
        v_file.write_bytes(b"dummy")

        media = LocalMedia(
            path=v_file,
            duration=30.0,
            format_name="mp4",
            size=10 * 1024 * 1024,
            streams=(
                LocalStream(index=0, kind="video", codec="h264", width=1920, height=1080),
                LocalStream(index=1, kind="audio", codec="aac"),
            ),
        )
        panel._media.append(media)
        panel._update_plan()

        assert not panel._plan.isHidden()
        assert "Tamanho estimado:" in panel._plan.text()
        assert "KB" in panel._plan.text() or "MB" in panel._plan.text() or "GB" in panel._plan.text()

        # Muda para conversão de vídeo
        panel._to_video.setChecked(True)
        assert "MB" in panel._plan.text() or "GB" in panel._plan.text()

    def test_export_dialog_shows_estimated_size(
        self, qapp: QApplication, dummy_tools: FFmpegTools, tmp_path: Path
    ) -> None:
        video_path = tmp_path / "orig.mp4"
        video_path.write_bytes(b"data")
        ref = MediaRef(
            path=video_path,
            kind=MediaKind.VIDEO,
            duration=40.0,
            width=1920,
            height=1080,
            fps=30.0,
            has_audio=True,
        )
        local = LocalMedia(
            path=video_path,
            duration=40.0,
            format_name="mp4",
            size=15 * 1024 * 1024,
            streams=(
                LocalStream(index=0, kind="video", codec="h264", width=1920, height=1080, fps=30.0),
                LocalStream(index=1, kind="audio", codec="aac"),
            ),
        )
        clip = Clip(media=ref, start=0.0, duration=40.0)
        proj = new_project().with_track(
            TrackKind.VIDEO, name="Vídeo 1"
        ).with_clip(0, clip)

        dialog = ExportDialog(
            project=proj,
            settings=Settings(),
            pool=[ref],
            probed={video_path: local},
            ensure_tools=lambda: dummy_tools,
         processing=build_processing_service(), runtime=build_desktop_runtime())
        try:
            assert dialog._size_label.text() != "—"
            assert "MB" in dialog._size_label.text() or "GB" in dialog._size_label.text()
            assert "~" in dialog._size_label.text()

            # Ao marcar somente áudio, o tamanho deve diminuir substancialmente
            orig_text = dialog._size_label.text()
            dialog._audio_only_check.setChecked(True)
            audio_text = dialog._size_label.text()
            assert audio_text != orig_text
            assert "MB" in audio_text or "KB" in audio_text
        finally:
            dialog.close()


# Estes cenários exercitam adaptadores ou apresentação Qt.
pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")
