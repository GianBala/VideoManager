"""Vídeo HDR (PQ/HLG) sai em SDR com as cores certas, e o arquivo, a janela e a descrição dizem isso.

Sem conversão, o pixel da curva PQ passava por 8 bits como se fosse SDR e perdia a marca da curva: sombras levantadas, brilhos
achatados e cor desbotada, sem erro algum. A medida é a do pixel de verdade, contra uma fonte SDR que o teste reencoda em PQ:
a saída convertida tem de ficar perto da fonte original, e a sem conversão (o que o programa fazia) longe dela.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.application.media.conversion_description import describe_target
from videomanager.domain import i18n
from videomanager.domain.composition import Composition
from videomanager.domain.constants import HDR_TRANSFERS
from videomanager.domain.export_policy import has_hdr_source
from videomanager.domain.media import LocalMedia
from videomanager.domain.media import LocalStream
from videomanager.domain.media import VideoTarget
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.domain.project import media_ref
from videomanager.domain.project import new_project
from videomanager.infrastructure.ffmpeg.composer import HDR_TO_SDR_STEPS
from videomanager.infrastructure.ffmpeg.composer import build_graph
from videomanager.infrastructure.ffmpeg.converter import Converter
from videomanager.infrastructure.ffmpeg.converter import build_video_args
from videomanager.infrastructure.ffmpeg.converter import probe_file
from videomanager.infrastructure.storage.project_json import HDR_SOURCE_VERSION
from videomanager.infrastructure.storage.project_json import load_project
from videomanager.infrastructure.storage.project_json import project_to_dict
from videomanager.infrastructure.storage.project_json import save_project
from videomanager.infrastructure.system.binaries import find_tools
from videomanager.infrastructure.system.binaries import subprocess_kwargs

TOM = "tonemap=tonemap=mobius"


def _midia(hdr: bool, kind: MediaKind = MediaKind.VIDEO) -> MediaRef:
    return MediaRef(Path("/m/v.mp4"), kind, duration=3.0, width=640, height=360, fps=30.0, hdr=hdr)


def _projeto(*midias: MediaRef) -> Project:
    clips = tuple(Clip(m, 3.0 * i, 3.0) for i, m in enumerate(midias))
    return Project(tracks=(Track(TrackKind.VIDEO, clips=clips),), width=640, height=360, fps=30.0)


def _local(hdr: bool) -> LocalMedia:
    video = LocalStream(index=0, kind="video", codec="hevc", width=1920, height=1080, fps=30.0, hdr=hdr)
    return LocalMedia(Path("/m/v.mp4"), 3.0, "mov,mp4", 1000, (video,))


# ---------------------------------------------------------------------------
# Sem ffmpeg: o que o compositor, o arquivo, a janela e a descrição fazem com a marca
# ---------------------------------------------------------------------------


def test_so_o_bloco_de_video_hdr_leva_o_mapeamento_de_tons() -> None:
    for hdr, esperado in ((True, True), (False, False)):
        grafo = ";".join(build_graph(_projeto(_midia(hdr))).filters)
        assert (TOM in grafo) is esperado, (hdr, grafo)
    # Foto e áudio nunca são mapeados, mesmo com a marca.
    assert TOM not in ";".join(build_graph(_projeto(_midia(True, MediaKind.IMAGE))).filters)


def test_o_mapeamento_vem_antes_de_virar_rgba_e_a_cadeia_e_a_mesma_do_compositor() -> None:
    grafo = ";".join(build_graph(_projeto(_midia(True))).filters)
    cadeia = ",".join(HDR_TO_SDR_STEPS)
    assert cadeia in grafo
    assert grafo.index(cadeia) < grafo.index("rgba")


def test_misturar_hdr_e_sdr_converte_so_o_hdr() -> None:
    grafo = build_graph(_projeto(_midia(False), _midia(True))).filters
    cadeias = [f for f in grafo if f.startswith("[0:v]") or f.startswith("[1:v]")]
    assert TOM not in next(f for f in cadeias if f.startswith("[0:v]"))
    assert TOM in next(f for f in cadeias if f.startswith("[1:v]"))


def test_a_sonda_so_marca_as_curvas_pq_e_hlg() -> None:
    assert HDR_TRANSFERS == ("smpte2084", "arib-std-b67")


def test_projeto_com_midia_hdr_grava_a_versao_9_e_o_sem_hdr_fica_na_6(tmp_path: Path) -> None:
    com, sem = _projeto(_midia(True)), _projeto(_midia(False))
    dados = project_to_dict(com)
    assert dados["version"] == HDR_SOURCE_VERSION == 9
    assert project_to_dict(sem)["version"] == 6
    assert "hdr" not in str(project_to_dict(sem)), "o projeto sem HDR não pode ganhar chave nova"

    caminho = tmp_path / "p.vmp"
    save_project(com, caminho)
    lido, _ = load_project(caminho)
    assert lido.clips[0].media.hdr is True
    save_project(sem, tmp_path / "q.vmp")
    assert load_project(tmp_path / "q.vmp")[0].clips[0].media.hdr is False


def test_media_ref_so_leva_a_marca_do_video() -> None:
    assert media_ref(_local(True)).hdr is True
    assert media_ref(_local(False)).hdr is False
    foto = replace(_local(True), streams=(replace(_local(True).streams[0], codec="mjpeg", attached_picture=True),))
    assert media_ref(foto).hdr is False or media_ref(foto).kind is not MediaKind.VIDEO


def test_a_janela_de_exportar_avisa_do_hdr_nos_dois_idiomas() -> None:
    from videomanager.presentation.qt import strings, strings_en
    from videomanager.presentation.qt.export_dialog import _export_warning

    assert has_hdr_source(_projeto(_midia(True))) and not has_hdr_source(_projeto(_midia(False)))
    assert strings.EXPORT_HDR_NOTE in _export_warning("mp4", _projeto(_midia(True)), False)
    assert _export_warning("mp4", _projeto(_midia(False)), False) == ""
    assert strings_en.EXPORT_HDR_NOTE and strings_en.EXPORT_HDR_NOTE != strings.EXPORT_HDR_NOTE


def test_a_descricao_da_conversao_diz_que_o_hdr_vira_sdr_so_quando_recodifica() -> None:
    antes = i18n.language()
    try:
        for idioma, frase in ((i18n.PORTUGUESE, "HDR convertido para SDR"), (i18n.ENGLISH, "HDR converted to SDR")):
            i18n.set_language(idioma)
            assert frase in describe_target(_local(True), VideoTarget(container="mp4", video_codec="h264"))
            assert "HDR" not in describe_target(_local(False), VideoTarget(container="mp4", video_codec="h264"))
            assert "HDR" not in describe_target(_local(True), VideoTarget(container="mp4", video_codec="copy"))
    finally:
        i18n.set_language(antes)


# ---------------------------------------------------------------------------
# Com ffmpeg: a imagem que sai
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tools():
    found = find_tools()
    if found is None:
        pytest.skip("FFmpeg não disponível")
    return found


def _ffmpeg(tools, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "error", "-y", *args],
                          text=True, timeout=120, **subprocess_kwargs())


def _medidas(tools, arquivo: Path) -> dict[str, float]:
    """Sombras, brilhos e saturação do quadro 10, numa escala de 8 bits (``signalstats``)."""
    saida = subprocess.run(
        [tools.ffmpeg_str, "-nostdin", "-hide_banner", "-v", "info", "-i", str(arquivo), "-vf",
         "select=eq(n\\,10),scale=640:360,format=yuv420p10le,signalstats,metadata=print", "-frames:v", "1", "-f", "null", "-"],
        text=True, timeout=120, **subprocess_kwargs()).stderr
    medidas = {nome: float(valor) / 4 for nome, valor in re.findall(r"signalstats\.(YLOW|YHIGH|SATAVG)=([\d.]+)", saida)}
    assert len(medidas) == 3, saida[-400:]
    return medidas


@pytest.fixture(scope="module")
def fontes(tools, tmp_path_factory) -> tuple[Path, Path]:
    """A mesma imagem em SDR e em PQ/BT.2020 de 10 bits, com as marcas de cor que um celular grava."""
    pasta = tmp_path_factory.mktemp("hdr")
    sdr, hdr = pasta / "sdr.mp4", pasta / "hdr.mp4"
    base = "testsrc2=s=640x360:r=30:d=1"
    assert _ffmpeg(tools, "-f", "lavfi", "-i", base, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(sdr)).returncode == 0
    gerado = _ffmpeg(
        tools, "-f", "lavfi", "-i", base, "-vf",
        "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv,"
        "zscale=t=smpte2084:p=bt2020:m=bt2020nc:npl=203,format=yuv420p10le",
        "-c:v", "libx265", "-preset", "ultrafast", "-x265-params",
        "log-level=none:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:range=limited", str(hdr))
    if gerado.returncode != 0:
        pytest.skip(f"este ffmpeg não gera a fonte HDR de teste: {gerado.stderr[-200:]}")
    return sdr, hdr


def _exporta(tools, origem: Path, destino: Path) -> None:
    local = probe_file(origem, tools)
    Converter(local, Composition(new_project(media_ref(local)), "mp4"), destino, tools).run()


@pytest.mark.ffmpeg
def test_a_sonda_marca_a_midia_hdr_e_a_sdr_nao(tools, fontes) -> None:
    sdr, hdr = fontes
    assert probe_file(hdr, tools).video.hdr is True
    assert probe_file(sdr, tools).video.hdr is False
    assert media_ref(probe_file(hdr, tools)).hdr is True
    assert media_ref(probe_file(sdr, tools)).hdr is False


@pytest.mark.ffmpeg
def test_a_exportacao_de_um_hdr_fica_perto_do_sdr_original_e_nao_lavada(tools, fontes, tmp_path: Path) -> None:
    sdr, hdr = fontes
    saida = tmp_path / "convertido.mp4"
    _exporta(tools, hdr, saida)
    original, convertido, lavado = _medidas(tools, sdr), _medidas(tools, saida), _medidas(tools, hdr)
    # O que o programa fazia: os pixels da curva PQ lidos como SDR, com a cor desbotada e os brilhos achatados.
    assert lavado["SATAVG"] < original["SATAVG"] * 0.4 and lavado["YHIGH"] < original["YHIGH"] - 40, (lavado, original)
    assert convertido["SATAVG"] > original["SATAVG"] * 0.75, (convertido, original)
    assert abs(convertido["YHIGH"] - original["YHIGH"]) < 30 and abs(convertido["YLOW"] - original["YLOW"]) < 15, (
        convertido, original)


@pytest.mark.ffmpeg
def test_a_saida_vem_em_8_bits_sem_declarar_hdr_nem_bt2020(tools, fontes, tmp_path: Path) -> None:
    """A marca ``bt709`` depende do ffmpeg (sai no 7.1 e no 9.0, e no 6.1 a saída fica sem marca, como toda exportação de SDR);
    o que vale em todos é que o arquivo não afirme ser o que não é."""
    _, hdr = fontes
    saida = tmp_path / "saida.mp4"
    _exporta(tools, hdr, saida)
    info = subprocess.run(
        [tools.ffprobe_str, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=pix_fmt,color_space,color_transfer,color_primaries", "-of", "json", str(saida)],
        text=True, **subprocess_kwargs()).stdout
    fluxo = json.loads(info)["streams"][0]
    assert fluxo["pix_fmt"] == "yuv420p", fluxo
    assert fluxo.get("color_transfer") not in HDR_TRANSFERS, fluxo
    assert not str(fluxo.get("color_space", "")).startswith("bt2020"), fluxo
    assert not str(fluxo.get("color_primaries", "")).startswith("bt2020"), fluxo


@pytest.mark.ffmpeg
def test_a_conversao_da_aba_converter_tambem_mapeia_os_tons_ao_recodificar(tools, fontes, tmp_path: Path) -> None:
    _, hdr = fontes
    local = probe_file(hdr, tools)
    recodifica = build_video_args(local, VideoTarget(container="mp4", video_codec="h264"), tmp_path / "x.mp4", tools)
    assert TOM in recodifica[recodifica.index("-vf") + 1]
    copia = build_video_args(local, VideoTarget(container="mp4", video_codec="copy"), tmp_path / "y.mp4", tools)
    assert "-vf" not in copia

    saida = tmp_path / "x.mp4"
    Converter(local, VideoTarget(container="mp4", video_codec="h264"), saida, tools).run()
    sdr, _ = fontes
    assert _medidas(tools, saida)["SATAVG"] > _medidas(tools, sdr)["SATAVG"] * 0.75
