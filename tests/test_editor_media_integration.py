"""Mídias sintéticas do plano: classificação, orientação e saída efetiva."""
import subprocess

import pytest

from videomanager.domain.project import MediaKind, media_ref, new_project
from videomanager.domain.composition import Composition
from videomanager.infrastructure.ffmpeg.converter import Converter, probe_file
from videomanager.infrastructure.ffmpeg.composer import frame_command
from videomanager.infrastructure.ffmpeg.preview import frame_from_command
from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs

pytestmark = pytest.mark.ffmpeg


@pytest.fixture
def tools():
    found = find_tools()
    if found is None:
        pytest.skip('FFmpeg não disponível')
    return found


def run(tools, *args):
    subprocess.run([tools.ffmpeg_str, '-nostdin', '-v', 'error', '-y', *map(str, args)],
                   check=True, timeout=30, **subprocess_kwargs())


@pytest.mark.parametrize('sound', [False, True])
def test_avi_mjpeg_temporal_real(tools, tmp_path, sound):
    path = tmp_path / 'camera.avi'
    args = ['-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=25:d=1']
    if sound:
        args += ['-f', 'lavfi', '-i', 'sine=duration=1', '-c:a', 'pcm_s16le']
    run(tools, *args, '-c:v', 'mjpeg', '-threads', '1', path)
    local = probe_file(path, tools)
    ref = media_ref(local)
    assert ref.kind is MediaKind.VIDEO and ref.has_audio == sound
    assert ref.duration == pytest.approx(1, abs=.04)


@pytest.mark.parametrize('angle', [-90, 90, 180])
def test_rotacao_probe_e_composicao_aplicam_uma_vez(tools, tmp_path, angle):
    source, rotated = tmp_path / 'source.mp4', tmp_path / 'rotated.mp4'
    run(tools, '-f', 'lavfi', '-i', 'color=c=red:s=160x120:r=25:d=1', '-c:v', 'libx264', source)
    run(tools, '-display_rotation', angle, '-i', source, '-c', 'copy', rotated)
    local = probe_file(rotated, tools)
    ref = media_ref(local)
    size = (120, 160) if abs(angle) == 90 else (160, 120)
    assert (local.video.width, local.video.height) == (160, 120)
    assert (ref.width, ref.height) == size
    project = new_project(ref)
    frame = frame_from_command(frame_command(project, .2, size, tools), size)
    assert frame is not None and frame.is_complete
    # Quatro regiões perto dos cantos detectam rotação dupla/letterbox indevido.
    data = frame.data
    for x, y in [(10, 10), (size[0]-11, 10), (10, size[1]-11), (size[0]-11, size[1]-11)]:
        pixel = data[(y*size[0]+x)*3:(y*size[0]+x)*3+3]
        assert pixel[0] > 220 and pixel[1] < 25 and pixel[2] < 25


def test_exportacao_exata_preserva_velocidade_e_opacidade(tools, tmp_path):
    source = tmp_path / 'source.mp4'
    run(tools, '-f', 'lavfi', '-i', 'color=c=red:s=160x120:r=25:d=2', '-c:v', 'libx264', source)
    local = probe_file(source, tools)
    project = new_project(media_ref(local))
    clip = project.clips[0]
    project = project.with_updated_clip(clip.clip_id, speed=2, duration=1, opacity=.5)
    destination = tmp_path / 'saida.mp4'
    Converter(local, Composition(project), destination, tools).run()
    result = probe_file(destination, tools)
    assert result.duration == pytest.approx(1, abs=.05)
    size = (160, 120)
    frame = frame_from_command(frame_command(new_project(media_ref(result)), .4, size, tools), size)
    assert frame is not None and frame.is_complete
    assert 105 <= frame.data[(60*160+80)*3] <= 145


def test_opacidade_de_99_porcento_nao_e_descartada(tools, tmp_path):
    source = tmp_path / 'white.mp4'
    run(tools, '-f', 'lavfi', '-i', 'color=c=white:s=160x120:r=20:d=1', '-c:v', 'libx264', source)
    project = new_project(media_ref(probe_file(source, tools)))
    project = project.with_updated_clip(project.clips[0].clip_id, opacity=.99)
    frame = frame_from_command(frame_command(project, .5, (160, 120), tools), (160, 120))
    assert frame
    assert 250 <= frame.data[(60*160+80)*3] <= 253


def test_quadros_de_animacao_antes_e_depois_do_split_sao_iguais(tools, tmp_path):
    from videomanager.domain.keyframe import Keyframe
    source = tmp_path / 'animated.mp4'
    run(tools, '-f', 'lavfi', '-i', 'color=c=red:s=160x120:r=25:d=10', '-c:v', 'libx264', source)
    project = new_project(media_ref(probe_file(source, tools)))
    clip = project.clips[0]
    project = project.with_updated_clip(clip.clip_id, scale=.4, scale_x=.4, scale_y=.4, keyframes=(
        Keyframe(0, x=.2, scale_x=.4, scale_y=.4),
        Keyframe(10, x=.8, scale_x=.4, scale_y=.4, easing='ease_in')))
    divided = project.split(clip.clip_id, 5)
    for t in (2.5, 5, 7.5):
        a = frame_from_command(frame_command(project, t, (160, 120), tools), (160, 120))
        b = frame_from_command(frame_command(divided, t, (160, 120), tools), (160, 120))
        assert a and b and a.is_complete and b.is_complete
        assert a.data == b.data


def test_video_superior_preserva_fundo_nas_barras(tools, tmp_path):
    from videomanager.domain.project import Clip, Project, Track, TrackKind
    blue, red = tmp_path / 'blue.mp4', tmp_path / 'red.mp4'
    run(tools, '-f', 'lavfi', '-i', 'color=c=blue:s=160x120:r=25:d=2', '-c:v', 'libx264', blue)
    run(tools, '-f', 'lavfi', '-i', 'color=c=red:s=80x120:r=25:d=2', '-c:v', 'libx264', red)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(media_ref(probe_file(red, tools)), 0, 2),)),
                              Track(TrackKind.VIDEO, clips=(Clip(media_ref(probe_file(blue, tools)), 0, 2),))),
                      width=160, height=120, fps=25)
    frame = frame_from_command(frame_command(project, .4, (160, 120), tools), (160, 120))
    assert frame and frame.is_complete
    assert frame.data[(60*160+5)*3+2] > 220


def test_filtros_consecutivos_nao_aplicam_duas_vezes_na_fronteira(tools, tmp_path):
    from pathlib import Path
    from videomanager.domain.project import Clip, Project, Track, TrackKind, MediaRef
    from videomanager.infrastructure.ffmpeg.composer import playback_command
    source = tmp_path / 'red.mp4'
    run(tools, '-f', 'lavfi', '-i', 'color=c=red:s=160x120:r=25:d=2', '-c:v', 'libx264', source)
    video = Clip(media_ref(probe_file(source, tools)), 0, 2)
    media = MediaRef(Path('Filtro_inverter'), MediaKind.IMAGE)
    project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(
        Clip(media, 0, 1, overlay_type='filter', filter_name='inverter'),
        Clip(media, 1, 1, overlay_type='filter', filter_name='inverter'))), Track(TrackKind.VIDEO, clips=(video,))),
        width=160, height=120, fps=25)
    result = subprocess.run(playback_command(project, 0, (160, 120), tools, fps=25),
                            timeout=30, check=True, **subprocess_kwargs())
    pixel = result.stdout[(25*160*120+60*160+80)*3:][:3]
    assert len(pixel) == 3 and pixel[0] < 25 and pixel[1] > 220 and pixel[2] > 220


def test_transicao_preserva_opacidade_animacao_e_alfa_exterior(tools, tmp_path):
    from pathlib import Path
    from videomanager.domain.keyframe import Keyframe
    from videomanager.domain.project import Clip, Project, Track, TrackKind, MediaRef
    blue, red = tmp_path / 'blue.mp4', tmp_path / 'red.mp4'
    run(tools, '-f', 'lavfi', '-i', 'color=c=blue:s=160x120:r=25:d=4', '-c:v', 'libx264', blue)
    run(tools, '-f', 'lavfi', '-i', 'color=c=red:s=160x120:r=25:d=4', '-c:v', 'libx264', red)
    ref = media_ref(probe_file(red, tools))
    keys = (Keyframe(0, x=.25, scale_x=.4, scale_y=.4, opacity=.5),
            Keyframe(2, x=.75, scale_x=.4, scale_y=.4, opacity=.5))
    left = Clip(ref, 0, 2, keyframes=keys)
    right = Clip(ref, 2, 2, in_point=2, keyframes=keys)
    marker = Clip(MediaRef(Path('Transição'), MediaKind.IMAGE), 1.5, 1, overlay_type='transition',
                  transition_name='fade', transition_left_id=left.clip_id, transition_right_id=right.clip_id)
    bg = Clip(media_ref(probe_file(blue, tools)), 0, 4)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(left, marker, right)),
                              Track(TrackKind.VIDEO, clips=(bg,))), width=160, height=120, fps=25)
    frame = frame_from_command(frame_command(project, 1.6, (160, 120), tools), (160, 120))
    assert frame and frame.is_complete
    # Exterior transparente preserva o azul; a pose animada fica à direita.
    exterior = frame.data[(10*160+10)*3:][:3]
    pose = frame.data[(60*160+105)*3:][:3]
    assert exterior[2] > 220 and exterior[0] < 25
    assert 70 < pose[0] < 155 and pose[2] > 90


@pytest.mark.parametrize('transition', ['fade', 'dissolve', 'wipeleft', 'wiperight', 'slideleft', 'slideright', 'fade_black', 'fade_white'])
def test_transicoes_em_camadas_com_adicional_e_filtro(tools, tmp_path, transition):
    from pathlib import Path
    from videomanager.domain.project import Clip, Project, Track, TrackKind, MediaRef
    red, logo = tmp_path / 'red.mp4', tmp_path / 'logo.png'
    run(tools, '-f', 'lavfi', '-i', 'color=c=red:s=160x120:r=25:d=4', '-c:v', 'libx264', red)
    run(tools, '-f', 'lavfi', '-i', 'color=c=white:s=32x32', '-frames:v', '1', logo)
    ref = media_ref(probe_file(red, tools))
    def video_track(name):
        left, right = Clip(ref, 0, 2), Clip(ref, 2, 2, in_point=2)
        marker = Clip(MediaRef(Path('Transição'), MediaKind.IMAGE), 1.5, 1, overlay_type='transition',
                      transition_name=name, transition_left_id=left.clip_id, transition_right_id=right.clip_id,
                      transition_affects_additionals=True)
        return Track(TrackKind.VIDEO, clips=(left, marker, right))
    photo = Clip(media_ref(probe_file(logo, tools)), 0, 4)
    effect = Clip(MediaRef(Path('Filtro'), MediaKind.IMAGE), 0, 4, overlay_type='filter', filter_name='pb')
    project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(photo,)),
                              Track(TrackKind.ADDITIONAL, clips=(effect,)),
                              video_track(transition), video_track('fade_black')),
                      width=160, height=120, fps=25)
    for t in (1.52, 2, 2.48):
        frame = frame_from_command(frame_command(project, t, (160, 120), tools), (160, 120))
        assert frame and frame.is_complete
        if transition == 'fade':
            # A transição inferior não pode escurecer nem encobrir o logo.
            center = frame.data[(60*160+80)*3:][:3]
            assert min(center) > 235


def test_filtro_na_mesma_trilha_afeta_imagem_antes_da_transicao(tools, tmp_path):
    from pathlib import Path
    from videomanager.domain.project import Clip, Project, Track, TrackKind, MediaRef
    paths = [tmp_path / name for name in ('base.mp4', 'left.png', 'right.png')]
    run(tools, '-f', 'lavfi', '-i', 'color=c=black:s=160x120:r=25:d=4', '-c:v', 'libx264', paths[0])
    for path, color in zip(paths[1:], ('blue', 'red')):
        run(tools, '-f', 'lavfi', '-i', f'color=c={color}:s=160x120', '-frames:v', '1', path)
    ref = media_ref(probe_file(paths[0], tools))
    left, right = Clip(ref, 0, 2), Clip(ref, 2, 2, in_point=2)
    marker = Clip(MediaRef(Path('Transição'), MediaKind.IMAGE), 1.5, 1, overlay_type='transition',
                  transition_name='fade', transition_left_id=left.clip_id, transition_right_id=right.clip_id,
                  transition_affects_additionals=True)
    image_left = Clip(media_ref(probe_file(paths[1], tools)), 0, 2)
    effect = Clip(MediaRef(Path('Filtro'), MediaKind.IMAGE), 1, 1, overlay_type='filter', filter_name='pb')
    image_right = Clip(media_ref(probe_file(paths[2], tools)), 2, 2)
    project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(image_left, effect, image_right)),
                              Track(TrackKind.VIDEO, clips=(left, marker, right))), width=160, height=120, fps=25)
    frame = frame_from_command(frame_command(project, 2, (160, 120), tools), (160, 120))
    assert frame and frame.is_complete
    pixel = frame.data[(60*160+80)*3:][:3]
    assert 125 < pixel[0] < 155 and 5 < pixel[1] < 25 and abs(pixel[2]-pixel[1]) < 8


@pytest.mark.usefixtures('desktop_app')
@pytest.mark.parametrize('animated', [False, True])
def test_texto_preserva_composicao_ao_alternar_resolucao(tools, tmp_path, animated):
    from videomanager.domain.project import Clip, Project, Track, TrackKind
    from videomanager.domain.keyframe import Keyframe
    from videomanager.infrastructure.qt.text import QtTextRasterizer
    from videomanager.infrastructure.storage.project_json import save_project, load_project
    from pathlib import Path
    from videomanager.domain.project import MediaRef
    clip = Clip(MediaRef(Path("Texto"), MediaKind.IMAGE), 0, 2, overlay_type='text', text_content='Teste', font_size=18, stroke_width=2,
                x=.5, y=.4, keyframes=(Keyframe(0, scale_x=.7, scale_y=.7),
                                      Keyframe(2, scale_x=1.3, scale_y=1.3)) if animated else ())
    project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(clip,)),), width=320, height=180)
    raster = QtTextRasterizer()
    assets = {clip.clip_id: raster.render(clip)}
    resized = project.with_output_canvas(640, 360)
    assert resized.clips == project.clips
    restored = resized.with_output_canvas(320, 180)
    assert restored == project
    path = tmp_path / 'texto.vmp'
    save_project(resized, path)
    reopened, _ = load_project(path)
    for p in (project, resized, reopened, restored):
        frame = frame_from_command(frame_command(p, .5, (320, 180), tools, text_assets=assets), (320, 180))
        assert frame is not None
        if p is project:
            expected = frame.data
        else:
            assert frame.data == expected


@pytest.mark.parametrize('transition', ['fade', 'dissolve', 'wipeleft', 'wiperight', 'slideleft', 'slideright'])
@pytest.mark.parametrize('effect_name', ['contraste', 'inverter', 'pb'])
def test_filtro_continuo_com_imagem_translucida_e_passagem_nao_muda_resultado(tools, tmp_path, transition, effect_name):
    from videomanager.domain.project import Clip, Project, Track, TrackKind, MediaRef
    base, photo = tmp_path / 'base.mp4', tmp_path / 'photo.png'
    run(tools, '-f', 'lavfi', '-i', 'color=c=gray:s=160x120:r=25:d=4', '-c:v', 'libx264', base)
    run(tools, '-f', 'lavfi', '-i', 'color=c=red:s=160x120', '-frames:v', '1', photo)
    ref = media_ref(probe_file(base, tools))
    left, right = Clip(ref, 0, 2), Clip(ref, 2, 2, in_point=2)
    marker = Clip(MediaRef(tmp_path / 'Tr', MediaKind.IMAGE), 1.5, 1, overlay_type='transition',
                  transition_name=transition, transition_left_id=left.clip_id, transition_right_id=right.clip_id,
                  transition_affects_additionals=True)
    photo_clip = Clip(media_ref(probe_file(photo, tools)), 0, 4, opacity=.5)
    effect = Clip(MediaRef(tmp_path / 'F', MediaKind.IMAGE), .1, 3.9, overlay_type='filter', filter_name=effect_name)
    p = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(photo_clip, effect)),
                        Track(TrackKind.VIDEO, clips=(left, marker, right))), width=160, height=120, fps=25)
    control = p.with_updated_clip(marker.clip_id, transition_affects_additionals=False)
    actual = frame_from_command(frame_command(p, 2, (160, 120), tools), (160, 120))
    expected = frame_from_command(frame_command(control, 2, (160, 120), tools), (160, 120))
    assert actual and expected
    assert max(abs(a-b) for a,b in zip(actual.data, expected.data)) <= 3


def test_fade_mistura_cores_proporcionalmente_ao_alfa_de_cada_lado(tools, tmp_path):
    from videomanager.domain.project import Clip, Project, Track, TrackKind, MediaRef
    refs = []
    for color in ('red', 'blue', 'lime'):
        path = tmp_path / f'{color}.mp4'
        run(tools, '-f', 'lavfi', '-i', f'color=c={color}:s=160x120:r=20:d=4', '-c:v', 'libx264', path)
        refs.append(media_ref(probe_file(path, tools)))
    left, right = Clip(refs[0], 0, 2, opacity=.5), Clip(refs[1], 2, 2)
    marker = Clip(MediaRef(tmp_path / 'Tr', MediaKind.IMAGE), 1.5, 1, overlay_type='transition',
                  transition_name='fade', transition_left_id=left.clip_id, transition_right_id=right.clip_id)
    project = Project(tracks=(Track(TrackKind.VIDEO, clips=(left, marker, right)),
                              Track(TrackKind.VIDEO, clips=(Clip(refs[2], 0, 4),))),
                      width=160, height=120, fps=20)
    frame = frame_from_command(frame_command(project, 2, (160, 120), tools), (160, 120))
    assert frame
    pixel = frame.data[(60*160+80)*3:][:3]
    # Metade de cada lado: 25% vermelho, 50% azul, 25% do fundo verde.
    assert tuple(pixel) == pytest.approx((64, 64, 128), abs=5)


def test_arbitragem_de_transicoes_e_por_item_sem_apagar_alca_de_outro(tools, tmp_path):
    from videomanager.domain.project import Clip, Project, Track, TrackKind, MediaRef
    base, photo = tmp_path / 'base.mp4', tmp_path / 'photo.png'
    run(tools, '-f', 'lavfi', '-i', 'color=c=black:s=160x120:r=20:d=4', '-c:v', 'libx264', base)
    run(tools, '-f', 'lavfi', '-i', 'color=c=red:s=160x120', '-frames:v', '1', photo)
    ref = media_ref(probe_file(base, tools))
    def track(cut, duration):
        left, right = Clip(ref, 0, cut), Clip(ref, cut, 4-cut, in_point=cut)
        marker = Clip(MediaRef(tmp_path / 'Tr', MediaKind.IMAGE), cut-duration/2, duration,
                      overlay_type='transition', transition_name='fade', transition_left_id=left.clip_id,
                      transition_right_id=right.clip_id, transition_affects_additionals=True)
        return Track(TrackKind.VIDEO, clips=(left, marker, right)), marker
    upper, upper_marker = track(2.5, .5)
    lower, _ = track(2, 1)
    outgoing = Clip(media_ref(probe_file(photo, tools)), 0, 2)
    continuous = Clip(outgoing.media, 0, 4, scale_x=.1, scale_y=.1, scale=.1, x=.9, y=.1)
    project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(outgoing, continuous)), upper, lower),
                      width=160, height=120, fps=20)
    control = project.with_updated_clip(upper_marker.clip_id, transition_affects_additionals=False)
    frames = [frame_from_command(frame_command(p, 2.3, (160, 120), tools), (160, 120)) for p in (project, control)]
    assert all(frames)
    pixels = [f.data[(60*160+80)*3:][:3] for f in frames]
    assert pixels[1][0] > 30
    assert tuple(pixels[0]) == pytest.approx(tuple(pixels[1]), abs=3)


def test_interpolacao_em_camera_lenta_cria_quadros_reais(tools, tmp_path):
    source = tmp_path / 'motion.mp4'
    run(tools, '-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=30:d=1', '-c:v', 'libx264', source)
    local = probe_file(source, tools)
    project = new_project(media_ref(local))
    project = project.with_updated_clip(project.clips[0].clip_id, speed=.5, duration=2)
    counts = []
    for interpolate in (False, True):
        output = tmp_path / f'export-{interpolate}.mp4'
        Converter(local, Composition(project, interpolate=interpolate), output, tools).run()
        result = probe_file(output, tools)
        assert result.duration == pytest.approx(2, abs=1/30)
        assert result.video.fps == pytest.approx(30)
        decoded = subprocess.run([tools.ffmpeg_str, '-v', 'error', '-i', str(output),
                                  '-vf', 'mpdecimate', '-f', 'framemd5', '-'],
                                 timeout=30, check=True, **subprocess_kwargs()).stdout
        counts.append(len([line for line in decoded.splitlines() if line and not line.startswith(b'#')]))
    assert counts[0] <= 31
    assert counts[1] >= 48


def test_fade_de_filtro_parcial_recebe_imagem_translucida_ja_composta(tools, tmp_path):
    from videomanager.domain.project import Clip, Project, Track, TrackKind, MediaRef
    base, photo = tmp_path / 'base.mp4', tmp_path / 'photo.png'
    run(tools, '-f', 'lavfi', '-i', 'color=c=gray:s=160x120:r=20:d=4', '-c:v', 'libx264', base)
    run(tools, '-f', 'lavfi', '-i', 'color=c=red:s=160x120', '-frames:v', '1', photo)
    ref = media_ref(probe_file(base, tools))
    left, right = Clip(ref, 0, 2), Clip(ref, 2, 2, in_point=2)
    marker = Clip(MediaRef(tmp_path / 'Tr', MediaKind.IMAGE), 1.5, 1, overlay_type='transition',
                  transition_name='fade', transition_left_id=left.clip_id, transition_right_id=right.clip_id,
                  transition_affects_additionals=True)
    image = Clip(media_ref(probe_file(photo, tools)), 0, 4, opacity=.5)
    effect = Clip(MediaRef(tmp_path / 'F', MediaKind.IMAGE), .1, 1.9, overlay_type='filter', filter_name='contraste')
    project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(image, effect)),
                              Track(TrackKind.VIDEO, clips=(left, marker, right))), width=160, height=120, fps=20)
    unfiltered = project.without_clip(effect.clip_id).with_updated_clip(marker.clip_id, transition_affects_additionals=False)
    filtered = project.with_updated_clip(effect.clip_id, duration=3.9).with_updated_clip(marker.clip_id, transition_affects_additionals=False)
    frames = [frame_from_command(frame_command(p, 2, (160, 120), tools), (160, 120))
              for p in (project, unfiltered, filtered)]
    assert all(frames)
    a, b, c = [f.data[(60*160+80)*3:][:3] for f in frames]
    assert tuple(a) == pytest.approx(tuple((x+y)/2 for x,y in zip(b,c)), abs=4)


@pytest.mark.parametrize('transition', ['slideleft', 'slideright'])
@pytest.mark.parametrize('moment', [1.6, 1.85, 2, 2.2, 2.4])
def test_slide_de_filtro_parcial_nao_desloca_fundo_uma_segunda_vez(tools, tmp_path, transition, moment):
    from videomanager.domain.project import Clip, Project, Track, TrackKind, MediaRef
    base, photo = tmp_path / 'base.mp4', tmp_path / 'photo.png'
    run(tools, '-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=20:d=4', '-c:v', 'libx264', base)
    run(tools, '-f', 'lavfi', '-i', 'color=c=red:s=160x120', '-frames:v', '1', photo)
    ref = media_ref(probe_file(base, tools))
    left, right = Clip(ref, 0, 2), Clip(ref, 2, 2, in_point=2)
    marker = Clip(MediaRef(tmp_path / 'Tr', MediaKind.IMAGE), 1.5, 1, overlay_type='transition',
                  transition_name=transition, transition_left_id=left.clip_id, transition_right_id=right.clip_id,
                  transition_affects_additionals=True)
    image = Clip(media_ref(probe_file(photo, tools)), 0, 4, opacity=.5)
    effect = Clip(MediaRef(tmp_path / 'F', MediaKind.IMAGE), .1, 1.9, overlay_type='filter', filter_name='contraste')
    project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(image, effect)),
                              Track(TrackKind.VIDEO, clips=(left, marker, right))), width=160, height=120, fps=20)
    unfiltered = project.without_clip(effect.clip_id).with_updated_clip(marker.clip_id, transition_affects_additionals=False)
    filtered = project.with_updated_clip(effect.clip_id, duration=3.9).with_updated_clip(marker.clip_id, transition_affects_additionals=False)
    frames = [frame_from_command(frame_command(p, moment, (160, 120), tools), (160, 120))
              for p in (project, unfiltered, filtered)]
    assert all(frames)
    for x in (20, 120):
        offset = (60*160+x)*3
        progress = moment - 1.5
        from_left = x < 160 * (1-progress) if transition == 'slideleft' else x >= 160 * progress
        expected = frames[2 if from_left else 1].data[offset:offset+3]
        assert tuple(frames[0].data[offset:offset+3]) == pytest.approx(tuple(expected), abs=4)


@pytest.mark.usefixtures('desktop_app')
def test_projeto_misto_cortado_salvo_movido_e_exportado_preserva_quadros(tools, tmp_path, monkeypatch):
    from videomanager.domain.project import Clip, Project, Track, TrackKind, MediaRef
    from videomanager.domain.keyframe import Keyframe
    from videomanager.infrastructure.qt.text import QtTextRasterizer
    from videomanager.infrastructure.storage.project_json import load_project, save_project
    folder = tmp_path / 'original'
    folder.mkdir()
    source, camera, photo = (folder / name for name in ('source.mp4', 'camera.avi', 'vertical.png'))
    run(tools, '-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=30:d=3', '-f', 'lavfi', '-i',
        'sine=duration=3', '-c:v', 'libx264', '-c:a', 'aac', source)
    run(tools, '-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=30:d=1', '-c:v', 'mjpeg', camera)
    run(tools, '-f', 'lavfi', '-i', 'color=c=blue:s=60x120', '-frames:v', '1', photo)
    local = probe_file(source, tools)
    video = Clip(media_ref(local), 0, 4, in_point=.5, speed=.5)
    text = Clip(MediaRef(folder / 'Texto', MediaKind.IMAGE), 0, 4, overlay_type='text',
                text_content='Projeto misto', font_size=12,
                keyframes=(Keyframe(0, x=.2), Keyframe(4, x=.8, easing='ease_in')))
    image = Clip(media_ref(probe_file(photo, tools)), 0, 4, opacity=.4)
    effect = Clip(MediaRef(folder / 'Filtro', MediaKind.IMAGE), 1, 3, overlay_type='filter', filter_name='contraste')
    project = Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(image, text, effect)),
                              Track(TrackKind.VIDEO, clips=(video, Clip(media_ref(probe_file(camera, tools)), 4, 1))),
                              Track(TrackKind.AUDIO)), width=160, height=120, fps=30)
    project = project.detached_audio(video.clip_id).split(video.clip_id, 2).split(text.clip_id, 2)
    halves = project.tracks[1].sorted_clips()
    marker = Clip(MediaRef(folder / 'Transição', MediaKind.IMAGE), 1.5, 1, overlay_type='transition',
                  transition_name='slideleft', transition_left_id=halves[0].clip_id,
                  transition_right_id=halves[1].clip_id, transition_affects_additionals=True)
    project = project.with_clip(1, marker)
    raster = QtTextRasterizer()
    def assets(p):
        return {c.clip_id: raster.render(c) for c in p.clips if c.overlay_type == 'text'}
    def frames(p):
        return [frame_from_command(frame_command(p, t, (160, 120), tools, text_assets=assets(p)), (160, 120))
                for t in (1.75, 2, 2.25, 4.5)]
    before = frames(project)
    assert all(before)
    save_project(project, folder / 'project.vmp')
    moved = tmp_path / 'movido'
    folder.rename(moved)
    monkeypatch.chdir(tmp_path)
    loaded, missing = load_project(moved / 'project.vmp')
    assert missing == []
    assert [c.clip_id for c in loaded.clips] == [c.clip_id for c in project.clips]
    assert [f.data for f in frames(loaded)] == [f.data for f in before]
    audio = next(c for c in loaded.clips if c.audio_only)
    assert audio.speed == .5 and audio.in_point == .5 and audio.duration == 4
    output = tmp_path / 'export.mp4'
    Converter(local, Composition(loaded), output, tools, text_assets=assets(loaded)).run()
    exported = probe_file(output, tools)
    assert exported.duration == pytest.approx(5, abs=1/30)
    assert exported.video is not None and exported.audio is not None
