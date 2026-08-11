"""Testes da normalização de formatos.

Dois grupos. Os **invariantes** rodam contra toda fixture real e afirmam
propriedades que precisam valer para qualquer extrator, conhecido ou não. Os
**casos dirigidos** fixam comportamentos específicos, cada um amarrado ao motivo
pelo qual aquela fixture entrou no repositório.
"""

from __future__ import annotations

import pytest
from conftest import FIXTURE_NAMES, fixture_formats

from videomanager.core.format_matrix import (
    audio_family,
    available_families,
    available_fps,
    available_heights,
    build_matrix,
    classify,
    extract_fps,
    extract_height,
    find_video,
    normalize_codec,
    pick_audio,
    pick_video,
    video_family,
)
from videomanager.core.models import Kind

# ---------------------------------------------------------------------------
# Invariantes: valem para qualquer extrator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_matrix_nunca_fica_vazia(name: str) -> None:
    """Toda fixture representa uma mídia baixável, logo deve gerar opções.

    Este é o teste que pegou o bug de classificação: o archive.org não declara
    codec nenhum e o HLS da Apple omite ``acodec``, e ambos resultavam em zero
    opções — ou seja, sites inteiros inacessíveis.
    """
    matrix = build_matrix(fixture_formats(name))
    assert not matrix.is_empty, f"{name} não produziu nenhuma opção"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_nenhum_formato_non_media_vaza(name: str) -> None:
    """Storyboards e afins nunca podem chegar à interface."""
    matrix = build_matrix(fixture_formats(name))
    for choice in matrix.video:
        for fmt in choice.formats:
            assert fmt.kind is not Kind.NON_MEDIA
    for choice in matrix.audio:
        for fmt in choice.formats:
            assert fmt.kind is not Kind.NON_MEDIA


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_toda_escolha_tem_formato_e_rotulo(name: str) -> None:
    """``best`` sempre existe e todo rótulo é exibível."""
    matrix = build_matrix(fixture_formats(name))
    for choice in (*matrix.video, *matrix.audio):
        assert choice.formats, "escolha sem nenhum formato torna best inválido"
        assert choice.best.format_id
        assert choice.label.strip(), "rótulo vazio deixaria o combo em branco"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_video_ordenado_da_melhor_para_a_pior(name: str) -> None:
    """Alturas conhecidas em ordem decrescente, desconhecidas ao final."""
    matrix = build_matrix(fixture_formats(name))
    heights = [c.height for c in matrix.video]
    known = [h for h in heights if h is not None]
    assert known == sorted(known, reverse=True)
    # Nenhuma altura conhecida aparece depois de uma desconhecida.
    if None in heights:
        primeiro_none = heights.index(None)
        assert all(h is None for h in heights[primeiro_none:])


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_formatos_com_drm_nunca_sao_oferecidos(name: str) -> None:
    """Um formato com DRM falha no meio do download; não deve ser selecionável."""
    raw = fixture_formats(name)
    for fmt in raw:
        fmt["has_drm"] = True
    matrix = build_matrix(raw)
    assert not matrix.video and not matrix.audio
    assert matrix.drm_blocked, "os formatos bloqueados devem ser reportados"


# ---------------------------------------------------------------------------
# Robustez a dados malformados
# ---------------------------------------------------------------------------


def test_nao_levanta_com_campos_nulos_ou_do_tipo_errado() -> None:
    """Um extrator quebrado não pode derrubar a aplicação.

    Nada aqui é hipotético: valores ``None`` onde se espera número e strings
    onde se espera int aparecem de verdade em extratores menos cuidados.
    """
    lixo = [
        {},  # sem format_id: inútil, deve ser descartado
        {"format_id": "a", "height": None, "fps": None, "tbr": None, "vcodec": None, "acodec": None},
        {"format_id": "b", "height": "1080", "fps": "60", "tbr": "4400", "vcodec": "avc1", "acodec": "mp4a"},
        {"format_id": "c", "height": -5, "fps": 0, "filesize": 0, "vcodec": "vp9", "acodec": "none"},
        {"format_id": "d", "height": {"nao": "numero"}, "fps": ["lista"], "vcodec": "av01", "acodec": "opus"},
        {"format_id": "e", "ext": None, "resolution": None, "format_note": None, "vcodec": "avc1", "acodec": "none"},
        "isto nem é um dicionário",
        None,
    ]
    matrix = build_matrix(lixo)  # não deve levantar
    for choice in (*matrix.video, *matrix.audio):
        assert choice.label.strip()


def test_entrada_nao_lista_devolve_matriz_vazia() -> None:
    for entrada in (None, {}, "texto", 42):
        assert build_matrix(entrada).is_empty


def test_bitrate_string_convertido() -> None:
    """Números vindos como string são aceitos, não descartados."""
    matrix = build_matrix(
        [{"format_id": "x", "vcodec": "avc1", "acodec": "none", "height": "720", "tbr": "1500.5"}]
    )
    assert matrix.video[0].height == 720
    assert matrix.video[0].best.tbr == pytest.approx(1500.5)


# ---------------------------------------------------------------------------
# Cadeias de fallback dos metadados
# ---------------------------------------------------------------------------


class TestExtractHeight:
    def test_campo_direto(self) -> None:
        assert extract_height({"height": 1080}) == (1080, False)

    def test_do_campo_resolution(self) -> None:
        assert extract_height({"resolution": "1920x1080"}) == (1080, False)

    def test_do_resolution_com_x_unicode(self) -> None:
        assert extract_height({"resolution": "1920×1080"}) == (1080, False)

    def test_do_texto_descritivo(self) -> None:
        assert extract_height({"format_note": "1080p"}) == (1080, False)

    def test_do_texto_com_fps_junto(self) -> None:
        """O caso que exige não usar \\b depois do "p": "1080p60"."""
        assert extract_height({"format_note": "1080p60 HDR"}) == (1080, False)

    def test_estimada_pela_largura(self) -> None:
        altura, estimada = extract_height({"width": 1920})
        assert altura == 1080
        assert estimada is True, "a estimativa precisa ser marcada como tal"

    def test_desconhecida_devolve_none(self) -> None:
        assert extract_height({"format_note": "melhor qualidade"}) == (None, False)

    def test_ignora_valores_absurdos(self) -> None:
        """"99999p" no texto não é resolução."""
        assert extract_height({"format_note": "99999p"}) == (None, False)


class TestExtractFps:
    def test_campo_direto(self) -> None:
        assert extract_fps({"fps": 59.94}) == pytest.approx(59.94)

    def test_do_texto_fps(self) -> None:
        assert extract_fps({"format_note": "1080p 60fps"}) == 60.0

    def test_do_padrao_resolucao_fps(self) -> None:
        assert extract_fps({"format_note": "2160p60"}) == 60.0

    def test_ausente_devolve_none(self) -> None:
        assert extract_fps({"format_note": "alta qualidade"}) is None

    def test_ignora_fps_absurdo(self) -> None:
        assert extract_fps({"format_note": "9999fps"}) is None


class TestCodecs:
    @pytest.mark.parametrize(
        ("codec", "esperado"),
        [
            ("avc1.640028", "H.264"),
            ("avc3.42E01E", "H.264"),
            ("h264", "H.264"),
            ("vp09.00.50.08", "VP9"),
            ("vp9", "VP9"),
            ("vp08", "VP8"),
            ("av01.0.08M.08", "AV1"),
            ("hev1.1.6.L120", "HEVC"),
            ("hvc1", "HEVC"),
        ],
    )
    def test_familias_de_video(self, codec: str, esperado: str) -> None:
        assert video_family(codec) == esperado

    @pytest.mark.parametrize(
        ("codec", "esperado"),
        [("mp4a.40.2", "AAC"), ("opus", "Opus"), ("vorbis", "Vorbis"), ("ec-3", "E-AC-3"), ("flac", "FLAC")],
    )
    def test_familias_de_audio(self, codec: str, esperado: str) -> None:
        assert audio_family(codec) == esperado

    def test_none_e_vazio_normalizam_para_none(self) -> None:
        for valor in (None, "", "none", "NONE", "unknown", "?"):
            assert normalize_codec(valor) is None

    def test_codec_desconhecido_ainda_e_exibivel(self) -> None:
        """Melhor mostrar o codec cru que esconder a informação."""
        assert video_family("algumcodecnovo.123") == "ALGUMCODECNOVO"


# ---------------------------------------------------------------------------
# Classificação: "não tem" versus "não informado"
# ---------------------------------------------------------------------------


class TestClassify:
    def test_storyboard_mhtml_nao_e_midia(self) -> None:
        raw = {"ext": "mhtml", "vcodec": "none", "acodec": "none", "format_note": "storyboard"}
        assert classify(raw, None, None) is Kind.NON_MEDIA

    def test_storyboard_por_protocolo(self) -> None:
        assert classify({"protocol": "mhtml"}, None, None) is Kind.NON_MEDIA

    def test_codecs_declarados_sao_respeitados(self) -> None:
        assert classify({"vcodec": "avc1", "acodec": "none"}, "avc1", None) is Kind.VIDEO_ONLY
        assert classify({"vcodec": "none", "acodec": "opus"}, None, "opus") is Kind.AUDIO_ONLY
        assert classify({"vcodec": "avc1", "acodec": "mp4a"}, "avc1", "mp4a") is Kind.MUXED

    def test_nenhum_codec_declarado_mas_tem_dimensoes(self) -> None:
        """O caso do archive.org: arquivo completo servido direto.

        Antes da correção isto era classificado como não-mídia e o site inteiro
        ficava inacessível.
        """
        raw = {"ext": "mp4", "height": 720, "width": 1280, "resolution": "1280x720"}
        assert classify(raw, None, None) is Kind.MUXED

    def test_acodec_ausente_com_marca_audio_only(self) -> None:
        """O caso do HLS da Apple e das faixas 233/234 do YouTube.

        ``vcodec`` é declarado como "none" mas ``acodec`` nem aparece. Descartar
        estas faixas produz download de vídeo **mudo**.
        """
        raw = {"ext": "mp4", "vcodec": "none", "resolution": "audio only", "format_note": "English"}
        assert classify(raw, None, None) is Kind.AUDIO_ONLY

    def test_extensao_de_audio_sem_codec_declarado(self) -> None:
        assert classify({"ext": "mp3"}, None, None) is Kind.AUDIO_ONLY

    def test_marca_video_only_impede_supor_audio(self) -> None:
        raw = {"ext": "mp4", "vcodec": "avc1", "height": 720, "format_note": "video only"}
        assert classify(raw, "avc1", None) is Kind.VIDEO_ONLY

    def test_sem_nenhuma_evidencia_nao_e_midia(self) -> None:
        assert classify({"ext": "bin"}, None, None) is Kind.NON_MEDIA


# ---------------------------------------------------------------------------
# Agrupamento
# ---------------------------------------------------------------------------


def test_fps_proximos_sao_agrupados() -> None:
    """29,97 e 30 são o mesmo pedido do ponto de vista do usuário."""
    matrix = build_matrix(
        [
            {"format_id": "a", "vcodec": "avc1", "acodec": "none", "height": 1080, "fps": 29.97, "tbr": 3000},
            {"format_id": "b", "vcodec": "avc1", "acodec": "none", "height": 1080, "fps": 30.0, "tbr": 3100},
        ]
    )
    assert len(matrix.video) == 1
    assert matrix.video[0].fps == 30


def test_codecs_diferentes_na_mesma_resolucao_ficam_separados() -> None:
    matrix = build_matrix(
        [
            {"format_id": "a", "vcodec": "avc1", "acodec": "none", "height": 1080, "fps": 30, "tbr": 4000},
            {"format_id": "b", "vcodec": "vp09", "acodec": "none", "height": 1080, "fps": 30, "tbr": 3000},
            {"format_id": "c", "vcodec": "av01", "acodec": "none", "height": 1080, "fps": 30, "tbr": 2500},
        ]
    )
    assert [c.family for c in matrix.video] == ["H.264", "AV1", "VP9"], (
        "H.264 primeiro por compatibilidade; os mais eficientes em seguida"
    )


def test_hdr_separado_do_sdr() -> None:
    matrix = build_matrix(
        [
            {"format_id": "a", "vcodec": "vp09", "acodec": "none", "height": 2160, "fps": 60, "dynamic_range": "SDR"},
            {"format_id": "b", "vcodec": "vp09", "acodec": "none", "height": 2160, "fps": 60, "dynamic_range": "HDR10"},
        ]
    )
    assert len(matrix.video) == 2
    faixas = {c.dynamic_range for c in matrix.video}
    assert faixas == {None, "HDR10"}, "SDR é o padrão e não deve poluir o rótulo"


def test_stream_separado_preferido_ao_mesclado_na_mesma_resolucao() -> None:
    """O mesclado costuma trazer áudio pior e fixo."""
    matrix = build_matrix(
        [
            {"format_id": "muxed", "vcodec": "avc1", "acodec": "mp4a", "height": 720, "fps": 30, "tbr": 1000},
            {"format_id": "solo", "vcodec": "avc1", "acodec": "none", "height": 720, "fps": 30, "tbr": 1500},
        ]
    )
    assert len(matrix.video) == 1, "não deve duplicar a linha 720p"
    assert matrix.video[0].best.format_id == "solo"
    assert matrix.video[0].is_muxed is False


def test_audio_de_fonte_mesclada_prefere_o_menor_arquivo() -> None:
    """Baixar 332 MB para extrair o mesmo áudio de um arquivo de 45 MB é desperdício.

    Reproduz o archive.org: três derivados mesclados, nenhum com bitrate de
    áudio informado.
    """
    matrix = build_matrix(
        [
            {"format_id": "grande", "ext": "avi", "height": 720, "filesize": 332_000_000},
            {"format_id": "medio", "ext": "mp4", "height": 360, "filesize": 61_000_000},
            {"format_id": "pequeno", "ext": "ogv", "height": 300, "filesize": 46_000_000},
        ]
    )
    assert matrix.audio[0].best.format_id == "pequeno"
    assert matrix.audio[0].is_extracted_from_video is True
    assert "extraído do vídeo" in matrix.audio[0].label


def test_audio_com_bitrate_conhecido_prefere_o_maior() -> None:
    matrix = build_matrix(
        [
            {"format_id": "baixo", "vcodec": "none", "acodec": "opus", "abr": 64, "filesize": 1000},
            {"format_id": "alto", "vcodec": "none", "acodec": "opus", "abr": 160, "filesize": 5000},
        ]
    )
    assert matrix.audio[0].best.format_id == "alto"


def test_needs_muxing_falso_quando_so_ha_mesclados() -> None:
    """Sem trilhas separadas, um seletor de áudio só confundiria."""
    matrix = build_matrix(
        [{"format_id": "a", "vcodec": "avc1", "acodec": "mp4a", "height": 720, "fps": 30}]
    )
    assert matrix.needs_muxing is False


# ---------------------------------------------------------------------------
# Consultas usadas pela interface
# ---------------------------------------------------------------------------


def test_pick_video_respeita_limites() -> None:
    matrix = build_matrix(fixture_formats("youtube_dash"))
    escolha = pick_video(matrix, max_height=720)
    assert escolha is not None
    assert escolha.height is not None and escolha.height <= 720


def test_pick_video_nao_descarta_altura_desconhecida() -> None:
    """Não se pode afirmar que um formato sem altura viola o limite.

    Descartá-los deixaria sem nenhuma opção justamente os sites que não
    informam resolução.
    """
    matrix = build_matrix(
        [{"format_id": "hls", "vcodec": "avc1", "acodec": "mp4a", "tbr": 2500}]
    )
    assert pick_video(matrix, max_height=720) is not None


def test_pick_video_cai_para_a_melhor_quando_nada_cabe() -> None:
    """Um vídeo só em 4K é melhor que um erro de "resolução indisponível"."""
    matrix = build_matrix(
        [{"format_id": "4k", "vcodec": "avc1", "acodec": "none", "height": 2160, "fps": 30}]
    )
    escolha = pick_video(matrix, max_height=480)
    assert escolha is not None and escolha.height == 2160


def test_pick_audio_por_idioma() -> None:
    matrix = build_matrix(
        [
            {"format_id": "en", "vcodec": "none", "acodec": "mp4a", "abr": 128, "language": "en"},
            {"format_id": "pt", "vcodec": "none", "acodec": "mp4a", "abr": 128, "language": "pt"},
        ]
    )
    escolha = pick_audio(matrix, language="pt")
    assert escolha is not None and escolha.best.format_id == "pt"


def test_find_video_sem_altura_respeita_o_codec_pedido() -> None:
    """Regressão: "Melhor disponível" + H.264 baixava o AV1 de 2160p.

    Nesta fixture — como em quase todo o YouTube — não existe H.264 acima de
    1080p. Pedir "a melhor" com um codec escolhido é pedir a melhor **daquele
    codec**, e não a melhor de todas.
    """
    matrix = build_matrix(fixture_formats("youtube_dash"))
    escolha = find_video(matrix, height=None, family="H.264")
    assert escolha is not None
    assert escolha.family == "H.264"
    assert escolha.height == 1080


def test_find_video_afrouxa_quando_o_codec_nao_existe_na_resolucao() -> None:
    """Em 2160p só há AV1 e VP9: a resolução pedida prevalece sobre o codec.

    Devolver ``None`` deixaria o usuário sem download nenhum. Quem avisa que o
    codec mudou é a interface, antes de enfileirar.
    """
    matrix = build_matrix(fixture_formats("youtube_dash"))
    escolha = find_video(matrix, height=2160, family="H.264")
    assert escolha is not None
    assert escolha.height == 2160
    assert escolha.family != "H.264"


def test_listas_para_os_combos_da_interface() -> None:
    matrix = build_matrix(fixture_formats("youtube_dash"))
    alturas = available_heights(matrix)
    assert alturas == tuple(sorted(alturas, reverse=True))
    assert 1080 in alturas
    assert available_fps(matrix, height=1080)
    assert "H.264" in available_families(matrix, height=1080)


# ---------------------------------------------------------------------------
# Casos dirigidos, um por fixture
# ---------------------------------------------------------------------------


def test_youtube_descarta_storyboards_e_acha_60fps() -> None:
    matrix = build_matrix(fixture_formats("youtube_dash"))
    assert matrix.discarded >= 4, "os storyboards mhtml precisam ser descartados"
    assert any(c.fps == 60 for c in matrix.video)
    assert {"H.264", "VP9", "AV1"} <= {c.family for c in matrix.video}
    assert matrix.needs_muxing is True


def test_youtube_inclui_faixas_de_audio_sem_acodec_declarado() -> None:
    """Regressão: as faixas HLS 233/234 eram descartadas em silêncio."""
    ids = {f.format_id for c in build_matrix(fixture_formats("youtube_dash")).audio for f in c.formats}
    assert {"233", "234"} <= ids


def test_archive_org_sem_codec_declarado_e_sem_fps() -> None:
    matrix = build_matrix(fixture_formats("archive_muxed"))
    assert len(matrix.video) == 3
    assert all(c.is_muxed for c in matrix.video)
    assert all(c.fps is None for c in matrix.video), "nenhum formato informa fps"
    assert matrix.needs_muxing is False


def test_hls_da_apple_tem_audio_e_video() -> None:
    matrix = build_matrix(fixture_formats("hls_no_metadata"))
    assert matrix.video, "as variantes de vídeo devem estar disponíveis"
    assert matrix.audio, "sem isto o download sairia mudo"
    assert all(c.best.filesize is None for c in matrix.video), "HLS não informa tamanho"


def test_soundcloud_e_so_audio() -> None:
    matrix = build_matrix(fixture_formats("soundcloud_audio"))
    assert not matrix.video
    assert matrix.audio
    assert matrix.best_audio_bitrate == pytest.approx(128, abs=1)
    assert matrix.audio[0].best.filesize_is_estimated is True, "veio como filesize_approx"
