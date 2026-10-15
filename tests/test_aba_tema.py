"""A aba Tema das configurações: o modo e a paleta, escolhidos juntos e gravados só ao confirmar.

O diálogo devolve as novas preferências sem alterar as antigas (``result_settings``): cancelar não
pode mexer em nada. A preferência ``palette`` é validada na leitura, como o idioma, porque um
arquivo editado à mão ou gravado por uma versão futura não pode deixar o aplicativo sem cores.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest
from PySide6.QtWidgets import QTabWidget

from videomanager.application.preferences import Preferences
from videomanager.bootstrap import build_desktop_runtime
from videomanager.domain.appearance import DEFAULT_PALETTE, PALETTES
from videomanager.infrastructure.storage.settings import Settings
from videomanager.presentation.qt import strings
from videomanager.presentation.qt.settings_dialog import SettingsDialog


class _SemFerramentas:
    """Runtime sem ffmpeg: o diálogo de configurações não sonda a placa."""

    def __init__(self, runtime):
        self._runtime = runtime

    def __getattr__(self, nome):
        return getattr(self._runtime, nome)

    def find_tools(self):
        return None


@pytest.fixture
def abrir(desktop_app):
    abertos = []

    def _abrir(**preferencias):
        dialogo = SettingsDialog(Settings(**preferencias), runtime=_SemFerramentas(build_desktop_runtime(audio_enabled=False)))
        abertos.append(dialogo)
        return dialogo

    yield _abrir
    for dialogo in abertos:
        dialogo.deleteLater()


def _abas(dialogo) -> QTabWidget:
    return dialogo.findChild(QTabWidget)


def test_a_aba_tema_e_a_segunda_e_leva_o_modo(abrir):
    dialogo = abrir()
    abas = _abas(dialogo)
    assert [abas.tabText(i) for i in range(abas.count())][:2] == [strings.SETTINGS_TAB_GENERAL, strings.SETTINGS_TAB_THEME]
    assert abas.widget(1).isAncestorOf(dialogo._theme)
    assert not abas.widget(0).isAncestorOf(dialogo._theme)


def test_seis_cartoes_na_ordem_com_o_da_preferencia_marcado(abrir):
    dialogo = abrir(palette="aurora")
    cartoes = list(dialogo._palette_picker._cartoes.values())
    assert [c.nome for c in cartoes] == list(PALETTES)
    assert [c.nome for c in cartoes if c.isChecked()] == ["aurora"]
    assert [c.accessibleName() for c in cartoes] == [strings.PALETTE_NAMES[n] for n in PALETTES]


def test_escolher_um_cartao_muda_a_paleta_devolvida_e_so_ela(abrir):
    dialogo = abrir(palette="atual", theme="dark")
    avisos = []
    dialogo._palette_picker.changed.connect(avisos.append)
    dialogo._palette_picker._cartoes["cinema"].click()
    novo = dialogo.result_settings()
    assert novo.palette == "cinema" and novo.theme == "dark"
    assert avisos == ["cinema"]
    assert [c.isChecked() for c in dialogo._palette_picker._cartoes.values()].count(True) == 1


def test_cancelar_nao_altera_as_preferencias_de_origem(abrir):
    dialogo = abrir(palette="atual")
    dialogo._palette_picker._cartoes["mare"].click()
    dialogo._theme.setCurrentIndex(dialogo._theme.findData("light"))
    dialogo.result_settings()
    assert dialogo._settings.palette == "atual" and dialogo._settings.theme == "dark"


def test_o_modo_repinta_as_miniaturas(abrir):
    dialogo = abrir(theme="dark")
    miniatura = dialogo._palette_picker._cartoes["grafite"].miniatura
    assert miniatura._modo == "dark"
    dialogo._theme.setCurrentIndex(dialogo._theme.findData("light"))
    assert all(c.miniatura._modo == "light" for c in dialogo._palette_picker._cartoes.values())
    assert dialogo.result_settings().theme == "light"


def test_os_cartoes_tem_altura_que_cabe_miniatura_nome_e_linha(abrir):
    dialogo = abrir()
    dialogo.show()
    for cartao in dialogo._palette_picker._cartoes.values():
        assert cartao.sizeHint().height() >= cartao.miniatura.height() + 30


# ---------------------------------------------------------------- a preferência em disco
def test_palette_tem_padrao_grafite_e_vai_para_o_arquivo():
    # A paleta do protótipo é a de quem abre o aplicativo pela primeira vez; "Atual" segue na aba Tema, para quem prefere as
    # cores de antes da renovação.
    assert Preferences().palette == DEFAULT_PALETTE == "grafite"
    assert asdict(Preferences(palette="estudio"))["palette"] == "estudio"


def test_arquivo_sem_a_chave_abre_na_paleta_padrao():
    # Quem atualiza o aplicativo tem um settings.json sem ``palette`` e recebe a aparência renovada, na paleta do protótipo; as
    # cores de antes estão em Configurações → Tema → Atual.
    assert Preferences.from_dict({"theme": "light"}).palette == "grafite"


@pytest.mark.parametrize("nome", PALETTES)
def test_toda_paleta_do_dominio_e_aceita_na_leitura(nome):
    assert Preferences.from_dict({"palette": nome}).palette == nome


@pytest.mark.parametrize("valor", ["nao-existe", "", 3, None, ["aurora"]])
def test_paleta_desconhecida_ou_de_tipo_errado_volta_ao_padrao(valor):
    assert Preferences.from_dict({"palette": valor}).palette == "grafite"


def test_versao_antiga_ignora_a_chave_nova_sem_quebrar():
    # O inverso do caso acima: uma versão que não conhece ``palette`` lê o arquivo sem erro,
    # porque ``from_dict`` ignora chaves desconhecidas.
    class Antiga(Preferences):
        pass

    campos = {"theme": "dark", "palette": "aurora", "chave_do_futuro": 1}
    assert Antiga.from_dict(campos).theme == "dark"


def test_o_editor_nasce_na_paleta_das_preferencias(desktop_app):
    from videomanager.bootstrap import build_editor_service, build_processing_service
    from videomanager.presentation.qt.panels.edit_panel import EditPanel
    from videomanager.presentation.qt.theme import palette
    painel = EditPanel(Settings(palette="aurora"), ensure_tools=lambda: None, editor=build_editor_service(),
                       processing=build_processing_service(), runtime=build_desktop_runtime())
    try:
        assert painel._colors == palette("dark", "aurora")
    finally:
        painel.shutdown()
