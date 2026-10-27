"""Resposta imediata e integridade visual das camadas de interação."""
from dataclasses import replace
from pathlib import Path
import subprocess

import pytest
from PySide6.QtGui import QImage, QPixmap

from videomanager.application.media.interaction import interaction_plan
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.infrastructure.ffmpeg.composer import frame_command, interaction_commands
from videomanager.infrastructure.ffmpeg.preview import _run
from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs
from videomanager.presentation.qt.panels.edit_widgets import _Preview

pytestmark = pytest.mark.usefixtures('desktop_app')


def picture(path, color, w=160, h=90):
    image = QImage(w, h, QImage.Format.Format_RGBA8888)
    image.fill(color)
    assert image.save(str(path))
    return MediaRef(path, MediaKind.IMAGE, width=w, height=h)


def scene(tmp_path):
    from PySide6.QtGui import QColor
    green = Clip(picture(tmp_path / 'green.png', QColor('lime')), 0, 5)
    red = Clip(picture(tmp_path / 'red.png', QColor('red')), 0, 5,
               scale_x=.5, scale_y=.5, opacity=.5)
    blue = Clip(picture(tmp_path / 'blue.png', QColor('blue')), 0, 5,
                scale_x=.2, scale_y=.2)
    project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(blue,)),
                              Track(TrackKind.ADDITIONAL, clips=(red,)),
                              Track(TrackKind.VIDEO, clips=(green,))), width=320, height=180)
    return project, red


def test_plano_estavel_durante_pose_mas_invalidado_por_contexto(tmp_path):
    project, clip = scene(tmp_path)
    plan = interaction_plan(project, clip.clip_id, 1)
    assert plan == interaction_plan(project.with_updated_clip(clip.clip_id, x=.2, rotation=35, opacity=.4), clip.clip_id, 1)
    assert plan != interaction_plan(project, clip.clip_id, 2)
    other = project.tracks[0].clips[0]
    assert plan != interaction_plan(project.with_updated_clip(other.clip_id, x=.1), clip.clip_id, 1)
    effect = Clip(None, 0, 5, overlay_type='filter', filter_name='inverter')
    assert interaction_plan(replace(project, tracks=(Track(TrackKind.ADDITIONAL, clips=(effect,)), *project.tracks)), clip.clip_id, 1) is None
    below = replace(project, tracks=(*project.tracks, Track(TrackKind.ADDITIONAL, clips=(effect,))))
    assert interaction_plan(below, clip.clip_id, 1) is not None


def test_bloco_com_fundo_desfocado_pede_a_imagem_do_fundo_no_gesto(tmp_path):
    """O fundo é de tela cheia e segue a opacidade: não cabe nas três camadas, tem a sua."""
    project, clip = scene(tmp_path)
    assert not interaction_plan(project, clip.clip_id, 1).blur
    ligado = project.with_updated_clip(clip.clip_id, blur_background=True)
    assert interaction_plan(ligado, clip.clip_id, 1).blur
    # Cobrindo a tela parado, o fundo não aparece, mas o gesto pode descobri-la: a imagem tem de estar pronta.
    cobrindo = ligado.with_updated_clip(clip.clip_id, scale=1., scale_x=1., scale_y=1.)
    assert interaction_plan(cobrindo, clip.clip_id, 1).blur
    # Sem efeito (chroma key), nada a preparar.
    chroma = ligado.with_updated_clip(clip.clip_id, chromakey_enabled=True, chromakey_color='#ff0000')
    assert not interaction_plan(chroma, clip.clip_id, 1).blur
    # Ligar a opção troca o plano, senão as camadas prontas de antes seriam reaproveitadas sem o fundo.
    assert interaction_plan(project, clip.clip_id, 1) != interaction_plan(ligado, clip.clip_id, 1)


def _camadas_do_arrasto(project, clip, size, tools):
    plan = interaction_plan(project, clip.clip_id, 1)
    return tuple(QPixmap.fromImage(QImage.fromData(_run(c, 30, strict=True)))
                 for c in interaction_commands(plan, size, tools))


@pytest.mark.ffmpeg
@pytest.mark.parametrize('video', [False, True])
@pytest.mark.parametrize('pose', [dict(x=.7), dict(x=.7, opacity=.6), dict(x=.7, rotation=15., opacity=.6)],
                         ids=['movido', 'movido_e_translucido', 'movido_girado_e_translucido'])
def test_gesto_com_fundo_desfocado_acompanha_o_quadro_final(tmp_path, video, pose):
    """As quatro camadas pintadas pelo Qt batem com o quadro que o ffmpeg comporia na pose do gesto.

    O fundo desfocado de um vídeo yuv420p já divergiu da foto do mesmo quadro (ver
    ``test_fundo_desfocado_caminhos``); medido, a diferença aqui é de até 3 em 255.
    """
    from PySide6.QtGui import QColor
    tools = find_tools()
    if tools is None:
        pytest.skip('FFmpeg indisponível')
    fonte = tmp_path / ('fonte.mp4' if video else 'fonte.png')
    saida = ['-c:v', 'libx264', '-pix_fmt', 'yuv420p'] if video else ['-frames:v', '1']
    subprocess.run([tools.ffmpeg_str, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=30:d=5',
                    *saida, str(fonte)], check=True, timeout=30, **subprocess_kwargs())
    media = (MediaRef(fonte, MediaKind.VIDEO, width=160, height=90, duration=5) if video
             else MediaRef(fonte, MediaKind.IMAGE, width=160, height=90))
    chao = Clip(picture(tmp_path / 'verde.png', QColor('lime')), 0, 5)
    bloco = Clip(media, 0, 5, scale_x=.5, scale_y=.5, blur_background=True)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(bloco,)), Track(TrackKind.VIDEO, clips=(chao,))),
                      width=320, height=180)
    size = (640, 360)
    camadas = _camadas_do_arrasto(project, bloco, size, tools)
    assert len(camadas) == 4 and all(not p.isNull() for p in camadas)
    preview = _Preview()
    preview.resize(*size)
    preview.set_frame_pixmap(QPixmap.fromImage(QImage.fromData(
        _run(frame_command(project, 1, size, tools, png=True), 30, strict=True))))
    preview.set_active_clip(bloco, project.width, project.height)
    preview.set_position(1)
    preview.set_interaction_layers(camadas)
    preview.set_active_clip(replace(bloco, **pose), project.width, project.height)
    assert preview.begin_interaction()
    atual = preview.grab().toImage()
    esperado = QImage.fromData(_run(frame_command(project.with_updated_clip(bloco.clip_id, **pose), 1, size, tools,
                                                  png=True), 30, strict=True))
    # À esquerda da frente (que está em x=.7): só fundo desfocado sobre a trilha de baixo, longe das alças.
    for x in range(20, 240, 40):
        for y in range(20, 350, 40):
            a, b = atual.pixelColor(x, y), esperado.pixelColor(x, y)
            assert max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue())) <= 4, \
                (video, pose, x, y, a.getRgb(), b.getRgb())


def test_camada_do_fundo_so_e_pintada_onde_o_quadro_final_a_mostraria():
    """A pose de agora decide, como em ``Clip.shows_blur_background``: com a opção sem efeito, o fundo fica de fora."""
    from PySide6.QtGui import QColor

    def solida(cor):
        imagem = QPixmap(640, 360)
        imagem.fill(QColor(cor))
        return imagem

    media = MediaRef(Path('video.mp4'), MediaKind.VIDEO, width=640, height=360, duration=5)
    camadas = (solida('black'), solida('#00000000'), solida('#00000000'), solida('white'))
    brancos = {}
    for nome, extra in (('ligado', {}), ('chroma', dict(chromakey_enabled=True))):
        preview = _Preview()
        preview.resize(640, 360)
        preview.set_frame_pixmap(solida('black'))
        # Parado cobre a tela; o gesto o leva para a direita e a esquerda fica descoberta.
        parado = Clip(media, 0, 5, blur_background=True, **extra)
        preview.set_active_clip(parado, 640, 360)
        preview.set_position(1)
        preview.set_interaction_layers(camadas)
        preview.set_active_clip(replace(parado, x=.8), 640, 360)
        assert preview.begin_interaction()
        brancos[nome] = preview.grab().toImage().pixelColor(30, 180).red()
    assert brancos['ligado'] > 200, 'o fundo devia aparecer na faixa descoberta'
    assert brancos['chroma'] < 50, 'com chroma key a opção não tem efeito e o fundo não pode ser pintado'


@pytest.mark.ffmpeg
@pytest.mark.parametrize('video', [False, True])
def test_gesto_preserva_fundo_alfa_e_objeto_superior(tmp_path, video):
    tools = find_tools()
    if tools is None:
        pytest.skip('FFmpeg indisponível')
    project, clip = scene(tmp_path)
    if video:
        source = tmp_path / 'red.mp4'
        subprocess.run([tools.ffmpeg_str, '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=red:s=160x90:r=30:d=5', '-c:v', 'libx264', str(source)],
                       check=True, timeout=30, **subprocess_kwargs())
        clip = replace(clip, media=MediaRef(source, MediaKind.VIDEO, width=160, height=90, duration=5))
        project = replace(project, tracks=(project.tracks[0], replace(project.tracks[1], clips=(clip,)), project.tracks[2]))
    size = (640, 360)
    plan = interaction_plan(project, clip.clip_id, 1)
    images = [QPixmap.fromImage(QImage.fromData(_run(c, 30, strict=True)))
              for c in interaction_commands(plan, size, tools)]
    assert all(not p.isNull() for p in images)
    assert images[2].toImage().pixelColor(0, 0).alpha() == 0
    preview = _Preview()
    preview.resize(*size)
    initial = QPixmap.fromImage(QImage.fromData(_run(frame_command(project, 1, size, tools, png=True), 30, strict=True)))
    preview.set_frame_pixmap(initial)
    preview.set_active_clip(clip, project.width, project.height)
    preview.set_position(1)
    preview.set_interaction_layers(tuple(images))
    moved = replace(clip, x=.7)
    preview.set_active_clip(moved, project.width, project.height)
    assert preview.begin_interaction()
    actual = preview.grab().toImage()
    updated = project.with_updated_clip(clip.clip_id, x=.7)
    expected = QImage.fromData(_run(frame_command(updated, 1, size, tools, png=True), 30, strict=True))
    # Interior do canvas, fora das alças: fundo descoberto, frente e alfa móvel.
    for x, y in [(280, 180), (320, 180), (460, 185), (380, 200), (70, 80)]:
        a, b = actual.pixelColor(x, y), expected.pixelColor(x, y)
        assert max(abs(a.red()-b.red()), abs(a.green()-b.green()), abs(a.blue()-b.blue())) <= 4, (video, x, y, a.getRgb(), b.getRgb())
    # Um resultado definitivo substitui o feedback; não há cópia antiga sobreposta.
    preview.set_frame_pixmap(QPixmap.fromImage(expected))
    assert not preview._interaction_visible


def mouse(preview, kind, x, y):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y),
                        Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    if kind == QEvent.Type.MouseButtonPress:
        preview.mousePressEvent(event)
    else:
        preview.mouseMoveEvent(event)


def test_rotacao_interativa_preserva_voltas_e_cruzamento_de_180_graus():
    from PySide6.QtCore import QEvent
    from videomanager.domain.keyframe import Keyframe
    import math
    preview = _Preview(); preview.resize(640, 360); preview.set_frame_pixmap(QPixmap(640, 360))
    clip = Clip(MediaRef(Path('video.mp4'), MediaKind.VIDEO, width=640, height=360), 0, 5,
                scale_x=.3, scale_y=.3, rotation=720,
                keyframes=(Keyframe(0, rotation=720, scale_x=.3, scale_y=.3), Keyframe(4, rotation=1080)))
    preview.set_active_clip(clip, 640, 360); preview.set_snap_enabled(False)
    cx, cy, w, h = preview._clip_geometry(clip)
    radius = h/2+24
    mouse(preview, QEvent.Type.MouseButtonPress, cx, cy-radius)
    assert preview._drag_mode == 'rotate'
    for angle in (-30, 30, 90, 150, 179, -179, -150):
        mouse(preview, QEvent.Type.MouseMove, cx+radius*math.cos(math.radians(angle)),
              cy+radius*math.sin(math.radians(angle)))
    assert preview._active_clip.transform_at(0).rotation == pytest.approx(1020, abs=2)
    assert preview._active_clip.keyframes[-1].rotation == 1080


@pytest.mark.parametrize('large', [False, True])
def test_alca_proporcional_nao_deforma_ao_atingir_limite(large):
    from PySide6.QtCore import QEvent
    preview = _Preview(); preview.resize(640, 360); preview.set_frame_pixmap(QPixmap(640, 360))
    clip = Clip(MediaRef(Path('video.mp4'), MediaKind.VIDEO, width=640, height=360), 0, 5,
                scale_x=.4, scale_y=.2)
    preview.set_active_clip(clip, 640, 360); preview.set_snap_enabled(False)
    cx, cy, w, h = preview._clip_geometry(clip)
    mouse(preview, QEvent.Type.MouseButtonPress, cx+w/2, cy+h/2)
    assert preview._drag_mode == 'scale_br'
    opposite = (cx-w/2, cy-h/2)
    factor = 100 if large else .001
    mouse(preview, QEvent.Type.MouseMove, opposite[0]+w*factor, opposite[1]+h*factor)
    transformed = preview._active_clip
    assert transformed.scale_x / transformed.scale_y == pytest.approx(2)
    assert transformed.scale_x == pytest.approx(10 if large else .1)
    assert transformed.scale_y == pytest.approx(5 if large else .05)


@pytest.mark.ffmpeg
@pytest.mark.parametrize('kind', ['text', 'chroma'])
def test_textura_isolada_preserva_texto_e_chroma(tmp_path, kind):
    from PySide6.QtGui import QColor
    from videomanager.bootstrap import build_editor_service
    tools = find_tools()
    if tools is None:
        pytest.skip('FFmpeg indisponível')
    project, clip = scene(tmp_path)
    if kind == 'text':
        clip = replace(clip, overlay_type='text', text_content='Movimento', font_size=22,
                       scale_x=1, scale_y=1, stroke_width=2)
    else:
        # Chroma aplicado à mídia isolada mantém a transparência ao mover.
        clip = replace(clip, chromakey_enabled=True, chromakey_color='#ff0000')
    project = replace(project, tracks=(project.tracks[0], replace(project.tracks[1], clips=(clip,)), project.tracks[2]))
    service = build_editor_service()
    assets = service.text_assets(project)
    plan = interaction_plan(project, clip.clip_id, 1)
    images = [QImage.fromData(_run(c, 30, strict=True))
              for c in interaction_commands(plan, (640, 360), tools, text_assets=assets)]
    assert all(not im.isNull() for im in images)
    texture = images[1]
    if kind == 'chroma':
        assert texture.pixelColor(texture.width()//2, texture.height()//2).alpha() < 5
    else:
        assert texture.pixelColor(0, 0).alpha() == 0
        assert any(texture.pixelColor(x, y).alpha() > 200
                   for y in range(texture.height()) for x in range(texture.width()))
    # Frente não passa a ter fundo preto opaco quando contém outra camada.
    assert images[2].pixelColor(0, 0) == QColor(0, 0, 0, 0)


# --- aba Propriedades ---------------------------------------------------------------

def _png(color: str) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor
    image = QImage(32, 18, QImage.Format.Format_RGBA8888)
    image.fill(QColor(color))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    buffer.close()
    return bytes(data.data())


@pytest.fixture
def pose_panel(isolated_audio, monkeypatch, tmp_path):
    """Painel com imagem selecionada sobre vídeo, workers falsos e camadas prontas."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMessageBox

    from videomanager.application.capabilities import FFmpegTools
    from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
    from videomanager.domain.preview import RawFrame
    from videomanager.infrastructure.qt.workers.signals import PreviewSignals
    from videomanager.infrastructure.storage.settings import Settings
    from videomanager.presentation.qt.panels.edit_panel import EditPanel

    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: QMessageBox.StandardButton.Ok)
    tools = FFmpegTools(Path('/usr/bin/ffmpeg'), Path('/usr/bin/ffprobe'), 'teste')
    runtime = build_desktop_runtime(audio_enabled=False)
    calls = SimpleNamespace(frames=[], interaction=[], playback=[])

    def fake(kind):
        def factory(*args, **kwargs):
            worker = SimpleNamespace(args=args, kwargs=kwargs, signals=PreviewSignals(), cancelled=[])
            worker.cancel = lambda: worker.cancelled.append(True)
            worker.start_playback = lambda: None
            getattr(calls, kind).append(worker)
            return worker
        return factory

    monkeypatch.setattr(runtime, 'frame_worker', fake('frames'))
    monkeypatch.setattr(runtime, 'interaction_worker', fake('interaction'))
    monkeypatch.setattr(runtime, 'playback_worker', fake('playback'))
    panel = EditPanel(Settings(), ensure_tools=lambda: tools, editor=build_editor_service(),
                      processing=build_processing_service(), runtime=runtime)
    for runner in (panel._runner, panel._scrub_runner, panel._background):
        monkeypatch.setattr(runner, 'start', lambda *args: None)
    panel._scrub_fill_timer.timeout.disconnect()
    video = MediaRef(Path('/m/fundo.mp4'), MediaKind.VIDEO, duration=10, width=320, height=180, fps=30)
    photo = MediaRef(tmp_path / 'foto.png', MediaKind.IMAGE, width=64, height=64)
    item = Clip(photo, 0, 5, x=.3, scale=.3, scale_x=.3, scale_y=.3)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(item,)),
                              Track(TrackKind.VIDEO, clips=(Clip(video, 0, 10),))),
                      width=320, height=180, fps=30)
    panel.install_project(project, None, [], {})
    panel._timeline.set_position(1.0)
    panel._open_properties_tab(item.clip_id)

    def deliver(worker, seconds=1.0):
        size = panel._preview_size()
        worker.signals.frame.emit(worker.args[4], RawFrame(b'\x10' * (size[0] * size[1] * 3), *size, seconds))
        worker.signals.done.emit()

    while panel._frame_busy:  # o quadro atual chega e prepara as camadas do item
        deliver(calls.frames[-1])
    layers = calls.interaction[-1]
    layers.signals.frame.emit(layers.args[3], (_png('lime'), _png('red'), _png('#00000000')))
    layers.signals.done.emit()
    assert panel._preview._interaction_layers is not None, 'camadas do item deviam estar prontas'
    yield panel, calls, item, deliver
    panel.shutdown()


def _keys(panel, field: str, key, times: int = 1) -> None:
    from PySide6.QtTest import QTest
    spin = getattr(panel._properties_widget, field)
    for _ in range(times):
        QTest.keyClick(spin, key)


@pytest.mark.parametrize('field', ['_spin_x', '_spin_scale', '_spin_rot', '_spin_opacity'])
def test_pose_pela_aba_propriedades_aparece_na_hora(pose_panel, field):
    """Mudar a pose pela aba redesenha a prévia na hora, como arrastar o objeto.

    Antes, cada tecla pedia um quadro inteiro ao ffmpeg e a imagem ficava
    atrás do número digitado — medido: cerca de 20 px atrás durante as teclas
    e 180 ms até alcançar a última.
    """
    from PySide6.QtCore import Qt
    panel, calls, item, _ = pose_panel
    before = len(calls.frames)
    key = Qt.Key.Key_Down if field == '_spin_opacity' else Qt.Key.Key_PageUp
    _keys(panel, field, key, times=3)
    edited = panel._project.find(item.clip_id)[1]
    assert edited != item, 'as teclas precisam editar o bloco'
    assert panel._preview._active_clip == edited
    assert panel._preview._interaction_visible, 'a pose nova não foi desenhada na hora'
    assert len(calls.frames) == before, 'cada tecla compôs um quadro inteiro'
    # A mão parou: um só quadro composto, da versão final.
    panel._pose_settle_timer.timeout.emit()
    assert len(calls.frames) == before + 1
    assert calls.frames[-1].args[0] == panel._project


def test_quadro_composto_antes_da_pose_nova_nao_volta_o_objeto(pose_panel):
    """Um quadro em andamento quando a pose muda é de uma pose anterior.

    Mostrado, ele voltaria o objeto para trás até o definitivo chegar — tanto
    durante as teclas quanto depois de a mão parar, se ainda estiver na fila.
    """
    from PySide6.QtCore import Qt
    from videomanager.domain.preview import RawFrame
    panel, calls, item, deliver = pose_panel
    panel._request_frame(force=True)
    stale = calls.frames[-1]  # em andamento quando a primeira tecla chega
    size = panel._preview_size()
    old = RawFrame(b' ' * (size[0] * size[1] * 3), *size, 1.0)
    _keys(panel, '_spin_x', Qt.Key.Key_PageUp, times=2)
    stale.signals.frame.emit(stale.args[4], old)
    assert panel._preview._interaction_visible, 'quadro da pose anterior cobriu a pose nova'
    panel._pose_settle_timer.timeout.emit()  # a mão parou com o quadro antigo ainda na fila
    stale.signals.frame.emit(stale.args[4], old)
    assert panel._preview._interaction_visible, 'quadro da pose anterior cobriu a pose nova'
    stale.signals.done.emit()
    final = calls.frames[-1]
    assert final is not stale and final.args[0] == panel._project
    deliver(final)
    assert not panel._preview._interaction_visible, 'o quadro definitivo substitui as camadas'


def test_propriedade_fora_da_pose_continua_composta_pelo_ffmpeg(pose_panel):
    """Chroma muda os pixels do objeto: as camadas não servem e o quadro é composto."""
    panel, calls, item, _ = pose_panel
    before = len(calls.frames)
    panel._properties_widget._chk_chroma.click()
    assert panel._project.find(item.clip_id)[1].chromakey_enabled
    assert len(calls.frames) == before + 1
    assert not panel._preview._interaction_visible


def test_fundo_desfocado_ligado_pela_aba_entrega_a_quarta_camada_a_previa(pose_panel):
    """Ligar a opção refaz as camadas do gesto, e a imagem do fundo chega à prévia."""
    panel, calls, item, deliver = pose_panel
    antes = len(calls.interaction)
    panel._properties_widget._chk_blur.click()
    assert panel._project.find(item.clip_id)[1].blur_background
    while panel._frame_busy:
        deliver(calls.frames[-1])
    assert len(calls.interaction) == antes + 1, 'ligar o fundo não refez as camadas do gesto'
    worker = calls.interaction[-1]
    assert worker.args[0].blur
    worker.signals.frame.emit(worker.args[3], (_png('lime'), _png('red'), _png('#00000000'), _png('blue')))
    worker.signals.done.emit()
    assert len(panel._preview._interaction_layers) == 4


def test_camadas_do_gesto_so_valem_com_a_contagem_do_plano(pose_panel):
    """Com fundo são quatro imagens; sem, três. Outra contagem não é do plano e não se instala.

    Três imagens para um plano com fundo deixariam a faixa descoberta mostrando
    a trilha de baixo (o defeito que a quarta imagem resolve), sem erro nenhum.
    """
    panel, calls, item, deliver = pose_panel
    panel._properties_widget._chk_blur.click()
    while panel._frame_busy:
        deliver(calls.frames[-1])
    com_fundo = calls.interaction[-1]
    assert com_fundo.args[0].blur
    com_fundo.signals.frame.emit(com_fundo.args[3], (_png('lime'), _png('red'), _png('#00000000')))
    assert panel._preview._interaction_layers is None, 'três imagens para um plano com fundo foram instaladas'
    com_fundo.signals.frame.emit(com_fundo.args[3], (_png('lime'), _png('red'), _png('#00000000'), _png('blue')))
    assert len(panel._preview._interaction_layers) == 4, 'a recusa anterior não pode travar a entrega certa'
    com_fundo.signals.done.emit()

    panel._properties_widget._chk_blur.click()
    while panel._frame_busy:
        deliver(calls.frames[-1])
    sem_fundo = calls.interaction[-1]
    assert not sem_fundo.args[0].blur and sem_fundo is not com_fundo
    sem_fundo.signals.frame.emit(sem_fundo.args[3], (_png('lime'), _png('red'), _png('#00000000'), _png('blue')))
    assert panel._preview._interaction_layers is None, 'quatro imagens para um plano sem fundo foram instaladas'
    sem_fundo.signals.frame.emit(sem_fundo.args[3], (_png('lime'), _png('red'), _png('#00000000')))
    assert len(panel._preview._interaction_layers) == 3


def _com_desfoque_acima(panel, deliver, calls):
    """Põe um desfoque de região acima do item selecionado e devolve o worker das camadas que isso pede."""
    from videomanager.domain.constants import REGION_BLUR
    from videomanager.domain.project import OverlayType, pseudo_media
    desfoque = Clip(pseudo_media(OverlayType.FILTER, REGION_BLUR, 10.0), 0, 10, overlay_type='filter',
                    filter_name=REGION_BLUR, x=.4, y=.5, scale=.3, scale_x=.3, scale_y=.3)
    panel._apply(replace(panel._project, tracks=(Track(TrackKind.ADDITIONAL, clips=(desfoque,)),
                                                 *panel._project.tracks)))
    while panel._frame_busy:
        deliver(calls.frames[-1])
    return desfoque, calls.interaction[-1]


def test_desfoque_acima_do_item_pede_uma_imagem_a_mais_e_a_previa_a_recebe_com_a_regiao(pose_panel):
    """Com um desfoque acima do item, o plano tem um trecho e a imagem dele chega à prévia junto da região."""
    panel, calls, item, deliver = pose_panel
    desfoque, worker = _com_desfoque_acima(panel, deliver, calls)
    plano = worker.args[0]
    assert [r.clip_id for r, _ in plano.stages] == [desfoque.clip_id]
    worker.signals.frame.emit(worker.args[3], (_png('lime'), _png('red'), _png('#00000000'), _png('#00000000')))
    worker.signals.done.emit()
    assert len(panel._preview._interaction_layers) == 3
    assert [r.clip_id for r, _ in panel._preview._interaction_stages] == [desfoque.clip_id]
    assert not panel._preview._interaction_stages[0][1].isNull()


def test_camadas_com_desfoque_acima_so_valem_com_a_contagem_do_plano(pose_panel):
    """Sem a imagem do trecho depois do desfoque, o desfoque sairia sem o que o cobre: não se instala."""
    panel, calls, item, deliver = pose_panel
    _, worker = _com_desfoque_acima(panel, deliver, calls)
    worker.signals.frame.emit(worker.args[3], (_png('lime'), _png('red'), _png('#00000000')))
    assert panel._preview._interaction_layers is None, 'três imagens para um plano com desfoque foram instaladas'
    worker.signals.frame.emit(worker.args[3], (_png('lime'), _png('red'), _png('#00000000'), _png('#00000000'),
                                               _png('#00000000')))
    assert panel._preview._interaction_layers is None, 'imagem a mais para um plano com um desfoque foi instalada'
    worker.signals.frame.emit(worker.args[3], (_png('lime'), _png('red'), _png('#00000000'), _png('#00000000')))
    assert panel._preview._interaction_layers is not None, 'a recusa anterior não pode travar a entrega certa'


def test_pose_com_desfoque_acima_aparece_na_hora_sem_pedir_quadro_ao_ffmpeg(pose_panel):
    """Era o caminho lento: um render inteiro por tecla ou movimento. Com as camadas prontas, a pose é desenhada na hora."""
    from PySide6.QtCore import Qt
    panel, calls, item, deliver = pose_panel
    _, worker = _com_desfoque_acima(panel, deliver, calls)
    worker.signals.frame.emit(worker.args[3], (_png('lime'), _png('red'), _png('#00000000'), _png('#00000000')))
    worker.signals.done.emit()
    antes = len(calls.frames)
    _keys(panel, '_spin_x', Qt.Key.Key_PageUp, times=3)
    assert panel._project.find(item.clip_id)[1] != item
    assert panel._preview._interaction_visible, 'a pose nova não foi desenhada na hora'
    assert len(calls.frames) == antes, 'cada tecla compôs um quadro inteiro'
