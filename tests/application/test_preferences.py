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


def test_tipo_errado_volta_ao_padrao_e_chave_desconhecida_e_ignorada():
    padrao = Preferences()
    lidas = Preferences.from_dict({"max_concurrent_jobs": "4", "embed_thumbnail": 1, "theme": 5,
                                   "subtitle_langs": "pt", "chave_de_uma_versao_futura": True})
    assert lidas == padrao


def test_ida_e_volta_de_todos_os_campos():
    """Todo campo gravado volta igual. Um campo de tipo que ``from_dict`` não
    sabe ler (um ``float``, por exemplo) seria descartado em silêncio ao abrir,
    e é aqui que isso aparece."""
    from dataclasses import asdict, fields

    from videomanager.domain.i18n import LANGUAGES

    padrao = Preferences()
    valores = {}
    for campo in fields(Preferences):
        atual = getattr(padrao, campo.name)
        if campo.name == "language":
            valores[campo.name] = next(lang for lang in LANGUAGES if lang != atual)
        elif isinstance(atual, bool):
            valores[campo.name] = not atual
        elif isinstance(atual, int):
            baixo, alto = RANGES.get(campo.name, (atual + 1, atual + 1))
            valores[campo.name] = alto if atual != alto else baixo
        elif isinstance(atual, str):
            valores[campo.name] = atual + "-outro"
        elif isinstance(atual, list):
            valores[campo.name] = ["a", "b"]
        else:
            raise AssertionError(f"{campo.name}: tipo {type(atual).__name__} sem leitura em from_dict")
    gravadas = Preferences(**valores)
    assert gravadas != padrao
    assert Preferences.from_dict(asdict(gravadas)) == gravadas
