"""Leitura tolerante das preferências (RN-24) e limites dos campos numéricos."""

from videomanager.application.preferences import Preferences, RANGES


def test_concorrencia_fora_da_faixa_volta_para_dentro_dela():
    # A tela limita de 1 a 10, mas um settings.json editado à mão com 200
    # abria 200 downloads simultâneos, cada um com seus fragmentos.
    lidas = Preferences.from_dict({"max_concurrent_jobs": 200, "concurrent_fragments": -3,
                                   "rate_limit_kbps": -1, "preview_volume": 900})
    assert lidas.max_concurrent_jobs == RANGES["max_concurrent_jobs"][1]
    assert lidas.concurrent_fragments == RANGES["concurrent_fragments"][0]
    assert lidas.rate_limit_kbps == 0
    assert lidas.preview_volume == 100


def test_valor_dentro_da_faixa_nao_muda():
    assert Preferences.from_dict({"max_concurrent_jobs": 4}).max_concurrent_jobs == 4
