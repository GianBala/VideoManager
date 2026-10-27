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


@pytest.mark.parametrize("nome", ["sepia", "pb", "inverter", "vinheta", "contraste"])
def test_outro_filtro_acima_do_item_continua_sem_plano_rapido(tmp_path, nome):
    """Só o desfoque de região é refeito na prévia: os de tela inteira mudam tudo que está abaixo."""
    item = _imagem(tmp_path / "item.png", QColor("red"), scale_x=.4, scale_y=.4)
    assert interaction_plan(_pilha(tmp_path, _filtro(nome), item), item.clip_id, 1.0) is None
    assert interaction_plan(_pilha(tmp_path, _filtro(nome), _filtro(), item), item.clip_id, 1.0) is None
    assert interaction_plan(_pilha(tmp_path, _filtro(), _filtro(nome), item), item.clip_id, 1.0) is None


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

def _cena_com_desfoque_acima(tmp_path: Path, tools):
    fonte = tmp_path / "fonte.png"
    subprocess.run([tools.ffmpeg_str, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=5",
                    "-frames:v", "1", str(fonte)], check=True, timeout=30, **subprocess_kwargs())
    chao = Clip(MediaRef(fonte, MediaKind.IMAGE, width=320, height=180), 0, 5, overlay_type="image",
                scale_x=1.0, scale_y=1.0)
    arrastado = _imagem(tmp_path / "vermelho.png", QColor("red"), scale_x=.5, scale_y=.5, x=.3, y=.5)
    # O verde fica acima do desfoque e invade a região: tem de continuar nítido.
    sobre = _imagem(tmp_path / "verde.png", QColor(30, 200, 30), scale_x=.12, scale_y=.12, x=.5, y=.5)
    desfoque = _filtro(x=.4, y=.5)
    return _pilha(tmp_path, sobre, desfoque, arrastado, base=chao), arrastado, desfoque, sobre


def _medir(tmp_path: Path, x: float) -> SimpleNamespace:
    """Arrasta o item até ``x`` na prévia e mede a diferença para o quadro que o ffmpeg comporia ali."""
    tools = find_tools()
    if tools is None:
        pytest.skip("FFmpeg não disponível")
    projeto, arrastado, desfoque, sobre = _cena_com_desfoque_acima(tmp_path, tools)
    plano = interaction_plan(projeto, arrastado.clip_id, 1.0)
    assert plano is not None and len(plano.stages) == 1
    tamanho = (640, 360)
    camadas = tuple(QPixmap.fromImage(QImage.fromData(_run(c, 30, strict=True)))
                    for c in interaction_commands(plano, tamanho, tools))
    assert len(camadas) == 4 and all(not p.isNull() for p in camadas)
    previa = _Preview()
    previa.resize(*tamanho)
    previa.set_frame_pixmap(QPixmap.fromImage(QImage.fromData(
        _run(frame_command(projeto, 1, tamanho, tools, png=True), 30, strict=True))))
    previa.set_active_clip(arrastado, projeto.width, projeto.height)
    previa.set_position(1)
    previa.set_interaction_layers(camadas[:3], tuple(zip((r for r, _ in plano.stages), camadas[3:])))
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
def test_o_teste_acima_enxerga_o_desfoque_que_falta(tmp_path, monkeypatch):
    """Guarda: sem borrar a região na prévia, o mesmo quadro estoura os limites do teste acima."""
    from videomanager.presentation.qt.panels import edit_widgets
    monkeypatch.setattr(edit_widgets, "blur_region", lambda *args: None)
    medida = _medir(tmp_path, .4)
    assert sum(medida.dentro) / len(medida.dentro) > 4 or max(medida.dentro) > 60
