"""Testes da tradução de escolha do usuário em opções do yt-dlp.

O teste mais importante do arquivo é
:func:`test_toda_expressao_gerada_e_valida_para_o_ytdlp`: ele submete cada
expressão de formato ao **parser real** do yt-dlp. Um erro de sintaxe aqui não
apareceria em nenhum teste que só compare strings — apareceria no primeiro
download do usuário.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yt_dlp
from conftest import FIXTURE_NAMES, fixture_formats

from videomanager.core.binaries import FFmpegTools
from videomanager.core.format_matrix import build_matrix
from videomanager.core.models import MediaInfo
from videomanager.core.selector import (
    AUDIO_CODECS,
    CONTAINER_AUTO,
    CONTAINERS,
    AudioRequest,
    VideoRequest,
    audio_quality_warning,
    build_audio_format_string,
    build_audio_opts,
    build_opts,
    build_outtmpl,
    build_video_format_string,
    build_video_opts,
    describe_request,
    plan_container,
)
from videomanager.core.settings import Settings

TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")


def media(name: str) -> MediaInfo:
    matrix = build_matrix(fixture_formats(name))
    return MediaInfo(url=f"https://exemplo/{name}", title=name, matrix=matrix)


def synthetic(*formats: dict) -> MediaInfo:
    return MediaInfo(url="https://exemplo/x", title="x", matrix=build_matrix(list(formats)))


# ---------------------------------------------------------------------------
# Validade sintática — o teste que importa mais
# ---------------------------------------------------------------------------


def _todas_as_expressoes() -> list[tuple[str, str]]:
    """Gera expressões cobrindo cada combinação de fixture, container e modo."""
    casos: list[tuple[str, str]] = []
    parser = yt_dlp.YoutubeDL({"quiet": True})
    assert parser  # apenas para deixar claro que o parser existe

    for name in FIXTURE_NAMES:
        info = media(name)
        matrix = info.matrix
        for container in CONTAINERS:
            # explícito, quando houver o que escolher
            if matrix.video:
                video = matrix.video[0]
                audio = matrix.audio[0] if matrix.audio else None
                plan = plan_container(matrix, video, audio, container)
                casos.append(
                    (
                        f"{name}/{container}/explícito",
                        build_video_format_string(
                            matrix, plan.video, plan.audio, container=plan.container
                        ),
                    )
                )
            # automático
            for altura, fps in ((None, None), (720, 30), (2160, 60), (144, 24)):
                casos.append(
                    (
                        f"{name}/{container}/auto/{altura}p{fps}",
                        build_video_format_string(
                            matrix, None, None, container=container,
                            max_height=altura, max_fps=fps,
                        ),
                    )
                )
        casos.append((f"{name}/áudio/auto", build_audio_format_string(None)))
        if matrix.audio:
            casos.append((f"{name}/áudio/explícito", build_audio_format_string(matrix.audio[0])))
    return casos


@pytest.mark.parametrize(("rotulo", "expressao"), _todas_as_expressoes())
def test_toda_expressao_gerada_e_valida_para_o_ytdlp(rotulo: str, expressao: str) -> None:
    """O yt-dlp precisa conseguir compilar a expressão.

    Cobre a sintaxe de filtro não-estrito (``[height<=?720]``) e o operador de
    regex (``~=``), que são fáceis de escrever errado e impossíveis de validar
    de cabeça.
    """
    ydl = yt_dlp.YoutubeDL({"quiet": True})
    assert ydl.build_format_selector(expressao) is not None, rotulo


# ---------------------------------------------------------------------------
# Filtros não-estritos
# ---------------------------------------------------------------------------


def test_filtros_de_limite_sao_nao_estritos() -> None:
    """Sem o ``?``, sites que não informam fps perderiam todos os formatos."""
    expressao = build_video_format_string(
        build_matrix([]), None, None, max_height=720, max_fps=30
    )
    assert "[height<=?720]" in expressao
    assert "[fps<=?30]" in expressao
    assert "[height<=720]" not in expressao, "filtro estrito eliminaria formatos sem height"
    assert "[fps<=30]" not in expressao, "filtro estrito eliminaria formatos sem fps"


def test_filtro_nao_estrito_realmente_preserva_formato_sem_fps() -> None:
    """Verificação de comportamento, não de texto: o archive.org não tem fps.

    Executa o seletor do yt-dlp sobre os formatos da fixture e confirma que algo
    é escolhido mesmo com um limite de framerate ativo.
    """
    info = media("archive_muxed")
    expressao = build_video_format_string(
        info.matrix, None, None, max_height=1080, max_fps=30
    )
    ydl = yt_dlp.YoutubeDL({"quiet": True})
    seletor = ydl.build_format_selector(expressao)
    formatos = fixture_formats("archive_muxed")
    escolhidos = list(seletor({"formats": formatos, "incomplete_formats": False}))
    assert escolhidos, "nenhum formato sobreviveu ao limite de fps num site sem fps"


# ---------------------------------------------------------------------------
# Nunca baixar vídeo mudo
# ---------------------------------------------------------------------------


def test_nenhum_elo_baixa_video_sem_audio_quando_ha_audio() -> None:
    """Um arquivo mudo é um defeito silencioso, pior que um erro explícito.

    Com trilhas separadas, todo elo que peça um formato só-vídeo tem de somar
    uma trilha de áudio.
    """
    info = media("youtube_dash")
    video = info.matrix.video[0]  # só-vídeo (DASH)
    audio = info.matrix.audio[0]
    expressao = build_video_format_string(info.matrix, video, audio)

    ids_so_video = {
        f.format_id
        for c in info.matrix.video
        for f in c.formats
        if not c.is_muxed
    }
    for elo in expressao.split("/"):
        if elo in ids_so_video:
            pytest.fail(f"o elo {elo!r} baixaria vídeo sem áudio")


def test_formato_mesclado_nao_recebe_audio_somado() -> None:
    """Somar áudio a um formato que já o tem duplicaria a trilha."""
    info = synthetic(
        {"format_id": "18", "vcodec": "avc1", "acodec": "mp4a", "height": 360, "fps": 30}
    )
    expressao = build_video_format_string(info.matrix, info.matrix.video[0], None)
    assert expressao.split("/")[0] == "18"


def test_sem_audio_na_midia_nao_exige_audio() -> None:
    """Numa mídia sem trilha de áudio, exigir áudio faria todo elo falhar."""
    info = synthetic(
        {"format_id": "v", "vcodec": "avc1", "acodec": "none", "height": 720, "format_note": "video only"}
    )
    assert info.matrix.has_audio is False
    assert build_video_format_string(info.matrix, info.matrix.video[0], None).split("/")[0] == "v"


def test_cadeia_termina_em_fallback_generico() -> None:
    info = media("youtube_dash")
    expressao = build_video_format_string(info.matrix, info.matrix.video[0], info.matrix.audio[0])
    assert expressao.split("/")[-1] == "b", "a cadeia precisa de uma rede de segurança final"


def test_cadeia_nao_repete_elos() -> None:
    info = media("youtube_dash")
    elos = build_video_format_string(info.matrix, info.matrix.video[0], info.matrix.audio[0]).split("/")
    assert len(elos) == len(set(elos))


# ---------------------------------------------------------------------------
# Container: trocar stream, nunca recodificar
# ---------------------------------------------------------------------------


class TestPlanContainer:
    def test_mkv_aceita_tudo_sem_aviso(self) -> None:
        info = media("youtube_dash")
        plano = plan_container(info.matrix, info.matrix.video[0], info.matrix.audio[0], "mkv")
        assert plano.container == "mkv"
        assert plano.warnings == ()

    def test_auto_deixa_o_ytdlp_decidir(self) -> None:
        info = media("youtube_dash")
        plano = plan_container(info.matrix, info.matrix.video[0], info.matrix.audio[0], CONTAINER_AUTO)
        assert plano.merge_output_format is None

    def test_mp4_troca_opus_por_aac_sem_recodificar(self) -> None:
        """Troca de stream: mesma qualidade, sem recodificação."""
        info = synthetic(
            {"format_id": "v", "vcodec": "avc1", "acodec": "none", "height": 1080, "fps": 30},
            {"format_id": "opus", "vcodec": "none", "acodec": "opus", "abr": 160},
            {"format_id": "aac", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128},
        )
        opus = next(c for c in info.matrix.audio if c.family == "Opus")
        plano = plan_container(info.matrix, info.matrix.video[0], opus, "mp4")
        assert plano.audio is not None and plano.audio.family == "AAC"
        assert plano.container == "mp4"
        assert any("sem recodificar" in aviso for aviso in plano.warnings)

    def test_mp4_cai_para_mkv_quando_o_audio_nao_tem_alternativa(self) -> None:
        """Sem trilha compatível, trocar o container preserva o áudio original."""
        info = synthetic(
            {"format_id": "v", "vcodec": "avc1", "acodec": "none", "height": 720, "fps": 30},
            {"format_id": "vorb", "vcodec": "none", "acodec": "vorbis", "abr": 128},
        )
        plano = plan_container(info.matrix, info.matrix.video[0], info.matrix.audio[0], "mp4")
        assert plano.container == "mkv"
        assert plano.audio is not None and plano.audio.family == "Vorbis"
        assert plano.warnings

    def test_webm_com_h264_cai_para_mkv(self) -> None:
        """H.264 não é válido em WebM."""
        info = synthetic(
            {"format_id": "v", "vcodec": "avc1", "acodec": "none", "height": 720, "fps": 30},
            {"format_id": "a", "vcodec": "none", "acodec": "opus", "abr": 128},
        )
        plano = plan_container(info.matrix, info.matrix.video[0], info.matrix.audio[0], "webm")
        assert plano.container == "mkv"

    def test_vp9_em_mp4_avisa_sobre_compatibilidade(self) -> None:
        """Gera arquivo válido, mas muitos aparelhos não reproduzem."""
        info = synthetic(
            {"format_id": "v", "vcodec": "vp09.00.50.08", "acodec": "none", "height": 2160, "fps": 60},
            {"format_id": "a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128},
        )
        plano = plan_container(info.matrix, info.matrix.video[0], info.matrix.audio[0], "mp4")
        assert plano.warnings, "o usuário precisa ser avisado antes do download"

    def test_mp4_mantem_a_resolucao_ao_trocar_de_codec(self) -> None:
        """Trocar de codec não deve rebaixar a resolução escolhida."""
        info = synthetic(
            {"format_id": "vp9-1080", "vcodec": "vp08", "acodec": "none", "height": 1080, "fps": 30},
            {"format_id": "h264-1080", "vcodec": "avc1", "acodec": "none", "height": 1080, "fps": 30},
            {"format_id": "h264-480", "vcodec": "avc1", "acodec": "none", "height": 480, "fps": 30},
            {"format_id": "a", "vcodec": "none", "acodec": "mp4a", "abr": 128},
        )
        vp8 = next(c for c in info.matrix.video if c.family == "VP8")
        plano = plan_container(info.matrix, vp8, info.matrix.audio[0], "mp4")
        assert plano.video is not None
        assert plano.video.height == 1080, "não deve cair para 480p ao trocar de codec"
        assert plano.video.family == "H.264"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
@pytest.mark.parametrize("container", CONTAINERS)
def test_plano_nunca_pede_recodificacao(name: str, container: str) -> None:
    """Invariante central: nenhum caminho recodifica sem consentimento.

    Um postprocessor de conversão de vídeo nunca deve aparecer nas opções
    geradas por escolha de container.
    """
    info = media(name)
    if not info.matrix.video:
        pytest.skip("fixture sem vídeo")
    pedido = VideoRequest(
        video=info.matrix.video[0],
        audio=info.matrix.audio[0] if info.matrix.audio else None,
        container=container,
    )
    opts, _plano = build_video_opts(pedido, info, Settings(), TOOLS, Path("/tmp/d"), Path("/tmp/t"))
    chaves = {pp["key"] for pp in opts.get("postprocessors", [])}
    assert "FFmpegVideoConvertor" not in chaves


# ---------------------------------------------------------------------------
# Somente áudio
# ---------------------------------------------------------------------------


class TestAudio:
    def test_original_nao_recodifica(self) -> None:
        info = media("youtube_dash")
        opts = build_audio_opts(
            AudioRequest(audio=info.matrix.audio[0], codec="best"),
            info, Settings(), TOOLS, Path("/tmp/d"), Path("/tmp/t"),
        )
        extract = next(pp for pp in opts["postprocessors"] if pp["key"] == "FFmpegExtractAudio")
        assert extract["preferredcodec"] == "best"
        assert "preferredquality" not in extract, "não faz sentido pedir bitrate ao copiar"

    def test_mp3_recebe_bitrate_e_id3v2_3(self) -> None:
        """Sem ID3v2.3 o Windows não mostra título nem artista."""
        info = media("youtube_dash")
        opts = build_audio_opts(
            AudioRequest(audio=info.matrix.audio[0], codec="mp3", quality="320"),
            info, Settings(), TOOLS, Path("/tmp/d"), Path("/tmp/t"),
        )
        extract = next(pp for pp in opts["postprocessors"] if pp["key"] == "FFmpegExtractAudio")
        assert extract["preferredquality"] == "320"
        assert opts["postprocessor_args"]["extractaudio"] == ["-id3v2_version", "3", "-metadata", "title="]
        assert opts["postprocessor_args"]["default"] == ["-metadata", "title="]

    @pytest.mark.parametrize("codec", ("flac", "wav", "alac"))
    def test_formatos_sem_perda_nao_recebem_bitrate(self, codec: str) -> None:
        info = media("youtube_dash")
        opts = build_audio_opts(
            AudioRequest(audio=info.matrix.audio[0], codec=codec, quality="320"),
            info, Settings(), TOOLS, Path("/tmp/d"), Path("/tmp/t"),
        )
        extract = next(pp for pp in opts["postprocessors"] if pp["key"] == "FFmpegExtractAudio")
        assert "preferredquality" not in extract

    @pytest.mark.parametrize("codec", AUDIO_CODECS)
    def test_todo_codec_oferecido_e_aceito_pelo_ytdlp(self, codec: str) -> None:
        """A lista da interface não pode oferecer codec que o yt-dlp recusa."""
        from yt_dlp.postprocessor import FFmpegExtractAudioPP

        assert codec == "best" or codec in FFmpegExtractAudioPP.SUPPORTED_EXTS

    def test_expressao_de_audio_aceita_fonte_mesclada(self) -> None:
        """Em sites sem trilha separada, ``ba`` falharia sozinho."""
        assert "ba*" in build_audio_format_string(None)


class TestAvisoDeBitrate:
    def test_avisa_ao_pedir_mais_do_que_a_fonte_tem(self) -> None:
        matrix = build_matrix(
            [{"format_id": "a", "vcodec": "none", "acodec": "opus", "abr": 128}]
        )
        aviso = audio_quality_warning(matrix, "mp3", "320")
        assert aviso and "128" in aviso

    def test_nao_avisa_quando_o_pedido_cabe(self) -> None:
        matrix = build_matrix(
            [{"format_id": "a", "vcodec": "none", "acodec": "opus", "abr": 256}]
        )
        assert audio_quality_warning(matrix, "mp3", "192") is None

    def test_nao_avisa_para_sem_perda_nem_para_original(self) -> None:
        matrix = build_matrix([{"format_id": "a", "vcodec": "none", "acodec": "opus", "abr": 64}])
        assert audio_quality_warning(matrix, "flac", "320") is None
        assert audio_quality_warning(matrix, "best", "320") is None

    def test_bitrate_invalido_nao_quebra(self) -> None:
        matrix = build_matrix([{"format_id": "a", "vcodec": "none", "acodec": "opus", "abr": 64}])
        assert audio_quality_warning(matrix, "mp3", "não é número") is None


# ---------------------------------------------------------------------------
# Opções gerais
# ---------------------------------------------------------------------------


class TestOpcoesBase:
    def _opts(self, settings: Settings | None = None) -> dict:
        info = media("youtube_dash")
        opts, _ = build_video_opts(
            VideoRequest(video=info.matrix.video[0], audio=info.matrix.audio[0]),
            info, settings or Settings(), TOOLS, Path("/destino"), Path("/temp"),
        )
        return opts

    def test_parciais_ficam_fora_da_pasta_de_destino(self) -> None:
        caminhos = self._opts()["paths"]
        assert caminhos["home"] == "/destino"
        assert caminhos["temp"] == "/temp", "sem isto, arquivos .part sujam a pasta final"

    def test_playlist_nao_e_arrastada_num_video_unico(self) -> None:
        """Uma URL com "&list=" não deve baixar a playlist inteira."""
        assert self._opts()["noplaylist"] is True

    def test_sanitizacao_windows_sempre_ativa(self) -> None:
        assert self._opts()["windowsfilenames"] is True

    def test_ffmpeg_localizado_explicitamente(self) -> None:
        assert self._opts()["ffmpeg_location"] == str(TOOLS.ffmpeg)

    def test_limite_de_banda_convertido_para_bytes(self) -> None:
        opts = self._opts(Settings(rate_limit_kbps=500))
        assert opts["ratelimit"] == 500 * 1024

    def test_sem_limite_nao_define_ratelimit(self) -> None:
        assert "ratelimit" not in self._opts(Settings(rate_limit_kbps=0))

    def test_cookies_do_navegador_no_formato_de_tupla(self) -> None:
        opts = self._opts(Settings(cookies_browser="firefox"))
        assert opts["cookiesfrombrowser"] == ("firefox", None, None, None)

    def test_sem_navegador_nao_tenta_ler_cookies(self) -> None:
        assert "cookiesfrombrowser" not in self._opts(Settings(cookies_browser=""))

    def test_fragmentos_simultaneos_nunca_zero(self) -> None:
        assert self._opts(Settings(concurrent_fragments=0))["concurrent_fragment_downloads"] >= 1


class TestOuttmpl:
    def test_titulo_truncado_em_bytes(self) -> None:
        """O ``B`` corta em bytes, o que evita partir um caractere UTF-8 no meio.

        Cortar por caracteres estouraria o limite de caminho do Windows em
        títulos com acentos ou ideogramas; cortar por bytes sem o ``B`` do yt-dlp
        produziria um nome inválido.
        """
        assert "%(title).150B" in build_outtmpl(Settings())

    def test_id_evita_colisao_de_nomes(self) -> None:
        assert "%(id)s" in build_outtmpl(Settings())

    def test_subpasta_por_site_quando_ativado(self) -> None:
        tmpl = build_outtmpl(Settings(separate_by_site=True))
        assert tmpl.startswith("%(extractor_key,extractor)s/")

    def test_outtmpl_e_valido_para_o_ytdlp(self) -> None:
        """Um template inválido só falharia na hora de nomear o arquivo."""
        for settings in (Settings(), Settings(separate_by_site=True)):
            ydl = yt_dlp.YoutubeDL({"quiet": True, "outtmpl": build_outtmpl(settings)})
            nome = ydl.prepare_filename(
                {"id": "abc123", "title": "Um Título Acentuado — çãõ", "ext": "mp4"}
            )
            assert nome and nome.endswith(".mp4")


class TestMetadados:
    def test_capa_e_metadados_por_padrao(self) -> None:
        info = media("youtube_dash")
        opts, _ = build_video_opts(
            VideoRequest(video=info.matrix.video[0], audio=info.matrix.audio[0]),
            info, Settings(), TOOLS, Path("/d"), Path("/t"),
        )
        chaves = [pp["key"] for pp in opts["postprocessors"]]
        assert "FFmpegMetadata" in chaves
        assert "EmbedThumbnail" in chaves
        assert opts["writethumbnail"] is True
        assert chaves.index("FFmpegMetadata") < chaves.index("EmbedThumbnail"), (
            "a capa reescreve o container e pode descartar tags gravadas depois"
        )

    def test_podem_ser_desligados(self) -> None:
        info = media("youtube_dash")
        opts, _ = build_video_opts(
            VideoRequest(video=info.matrix.video[0], audio=info.matrix.audio[0]),
            info, Settings(embed_metadata=False, embed_thumbnail=False),
            TOOLS, Path("/d"), Path("/t"),
        )
        assert not opts.get("postprocessors")
        assert "writethumbnail" not in opts


class TestLegendas:
    def test_desativadas_por_padrao(self) -> None:
        info = media("youtube_dash")
        opts, _ = build_video_opts(
            VideoRequest(video=info.matrix.video[0]), info, Settings(), TOOLS, Path("/d"), Path("/t")
        )
        assert "writesubtitles" not in opts

    def test_embutir_adiciona_postprocessor(self) -> None:
        info = media("youtube_dash")
        opts, _ = build_video_opts(
            VideoRequest(video=info.matrix.video[0]), info,
            Settings(embed_subtitles=True, subtitle_langs=["pt-BR"]),
            TOOLS, Path("/d"), Path("/t"),
        )
        assert opts["writesubtitles"] is True
        assert opts["subtitleslangs"] == ["pt-BR"]
        assert "FFmpegEmbedSubtitle" in {pp["key"] for pp in opts["postprocessors"]}


# ---------------------------------------------------------------------------
# Despacho e descrição
# ---------------------------------------------------------------------------


def test_build_opts_despacha_por_tipo_de_pedido() -> None:
    info = media("youtube_dash")
    opts_video, plano = build_opts(
        VideoRequest(video=info.matrix.video[0]), info, Settings(), TOOLS, Path("/d"), Path("/t")
    )
    assert plano is not None
    opts_audio, plano_audio = build_opts(
        AudioRequest(codec="mp3"), info, Settings(), TOOLS, Path("/d"), Path("/t")
    )
    assert plano_audio is None
    assert "FFmpegExtractAudio" in {pp["key"] for pp in opts_audio["postprocessors"]}
    assert "FFmpegExtractAudio" not in {pp["key"] for pp in opts_video.get("postprocessors", [])}


def test_descricao_do_pedido_e_legivel() -> None:
    info = media("youtube_dash")
    assert "original" in describe_request(AudioRequest(codec="best"), None).lower()
    assert "320" in describe_request(AudioRequest(codec="mp3", quality="320"), None)
    pedido = VideoRequest(video=info.matrix.video[0], container="mp4")
    plano = plan_container(info.matrix, pedido.video, None, "mp4")
    assert ".mp4" in describe_request(pedido, plano)
