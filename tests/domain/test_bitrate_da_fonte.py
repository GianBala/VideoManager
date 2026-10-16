"""Uma regra só para "a fonte já está no bitrate pedido" (``selection.keeps_source``).

O aviso do painel, a estimativa do tamanho e o ffmpeg do download decidem a mesma coisa; se discordassem, o painel
prometeria "mantido" e o download recodificaria, ou o contrário, sem erro nenhum.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from videomanager.domain.estimator import recode_video_bytes
from videomanager.domain.estimator import video_only_kbps
from videomanager.domain.formats import Kind
from videomanager.domain.selection import SOURCE_BITRATE_TOLERANCE
from videomanager.domain.selection import keeps_source


@pytest.mark.parametrize("fonte, pedido, mantida", [
    (4000.0, 2500, False),
    (2500.0, 2500, True),    # já está no bitrate pedido
    (2550.0, 2500, True),    # dentro da folga de 2% (o ffprobe oscila uns pontos)
    (2551.0, 2500, False),
    (900.0, 2500, True),     # abaixo: recodificar só aumentaria o arquivo
    (None, 2500, False),     # bitrate desconhecido: vale o pedido
])
def test_a_fonte_no_bitrate_pedido_ou_abaixo_e_mantida(fonte, pedido, mantida):
    assert keeps_source(fonte, pedido) is mantida
    assert SOURCE_BITRATE_TOLERANCE == 1.02


@pytest.mark.parametrize("fonte", [4000.0, 2500.0, 2550.0, 2551.0, 900.0, None])
def test_a_estimativa_acompanha_a_regra(fonte):
    formato = SimpleNamespace(vbr=fonte, tbr=None, abr=None, kind=Kind.VIDEO_ONLY)
    estimado = recode_video_bytes(formato, 600.0, 2500)
    assert (estimado is None) is keeps_source(fonte, 2500)
    if estimado is not None:
        assert estimado == int(2500 * 1000 / 8 * 600.0)


def test_o_bitrate_so_do_video_tira_o_audio_do_formato_muxado():
    muxado = SimpleNamespace(vbr=None, tbr=2628.0, abr=128.0, kind=Kind.MUXED)
    assert video_only_kbps(muxado) == 2500.0
    assert video_only_kbps(SimpleNamespace(vbr=1800.0, tbr=2628.0, abr=128.0, kind=Kind.MUXED)) == 1800.0
    assert video_only_kbps(SimpleNamespace(vbr=None, tbr=None, abr=None, kind=Kind.VIDEO_ONLY)) is None
