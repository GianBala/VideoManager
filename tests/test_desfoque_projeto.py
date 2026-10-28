"""O desfoque de região no arquivo .vmp: ida e volta, projeto da versão anterior e nenhum campo novo.

A região é a pose do bloco (``x``, ``y``, ``scale_x``, ``scale_y`` e os quadros-chave), que o arquivo já grava;
o desfoque só acrescenta um **valor** (``filter_name = "desfoque"``). Sem versão nova, uma versão antiga abriria o
bloco como Preto e Branco no quadro **inteiro**, sem desfocar nada. Por isso o projeto que tem desfoque grava a
versão 7 (a anterior recusa o arquivo com mensagem) e o que não tem continua na 6, igual ao de antes.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from videomanager.domain.constants import REGION_BLUR
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import OverlayType
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.domain.project import filter_pose
from videomanager.domain.project import pseudo_media
from videomanager.infrastructure.storage import project_json
from videomanager.infrastructure.storage.project_json import PROJECT_VERSION
from videomanager.infrastructure.storage.project_json import MOVABLE_FILTER_VERSION
from videomanager.infrastructure.storage.project_json import REGION_BLUR_VERSION
from videomanager.infrastructure.storage.project_json import SUPPORTED_VERSION
from videomanager.infrastructure.storage.project_json import load_project
from videomanager.infrastructure.storage.project_json import ProjectError
from videomanager.infrastructure.storage.project_json import project_from_dict
from videomanager.infrastructure.storage.project_json import project_to_dict
from videomanager.infrastructure.storage.project_json import save_project


def _projeto(tmp_path: Path, nome: str = REGION_BLUR, **extra) -> tuple[Project, Clip]:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"x")
    base = Clip(MediaRef(video, MediaKind.VIDEO, duration=10.0, width=1280, height=720, fps=30.0), 0.0, 10.0)
    pose = {} if "scale_x" in extra else filter_pose(nome)
    filtro = Clip(pseudo_media(OverlayType.FILTER, nome, 4.0), 1.0, 4.0, overlay_type="filter", filter_name=nome,
                  **pose, **extra)
    return Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(filtro,), name="Adicionais 1"),
                           Track(TrackKind.VIDEO, clips=(base,), name="Vídeo 1")), width=1280, height=720, fps=30.0), filtro


def test_ida_e_volta_guarda_a_regiao_com_os_quadros_chave(tmp_path: Path) -> None:
    projeto, filtro = _projeto(tmp_path, x=0.3, y=0.6, scale_x=0.25, scale_y=0.4, scale=0.325, keyframes=(
        Keyframe(0.0, x=0.3, y=0.6, scale_x=0.25, scale_y=0.4),
        Keyframe(3.0, x=0.7, y=0.4, scale_x=0.25, scale_y=0.4, easing="ease_in_out")))
    caminho = tmp_path / "desfoque.vmp"
    save_project(projeto, caminho)
    carregado, faltando = load_project(caminho)
    assert not faltando
    volta = carregado.additional_tracks[0].clips[0]
    assert volta.has_region and volta.filter_name == REGION_BLUR
    assert (volta.x, volta.y, volta.scale_x, volta.scale_y) == (0.3, 0.6, 0.25, 0.4)
    assert volta.keyframes == filtro.keyframes
    assert volta.region_rect(1280, 720, 1.5) == filtro.region_rect(1280, 720, 1.5)


def test_salvar_sem_editar_grava_o_mesmo_arquivo(tmp_path: Path) -> None:
    projeto, _ = _projeto(tmp_path, x=0.3, y=0.6, scale_x=0.25, scale_y=0.4, scale=0.325)
    primeiro, segundo = tmp_path / "um.vmp", tmp_path / "dois.vmp"
    save_project(projeto, primeiro)
    carregado, _ = load_project(primeiro)
    save_project(carregado, segundo)
    assert primeiro.read_bytes() == segundo.read_bytes()
    assert carregado == projeto


def test_o_desfoque_nao_acrescenta_campo_ao_arquivo(tmp_path: Path) -> None:
    desfoque, _ = _projeto(tmp_path)
    sepia, _ = _projeto(tmp_path, "sepia")
    chaves = lambda p: set(project_to_dict(p, base_dir=tmp_path)["tracks"][0]["clips"][0])  # noqa: E731
    assert chaves(desfoque) == chaves(sepia)


def test_o_projeto_com_desfoque_grava_a_versao_7_e_o_sem_desfoque_continua_na_6(tmp_path: Path) -> None:
    desfoque, _ = _projeto(tmp_path)
    sepia, _ = _projeto(tmp_path, "sepia")
    assert project_to_dict(desfoque, base_dir=tmp_path)["version"] == REGION_BLUR_VERSION == 7
    assert project_to_dict(sepia, base_dir=tmp_path)["version"] == PROJECT_VERSION == 6


def test_o_desfoque_na_versao_7_relê_igual(tmp_path: Path) -> None:
    projeto, _ = _projeto(tmp_path, x=0.3, y=0.6, scale_x=0.25, scale_y=0.4, scale=0.325)
    caminho = tmp_path / "desfoque.vmp"
    save_project(projeto, caminho)
    assert json.loads(caminho.read_text(encoding="utf-8"))["version"] == 7
    carregado, _ = load_project(caminho)
    assert carregado == projeto


def test_a_versao_anterior_recusa_o_projeto_com_desfoque_e_abre_os_outros(tmp_path: Path, monkeypatch) -> None:
    """Uma versão anterior lê até a 6: o arquivo com desfoque é recusado com mensagem, em vez de virar um
    quadro todo em Preto e Branco sem desfocar nada; o que não tem desfoque abre como sempre."""
    desfoque, _ = _projeto(tmp_path)
    sepia, _ = _projeto(tmp_path, "sepia")
    com, sem = (project_to_dict(p, base_dir=tmp_path) for p in (desfoque, sepia))
    assert SUPPORTED_VERSION == MOVABLE_FILTER_VERSION == 8
    monkeypatch.setattr(project_json, "SUPPORTED_VERSION", PROJECT_VERSION)
    with pytest.raises(ProjectError):
        project_from_dict(com, base_dir=tmp_path)
    lido, _ = project_from_dict(sem, base_dir=tmp_path)
    assert lido.additional_tracks[0].clips[0].filter_name == "sepia"


def test_gravar_a_versao_7_sobre_a_6_guarda_a_copia_e_sem_desfoque_volta_a_6(tmp_path: Path) -> None:
    """O mecanismo de ``.vN.bak`` vale para a versão que vai ser gravada, não para a mais alta que o programa lê."""
    sepia, _ = _projeto(tmp_path, "sepia")
    desfoque, _ = _projeto(tmp_path)
    caminho = tmp_path / "p.vmp"
    save_project(sepia, caminho)
    original = caminho.read_bytes()
    save_project(desfoque, caminho)                                   # 6 -> 7: o original é preservado
    assert json.loads(caminho.read_text(encoding="utf-8"))["version"] == 7
    assert (tmp_path / "p.vmp.v6.bak").read_bytes() == original
    save_project(sepia, caminho)                                      # 7 -> 6 (tirou o desfoque): nada a guardar
    assert json.loads(caminho.read_text(encoding="utf-8"))["version"] == 6
    assert sorted(f.name for f in tmp_path.glob("p.vmp*")) == ["p.vmp", "p.vmp.v6.bak"]


def test_um_projeto_salvo_pela_versao_anterior_abre_com_o_filtro_em_tela_cheia(tmp_path: Path) -> None:
    """Um filtro antigo traz a pose padrão e nenhum desfoque: abre como era, sem região e sem mexer no desenho."""
    projeto, filtro = _projeto(tmp_path, "sepia")
    dados = project_to_dict(projeto, base_dir=tmp_path)
    assert (dados["tracks"][0]["clips"][0]["x"], dados["tracks"][0]["clips"][0]["scale_x"]) == (0.5, 1.0)
    volta, _ = project_from_dict(dados, base_dir=tmp_path)
    antigo = volta.additional_tracks[0].clips[0]
    assert not antigo.has_region and antigo.region_rect(1280, 720) == (0, 0, 1280, 720)


@pytest.mark.parametrize("nome", ["pb", "sepia", "contraste", "vinheta", "inverter"])
def test_os_filtros_antigos_nascem_com_a_pose_que_o_arquivo_sempre_gravou(tmp_path: Path, nome: str) -> None:
    _, filtro = _projeto(tmp_path, nome)
    assert (filtro.x, filtro.y, filtro.scale_x, filtro.scale_y, filtro.keyframes) == (0.5, 0.5, 1.0, 1.0, ())


def test_abrir_um_projeto_com_desfoque_no_editor_nao_o_marca_como_alterado(tmp_path: Path, painel_de_edicao) -> None:
    projeto, filtro = _projeto(tmp_path, x=0.3, y=0.6, scale_x=0.25, scale_y=0.4, scale=0.325, keyframes=(
        Keyframe(0.0, x=0.3, y=0.6, scale_x=0.25, scale_y=0.4), Keyframe(3.0, x=0.7, y=0.4, scale_x=0.25, scale_y=0.4)))
    caminho = tmp_path / "desfoque.vmp"
    save_project(projeto, caminho)
    carregado, _ = load_project(caminho)
    painel = painel_de_edicao
    painel.install_project(carregado, caminho, [], {})
    painel._timeline.select(filtro.clip_id)
    assert not painel._session.has_changes
    assert painel._project == carregado
    # E o que o painel guarda depois de ser aberto é o mesmo desfoque, no mesmo lugar.
    volta = next(c for t in painel._project.additional_tracks for c in t.clips)
    assert volta.region_rect(1280, 720, 1.5) == filtro.region_rect(1280, 720, 1.5)


def test_a_7_e_a_8_tem_dono_e_a_leitura_vai_ate_a_maior_das_versoes() -> None:
    """A 7 é do desfoque e a 8 do filtro móvel: uma chave nova que todo arquivo grava é a 9. Tomar a 7 ou a 8 faria um
    programa que só conhece uma delas perder a chave ao salvar."""
    assert PROJECT_VERSION not in (REGION_BLUR_VERSION, MOVABLE_FILTER_VERSION), \
        "a 7 é do desfoque e a 8 do filtro móvel: uma chave nova sobe PROJECT_VERSION para 9"
    assert SUPPORTED_VERSION == max(PROJECT_VERSION, REGION_BLUR_VERSION, MOVABLE_FILTER_VERSION)


def test_com_uma_chave_nova_na_versao_9_todo_projeto_grava_9_inclusive_o_com_desfoque_e_o_movel(
        tmp_path: Path, monkeypatch) -> None:
    """Os projetos com desfoque e com filtro móvel gravam a maior das versões: gravar 7 ou 8 deixaria a chave da 9 sem
    quem a entenda."""
    monkeypatch.setattr(project_json, "PROJECT_VERSION", 9)
    desfoque, _ = _projeto(tmp_path)
    sepia, _ = _projeto(tmp_path, "sepia")
    movel, _ = _projeto(tmp_path, "sepia", movable=True)
    for projeto in (desfoque, sepia, movel):
        assert project_to_dict(projeto, base_dir=tmp_path)["version"] == 9


# -- o filtro móvel no arquivo -------------------------------------------------------------------

def _movel(tmp_path: Path, nome: str = "sepia", **extra) -> tuple[Project, Clip]:
    return _projeto(tmp_path, nome, movable=True, x=0.3, y=0.6, scale_x=0.25, scale_y=0.4, scale=0.325, **extra)


def test_o_filtro_movel_grava_a_chave_e_a_versao_8_e_o_comum_nao_grava_nenhuma_das_duas(tmp_path: Path) -> None:
    movel, _ = _movel(tmp_path)
    comum, _ = _projeto(tmp_path, "sepia")
    com = project_to_dict(movel, base_dir=tmp_path)
    sem = project_to_dict(comum, base_dir=tmp_path)
    assert com["version"] == MOVABLE_FILTER_VERSION == 8 and com["tracks"][0]["clips"][0]["movable"] is True
    assert sem["version"] == PROJECT_VERSION == 6 and "movable" not in sem["tracks"][0]["clips"][0]


def test_o_desfoque_continua_na_7_e_sem_a_chave(tmp_path: Path) -> None:
    desfoque, _ = _projeto(tmp_path)
    dados = project_to_dict(desfoque, base_dir=tmp_path)
    assert dados["version"] == REGION_BLUR_VERSION and "movable" not in dados["tracks"][0]["clips"][0]


def test_desfoque_e_filtro_movel_no_mesmo_projeto_gravam_a_8(tmp_path: Path) -> None:
    movel, filtro = _movel(tmp_path)
    desfoque, bloco = _projeto(tmp_path)
    junto = replace(movel, tracks=(*movel.tracks, Track(TrackKind.ADDITIONAL, clips=(bloco,), name="Adicionais 2")))
    assert project_to_dict(junto, base_dir=tmp_path)["version"] == 8


@pytest.mark.parametrize("nome", ["pb", "sepia", "inverter", "contraste", "vinheta"])
def test_o_filtro_movel_relê_igual_com_a_posicao_o_tamanho_e_os_quadros_chave(tmp_path: Path, nome: str) -> None:
    chaves = (Keyframe(0.0, x=0.3, y=0.6, scale_x=0.25, scale_y=0.4), Keyframe(3.0, x=0.7, y=0.4, scale_x=0.25, scale_y=0.4))
    projeto, filtro = _movel(tmp_path, nome, keyframes=chaves)
    caminho = tmp_path / "movel.vmp"
    save_project(projeto, caminho)
    assert json.loads(caminho.read_text(encoding="utf-8"))["version"] == 8
    carregado, _ = load_project(caminho)
    volta = carregado.additional_tracks[0].clips[0]
    assert volta.movable and volta.has_region and not volta.is_region_blur and volta.filter_name == nome
    assert volta.region_rect(1280, 720, 1.5) == filtro.region_rect(1280, 720, 1.5)
    assert carregado == projeto
    segundo = tmp_path / "dois.vmp"
    save_project(carregado, segundo)
    assert segundo.read_bytes() == caminho.read_bytes()          # abrir e salvar sem editar grava o mesmo arquivo


def test_a_versao_anterior_recusa_o_projeto_com_filtro_movel_e_abre_os_outros(tmp_path: Path, monkeypatch) -> None:
    """Uma versão que só lê até a 7 recusa o arquivo com filtro móvel (ela o aplicaria à tela inteira e o perderia ao
    salvar); o projeto sem filtro móvel, com ou sem desfoque, abre."""
    movel, _ = _movel(tmp_path)
    desfoque, _ = _projeto(tmp_path)
    com, comum = (project_to_dict(p, base_dir=tmp_path) for p in (movel, desfoque))
    monkeypatch.setattr(project_json, "SUPPORTED_VERSION", REGION_BLUR_VERSION)
    with pytest.raises(ProjectError):
        project_from_dict(com, base_dir=tmp_path)
    lido, _ = project_from_dict(comum, base_dir=tmp_path)
    assert lido.additional_tracks[0].clips[0].is_region_blur


def test_o_arquivo_sem_a_chave_abre_como_filtro_de_tela_inteira(tmp_path: Path) -> None:
    comum, _ = _projeto(tmp_path, "sepia")
    lido, _ = project_from_dict(project_to_dict(comum, base_dir=tmp_path), base_dir=tmp_path)
    bloco = lido.additional_tracks[0].clips[0]
    assert not bloco.movable and not bloco.has_region


def test_gravar_a_8_sobre_a_6_guarda_a_copia_e_sem_filtro_movel_volta_a_6(tmp_path: Path) -> None:
    comum, _ = _projeto(tmp_path, "sepia")
    movel, _ = _movel(tmp_path)
    caminho = tmp_path / "p.vmp"
    save_project(comum, caminho)
    original = caminho.read_bytes()
    save_project(movel, caminho)
    assert json.loads(caminho.read_text(encoding="utf-8"))["version"] == 8
    assert (tmp_path / "p.vmp.v6.bak").read_bytes() == original
    save_project(comum, caminho)                                      # tirou o filtro móvel: volta ao formato antigo
    assert json.loads(caminho.read_text(encoding="utf-8"))["version"] == 6
