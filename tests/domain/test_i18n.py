"""Núcleo do idioma: catálogo, texto guardado e números nos dois idiomas."""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.application.formatting import format_bitrate, format_rate, format_size
from videomanager.domain import i18n
from videomanager.domain.project import Clip, MediaKind, MediaRef
from videomanager.domain.timing import format_span, format_timecode, parse_timecode

i18n.register({
    "TESTE_SAUDACAO": ("Olá, {nome}", "Hello, {nome}"),
    "TESTE_FIXO": ("Fila", "Queue"),
})


@pytest.fixture
def ingles():
    i18n.set_language(i18n.ENGLISH)


def test_texto_no_idioma_de_agora():
    assert i18n.t("TESTE_FIXO") == "Fila"
    i18n.set_language(i18n.ENGLISH)
    assert i18n.t("TESTE_FIXO") == "Queue"
    assert i18n.t("TESTE_SAUDACAO", nome="Ana") == "Hello, Ana"


def test_texto_guardado_acompanha_a_troca():
    guardado = i18n.Text("TESTE_SAUDACAO", nome=i18n.Text("TESTE_FIXO"))
    assert str(guardado) == "Olá, Fila"
    i18n.set_language(i18n.ENGLISH)
    assert str(guardado) == "Hello, Queue"
    assert f"[{guardado}]" == "[Hello, Queue]"


def test_texto_calculado_na_exibicao():
    guardado = i18n.Text("TESTE_SAUDACAO", nome=i18n.Text.of(format_span, 4.25))
    assert str(guardado) == "Olá, 4,25 s"
    i18n.set_language(i18n.ENGLISH)
    assert str(guardado) == "Hello, 4.25 s"
    assert str(i18n.Text.of(format_size, 1536)) == "1.5 KB"


def test_variantes_de_uma_chave():
    assert i18n.variants("TESTE_FIXO") == ("Fila", "Queue")


def test_parametro_faltando_e_chave_ausente_falham():
    with pytest.raises(KeyError):
        i18n.t("TESTE_SAUDACAO")
    with pytest.raises(KeyError):
        i18n.t("TESTE_NAO_EXISTE")


def test_catalogos_nao_disputam_a_mesma_chave():
    i18n.register({"TESTE_FIXO": ("Fila", "Queue")})  # repetir igual não é conflito
    with pytest.raises(ValueError):
        i18n.register({"TESTE_FIXO": ("Fila", "Line")})
    assert i18n.t("TESTE_FIXO") == "Fila"


def test_idioma_desconhecido_e_recusado():
    with pytest.raises(ValueError):
        i18n.set_language("fr")
    assert i18n.language() == i18n.PORTUGUESE


@pytest.mark.parametrize(("args", "pt", "en"), [
    ((2.5,), "2,5", "2.5"),
    ((2.0, 1), "2,0", "2.0"),
    ((-6.0,), "-6,0", "-6.0"),
    ((1234.5678, 2), "1234,57", "1234.57"),
])
def test_decimal(args, pt, en):
    assert i18n.decimal(*args) == pt
    i18n.set_language(i18n.ENGLISH)
    assert i18n.decimal(*args) == en


def test_decimal_com_sinal_e_sem_zero_inutil():
    assert i18n.decimal(3.0, sign=True) == "+3,0"
    assert i18n.decimal(2.0, 2, trim=True) == "2"
    assert i18n.decimal(2.50, 2, trim=True) == "2,5"
    i18n.set_language(i18n.ENGLISH)
    assert i18n.decimal(3.0, sign=True) == "+3.0"
    assert i18n.decimal(2.50, 2, trim=True) == "2.5"


def test_timecode_e_trecho_no_separador_do_idioma():
    assert format_timecode(62.5) == "0:01:02,500"
    assert format_span(4.25) == "4,25 s"
    i18n.set_language(i18n.ENGLISH)
    assert format_timecode(62.5) == "0:01:02.500"
    assert format_timecode(62.5, milliseconds=False) == "0:01:02"
    assert format_span(4.25) == "4.25 s"
    assert format_span(125.0) == "02:05.000"


@pytest.mark.parametrize("idioma", i18n.LANGUAGES)
def test_timecode_le_os_dois_separadores_nos_dois_idiomas(idioma):
    i18n.set_language(idioma)
    assert parse_timecode("1:02,5") == pytest.approx(62.5)
    assert parse_timecode("1:02.5") == pytest.approx(62.5)
    assert parse_timecode(format_timecode(3725.25)) == pytest.approx(3725.25)


def test_formatacao_de_numeros_em_ingles(ingles):
    assert format_size(1536) == "1.5 KB"
    assert format_size(2 * 1024 * 1024) == "2 MB"
    assert format_bitrate(2500) == "2.5 Mbps"
    assert format_rate(29.97) == "29.97"


def test_rotulos_do_bloco_em_ingles(ingles):
    midia = MediaRef(Path("a.mp4"), MediaKind.VIDEO, duration=10.0)
    assert Clip(midia, 0.0, 5.0, gain_db=-6.0).gain_label == "-6.0 dB"
    assert Clip(midia, 0.0, 5.0, speed=0.5).speed_label == "0.5x"


def test_trilhas_novas_nascem_no_idioma_da_tela(ingles):
    from videomanager.domain.project import TrackKind, new_project
    projeto = new_project()
    assert [trilha.name for trilha in projeto.tracks] == ["Video 1", "Audio 1"]
    assert projeto.with_track(TrackKind.ADDITIONAL).tracks[0].name == "Overlays 1"


def test_numeracao_enxerga_os_nomes_dos_dois_idiomas():
    from videomanager.domain.project import TrackKind, new_project
    projeto = new_project().with_track(TrackKind.VIDEO)  # "Vídeo 1" e "Vídeo 2"
    i18n.set_language(i18n.ENGLISH)
    nomes = [t.name for t in projeto.with_track(TrackKind.VIDEO).tracks if t.kind is TrackKind.VIDEO]
    assert sorted(nomes) == ["Video 3", "Vídeo 1", "Vídeo 2"]


def test_nome_padrao_aparece_no_idioma_da_tela_e_o_do_usuario_nao_muda():
    from videomanager.domain.project import Track, TrackKind
    padrao = Track(TrackKind.VIDEO, name="Vídeo 3")
    proprio = Track(TrackKind.VIDEO, name="Câmera 2")
    outra_especie = Track(TrackKind.VIDEO, name="Áudio 2")
    assert (padrao.title, proprio.title) == ("Vídeo 3", "Câmera 2")
    i18n.set_language(i18n.ENGLISH)
    assert (padrao.title, proprio.title, outra_especie.title) == ("Video 3", "Câmera 2", "Áudio 2")
    assert padrao.name == "Vídeo 3"
    assert Track(TrackKind.AUDIO, name="Audio 4").title == "Audio 4"
    i18n.set_language(i18n.PORTUGUESE)
    assert Track(TrackKind.ADDITIONAL, name="Overlays 2").title == "Adicionais 2"


def test_rotulos_de_som_do_bloco_em_ingles(ingles):
    midia = MediaRef(Path("a.mp4"), MediaKind.VIDEO, duration=10.0)
    assert Clip(midia, 0.0, 5.0, muted=True).gain_label == "muted"
    assert Clip(midia, 0.0, 5.0, detached=True).gain_label == "audio detached"


def test_catalogos_das_camadas_tem_os_dois_idiomas_com_os_mesmos_parametros():
    import importlib
    import string

    # Importar o pacote registra o catálogo da camada.
    for camada in ("videomanager.application", "videomanager.infrastructure"):
        importlib.import_module(camada)

    def campos(texto):
        return sorted(nome for _, nome, _, _ in string.Formatter().parse(texto) if nome is not None)

    chaves = [chave for chave in i18n._catalog if not chave.startswith("TESTE_")]
    assert len(chaves) > 150
    for chave in chaves:
        pt, en = i18n.variants(chave)
        assert pt.strip() and en.strip(), chave
        # Um parâmetro a menos no inglês levantaria KeyError só nesse idioma.
        assert campos(pt) == campos(en), chave
        # O espaço da ponta faz parte da frase montada (" (placa, se disponível)").
        assert (pt[:1] == " ", pt[-1:] == " ") == (en[:1] == " ", en[-1:] == " "), chave
