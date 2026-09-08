"""Contrato de propriedade e publicação de saídas no sistema de arquivos real."""
import pytest
from videomanager.domain.media import AudioTarget
from videomanager.infrastructure.storage.outputs import FileOutputStore
from videomanager.application.errors import ConversionError


@pytest.mark.parametrize('name', ['../fora', '/absoluto', 'sub/arquivo', 'sub\\arquivo', '.', '..', 'nome\0invalido'])
def test_nome_personalizado_nao_pode_escapar_da_pasta_escolhida(tmp_path, name):
    with pytest.raises(ConversionError, match='nome de arquivo'):
        FileOutputStore().reserve(tmp_path / 'origem.wav', AudioTarget(),
                                  tmp_path / 'destino', custom_stem=name)
    assert not list(tmp_path.iterdir())


def test_reservas_de_mesmo_nome_sao_distintas_e_abortaveis(tmp_path):
    outputs = FileOutputStore()
    source = tmp_path / 'origem.wav'
    one = outputs.reserve(source, AudioTarget(), tmp_path)
    two = outputs.reserve(source, AudioTarget(), tmp_path)
    assert one.path != two.path
    outputs.abort(one.path, lease=one)
    assert not one.path.exists() and two.path.exists()
    outputs.abort(two.path, lease=two)


def test_publicacao_entrega_conteudo_e_invalida_reserva(tmp_path):
    outputs = FileOutputStore()
    lease = outputs.reserve(tmp_path / 'origem.wav', AudioTarget(), tmp_path)
    temporary = tmp_path / 'render.tmp'
    temporary.write_bytes(b'arquivo final')
    outputs.commit(temporary, lease.path, lease=lease)
    outputs.abort(lease.path, lease=lease)
    assert lease.path.read_bytes() == b'arquivo final'
    assert not temporary.exists()


def test_reserva_nao_apaga_nem_sobrescreve_resultado_de_outro_dono(tmp_path):
    outputs = FileOutputStore()
    lease = outputs.reserve(tmp_path / 'origem.wav', AudioTarget(), tmp_path)
    replacement = tmp_path / 'outro.tmp'
    replacement.write_bytes(b'outro dono')
    replacement.replace(lease.path)
    outputs.abort(lease.path, lease=lease)
    temporary = tmp_path / 'render.tmp'
    temporary.write_bytes(b'novo')
    with pytest.raises(ConversionError, match='alterado'):
        outputs.commit(temporary, lease.path, lease=lease)
    assert lease.path.read_bytes() == b'outro dono'


def test_reserva_de_outro_caminho_nao_autoriza_publicacao(tmp_path):
    outputs = FileOutputStore()
    one = outputs.reserve(tmp_path / 'origem.wav', AudioTarget(), tmp_path)
    two = outputs.reserve(tmp_path / 'origem.wav', AudioTarget(), tmp_path)
    temporary = tmp_path / 'render.tmp'
    temporary.write_bytes(b'dados')
    with pytest.raises(ConversionError):
        outputs.commit(temporary, two.path, lease=one)
    assert two.path.stat().st_size == 0
