"""Arrastar um item com um desfoque de região acima dele: o plano rápido refaz o desfoque a cada movimento.

O desfoque borra o que o item móvel desenha, então ele não cabe numa imagem pronta, e antes (``interaction_plan``
devolvia ``None`` para qualquer filtro acima) o conteúdo não acompanhava o mouse: um render inteiro por passo. A
prévia compõe o quadro do gesto e borra a região nele, na mesma conta do compositor.
"""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QColor
from PySide6.QtGui import QImage
from PySide6.QtGui import QPixmap

from videomanager.application.capabilities import FFmpegTools
from videomanager.application.media.interaction import interaction_plan
from videomanager.domain.constants import REGION_BLUR
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import OverlayType
from videomanager.domain.project import Project
from videomanager.domain.project import Track
from videomanager.domain.project import TrackKind
from videomanager.domain.project import pseudo_media
from videomanager.infrastructure.ffmpeg.composer import frame_command
from videomanager.infrastructure.ffmpeg.composer import interaction_commands
from videomanager.infrastructure.ffmpeg.preview import _run
from videomanager.infrastructure.system.binaries import find_tools
from videomanager.infrastructure.system.binaries import subprocess_kwargs
from videomanager.presentation.qt.panels.edit_widgets import _Preview
from videomanager.presentation.qt.panels.region_blur import blur_region

pytestmark = pytest.mark.usefixtures("desktop_app")

FALSO = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")


def _imagem(caminho: Path, cor: QColor, **pose) -> Clip:
    quadro = QImage(64, 64, QImage.Format.Format_RGBA8888)
    quadro.fill(cor)
    assert quadro.save(str(caminho))
    return Clip(MediaRef(caminho, MediaKind.IMAGE, width=64, height=64), 0, 5, overlay_type="image", **pose)


def _filtro(nome: str = REGION_BLUR, **pose) -> Clip:
    extra = dict(x=0.4, y=0.5, scale=0.3, scale_x=0.3, scale_y=0.3) if nome == REGION_BLUR else {}
    return Clip(pseudo_media(OverlayType.FILTER, nome, 5.0), 0, 5, overlay_type="filter", filter_name=nome,
                **{**extra, **pose})


def _pilha(tmp_path: Path, *de_cima_para_baixo: Clip, base: Clip | None = None) -> Project:
    """Cada bloco numa trilha de adicionais, do topo para baixo, sobre um fundo de vídeo."""
    fundo = base or _imagem(tmp_path / "fundo.png", QColor("lime"), scale_x=1.0, scale_y=1.0)
    return Project(tracks=(*(Track(TrackKind.ADDITIONAL, clips=(c,), name=f"T{i}")
                             for i, c in enumerate(de_cima_para_baixo)),
                           Track(TrackKind.VIDEO, clips=(replace(fundo, overlay_type="image"),), name="Vídeo")),
                   width=320, height=180)


# -- o plano ---------------------------------------------------------------------------------

def test_o_plano_aceita_desfoque_acima_do_item_e_guarda_o_que_vem_depois_dele(tmp_path):
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    sobre = _imagem(tmp_path / "sobre.png", QColor("blue"), scale_x=.2, scale_y=.2)
    desfoque = _filtro()
    # De cima para baixo: o bloco azul, o desfoque, o item. O azul fica depois do desfoque (nítido).
    projeto = _pilha(tmp_path, sobre, desfoque, item)
    plano = interaction_plan(projeto, item.clip_id, 1.0)
    assert plano is not None
    assert [r.clip_id for r, _ in plano.stages] == [desfoque.clip_id]
    assert [c.clip_id for t in plano.stages[0][1].tracks for c in t.clips] == [sobre.clip_id]
    assert not [c for t in plano.foreground.tracks for c in t.clips]       # nada entre o item e o desfoque


def test_o_que_esta_entre_o_item_e_o_primeiro_desfoque_continua_na_frente_pronta(tmp_path):
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    entre = _imagem(tmp_path / "entre.png", QColor("blue"), scale_x=.2, scale_y=.2)
    desfoque = _filtro()
    plano = interaction_plan(_pilha(tmp_path, desfoque, entre, item), item.clip_id, 1.0)
    assert [c.clip_id for t in plano.foreground.tracks for c in t.clips] == [entre.clip_id]
    assert len(plano.stages) == 1 and not [c for t in plano.stages[0][1].tracks for c in t.clips]


def test_dois_desfoques_acima_sao_dois_trechos_de_baixo_para_cima(tmp_path):
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    entre = _imagem(tmp_path / "entre.png", QColor("blue"), scale_x=.2, scale_y=.2)
    baixo, cima = _filtro(x=.4), _filtro(x=.6)
    plano = interaction_plan(_pilha(tmp_path, cima, entre, baixo, item), item.clip_id, 1.0)
    assert [r.clip_id for r, _ in plano.stages] == [baixo.clip_id, cima.clip_id]
    assert [c.clip_id for t in plano.stages[0][1].tracks for c in t.clips] == [entre.clip_id]
    assert not [c for t in plano.stages[1][1].tracks for c in t.clips]


def test_o_desfoque_abaixo_do_item_continua_na_imagem_de_baixo_e_nao_cria_trecho(tmp_path):
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    desfoque = _filtro()
    plano = interaction_plan(_pilha(tmp_path, item, desfoque), item.clip_id, 1.0)
    assert plano is not None and plano.stages == ()
    assert desfoque.clip_id in {c.clip_id for t in plano.background.tracks for c in t.clips}


def _ids(projeto):
    return {c.clip_id for t in projeto.tracks for c in t.clips}


@pytest.mark.parametrize("nome", ["sepia", "pb", "inverter", "contraste"])
def test_filtro_de_cor_acima_do_item_tem_plano_e_ja_vai_nas_imagens_prontas(tmp_path, nome):
    """Sépia, P&B, Inverter e Contraste são afins: filtrar a soma é filtrar cada camada. O filtro entra no fundo e na
    textura, e a prévia não precisa refazer nada a cada movimento."""
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    filtro = _filtro(nome)
    plano = interaction_plan(_pilha(tmp_path, filtro, item), item.clip_id, 1.0)
    assert plano is not None and plano.stages == () and plano.filters == (filtro,) and not plano.needs_mask
    assert filtro.clip_id in _ids(plano.background)                  # o fundo sai filtrado
    assert plano.base_layers == 3


def test_o_filtro_de_cor_so_age_nos_trechos_que_estao_abaixo_dele(tmp_path):
    """No meio da pilha, o filtro entra nos trechos que o têm acima e **não** nos que vêm depois dele."""
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    a = _imagem(tmp_path / "a.png", QColor("blue"), scale_x=.2, scale_y=.2)
    b = _imagem(tmp_path / "b.png", QColor("white"), scale_x=.2, scale_y=.2)
    desfoque, sepia = _filtro(), _filtro("sepia")
    # De cima para baixo: b, sepia, desfoque, a, item. O Sépia fica entre o desfoque e b.
    plano = interaction_plan(_pilha(tmp_path, b, sepia, desfoque, a, item), item.clip_id, 1.0)
    assert _ids(plano.foreground) == {a.clip_id, sepia.clip_id}       # a está abaixo do Sépia
    assert [(r.clip_id, _ids(p)) for r, p in plano.stages] == [(desfoque.clip_id, {b.clip_id})]   # b está acima: sem Sépia
    assert plano.filters == (sepia,) and sepia.clip_id in _ids(plano.background)


def test_a_vinheta_acima_do_item_e_um_trecho_com_mascara_e_nao_vai_nas_imagens_prontas(tmp_path):
    """A vinheta escurece por posição na tela e o item muda de posição: refeita a cada movimento, com uma máscara."""
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    sobre = _imagem(tmp_path / "sobre.png", QColor("blue"), scale_x=.2, scale_y=.2)
    vinheta = _filtro("vinheta")
    plano = interaction_plan(_pilha(tmp_path, sobre, vinheta, item), item.clip_id, 1.0)
    assert plano.needs_mask and plano.filters == ()
    assert [(r.clip_id, _ids(p)) for r, p in plano.stages] == [(vinheta.clip_id, {sobre.clip_id})]
    assert vinheta.clip_id not in _ids(plano.background) and vinheta.clip_id not in _ids(plano.foreground)
    comandos = interaction_commands(plano, (320, 180), FALSO)
    assert len(comandos) == 3 + 1 + 1                                   # base, o trecho depois da vinheta e a máscara
    assert "vignette=PI/4" in " ".join(comandos[-1]) and "color=c=white" in " ".join(comandos[-1])


@pytest.mark.parametrize("acima, tem_plano", [("inverter", False), ("contraste", False), ("sepia", True), ("pb", True)])
def test_vinheta_abaixo_de_um_filtro_com_termo_constante_fica_sem_plano(tmp_path, acima, tem_plano):
    """Inverter e Contraste não comutam com a multiplicação da vinheta; Sépia e P&B (lineares) comutam."""
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    plano = interaction_plan(_pilha(tmp_path, _filtro(acima), _filtro("vinheta"), item), item.clip_id, 1.0)
    assert (plano is not None) is tem_plano
    # Com a vinheta **acima** do Inverter a ordem se refaz sozinha (a vinheta multiplica por último): tem plano.
    assert interaction_plan(_pilha(tmp_path, _filtro("vinheta"), _filtro(acima), item), item.clip_id, 1.0) is not None


def test_filtro_que_o_plano_nao_conhece_ou_transicao_acima_do_item_fica_sem_plano(tmp_path):
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    assert interaction_plan(_pilha(tmp_path, _filtro("filtro-novo"), item), item.clip_id, 1.0) is None


def test_a_textura_e_o_fundo_desfocado_saem_com_a_cadeia_dos_filtros_de_cor(tmp_path):
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4, blur_background=True)
    sem = " ".join(interaction_commands(interaction_plan(_pilha(tmp_path, item), item.clip_id, 1.0), (320, 180), FALSO)[1])
    plano = interaction_plan(_pilha(tmp_path, _filtro("sepia"), _filtro("inverter"), item), item.clip_id, 1.0)
    comandos = interaction_commands(plano, (320, 180), FALSO)
    assert len(comandos) == 4                                          # fundo, textura, frente e fundo desfocado
    textura, fundo_desfocado = " ".join(comandos[1]), " ".join(comandos[3])
    assert "colorchannelmixer" not in sem
    for comando in (textura, fundo_desfocado):
        # Na ordem da pilha, de baixo para cima: o Inverter (mais baixo) age antes do Sépia (que está no topo).
        assert 0 <= comando.index("negate") < comando.index("colorchannelmixer")


def test_o_plano_nao_depende_da_pose_do_item_mas_muda_com_o_desfoque(tmp_path):
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    desfoque = _filtro()
    projeto = _pilha(tmp_path, desfoque, item)
    plano = interaction_plan(projeto, item.clip_id, 1.0)
    assert plano == interaction_plan(projeto.with_updated_clip(item.clip_id, x=.2, rotation=35, opacity=.4),
                                     item.clip_id, 1.0)
    # Mexer no desfoque troca o plano: as camadas prontas de antes não valem para a região nova.
    assert plano != interaction_plan(projeto.with_updated_clip(desfoque.clip_id, x=.7), item.clip_id, 1.0)


def test_um_comando_a_mais_por_desfoque_depois_das_camadas_de_sempre(tmp_path):
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    sem = interaction_plan(_pilha(tmp_path, item), item.clip_id, 1.0)
    um = interaction_plan(_pilha(tmp_path, _filtro(), item), item.clip_id, 1.0)
    dois = interaction_plan(_pilha(tmp_path, _filtro(x=.7), _filtro(), item), item.clip_id, 1.0)
    assert [len(interaction_commands(p, (320, 180), FALSO)) for p in (sem, um, dois)] == [3, 4, 5]
    com_fundo = replace(item, blur_background=True)
    assert len(interaction_commands(interaction_plan(_pilha(tmp_path, _filtro(), com_fundo), item.clip_id, 1.0),
                                    (320, 180), FALSO)) == 5     # as quatro de sempre mais a do desfoque


def test_sem_desfoque_acima_os_comandos_sao_os_de_antes(tmp_path):
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    plano = interaction_plan(_pilha(tmp_path, item), item.clip_id, 1.0)
    assert plano.stages == ()
    comandos = interaction_commands(plano, (320, 180), FALSO)
    assert len(comandos) == 3


# -- arrastar o próprio desfoque ----------------------------------------------------------------

def test_o_plano_do_desfoque_arrastado_tem_o_que_esta_abaixo_e_acima_e_nenhuma_textura(tmp_path):
    abaixo = _imagem(tmp_path / "abaixo.png", QColor("red"), scale_x=.4, scale_y=.4)
    sobre = _imagem(tmp_path / "sobre.png", QColor("blue"), scale_x=.2, scale_y=.2)
    desfoque = _filtro()
    plano = interaction_plan(_pilha(tmp_path, sobre, desfoque, abaixo), desfoque.clip_id, 1.0)
    assert plano is not None and plano.source is None and plano.stages == () and not plano.blur
    assert plano.base_layers == 2
    ids = lambda projeto: {c.clip_id for t in projeto.tracks for c in t.clips}                 # noqa: E731
    assert abaixo.clip_id in ids(plano.background) and desfoque.clip_id not in ids(plano.background)
    assert ids(plano.foreground) == {sobre.clip_id}


def test_o_plano_do_desfoque_arrastado_nao_depende_da_pose_dele(tmp_path):
    """O que está abaixo e acima não muda enquanto a mão move a região: as camadas prontas valem o gesto todo."""
    abaixo = _imagem(tmp_path / "abaixo.png", QColor("red"), scale_x=.4, scale_y=.4)
    desfoque = _filtro()
    projeto = _pilha(tmp_path, desfoque, abaixo)
    plano = interaction_plan(projeto, desfoque.clip_id, 1.0)
    movido = projeto.with_updated_clip(desfoque.clip_id, x=.8, y=.2, scale_x=.1, scale_y=.4)
    assert plano == interaction_plan(movido, desfoque.clip_id, 1.0)
    # Mexer no que está abaixo, sim, troca o plano.
    assert plano != interaction_plan(projeto.with_updated_clip(abaixo.clip_id, x=.1), desfoque.clip_id, 1.0)


def test_o_desfoque_arrastado_com_outro_desfoque_acima_deixa_o_de_cima_como_trecho(tmp_path):
    abaixo = _imagem(tmp_path / "abaixo.png", QColor("red"), scale_x=.4, scale_y=.4)
    entre = _imagem(tmp_path / "entre.png", QColor("blue"), scale_x=.2, scale_y=.2)
    de_baixo, de_cima = _filtro(x=.3), _filtro(x=.6)
    plano = interaction_plan(_pilha(tmp_path, de_cima, entre, de_baixo, abaixo), de_baixo.clip_id, 1.0)
    assert [r.clip_id for r, _ in plano.stages] == [de_cima.clip_id]
    assert [c.clip_id for t in plano.foreground.tracks for c in t.clips] == [entre.clip_id]
    # O de cima, arrastado, tem o de baixo já borrado na imagem de baixo.
    plano = interaction_plan(_pilha(tmp_path, de_cima, entre, de_baixo, abaixo), de_cima.clip_id, 1.0)
    assert plano.stages == () and de_baixo.clip_id in {c.clip_id for t in plano.background.tracks for c in t.clips}


@pytest.mark.parametrize("acima", ["sepia", "pb", "inverter", "contraste"])
def test_o_desfoque_arrastado_com_filtro_de_cor_acima_tem_plano_com_o_filtro_no_fundo(tmp_path, acima):
    abaixo = _imagem(tmp_path / "abaixo.png", QColor("red"), scale_x=.4, scale_y=.4)
    desfoque, filtro = _filtro(), _filtro(acima)
    plano = interaction_plan(_pilha(tmp_path, filtro, desfoque, abaixo), desfoque.clip_id, 1.0)
    assert plano is not None and plano.source is None and plano.filters == (filtro,)
    assert filtro.clip_id in _ids(plano.background) and desfoque.clip_id not in _ids(plano.background)


def test_o_desfoque_arrastado_com_filtro_desconhecido_acima_fica_sem_plano(tmp_path):
    abaixo = _imagem(tmp_path / "abaixo.png", QColor("red"), scale_x=.4, scale_y=.4)
    desfoque = _filtro()
    assert interaction_plan(_pilha(tmp_path, _filtro("filtro-novo"), desfoque, abaixo), desfoque.clip_id, 1.0) is None


def test_o_desfoque_arrastado_pede_so_duas_imagens_mais_uma_por_desfoque_acima(tmp_path):
    abaixo = _imagem(tmp_path / "abaixo.png", QColor("red"), scale_x=.4, scale_y=.4)
    desfoque = _filtro()
    um = interaction_plan(_pilha(tmp_path, desfoque, abaixo), desfoque.clip_id, 1.0)
    dois = interaction_plan(_pilha(tmp_path, _filtro(x=.7), desfoque, abaixo), desfoque.clip_id, 1.0)
    assert [len(interaction_commands(p, (320, 180), FALSO)) for p in (um, dois)] == [2, 3]


def _cena_arrastando_o_desfoque(tmp_path: Path, tools, *, com_outro_acima: bool = False, animado: bool = False):
    fonte = tmp_path / "fonte.png"
    subprocess.run([tools.ffmpeg_str, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=5",
                    "-frames:v", "1", str(fonte)], check=True, timeout=30, **subprocess_kwargs())
    chao = Clip(MediaRef(fonte, MediaKind.IMAGE, width=320, height=180), 0, 5, overlay_type="image",
                scale_x=1.0, scale_y=1.0)
    # O vermelho fica abaixo do desfoque: é borrado onde a região passa. O verde fica acima: nítido.
    abaixo = _imagem(tmp_path / "vermelho.png", QColor("red"), scale_x=.4, scale_y=.4, x=.5, y=.5)
    sobre = _imagem(tmp_path / "verde.png", QColor(30, 200, 30), scale_x=.12, scale_y=.12, x=.6, y=.3)
    desfoque = _filtro(x=.3, y=.5)
    # Um segundo desfoque, acima: borra também o que o primeiro deixou.
    # Com ``animado``, ele anda entre dois quadros-chave: a posição que vale é a da agulha (1 s), não a do início do bloco.
    chaves = (Keyframe(0.0, x=.2, y=.65, scale_x=.25, scale_y=.25), Keyframe(4.0, x=.8, y=.65, scale_x=.25, scale_y=.25))
    outro = _filtro(x=.75, y=.65, scale_x=.25, scale_y=.25, scale=.25, **(dict(keyframes=chaves) if animado else {}))
    acima = (outro,) if com_outro_acima else ()
    return _pilha(tmp_path, *acima, sobre, desfoque, abaixo, base=chao), desfoque, sobre, outro


def _medir_regiao(tmp_path: Path, movida: dict, *, com_outro_acima: bool = False, animado: bool = False) -> SimpleNamespace:
    """Arrasta o desfoque (``movida``: campos novos do bloco) na prévia e mede contra o quadro que o ffmpeg comporia."""
    tools = find_tools()
    if tools is None:
        pytest.skip("FFmpeg não disponível")
    projeto, desfoque, sobre, outro = _cena_arrastando_o_desfoque(tmp_path, tools, com_outro_acima=com_outro_acima,
                                                                   animado=animado)
    plano = interaction_plan(projeto, desfoque.clip_id, 1.0)
    assert plano is not None and plano.source is None and len(plano.stages) == int(com_outro_acima)
    tamanho = (640, 360)
    camadas = tuple(QPixmap.fromImage(QImage.fromData(_run(c, 30, strict=True)))
                    for c in interaction_commands(plano, tamanho, tools))
    assert len(camadas) == 2 + len(plano.stages) and all(not p.isNull() for p in camadas)
    previa = _Preview()
    previa.resize(*tamanho)
    previa.set_frame_pixmap(QPixmap.fromImage(QImage.fromData(
        _run(frame_command(projeto, 1, tamanho, tools, png=True), 30, strict=True))))
    previa.set_active_clip(desfoque, projeto.width, projeto.height)
    previa.set_position(1)
    previa.set_interaction_layers(camadas[:2], tuple(zip((r for r, _ in plano.stages), camadas[2:])))
    novo = replace(desfoque, **movida)
    previa.set_active_clip(novo, projeto.width, projeto.height)
    assert previa.begin_interaction()
    atual = previa.grab().toImage()
    esperado = QImage.fromData(_run(frame_command(projeto.with_updated_clip(desfoque.clip_id, **movida), 1, tamanho,
                                                  tools, png=True), 30, strict=True))
    esq, topo, w, h = novo.region_rect(*tamanho, 1.0)

    def diferenca(px: int, py: int) -> int:
        a, b = atual.pixelColor(px, py), esperado.pixelColor(px, py)
        return max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue()))

    # A caixa e as alças do bloco ativo ficam na borda da região: lê-se longe dela, dos dois lados.
    dentro = [diferenca(px, py) for py in range(topo + 12, topo + h - 12, 5) for px in range(esq + 12, esq + w - 12, 5)]
    fora = [diferenca(px, py) for py in range(14, 346, 12) for px in range(14, 626, 12)
            if not (esq - 14 <= px < esq + w + 14 and topo - 14 <= py < topo + h + 14)]
    return SimpleNamespace(dentro=dentro, fora=fora)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("movida", [dict(x=.3), dict(x=.45), dict(x=.7, y=.3), dict(x=.5, y=.6, scale_x=.45, scale_y=.2)],
                         ids=["parado", "para_a_direita", "para_cima_e_a_direita", "redimensionado"])
def test_o_desfoque_arrastado_borra_na_pose_da_mao_e_o_resto_fica_como_estava(tmp_path, movida):
    """A região na pose nova borra o que está embaixo; o lugar onde ela estava volta a ficar nítido; o que está acima
    dela continua nítido. Medido contra o quadro do ffmpeg numa cena com barras de cor (o pior caso para um borrão)."""
    medida = _medir_regiao(tmp_path, movida)
    assert len(medida.dentro) > 40
    assert sum(medida.dentro) / len(medida.dentro) <= 4, sum(medida.dentro) / len(medida.dentro)
    assert max(medida.dentro) <= 60, max(medida.dentro)
    assert sum(medida.fora) / len(medida.fora) <= 1.5, sum(medida.fora) / len(medida.fora)
    # Fora da região só diferem as bordas do quadrado verde, que a imagem da frente (composta em base transparente na tela
    # do projeto e ampliada) tem um pouco diferentes das do quadro inteiro: até ~50 em 255 em um pixel de borda.
    assert max(medida.fora) <= 60, max(medida.fora)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("movida", [dict(x=.3), dict(x=.6, y=.5)], ids=["parado", "movido"])
def test_o_desfoque_arrastado_com_outro_desfoque_acima_junta_as_tres_imagens(tmp_path, movida):
    medida = _medir_regiao(tmp_path, movida, com_outro_acima=True)
    assert sum(medida.dentro) / len(medida.dentro) <= 4, sum(medida.dentro) / len(medida.dentro)
    assert max(medida.dentro) <= 60, max(medida.dentro)
    assert sum(medida.fora) / len(medida.fora) <= 3, sum(medida.fora) / len(medida.fora)


@pytest.mark.ffmpeg
def test_o_desfoque_arrastado_e_o_de_cima_usam_a_posicao_da_agulha_quando_ha_quadros_chave(tmp_path):
    """Entre quadros-chave a região anda: a prévia a borra onde ela está na agulha, e não onde começa o bloco."""
    chaves = (Keyframe(0.0, x=.2, y=.5, scale_x=.3, scale_y=.3), Keyframe(4.0, x=.8, y=.5, scale_x=.3, scale_y=.3))
    medida = _medir_regiao(tmp_path, dict(keyframes=chaves), com_outro_acima=True, animado=True)
    assert sum(medida.dentro) / len(medida.dentro) <= 4, sum(medida.dentro) / len(medida.dentro)
    assert max(medida.dentro) <= 60, max(medida.dentro)
    assert sum(medida.fora) / len(medida.fora) <= 3, sum(medida.fora) / len(medida.fora)


@pytest.mark.ffmpeg
def test_o_teste_acima_enxerga_o_desfoque_arrastado_que_nao_e_borrado(tmp_path, monkeypatch):
    """Guarda: sem borrar a região na pose da mão, o mesmo quadro estoura os limites do teste acima."""
    from videomanager.presentation.qt.panels import edit_widgets
    monkeypatch.setattr(edit_widgets, "blur_region", lambda *args: None)
    medida = _medir_regiao(tmp_path, dict(x=.45))
    assert sum(medida.dentro) / len(medida.dentro) > 4 or max(medida.dentro) > 60


# -- filtros de tela inteira acima do que se arrasta -------------------------------------------

def _medir_com_filtros(tmp_path: Path, arrasta: str, filtros: tuple[str, ...], com_desfoque: bool,
                       *, sem_o_filtro_na_textura: bool = False) -> SimpleNamespace:
    """Arrasta o item (ou o desfoque) com ``filtros`` no topo da pilha e mede o quadro todo contra o do ffmpeg.

    ``filtros`` vai do topo para baixo. Os pontos junto da caixa do bloco ativo (contorno e alças, que o ffmpeg não
    desenha) ficam de fora.
    """
    tools = find_tools()
    if tools is None:
        pytest.skip("FFmpeg não disponível")
    fonte = tmp_path / "fonte.png"
    subprocess.run([tools.ffmpeg_str, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=5",
                    "-frames:v", "1", str(fonte)], check=True, timeout=30, **subprocess_kwargs())
    chao = Clip(MediaRef(fonte, MediaKind.IMAGE, width=320, height=180), 0, 5, overlay_type="image",
                scale_x=1.0, scale_y=1.0)
    item = _imagem(tmp_path / "vermelho.png", QColor(200, 40, 40), scale_x=.5, scale_y=.5, x=.3, y=.5, opacity=.8)
    sobre = _imagem(tmp_path / "verde.png", QColor(30, 200, 30), scale_x=.12, scale_y=.12, x=.6, y=.3)
    desfoque = _filtro(x=.4, y=.5)
    pilha = [*(_filtro(f) for f in filtros), sobre, *([desfoque] if com_desfoque or arrasta == "regiao" else []), item]
    projeto = _pilha(tmp_path, *pilha, base=chao)
    alvo = item if arrasta == "item" else desfoque
    plano = interaction_plan(projeto, alvo.clip_id, 1.0)
    assert plano is not None
    if sem_o_filtro_na_textura:
        plano = replace(plano, filters=())
    tamanho = (640, 360)
    camadas = tuple(QPixmap.fromImage(QImage.fromData(_run(c, 30, strict=True)))
                    for c in interaction_commands(plano, tamanho, tools))
    base, fim = plano.base_layers, plano.base_layers + len(plano.stages)
    assert len(camadas) == fim + int(plano.needs_mask) and all(not c.isNull() for c in camadas)
    previa = _Preview()
    previa.resize(*tamanho)
    previa.set_frame_pixmap(QPixmap.fromImage(QImage.fromData(
        _run(frame_command(projeto, 1, tamanho, tools, png=True), 30, strict=True))))
    previa.set_active_clip(alvo, projeto.width, projeto.height)
    previa.set_position(1)
    previa.set_interaction_layers(camadas[:base], tuple(zip((r for r, _ in plano.stages), camadas[base:fim])),
                                  camadas[fim] if plano.needs_mask else None)
    movida = replace(alvo, x=.55) if arrasta == "item" else replace(alvo, x=.6, y=.55)
    previa.set_active_clip(movida, projeto.width, projeto.height)
    assert previa.begin_interaction()
    atual = previa.grab().toImage()
    esperado = QImage.fromData(_run(frame_command(projeto.with_updated_clip(alvo.clip_id, x=movida.x, y=movida.y), 1,
                                                  tamanho, tools, png=True), 30, strict=True))
    cx, cy, bw, bh = previa._clip_geometry(movida)
    x0, x1, y0, y1 = cx - bw / 2, cx + bw / 2, cy - bh / 2, cy + bh / 2
    erros = []
    for py in range(14, 346, 6):
        for px in range(14, 626, 6):
            if ((min(abs(px - x0), abs(px - x1)) < 10 and y0 - 10 < py < y1 + 10)
                    or (min(abs(py - y0), abs(py - y1)) < 10 and x0 - 10 < px < x1 + 10)):
                continue
            a, b = atual.pixelColor(px, py), esperado.pixelColor(px, py)
            erros.append(max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue())))
    erros.sort()
    return SimpleNamespace(media=sum(erros) / len(erros), p95=erros[int(len(erros) * .95)], n=len(erros))


CASOS_DE_FILTROS = [
    pytest.param("item", ("pb",), False, id="item+pb"),
    pytest.param("item", ("sepia",), False, id="item+sepia"),
    pytest.param("item", ("inverter",), False, id="item+inverter"),
    pytest.param("item", ("contraste",), False, id="item+contraste"),
    pytest.param("item", ("vinheta",), False, id="item+vinheta"),
    pytest.param("item", ("sepia",), True, id="item+desfoque+sepia"),
    pytest.param("item", ("vinheta",), True, id="item+desfoque+vinheta"),
    pytest.param("item", ("sepia", "pb"), True, id="item+desfoque+sepia+pb"),
    # Vinheta abaixo do Sépia: o ffmpeg escurece e depois aplica a matriz (que passa de 255 nos claros e é cortada);
    # a prévia aplica a matriz às camadas e escurece por último, então os claros saem um pouco mais escuros (~1 em 255).
    pytest.param("item", ("sepia", "vinheta"), False, id="item+vinheta+sepia"),
    pytest.param("item", ("vinheta", "inverter"), False, id="item+inverter+vinheta"),
    pytest.param("regiao", ("sepia",), False, id="regiao+sepia"),
    pytest.param("regiao", ("pb",), False, id="regiao+pb"),
    pytest.param("regiao", ("vinheta",), False, id="regiao+vinheta"),
    pytest.param("regiao", ("vinheta", "inverter"), False, id="regiao+inverter+vinheta"),
]


@pytest.mark.ffmpeg
@pytest.mark.parametrize("arrasta, filtros, com_desfoque", CASOS_DE_FILTROS)
def test_o_quadro_do_arrasto_com_filtros_acima_acompanha_o_quadro_final(tmp_path, arrasta, filtros, com_desfoque):
    """Com filtros de tela inteira acima, o item (ou o desfoque) arrastado sai com a cor do quadro final e a prévia não
    refaz nada a cada movimento. Medido na cena de barras de cor (o pior caso): média até ~2 e p95 até ~14 em 255; os
    pontos que passam disso estão nas arestas do item, onde a prévia desenha à parte do ffmpeg."""
    medida = _medir_com_filtros(tmp_path, arrasta, filtros, com_desfoque)
    vinheta_sob_sepia = filtros == ("sepia", "vinheta")
    assert medida.n > 1000
    assert medida.media <= (5 if vinheta_sob_sepia else 3), medida
    assert medida.p95 <= (34 if vinheta_sob_sepia else 24), medida


@pytest.mark.ffmpeg
@pytest.mark.parametrize("filtro", ["sepia", "inverter", "pb"])
def test_sem_o_filtro_na_textura_o_item_arrastado_destoa_do_quadro_final(tmp_path, filtro):
    """Guarda do teste acima: com a textura sem a cadeia dos filtros, o item sai com a cor errada e o limite estoura."""
    certo = _medir_com_filtros(tmp_path / "a", "item", (filtro,), False) if (tmp_path / "a").mkdir() is None else None
    errado = _medir_com_filtros(tmp_path / "b", "item", (filtro,), False, sem_o_filtro_na_textura=True) \
        if (tmp_path / "b").mkdir() is None else None
    assert errado.media > certo.media * 2 and errado.media > 1.5, (certo, errado)


# -- o desfoque no Qt --------------------------------------------------------------------------

def _xadrez(w: int, h: int) -> QImage:
    imagem = QImage(w, h, QImage.Format.Format_RGB32)
    for y in range(h):
        for x in range(w):
            imagem.setPixelColor(x, y, QColor("white") if (x // 4 + y // 4) % 2 else QColor("black"))
    return imagem


def test_blur_region_borra_so_o_retangulo():
    imagem = _xadrez(160, 90)
    antes = imagem.copy()
    blur_region(imagem, 40, 20, 80, 50)
    for y in range(90):
        for x in range(160):
            dentro = 40 <= x < 120 and 20 <= y < 70
            if not dentro:
                assert imagem.pixel(x, y) == antes.pixel(x, y), (x, y)
    # Dentro, o xadrez de 4 px vira um cinza quase uniforme.
    valores = [imagem.pixelColor(x, y).red() for y in range(24, 66) for x in range(44, 116)]
    assert max(valores) - min(valores) < 40
    assert 100 < sum(valores) / len(valores) < 160


def test_blur_region_ignora_o_que_cai_fora_da_imagem():
    imagem = _xadrez(64, 36)
    antes = imagem.copy()
    blur_region(imagem, 60, 30, 40, 40)          # quase tudo fora
    blur_region(imagem, -20, -20, 10, 10)        # inteiramente fora
    blur_region(imagem, 10, 10, 1, 1)            # menor que o mínimo
    assert imagem.pixel(0, 0) == antes.pixel(0, 0) and imagem.pixel(20, 20) == antes.pixel(20, 20)


def test_blur_region_repetida_com_os_mesmos_pixels_da_o_mesmo_resultado():
    a, b = _xadrez(96, 54), _xadrez(96, 54)
    blur_region(a, 10, 10, 60, 30)
    blur_region(b, 10, 10, 60, 30)
    assert a == b


# -- a prévia contra o quadro do ffmpeg ------------------------------------------------------

def _cena_com_desfoque_acima(tmp_path: Path, tools, *, fundo_desfocado: bool = False):
    fonte = tmp_path / "fonte.png"
    subprocess.run([tools.ffmpeg_str, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=5",
                    "-frames:v", "1", str(fonte)], check=True, timeout=30, **subprocess_kwargs())
    chao = Clip(MediaRef(fonte, MediaKind.IMAGE, width=320, height=180), 0, 5, overlay_type="image",
                scale_x=1.0, scale_y=1.0)
    arrastado = _imagem(tmp_path / "vermelho.png", QColor("red"), scale_x=.5, scale_y=.5, x=.3, y=.5,
                        blur_background=fundo_desfocado)
    # O verde fica acima do desfoque e invade a região: tem de continuar nítido.
    sobre = _imagem(tmp_path / "verde.png", QColor(30, 200, 30), scale_x=.12, scale_y=.12, x=.5, y=.5)
    desfoque = _filtro(x=.4, y=.5)
    # O azul fica entre o item arrastado e o desfoque: faz parte do que é borrado, e é a imagem "da frente" pronta.
    entre = _imagem(tmp_path / "azul.png", QColor(20, 20, 220), scale_x=.3, scale_y=.3, x=.4, y=.5)
    return _pilha(tmp_path, sobre, desfoque, entre, arrastado, base=chao), arrastado, desfoque, sobre


def _medir(tmp_path: Path, x: float, *, fundo_desfocado: bool = False) -> SimpleNamespace:
    """Arrasta o item até ``x`` na prévia e mede a diferença para o quadro que o ffmpeg comporia ali."""
    tools = find_tools()
    if tools is None:
        pytest.skip("FFmpeg não disponível")
    projeto, arrastado, desfoque, sobre = _cena_com_desfoque_acima(tmp_path, tools, fundo_desfocado=fundo_desfocado)
    plano = interaction_plan(projeto, arrastado.clip_id, 1.0)
    assert plano is not None and len(plano.stages) == 1 and plano.blur is fundo_desfocado
    base = 4 if fundo_desfocado else 3
    assert [c.clip_id for t in plano.foreground.tracks for c in t.clips], "o azul, entre o item e o desfoque, é a frente"
    tamanho = (640, 360)
    camadas = tuple(QPixmap.fromImage(QImage.fromData(_run(c, 30, strict=True)))
                    for c in interaction_commands(plano, tamanho, tools))
    assert len(camadas) == base + 1 and all(not p.isNull() for p in camadas)
    previa = _Preview()
    previa.resize(*tamanho)
    previa.set_frame_pixmap(QPixmap.fromImage(QImage.fromData(
        _run(frame_command(projeto, 1, tamanho, tools, png=True), 30, strict=True))))
    previa.set_active_clip(arrastado, projeto.width, projeto.height)
    previa.set_position(1)
    previa.set_interaction_layers(camadas[:base], tuple(zip((r for r, _ in plano.stages), camadas[base:])))
    previa.set_active_clip(replace(arrastado, x=x), projeto.width, projeto.height)
    assert previa.begin_interaction()
    atual = previa.grab().toImage()
    esperado = QImage.fromData(_run(frame_command(projeto.with_updated_clip(arrastado.clip_id, x=x), 1, tamanho,
                                                  tools, png=True), 30, strict=True))
    esq, topo, w, h = desfoque.region_rect(*tamanho, 1.0)
    cx, cy, bw, bh = previa._clip_geometry(replace(arrastado, x=x))
    caixa = (cx - bw / 2, cx + bw / 2, cy - bh / 2, cy + bh / 2)

    def perto_da_caixa(px: int, py: int) -> bool:        # contorno e alças do item ativo, que o ffmpeg não desenha
        return ((min(abs(px - caixa[0]), abs(px - caixa[1])) < 10 and caixa[2] - 10 < py < caixa[3] + 10)
                or (min(abs(py - caixa[2]), abs(py - caixa[3])) < 10 and caixa[0] - 10 < px < caixa[1] + 10))

    def diferenca(px: int, py: int) -> int:
        a, b = atual.pixelColor(px, py), esperado.pixelColor(px, py)
        return max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue()))

    dentro = [diferenca(px, py) for py in range(topo + 6, topo + h - 6, 6) for px in range(esq + 6, esq + w - 6, 6)
              if not perto_da_caixa(px, py)]
    fora = [diferenca(px, py) for py in range(12, 348, 12) for px in range(12, 628, 12)
            if not (esq - 4 <= px < esq + w + 4 and topo - 4 <= py < topo + h + 4) and not perto_da_caixa(px, py)]
    gx, gy, _, _ = previa._clip_geometry(sobre)
    return SimpleNamespace(dentro=dentro, fora=fora, verde=diferenca(round(gx), round(gy)),
                           verde_g=atual.pixelColor(round(gx), round(gy)).green())


@pytest.mark.ffmpeg
@pytest.mark.parametrize("x", [.3, .4, .45, .6], ids=lambda x: f"x={x}")
def test_o_quadro_do_arrasto_com_desfoque_acima_acompanha_o_quadro_final(tmp_path, x):
    """O item passa por baixo do desfoque e a prévia o borra na hora, como o ffmpeg fará no quadro final.

    Medido contra o quadro do ffmpeg numa cena com barras de cor (o pior caso para um borrão): dentro da região a
    diferença média é de ~1,5 em 255, e o que está acima do desfoque continua nítido.
    """
    medida = _medir(tmp_path, x)
    assert len(medida.dentro) > 100
    assert sum(medida.dentro) / len(medida.dentro) <= 4, sum(medida.dentro) / len(medida.dentro)
    assert max(medida.dentro) <= 60, max(medida.dentro)
    # O verde, acima do desfoque, está dentro da região e sai nítido: o centro dele é verde puro nos dois quadros.
    assert medida.verde <= 6 and medida.verde_g > 150
    # Fora da região e do contorno do item, a imagem é a mesma de sempre.
    assert sum(medida.fora) / len(medida.fora) <= 2, sum(medida.fora) / len(medida.fora)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("x", [.3, .45], ids=lambda x: f"x={x}")
def test_o_arrasto_com_fundo_desfocado_e_desfoque_acima_junta_as_cinco_camadas(tmp_path, x):
    """O item com "fundo desfocado" tem uma quarta camada, e a do desfoque de região vem depois dela: as cinco se compõem."""
    medida = _medir(tmp_path, x, fundo_desfocado=True)
    assert sum(medida.dentro) / len(medida.dentro) <= 4, sum(medida.dentro) / len(medida.dentro)
    assert max(medida.dentro) <= 60, max(medida.dentro)
    assert sum(medida.fora) / len(medida.fora) <= 3, sum(medida.fora) / len(medida.fora)


@pytest.mark.ffmpeg
def test_o_teste_acima_enxerga_o_desfoque_que_falta(tmp_path, monkeypatch):
    """Guarda: sem borrar a região na prévia, o mesmo quadro estoura os limites do teste acima."""
    from videomanager.presentation.qt.panels import edit_widgets
    monkeypatch.setattr(edit_widgets, "blur_region", lambda *args: None)
    medida = _medir(tmp_path, .4)
    assert sum(medida.dentro) / len(medida.dentro) > 4 or max(medida.dentro) > 60
