"""A divisão da suíte entre os jobs da CI (``VM_SHARD``) cobre tudo, sem repetir."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from conftest import fatiar, pytest_collection_modifyitems


class _Item:
    """O que ``fatiar`` lê de um item do pytest: o id e a marca ``ffmpeg``."""

    def __init__(self, nodeid: str, ffmpeg: bool = False) -> None:
        self.nodeid = nodeid
        self._ffmpeg = ffmpeg

    def get_closest_marker(self, nome: str):
        return object() if (nome == "ffmpeg" and self._ffmpeg) else None


def _suite() -> list[_Item]:
    itens = [_Item(f"tests/test_a.py::test_{i:02d}") for i in range(23)]
    itens += [_Item(f"tests/test_integration.py::TestX::test_{i:02d}", ffmpeg=True) for i in range(14)]
    itens += [_Item(f"tests/test_b.py::test_{i:02d}") for i in range(10)]
    return itens


@pytest.mark.parametrize("total", [1, 2, 3, 4, 7])
def test_as_fatias_juntas_sao_a_suite_inteira_sem_repetir(total):
    itens = _suite()
    partes = [fatiar(itens, i, total)[0] for i in range(1, total + 1)]
    ids = [item.nodeid for parte in partes for item in parte]
    assert sorted(ids) == sorted(item.nodeid for item in itens)
    assert len(ids) == len(set(ids))


def test_o_que_sobra_de_uma_fatia_e_o_resto_da_suite():
    itens = _suite()
    ficam, fora = fatiar(itens, 2, 3)
    assert {i.nodeid for i in ficam} | {i.nodeid for i in fora} == {i.nodeid for i in itens}
    assert not {i.nodeid for i in ficam} & {i.nodeid for i in fora}


def test_a_ordem_de_chegada_nao_muda_quem_fica_com_o_que():
    # Cada fatia roda numa máquina que coleta por conta própria; se a ordem de
    # coleta mudasse o resultado, um teste ficaria em duas fatias ou em nenhuma.
    itens = _suite()
    embaralhados = itens[:]
    random.Random(7).shuffle(embaralhados)
    for i in (1, 2, 3):
        assert {x.nodeid for x in fatiar(itens, i, 3)[0]} == {x.nodeid for x in fatiar(embaralhados, i, 3)[0]}


def test_as_fatias_saem_do_mesmo_tamanho_com_diferenca_de_um_no_maximo():
    tamanhos = [len(fatiar(_suite(), i, 4)[0]) for i in range(1, 5)]
    assert max(tamanhos) - min(tamanhos) <= 1


def test_testes_vizinhos_do_mesmo_arquivo_caem_em_fatias_diferentes():
    # Por arquivo, uma fatia levaria o test_integration.py inteiro.
    itens = _suite()
    dono = {x.nodeid: i for i in (1, 2, 3) for x in fatiar(itens, i, 3)[0]}
    integracao = sorted(n for n in dono if "test_integration" in n)
    assert len({dono[n] for n in integracao}) == 3
    assert all(dono[a] != dono[b] for a, b in zip(integracao, integracao[1:]))


def test_a_ordem_de_coleta_e_preservada_dentro_da_fatia():
    # A suíte tem dependência de ordem latente (um sinal tardio de um teste
    # chegava ao seguinte): a fatia só pode diferir da execução inteira pelos
    # testes que saem, nunca pela ordem dos que ficam. Aqui a lista chega fora
    # de ordem de id de propósito, e a fatia tem de sair na mesma ordem.
    itens = _suite()
    random.Random(3).shuffle(itens)
    for i in (1, 2, 3):
        ficam, _ = fatiar(itens, i, 3)
        assert ficam == [item for item in itens if item in ficam]


def _config():
    chamadas: list = []
    hook = SimpleNamespace(pytest_deselected=lambda items: chamadas.append(items))
    return SimpleNamespace(hook=hook), chamadas


def test_sem_vm_shard_a_lista_nao_muda(monkeypatch):
    monkeypatch.delenv("VM_SHARD", raising=False)
    itens = _suite()
    antes = itens[:]
    config, chamadas = _config()
    pytest_collection_modifyitems(config, itens)
    assert itens == antes and chamadas == []


def test_com_vm_shard_a_lista_vira_a_fatia_e_o_resto_e_dado_como_descartado(monkeypatch):
    monkeypatch.setenv("VM_SHARD", "2/3")
    itens = _suite()
    todos = {x.nodeid for x in itens}
    config, chamadas = _config()
    pytest_collection_modifyitems(config, itens)
    assert len(chamadas) == 1
    assert {x.nodeid for x in itens} | {x.nodeid for x in chamadas[0]} == todos
    assert not {x.nodeid for x in itens} & {x.nodeid for x in chamadas[0]}


def test_vm_shard_vazio_e_o_mesmo_que_ausente(monkeypatch):
    # O YAML pode deixar a variável em branco fora das células fatiadas.
    monkeypatch.setenv("VM_SHARD", "")
    config, chamadas = _config()
    itens = _suite()
    pytest_collection_modifyitems(config, itens)
    assert len(itens) == len(_suite()) and chamadas == []


@pytest.mark.parametrize("spec", ["0/2", "3/2", "1/0", "-1/2", "a/b", "1", "1/2/3"])
def test_vm_shard_malformado_para_a_execucao_em_vez_de_rodar_a_suite_errada(monkeypatch, spec):
    # Uma fatia mal escrita que rodasse "tudo" ou "nada" passaria verde na CI.
    monkeypatch.setenv("VM_SHARD", spec)
    with pytest.raises(pytest.UsageError):
        pytest_collection_modifyitems(_config()[0], _suite())
