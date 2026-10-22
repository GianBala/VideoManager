"""O desfoque de região no arquivo .vmp: ida e volta, projeto da versão anterior e nenhum campo novo.

A região é a pose do bloco (``x``, ``y``, ``scale_x``, ``scale_y`` e os quadros-chave), que o arquivo já grava;
o desfoque só acrescenta um **valor** (``filter_name = "desfoque"``). Por isso o formato não sobe de versão — ver o
relatório da mudança: uma versão antiga abriria o bloco como Preto e Branco.
"""

from __future__ import annotations

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
from videomanager.infrastructure.storage.project_json import load_project
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
    assert project_to_dict(desfoque, base_dir=tmp_path)["version"] == project_to_dict(sepia, base_dir=tmp_path)["version"]


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
