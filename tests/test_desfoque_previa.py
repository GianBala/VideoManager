"""O desfoque de região na prévia e na aba Propriedades: a caixa, o arrasto e os campos.

A caixa é desenhada pela mesma conta do compositor (``Clip.region_rect``) e tem de cair em cima do
retângulo que o ffmpeg borrou; o arrasto muda largura e altura independentes, não gira e nunca deixa a
região sair do quadro; a posição anima por quadros-chave e o tamanho é um só.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtCore import QPointF
from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtGui import QPixmap

from videomanager.domain.constants import REGION_BLUR
from videomanager.domain.constants import REGION_MIN_SCALE
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import Clip
from videomanager.domain.project import MediaKind
from videomanager.domain.project import MediaRef
from videomanager.domain.project import OverlayType
from videomanager.domain.project import filter_pose
from videomanager.domain.project import pseudo_media
from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget
from videomanager.presentation.qt.panels.edit_widgets import _Preview

pytestmark = pytest.mark.usefixtures("desktop_app")

LARGURA, ALTURA = 640, 360


def _filtro(nome: str = REGION_BLUR, **extra) -> Clip:
    pose = {} if "scale_x" in extra else filter_pose(nome)
    return Clip(pseudo_media(OverlayType.FILTER, nome, 4.0), 0.0, 4.0, overlay_type="filter", filter_name=nome,
                **pose, **extra)


def _previa(clip: Clip, posicao: float = 1.0) -> _Preview:
    previa = _Preview()
    previa.resize(LARGURA, ALTURA)
    previa.set_frame_pixmap(QPixmap(LARGURA, ALTURA))
    previa.set_active_clip(clip, LARGURA, ALTURA)
    previa.set_position(posicao)
    return previa


def _evento(tipo, ponto: QPointF, botoes=Qt.MouseButton.LeftButton) -> QMouseEvent:
    return QMouseEvent(tipo, ponto, ponto, Qt.MouseButton.LeftButton, botoes, Qt.KeyboardModifier.NoModifier)


def _arrastar(previa: _Preview, de: tuple[float, float], para: tuple[float, float]) -> None:
    previa.mousePressEvent(_evento(QMouseEvent.Type.MouseButtonPress, QPointF(*de)))
    previa.mouseMoveEvent(_evento(QMouseEvent.Type.MouseMove, QPointF(*para)))
    previa.mouseReleaseEvent(_evento(QMouseEvent.Type.MouseButtonRelease, QPointF(*para), Qt.MouseButton.NoButton))


# -- geometria e acerto --------------------------------------------------------------

def test_a_caixa_e_o_retangulo_que_o_dominio_calcula():
    clip = _filtro(x=0.3, y=0.6)
    previa = _previa(clip)
    cx, cy, w, h = previa._clip_geometry(clip)
    esq, topo, largura, altura = clip.region_rect(LARGURA, ALTURA, 1.0)
    assert (cx - w / 2, cy - h / 2, w, h) == pytest.approx((esq, topo, largura, altura))


def test_so_o_filtro_com_regiao_tem_caixa_na_previa():
    for nome in ("pb", "sepia", "contraste", "vinheta", "inverter"):
        previa = _previa(_filtro(nome))
        assert previa._hit_test_clip(previa._active_clip, QPoint(LARGURA // 2, ALTURA // 2)) == (None, None)
    previa = _previa(_filtro())
    modo, _ = previa._hit_test_clip(previa._active_clip, QPoint(LARGURA // 2, ALTURA // 2))
    assert modo == "move"


def test_a_regiao_tem_alcas_de_canto_e_nenhuma_de_rotacao():
    clip = _filtro()
    previa = _previa(clip)
    cx, cy, w, h = previa._clip_geometry(clip)
    assert previa._hit_test_clip(clip, QPoint(round(cx + w / 2), round(cy + h / 2)))[0] == "scale_br"
    assert previa._hit_test_clip(clip, QPoint(round(cx - w / 2), round(cy - h / 2)))[0] == "scale_tl"
    # Onde as imagens têm a alça de rotação (24 px acima do topo) a região não tem nada.
    assert previa._hit_test_clip(clip, QPoint(round(cx), round(cy - h / 2 - 24)))[0] is None


def test_desenhar_a_caixa_da_regiao_nao_quebra():
    previa = _previa(_filtro())
    imagem = previa.grab().toImage()
    assert not imagem.isNull()


# -- arrasto --------------------------------------------------------------------------

def test_arrastar_o_corpo_move_a_regiao_e_so_ela():
    clip = _filtro()
    previa = _previa(clip)
    emitidos = []
    previa.overlay_transformed.connect(lambda *args: emitidos.append(args))
    cx, cy, w, h = previa._clip_geometry(clip)
    _arrastar(previa, (cx, cy), (cx + 100, cy + 40))
    movido = previa._active_clip
    assert movido.x == pytest.approx(0.5 + 100 / LARGURA) and movido.y == pytest.approx(0.5 + 40 / ALTURA)
    assert (movido.scale_x, movido.scale_y) == (clip.scale_x, clip.scale_y)
    assert emitidos and emitidos[-1][3] == pytest.approx(clip.scale_x)


@pytest.mark.parametrize("destino", [(5000, 5000), (-5000, -5000), (5000, -5000)])
def test_a_regiao_nunca_sai_do_quadro_no_arrasto(destino):
    clip = _filtro()
    previa = _previa(clip)
    cx, cy, _w, _h = previa._clip_geometry(clip)
    _arrastar(previa, (cx, cy), destino)
    esq, topo, w, h = previa._active_clip.region_rect(LARGURA, ALTURA, 1.0)
    assert 0 <= esq and esq + w <= LARGURA and 0 <= topo and topo + h <= ALTURA


def test_o_canto_muda_largura_e_altura_independentes_e_o_oposto_nao_sai_do_lugar():
    clip = _filtro()
    previa = _previa(clip)
    cx, cy, w, h = previa._clip_geometry(clip)
    canto = (cx + w / 2, cy + h / 2)
    _arrastar(previa, canto, (canto[0] + 60, canto[1] + 15))
    novo = previa._active_clip
    assert novo.scale_x == pytest.approx(clip.scale_x + 60 / LARGURA)
    assert novo.scale_y == pytest.approx(clip.scale_y + 15 / ALTURA)
    antes = clip.region_rect(LARGURA, ALTURA, 1.0)
    depois = novo.region_rect(LARGURA, ALTURA, 1.0)
    assert depois[:2] == pytest.approx(antes[:2], abs=2)         # o canto de cima à esquerda não andou


def test_o_tamanho_da_regiao_tem_minimo_e_nao_passa_do_quadro():
    clip = _filtro()
    previa = _previa(clip)
    cx, cy, w, h = previa._clip_geometry(clip)
    _arrastar(previa, (cx + w / 2, cy + h / 2), (cx - w / 2 - 300, cy - h / 2 - 300))   # passa pelo canto oposto
    assert (previa._active_clip.scale_x, previa._active_clip.scale_y) == pytest.approx((REGION_MIN_SCALE,) * 2)
    grande = _previa(_filtro())
    cx, cy, w, h = grande._clip_geometry(grande._active_clip)
    _arrastar(grande, (cx + w / 2, cy + h / 2), (9000, 9000))
    esq, topo, largura, altura = grande._active_clip.region_rect(LARGURA, ALTURA, 1.0)
    assert esq + largura <= LARGURA and topo + altura <= ALTURA


@pytest.mark.parametrize("sx, sy", [(1, 1), (1, -1), (-1, 1), (-1, -1)], ids=["br", "tr", "bl", "tl"])
@pytest.mark.parametrize("gesto", ["para_fora_do_quadro", "passando_do_canto_oposto"])
def test_o_canto_oposto_fica_parado_ao_sair_do_quadro_e_ao_passar_dele(sx, sy, gesto):
    """O canto pego é preso ao quadro e ao tamanho mínimo; só o oposto é que não pode andar.

    Os testes de tamanho olham a região final, que ``with_region_size`` e ``region_origin`` já prendem por conta
    própria: sem as travas do arrasto o tamanho saía igual, mas o canto parado se deslocava.
    """
    clip = _filtro()
    previa = _previa(clip)
    esq, topo, w, h = clip.region_rect(LARGURA, ALTURA, 1.0)
    fixo = (esq if sx > 0 else esq + w, topo if sy > 0 else topo + h)
    cx, cy, gw, gh = previa._clip_geometry(clip)
    pego = (cx + sx * gw / 2, cy + sy * gh / 2)
    destino = ((pego[0] + sx * 9000, pego[1] + sy * 9000) if gesto == "para_fora_do_quadro"
               else (pego[0] - sx * (gw + 300), pego[1] - sy * (gh + 300)))
    _arrastar(previa, pego, destino)
    novo = previa._active_clip
    nesq, ntopo, nw, nh = novo.region_rect(LARGURA, ALTURA, 1.0)
    assert (nesq if sx > 0 else nesq + nw) == pytest.approx(fixo[0], abs=2)
    assert (ntopo if sy > 0 else ntopo + nh) == pytest.approx(fixo[1], abs=2)
    if gesto == "para_fora_do_quadro":
        assert (nesq + nw == LARGURA) if sx > 0 else nesq == 0        # o canto pego pára na borda do quadro
        assert (ntopo + nh == ALTURA) if sy > 0 else ntopo == 0
    else:
        assert (novo.scale_x, novo.scale_y) == pytest.approx((REGION_MIN_SCALE,) * 2)


def test_com_quadros_chave_mover_edita_so_o_ponto_da_agulha_e_o_tamanho_vale_para_todos():
    clip = _filtro(keyframes=(Keyframe(0.0, x=0.3, y=0.5, scale_x=0.3, scale_y=0.3),
                              Keyframe(3.0, x=0.7, y=0.5, scale_x=0.3, scale_y=0.3)))
    previa = _previa(clip, posicao=3.0)
    cx, cy, w, h = previa._clip_geometry(clip)
    _arrastar(previa, (cx, cy), (cx - 40, cy))
    movido = previa._active_clip
    assert movido.keyframes[0].x == pytest.approx(0.3)                      # o primeiro ponto ficou onde estava
    assert movido.keyframes[1].x == pytest.approx(0.7 - 40 / LARGURA)

    previa = _previa(clip, posicao=3.0)
    cx, cy, w, h = previa._clip_geometry(clip)
    _arrastar(previa, (cx + w / 2, cy + h / 2), (cx + w / 2 + 50, cy + h / 2 + 50))
    maior = previa._active_clip
    assert [(k.scale_x, k.scale_y) for k in maior.keyframes] == [(maior.scale_x, maior.scale_y)] * 2


def test_a_rotacao_guardada_no_arquivo_nao_gira_a_caixa():
    clip = _filtro(rotation=45.0)
    previa = _previa(clip)
    cx, cy, w, h = previa._clip_geometry(clip)
    assert previa._hit_test_clip(clip, QPoint(round(cx + w / 2 - 3), round(cy + h / 2 - 3)))[0] == "scale_br"
    _arrastar(previa, (cx, cy), (cx + 30, cy))
    assert previa._active_clip.region_rect(LARGURA, ALTURA, 1.0)[0] == pytest.approx(
        clip.region_rect(LARGURA, ALTURA, 1.0)[0] + 30, abs=2)


# -- a caixa cai em cima do que o ffmpeg borrou ---------------------------------------------

@pytest.mark.ffmpeg
@pytest.mark.parametrize("projeto, quadro, widget", [
    ((320, 180), (320, 180), (320, 180)),       # a prévia no tamanho do projeto
    ((1280, 720), (320, 180), (640, 360)),      # o quadro da prévia é menor que o projeto, e o widget maior que o quadro
    ((1920, 1080), (480, 270), (400, 225)),     # e o widget menor
])
def test_a_caixa_cai_em_cima_do_retangulo_que_o_ffmpeg_borrou(tmp_path: Path, projeto, quadro, widget):
    from dataclasses import replace
    from videomanager.domain.project import Project, Track, TrackKind, media_ref
    from videomanager.infrastructure.ffmpeg.composer import frame_command
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs

    tools = find_tools()
    if tools is None:
        pytest.skip("FFmpeg não disponível")
    ruido = tmp_path / "ruido.mkv"
    subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=gray:s=320x180:r=30:d=3,noise=alls=90:allf=t+u", "-c:v", "ffv1", "-pix_fmt", "yuv420p",
                    str(ruido)], check=True, timeout=60, **subprocess_kwargs())
    filtro = replace(_filtro(x=0.62, y=0.4, scale_x=0.35, scale_y=0.25, scale=0.3), start=0.0, duration=3.0)
    video = Clip(media_ref(probe_file(ruido, tools)), 0.0, 3.0)
    com = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(filtro,), name="A"), Track(TrackKind.VIDEO, clips=(video,), name="V")),
                  width=projeto[0], height=projeto[1], fps=30.0)
    sem = replace(com, tracks=com.tracks[1:])
    largura, altura = quadro
    imagem = [subprocess.run(frame_command(p, 1.0167, quadro, tools), check=True, timeout=60, **subprocess_kwargs()).stdout
              for p in (com, sem)]
    assert len(imagem[0]) == largura * altura * 3
    diferentes = [(i // 3) for i in range(0, len(imagem[0]), 3) if imagem[0][i:i + 3] != imagem[1][i:i + 3]]
    xs, ys = [p % largura for p in diferentes], [p // largura for p in diferentes]
    caixa_ffmpeg = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)

    previa = _Preview()
    previa.resize(*widget)
    previa.set_frame_pixmap(QPixmap(largura, altura))       # o quadro que o ffmpeg entregou, no tamanho da prévia
    previa.set_active_clip(filtro, *projeto)
    previa.set_position(1.0167)
    cx, cy, w, h = previa._clip_geometry(filtro)
    k = widget[0] / largura                                  # do quadro para o widget (a proporção é a mesma)
    esperado = tuple(valor * k for valor in caixa_ffmpeg)
    assert (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2) == pytest.approx(esperado, abs=1.0)


# -- aba Propriedades ----------------------------------------------------------------------

def _propriedades(clip: Clip, agulha: float = 1.0) -> tuple[_ClipPropertiesWidget, list[dict]]:
    widget = _ClipPropertiesWidget()
    emitidos: list[dict] = []
    widget.property_changed.connect(lambda _cid, mudancas: emitidos.append(mudancas))
    widget.load_clip(clip, 1920, 1080)
    widget.set_playhead_position(agulha)
    return widget, emitidos


def test_a_regiao_mostra_posicao_e_tamanho_mas_nao_rotacao_nem_opacidade():
    widget, _ = _propriedades(_filtro())
    assert not widget._transform_group.isHidden() and not widget._animation_group.isHidden()
    # Os controles pelo nome, e não a lista ``_region_hidden``: lida pelo teste, uma lista esvaziada por um defeito
    # passaria por "todos escondidos". ``isVisibleTo`` e não ``isVisible``: a janela não está na tela.
    for nome in ("_slider_opacity", "_spin_opacity", "_slider_rot", "_spin_rot", "_rotation_presets_box"):
        assert not getattr(widget, nome).isVisibleTo(widget), nome
    for nome in ("_spin_x", "_spin_y", "_spin_w", "_spin_h"):
        assert getattr(widget, nome).isVisibleTo(widget), nome
    assert widget._spin_x.value() == 960 and widget._spin_w.value() == round(1920 * 0.3)
    chaves = [widget._combo_presets.itemData(i) for i in range(widget._combo_presets.count())]
    assert chaves == ["", "clear"]                       # girar, surgir e deslizar não valem para um recorte


def test_depois_da_regiao_um_bloco_comum_volta_a_ter_rotacao_e_opacidade():
    widget, _ = _propriedades(_filtro())
    imagem = Clip(MediaRef(Path("a.png"), MediaKind.IMAGE, width=100, height=100), 0.0, 4.0, overlay_type="image")
    widget.load_clip(imagem, 1920, 1080)
    assert not any(w.isHidden() for w in widget._region_hidden)


def test_os_outros_filtros_continuam_sem_pose():
    widget, _ = _propriedades(_filtro("sepia"))
    assert widget._transform_group.isHidden() and widget._animation_group.isHidden()


def test_a_regiao_nao_tem_trava_de_proporcao_e_o_que_o_usuario_escolheu_volta_depois():
    widget, _ = _propriedades(_filtro())
    assert widget._chk_lock_ratio.isHidden() and not widget._chk_lock_ratio.isChecked()
    imagem = Clip(MediaRef(Path("a.png"), MediaKind.IMAGE, width=100, height=100), 0.0, 4.0, overlay_type="image")
    widget.load_clip(imagem, 1920, 1080)
    assert not widget._chk_lock_ratio.isHidden() and widget._chk_lock_ratio.isChecked()      # o padrão de antes
    widget._chk_lock_ratio.setChecked(False)                                                 # uma escolha do usuário
    widget.load_clip(_filtro(), 1920, 1080)
    widget.load_clip(imagem, 1920, 1080)
    assert not widget._chk_lock_ratio.isChecked()


def test_largura_e_altura_se_editam_sem_travar_a_proporcao_e_nao_passam_do_quadro():
    widget, emitidos = _propriedades(_filtro())
    widget._spin_w.setValue(1920 * 2)
    ultimo = emitidos[-1]
    assert ultimo["scale_x"] == pytest.approx(1.0) and ultimo["scale_y"] == pytest.approx(0.3)
    assert ultimo["x"] == pytest.approx(0.5)                                  # ocupa a largura toda: só cabe no centro


def test_um_x_perto_da_borda_nao_deixa_a_regiao_sair():
    widget, emitidos = _propriedades(_filtro())
    widget._spin_x.setValue(1920)                                             # centro na borda direita
    assert emitidos[-1]["x"] == pytest.approx(1 - 0.3 / 2)


def test_o_tamanho_editado_vale_para_todos_os_quadros_chave_e_a_posicao_so_para_o_da_agulha():
    clip = _filtro(keyframes=(Keyframe(0.0, x=0.3, y=0.5, scale_x=0.3, scale_y=0.3),
                              Keyframe(3.0, x=0.7, y=0.5, scale_x=0.3, scale_y=0.3)))
    widget, emitidos = _propriedades(clip, agulha=3.0)
    widget._spin_x.setValue(round(0.6 * 1920))
    assert [k.x for k in emitidos[-1]["keyframes"]] == [pytest.approx(0.3), pytest.approx(0.6)]
    widget._spin_h.setValue(round(1080 * 0.5))
    assert [(k.scale_x, k.scale_y) for k in emitidos[-1]["keyframes"]] == [(pytest.approx(0.3), pytest.approx(0.5))] * 2


@pytest.mark.ffmpeg
def test_desfoque_abaixo_do_bloco_arrastado_aparece_nas_camadas_como_no_quadro_final(tmp_path: Path):
    """As camadas do gesto são compostas em base transparente; o desfoque que cai numa delas tem de parecer o final.

    O vídeo de baixo cobre só o meio da tela, então parte da região cai numa área transparente da camada:
    ali o quadro final tem o vídeo borrado sobre preto, e a camada não pode inventar outra coisa.
    """
    from dataclasses import replace
    from PySide6.QtGui import QColor, QImage
    from videomanager.application.media.interaction import interaction_plan
    from videomanager.domain.project import Project, Track, TrackKind
    from videomanager.infrastructure.ffmpeg.composer import frame_command, interaction_commands
    from videomanager.infrastructure.ffmpeg.preview import _run
    from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs

    tools = find_tools()
    if tools is None:
        pytest.skip("FFmpeg não disponível")
    fonte = tmp_path / "fonte.png"
    subprocess.run([tools.ffmpeg_str, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=5",
                    "-frames:v", "1", str(fonte)], check=True, timeout=30, **subprocess_kwargs())
    imagem = QImage(40, 40, QImage.Format.Format_RGBA8888)
    imagem.fill(QColor("red"))
    assert imagem.save(str(tmp_path / "vermelho.png"))
    chao = Clip(MediaRef(fonte, MediaKind.IMAGE, width=160, height=90), 0.0, 5.0, scale_x=.5, scale_y=.5)
    arrastado = Clip(MediaRef(tmp_path / "vermelho.png", MediaKind.IMAGE, width=40, height=40), 0.0, 5.0,
                     scale_x=.2, scale_y=.2)
    projeto = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(arrastado,), name="Cima"),
                              Track(TrackKind.ADDITIONAL, clips=(_filtro(x=0.3, y=0.5, scale_x=0.3, scale_y=0.3, scale=0.3),), name="Meio"),
                              Track(TrackKind.VIDEO, clips=(chao,), name="Vídeo")), width=320, height=180)
    plano = interaction_plan(projeto, arrastado.clip_id, 1)
    assert plano is not None                       # o desfoque está abaixo do bloco arrastado: entra na camada de baixo
    tamanho = (640, 360)
    camadas = tuple(QPixmap.fromImage(QImage.fromData(_run(c, 30, strict=True)))
                    for c in interaction_commands(plano, tamanho, tools))
    previa = _Preview()
    previa.resize(*tamanho)
    previa.set_frame_pixmap(QPixmap.fromImage(QImage.fromData(
        _run(frame_command(projeto, 1, tamanho, tools, png=True), 30, strict=True))))
    previa.set_active_clip(arrastado, projeto.width, projeto.height)
    previa.set_position(1)
    previa.set_interaction_layers(camadas)
    previa.set_active_clip(replace(arrastado, x=.85), projeto.width, projeto.height)
    assert previa.begin_interaction()
    atual = previa.grab().toImage()
    esperado = QImage.fromData(_run(frame_command(projeto.with_updated_clip(arrastado.clip_id, x=.85), 1, tamanho, tools,
                                                  png=True), 30, strict=True))
    # Dentro da região (x de 96 a 288 e y de 126 a 234 no quadro de 640×360), dos dois lados da borda do vídeo (x = 160).
    for x in range(110, 280, 30):
        for y in (140, 170, 200):
            a, b = atual.pixelColor(x, y), esperado.pixelColor(x, y)
            assert max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue())) <= 8, \
                (x, y, a.getRgb(), b.getRgb())


# -- pelo painel inteiro ---------------------------------------------------------------------

def _regiao_do_painel(painel):
    return next(c for t in painel._project.additional_tracks for c in t.clips if c.overlay_type is OverlayType.FILTER)


def test_arrastar_a_regiao_no_painel_atualiza_o_projeto_e_o_desfazer_a_devolve(painel_de_edicao):
    painel = painel_de_edicao
    painel._insert_filter_clip(REGION_BLUR)
    bloco = _regiao_do_painel(painel)
    previa = painel._preview
    previa.resize(640, 360)
    painel._update_preview_overlay_clips()
    assert bloco.clip_id in [c.clip_id for c in previa._selectable_clips]      # dá para clicar nela na prévia
    antes = painel._project
    cx, cy, w, h = previa._clip_geometry(previa._active_clip)
    _arrastar(previa, (cx, cy), (cx + 80, cy + 30))
    movido = _regiao_do_painel(painel)
    assert movido.x > 0.5 and movido.y > 0.5 and (movido.scale_x, movido.scale_y) == (bloco.scale_x, bloco.scale_y)
    painel._undo_edit()
    assert painel._project == antes


def test_editar_um_campo_da_regiao_no_painel_prende_dentro_do_quadro(painel_de_edicao):
    painel = painel_de_edicao
    painel._insert_filter_clip(REGION_BLUR)
    bloco = _regiao_do_painel(painel)
    painel._properties_widget.load_clip(bloco, painel._project.width, painel._project.height, fps=painel._project.fps)
    painel._properties_widget._spin_x.setValue(painel._project.width)              # centro na borda direita
    editado = _regiao_do_painel(painel)
    assert editado.x == pytest.approx(1 - bloco.scale_x / 2)



# -- encaixe: a imagem e a região usam o mesmo ``_snap_axis`` ---------------------------------

def test_o_encaixe_cobre_as_duas_bordas_o_centro_e_o_limiar_de_14_px():
    from videomanager.presentation.qt.panels.edit_widgets import _snap_axis
    baixo, alto, meio, metade = 0.0, 640.0, 320.0, 50.0
    assert _snap_axis(metade + 5, metade, baixo, alto, meio) == (metade, baixo)              # borda esquerda
    assert _snap_axis(alto - metade - 5, metade, baixo, alto, meio) == (alto - metade, alto)  # borda direita
    assert _snap_axis(meio + 7, metade, baixo, alto, meio) == (meio, meio)                   # centro
    assert _snap_axis(metade + 12, metade, baixo, alto, meio)[1] == baixo                    # 12 px: ainda encaixa
    assert _snap_axis(metade + 15, metade, baixo, alto, meio) == (metade + 15, None)         # 15 px: já não
    assert _snap_axis(meio + 20, metade, baixo, alto, meio) == (meio + 20, None)
    # O que está mais perto ganha: a 4 px da borda esquerda e a 12 px do centro, é a borda.
    assert _snap_axis(metade + 4, metade, baixo, alto, meio)[1] == baixo


def _arrastar_vendo_a_guia(previa: _Preview, de: tuple[float, float], para: tuple[float, float]):
    """Arrasta e devolve as guias de encaixe **durante** o gesto: soltar o mouse as apaga."""
    previa.mousePressEvent(_evento(QMouseEvent.Type.MouseButtonPress, QPointF(*de)))
    previa.mouseMoveEvent(_evento(QMouseEvent.Type.MouseMove, QPointF(*para)))
    guias = previa._snap_guide_x, previa._snap_guide_y
    previa.mouseReleaseEvent(_evento(QMouseEvent.Type.MouseButtonRelease, QPointF(*para), Qt.MouseButton.NoButton))
    return guias


def _imagem_na_previa(x: float = 0.5, y: float = 0.5) -> tuple[_Preview, Clip]:
    imagem = Clip(MediaRef(Path("a.png"), MediaKind.IMAGE, width=100, height=100), 0.0, 4.0, overlay_type="image",
                  x=x, y=y, scale=0.3, scale_x=0.3, scale_y=0.3)
    return _previa(imagem), imagem


@pytest.mark.parametrize("quem", ["regiao", "imagem"])
@pytest.mark.parametrize("onde, eixo, guia", [
    ("borda_direita", "x", LARGURA), ("borda_inferior", "y", ALTURA), ("centro_x", "x", LARGURA / 2),
    ("centro_y", "y", ALTURA / 2), ("borda_esquerda", "x", 0), ("borda_superior", "y", 0)])
def test_arrastar_para_perto_encaixa_a_regiao_e_a_imagem_do_mesmo_jeito(quem, onde, eixo, guia):
    """Cinco pixels antes da borda (ou do centro), os dois blocos encaixam e mostram a guia; a imagem já era assim."""
    previa, clip = _previa(_filtro()), None
    if quem == "imagem":
        previa, clip = _imagem_na_previa()
    clip = previa._active_clip
    cx, cy, w, h = previa._clip_geometry(clip)
    meio, extensao = (cx, w) if eixo == "x" else (cy, h)
    total = LARGURA if eixo == "x" else ALTURA
    # Posição do centro que deixa o bloco a 5 px do ponto de encaixe.
    alvo = {"borda_direita": total - extensao / 2 - 5, "borda_inferior": total - extensao / 2 - 5,
            "centro_x": total / 2 + 5, "centro_y": total / 2 + 5,
            "borda_esquerda": extensao / 2 + 5, "borda_superior": extensao / 2 + 5}[onde]
    d = alvo - meio
    # O centro da imagem é o ``QRect.center()`` do quadro (inteiro: 319 e 179 em 640×360) e o da região o meio exato; as
    # duas posições finais não podem mudar (``_snap_axis``), e é isto que este teste prende.
    ajuste = -1 if quem == "imagem" and onde.startswith("centro") else 0
    guias = _arrastar_vendo_a_guia(previa, (cx, cy), (cx + d, cy) if eixo == "x" else (cx, cy + d))
    visto = guias[0] if eixo == "x" else guias[1]
    assert visto == pytest.approx(guia + ajuste)
    novo = previa._active_clip
    centro = novo.x * LARGURA if eixo == "x" else novo.y * ALTURA
    esperado = {"borda_direita": total - extensao / 2, "borda_inferior": total - extensao / 2,
                "centro_x": total / 2, "centro_y": total / 2,
                "borda_esquerda": extensao / 2, "borda_superior": extensao / 2}[onde]
    assert centro == pytest.approx(esperado + ajuste, abs=0.01)


@pytest.mark.parametrize("quem", ["regiao", "imagem"])
def test_longe_dos_pontos_de_encaixe_nao_ha_guia(quem):
    previa, _ = _imagem_na_previa() if quem == "imagem" else (_previa(_filtro()), None)
    cx, cy, _w, _h = previa._clip_geometry(previa._active_clip)
    assert _arrastar_vendo_a_guia(previa, (cx, cy), (cx + 40, cy + 30)) == (None, None)
