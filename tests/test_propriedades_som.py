"""A aba Propriedades por tipo de bloco: o que aparece para vídeo, áudio, imagem, texto, filtro e transição.

A espécie é do bloco, não da mídia dele. O bloco que "separar áudio" cria vem de um arquivo com
imagem e mesmo assim é áudio: decidir pela mídia mostrava, nele, o Fundo Verde (de um bloco que
não tem imagem). Nenhum desses erros levanta exceção: a seção errada simplesmente aparece.
"""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from videomanager.bootstrap import build_desktop_runtime, build_editor_service, build_processing_service
from videomanager.domain.keyframe import Keyframe
from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.panels.edit_panel import EditPanel
from videomanager.presentation.qt.panels.edit_widgets import _ClipPropertiesWidget

pytestmark = pytest.mark.usefixtures("desktop_app", "isolated_audio")


@pytest.fixture
def panel(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    instance = EditPanel(Settings(), ensure_tools=lambda: None, editor=build_editor_service(),
                         processing=build_processing_service(), runtime=build_desktop_runtime(audio_enabled=False))
    yield instance
    instance.shutdown()


def _video(audio=True) -> MediaRef:
    return MediaRef(Path("/m/video.mp4"), MediaKind.VIDEO, duration=10.0, width=1280, height=720, fps=30.0,
                    has_audio=audio, channels=2)


def _som() -> MediaRef:
    return MediaRef(Path("/m/som.mp3"), MediaKind.AUDIO, duration=10.0, has_audio=True, channels=2)


def _rotulo() -> MediaRef:
    return MediaRef(Path("Rótulo"), MediaKind.IMAGE, duration=3.0)


# Cada tipo de bloco e o que a aba tem de mostrar para ele (ver a tabela do relatório da revisão).
BLOCOS = {
    "video_com_som": lambda: Clip(_video(), 0.0, 5.0),
    "video_sem_som": lambda: Clip(_video(audio=False), 0.0, 5.0),
    "video_com_audio_separado": lambda: Clip(_video(), 0.0, 5.0, detached=True),
    "audio_separado": lambda: Clip(_video(), 0.0, 5.0, audio_only=True),
    "audio_puro": lambda: Clip(_som(), 0.0, 5.0),
    "imagem": lambda: Clip(MediaRef(Path("/m/foto.jpg"), MediaKind.IMAGE, width=800, height=600), 0.0, 5.0),
    "texto": lambda: Clip(_rotulo(), 0.0, 3.0, overlay_type="text", text_content="oi"),
    "filtro": lambda: Clip(_rotulo(), 0.0, 3.0, overlay_type="filter", filter_name="sepia"),
    "transicao": lambda: Clip(_rotulo(), 0.0, 1.0, overlay_type="transition", transition_name="fade"),
}


def _carregado(nome: str) -> _ClipPropertiesWidget:
    widget = _ClipPropertiesWidget()
    widget.load_clip(BLOCOS[nome](), 1920, 1080)
    return widget


@pytest.mark.parametrize(("nome", "fundo_verde", "desfoque"), [
    ("video_com_som", True, True),
    ("video_sem_som", True, True),
    ("video_com_audio_separado", True, True),
    ("audio_separado", False, False),      # era o defeito: a mídia tem imagem, o bloco não
    ("audio_puro", False, False),
    ("imagem", True, True),
    ("texto", False, False),
    ("filtro", False, False),
    ("transicao", False, False),
])
def test_fundo_verde_e_desfoque_so_aparecem_onde_ha_imagem(nome, fundo_verde, desfoque):
    widget = _carregado(nome)
    assert (not widget._chromakey_group.isHidden()) is fundo_verde, nome
    assert (not widget._blur_group.isHidden()) is desfoque, nome
    widget.deleteLater()


def test_propriedades_do_audio_separado_pelo_menu_nao_mostram_fundo_verde(panel):
    video = _video()
    projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(video, 0.0, 5.0),)),))
    projeto = projeto.detached_audio(projeto.clips[0].clip_id)
    separado = next(c for c in projeto.clips if c.audio_only)
    panel.install_project(projeto, None, [], {})

    indice, _ = projeto.find(separado.clip_id)
    menu = panel.build_menu("clip", indice, separado.clip_id)
    next(a for a in menu.actions() if a.text() == strings.EDIT_PROPERTIES).trigger()

    assert panel._properties_widget._chromakey_group.isHidden()
    assert panel._properties_widget._blur_group.isHidden()


# ---------------------------------------------------------------------------
# Velocidade e volume na aba: os mesmos ajustes dos botões ⚡ e 🔊 da barra
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("nome", "velocidade", "volume", "volume_ligado", "nota"), [
    ("video_com_som", True, True, True, False),
    ("video_sem_som", True, False, False, False),
    ("video_com_audio_separado", True, True, False, True),    # o som agora é do outro bloco: à vista, desligado, explicado
    ("audio_separado", True, True, True, False),
    ("audio_puro", True, True, True, False),
    ("imagem", False, False, False, False),
    ("texto", False, False, False, False),
    ("filtro", False, False, False, False),
    ("transicao", False, False, False, False),
])
def test_velocidade_e_volume_aparecem_onde_ha_relogio_de_midia_e_som(nome, velocidade, volume, volume_ligado, nota):
    widget = _carregado(nome)
    assert (not widget._speed_group.isHidden()) is velocidade, nome
    assert (not widget._volume_group.isHidden()) is volume, nome
    if volume:
        assert widget._spin_gain.isEnabled() is volume_ligado, nome
        assert (not widget._lbl_gain_detached.isHidden()) is nota, nome
    widget.deleteLater()


def test_aba_de_audio_nao_abre_vazia_e_mostra_os_valores_do_bloco():
    clip = Clip(_som(), 0.0, 5.0, speed=1.5, gain_db=-3.0)
    widget = _ClipPropertiesWidget()
    widget.load_clip(clip, 1920, 1080)
    assert not widget._speed_group.isHidden() and not widget._volume_group.isHidden()
    assert widget._spin_speed.value() == pytest.approx(1.5)
    assert widget._spin_gain.value() == pytest.approx(-3.0)
    assert widget._transform_group.isHidden() and widget._chromakey_group.isHidden()
    widget.deleteLater()


def test_campos_emitem_ao_editar_e_nao_ao_carregar():
    clip = BLOCOS["video_com_som"]()
    widget = _ClipPropertiesWidget()
    velocidades, mudancas = [], []
    widget.speed_changed.connect(lambda i, v: velocidades.append((i, v)))
    widget.property_changed.connect(lambda i, v: mudancas.append((i, v)))
    widget.load_clip(clip, 1920, 1080)
    assert not velocidades and not mudancas
    widget._spin_speed.setValue(2.0)
    widget._spin_gain.setValue(-6.0)
    assert velocidades == [(clip.clip_id, 2.0)]
    assert mudancas == [(clip.clip_id, {"gain_db": -6.0})]
    widget.deleteLater()


def _abre_propriedades(panel, *clips):
    projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=tuple(clips)),))
    panel.install_project(projeto, None, [], {})
    panel._open_properties_tab(clips[0].clip_id)
    return panel._properties_widget


def test_volume_da_aba_edita_o_bloco_atualiza_o_botao_e_desfaz_de_uma_vez(panel):
    clip = Clip(_video(), 0.0, 5.0)
    aba = _abre_propriedades(panel, clip)
    aba._spin_gain.setValue(-6.0)
    aba._spin_gain.setValue(-6.5)       # dois passos do mesmo ajuste: um desfazer só
    assert panel._project.find(clip.clip_id)[1].gain_db == pytest.approx(-6.5)
    assert "6" in panel._volume_btn.text()
    panel._end_edit_groups()
    panel._undo_edit()
    assert panel._project.find(clip.clip_id)[1].gain_db == 0.0


def test_velocidade_da_aba_reescala_a_duracao_e_os_quadros_chave(panel):
    animacao = (Keyframe(0.0, x=0.2), Keyframe(2.0, x=0.8))
    clip = Clip(_video(), 0.0, 5.0, keyframes=animacao)
    aba = _abre_propriedades(panel, clip)
    aba._spin_speed.setValue(2.0)
    depois = panel._project.find(clip.clip_id)[1]
    assert (depois.speed, depois.duration) == (pytest.approx(2.0), pytest.approx(2.5))
    assert [k.time_offset for k in depois.keyframes] == pytest.approx([0.0, 1.0])
    panel._end_edit_groups()
    panel._undo_edit()
    antes = panel._project.find(clip.clip_id)[1]
    assert (antes.speed, antes.duration) == (1.0, 5.0)


def test_velocidade_da_aba_recusada_por_colidir_avisa_uma_vez_e_o_campo_volta(panel, monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: avisos.append(args) or QMessageBox.StandardButton.Ok)
    primeiro, vizinho = Clip(_video(), 0.0, 5.0), Clip(_video(), 5.0, 5.0)
    aba = _abre_propriedades(panel, primeiro, vizinho)
    aba._spin_speed.setValue(0.5)       # dobraria a duração por cima do vizinho
    assert len(avisos) == 1
    assert panel._project.find(primeiro.clip_id)[1].speed == 1.0
    assert aba._spin_speed.value() == pytest.approx(1.0), "o campo mostra a velocidade que valeu"


def _cabe_na_coluna(panel) -> bool:
    """Sem rolar para o lado e com as abas à vista (o mesmo critério de tests/test_editor_regressions.py)."""
    barra = panel._extras_tabs.tabBar()
    return (panel._properties_widget._scroll.horizontalScrollBar().maximum() == 0
            and barra.sizeHint().width() <= barra.width())


@pytest.mark.parametrize("nome", ["audio_puro", "video_com_som", "video_com_audio_separado"])
def test_aba_com_velocidade_e_volume_cabe_na_coluna(panel, desktop_app, nome):
    clip = BLOCOS[nome]()
    panel.install_project(Project(tracks=(Track(TrackKind.VIDEO, clips=(clip,)),), width=1280, height=720), None, [], {})
    panel.resize(1880, 900)
    panel.show()
    desktop_app.processEvents()
    try:
        panel._open_properties_tab(clip.clip_id)
        desktop_app.processEvents()
        assert _cabe_na_coluna(panel), nome
    finally:
        panel.hide()


def test_titulos_dos_grupos_novos_trocam_de_idioma(desktop_app, pseudo):
    from videomanager.domain import i18n
    from videomanager.presentation.qt import i18n as idioma

    widget = _carregado("video_com_som")
    try:
        idioma.apply_language(i18n.ENGLISH)
        assert widget._speed_group.title().startswith("⟦") and widget._volume_group.title().startswith("⟦")
    finally:
        idioma.apply_language(i18n.PORTUGUESE)
        widget.deleteLater()


# ---------------------------------------------------------------------------
# Animação do volume: o mesmo painel de quadros-chave, agora também para o som
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("nome", "transformacao", "animacao"), [
    ("video_com_som", True, True),
    ("video_sem_som", True, True),
    ("video_com_audio_separado", True, True),     # a pose anima; o volume dele está desligado
    ("audio_separado", False, True),               # só o volume
    ("audio_puro", False, True),
    ("imagem", True, True),
    ("texto", True, True),
    ("filtro", False, False),
    ("transicao", False, False),
])
def test_animacao_aparece_onde_ha_o_que_animar(nome, transformacao, animacao):
    widget = _carregado(nome)
    assert (not widget._transform_group.isHidden()) is transformacao, nome
    assert (not widget._animation_group.isHidden()) is animacao, nome
    widget.deleteLater()


def _presets(widget) -> list:
    return [widget._combo_presets.itemData(i) for i in range(widget._combo_presets.count())]


def test_bloco_de_audio_so_oferece_remover_animacoes(desktop_app):
    """Os efeitos rápidos são de imagem (deslizar, girar, surgir): num bloco sem imagem sobra o de remover."""
    audio, video = _carregado("audio_puro"), _carregado("video_com_som")
    assert _presets(audio) == ["", "clear"]
    assert _presets(video) == list(strings.EDIT_ANIMATION_PRESETS)
    # O mesmo widget serve a qualquer bloco: a lista acompanha o bloco que está carregado.
    video.load_clip(BLOCOS["audio_puro"](), 1920, 1080)
    assert _presets(video) == ["", "clear"]
    video.load_clip(BLOCOS["video_com_som"](), 1920, 1080)
    assert _presets(video) == list(strings.EDIT_ANIMATION_PRESETS)
    audio.deleteLater(); video.deleteLater()


def _no_instante(nome: str, segundos: float):
    widget = _ClipPropertiesWidget()
    widget.load_clip(BLOCOS[nome](), 1920, 1080)
    widget.set_playhead_position(segundos)
    return widget


def test_volume_animado_pela_aba_em_um_bloco_de_audio():
    widget = _no_instante("audio_puro", 0.0)
    emitidos = []
    widget.property_changed.connect(lambda i, v: emitidos.append(v))
    widget._btn_kf_toggle.click()                       # ◇ no começo: a curva nasce neutra
    assert len(widget._clip.keyframes) == 1 and widget._clip.gain_at(0.0) == 0.0
    widget.set_playhead_position(2.0)
    widget._spin_gain.setValue(-12.0)                    # no instante 2,0 s: -12 dB
    clip = widget._clip
    assert len(clip.keyframes) == 2 and clip.gain_db == 0.0, "o volume do bloco não mexe: é um ponto da curva"
    assert clip.gain_at(0.0) == pytest.approx(0.0) and clip.gain_at(2.0) == pytest.approx(-12.0)
    assert emitidos[-1]["keyframes"] == clip.keyframes and emitidos[-1]["gain_db"] == 0.0
    widget.set_playhead_position(1.0)
    assert widget._spin_gain.value() == pytest.approx(-6.0), "o campo acompanha o cursor pela curva"
    widget.deleteLater()


def test_sem_quadros_chave_o_campo_volume_continua_sendo_o_do_bloco():
    widget = _no_instante("video_com_som", 1.0)
    emitidos = []
    widget.property_changed.connect(lambda i, v: emitidos.append(v))
    widget._spin_gain.setValue(-6.0)
    assert emitidos == [{"gain_db": -6.0}] and widget._clip.keyframes == ()
    widget.deleteLater()


def test_mexer_na_posicao_de_um_ponto_nao_apaga_o_volume_dele():
    widget = _no_instante("video_com_som", 0.0)
    widget._btn_kf_toggle.click()
    widget.set_playhead_position(2.0)
    widget._spin_gain.setValue(-12.0)
    widget._spin_x.setValue(round(0.9 * 1920))
    assert widget._clip.gain_at(2.0) == pytest.approx(-12.0)
    assert any(k.x == pytest.approx(0.9) and k.gain_offset_db == pytest.approx(-12.0) for k in widget._clip.keyframes)
    widget.deleteLater()


def test_editar_toda_a_animacao_desloca_o_volume_do_bloco_e_deixa_os_pontos():
    widget = _no_instante("audio_puro", 0.0)
    widget._btn_kf_toggle.click()
    widget.set_playhead_position(2.0)
    widget._spin_gain.setValue(-12.0)
    pontos = widget._clip.keyframes
    widget._whole_animation.setChecked(True)
    widget.set_playhead_position(2.0)
    widget._spin_gain.setValue(-6.0)                     # a curva toda sobe 6 dB
    assert widget._clip.keyframes == pontos
    assert widget._clip.gain_db == pytest.approx(6.0) and widget._clip.gain_at(2.0) == pytest.approx(-6.0)
    widget.deleteLater()


def test_remover_animacoes_apaga_a_curva_de_volume():
    widget = _no_instante("audio_puro", 0.0)
    widget._btn_kf_toggle.click()
    widget.set_playhead_position(2.0)
    widget._spin_gain.setValue(-12.0)
    widget._combo_presets.setCurrentIndex(_presets(widget).index("clear"))
    assert widget._clip.keyframes == () and widget._clip.gain_at(2.0) == 0.0
    widget.deleteLater()


def test_volume_da_aba_com_a_curva_chega_ao_projeto_e_desfaz_passo_a_passo(panel):
    clip = Clip(_video(), 0.0, 5.0)
    aba = _abre_propriedades(panel, clip)
    aba._btn_kf_toggle.click()
    panel._seek_to(2.0)
    aba._spin_gain.setValue(-12.0)
    no_projeto = panel._project.find(clip.clip_id)[1]
    assert len(no_projeto.keyframes) == 2
    assert no_projeto.gain_at(2.0) == pytest.approx(-12.0) and no_projeto.gain_at(0.0) == pytest.approx(0.0)
    # Mover o cursor fecha o agrupamento do desfazer (como em qualquer edição da aba): o ◇ e o ajuste de
    # volume são dois passos, e cada Ctrl+Z desfaz um.
    panel._end_edit_groups()
    panel._undo_edit()
    depois_de_um = panel._project.find(clip.clip_id)[1]
    assert len(depois_de_um.keyframes) == 1 and depois_de_um.gain_at(2.0) == pytest.approx(0.0)
    panel._undo_edit()
    assert panel._project.find(clip.clip_id)[1].keyframes == ()


def test_lista_de_efeitos_do_audio_acompanha_a_troca_de_idioma(desktop_app, pseudo):
    from videomanager.domain import i18n
    from videomanager.presentation.qt import i18n as idioma

    widget = _carregado("audio_puro")
    try:
        idioma.apply_language(i18n.ENGLISH)
        assert _presets(widget) == ["", "clear"]
        assert all(widget._combo_presets.itemText(i).startswith("⟦") for i in range(widget._combo_presets.count()))
    finally:
        idioma.apply_language(i18n.PORTUGUESE)
        widget.deleteLater()


def test_botoes_da_barra_sem_bloco_mostram_zero_sem_sinal(panel):
    """Sem bloco selecionado o volume é "0,0 dB" e a velocidade "1,0x": o sinal de "+" só aparece num bloco.
    Extrair os dois textos numa função os fazia nascer com "+0,0 dB", 4 px mais largos, e o retrato
    do comportamento (geometria do ``_clip_label``) acusou."""
    from videomanager.domain.i18n import decimal

    clip = Clip(_video(), 0.0, 5.0)
    panel.install_project(Project(tracks=(Track(TrackKind.VIDEO, clips=(clip,)),)), None, [], {})
    panel._refresh_clip_fields()
    assert panel._volume_btn.text() == f"🔊 {decimal(0.0)} dB"
    assert panel._speed_btn.text() == f"⚡ {decimal(1.0)}x"
    panel._timeline.select(clip.clip_id)
    assert panel._volume_btn.text() == f"🔊 {decimal(0.0, sign=True)} dB", "num bloco o sinal fica, como sempre"
