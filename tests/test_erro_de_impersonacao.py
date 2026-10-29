"""O erro de "impersonação" do yt-dlp vira uma frase que se entende.

Com o ``curl_cffi`` ausente, sites que exigem a impressão digital TLS de um navegador (o Dailymotion, medido; o yt-dlp tem ~30
extratores nessa situação) respondem com um texto técnico em inglês e um link, e o usuário não sabe o que fazer.
"""

from __future__ import annotations

from yt_dlp.utils import DownloadError

from videomanager import RELEASES_URL
from videomanager.domain import i18n
from videomanager.infrastructure.yt_dlp.probe import _translate_error

CRU = ("ERROR: [dailymotion] x8gtg6n: The extractor is attempting impersonation, but none of these impersonate targets "
       "are available: firefox. See  https://github.com/yt-dlp/yt-dlp#impersonation  for information on installing the "
       "required dependencies")


def test_o_erro_cru_de_impersonacao_diz_o_que_falta_e_onde_baixar():
    erro = _translate_error(DownloadError(CRU))
    texto = str(erro)
    assert "curl_cffi" in texto and RELEASES_URL in texto
    assert "attempting impersonation" not in texto


def test_o_mesmo_erro_sai_em_ingles_na_interface_em_ingles():
    i18n.set_language(i18n.ENGLISH)
    try:
        texto = str(_translate_error(DownloadError(CRU)))
    finally:
        i18n.set_language(i18n.PORTUGUESE)
    assert "latest Video Manager" in texto and RELEASES_URL in texto


def test_o_pedido_de_login_continua_sendo_pedido_de_login():
    erro = DownloadError("ERROR: [vimeo] 76979871: The web client only works when logged-in. Use --cookies, --cookies-from-browser")
    assert "conta conectada" in str(_translate_error(erro))
