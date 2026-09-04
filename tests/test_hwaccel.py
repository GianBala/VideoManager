"""Testes da escolha de encoder por placa de vídeo.

A sondagem é substituída aqui: o que se testa é a **decisão**, não o ffmpeg. O
que precisa valer é que a escolha do usuário nunca chegue à gravação sem passar
por um teste real, e que uma placa que não abre vire software em vez de tarefa
falhada — foi assim que se descobriu que esta máquina lista ``h264_nvenc`` e
falha ao abri-lo (driver mais antigo que a build).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from videomanager.core import hwaccel
from videomanager.core.binaries import FFmpegTools

TOOLS = FFmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"), "teste")


@pytest.fixture(autouse=True)
def sondagens_limpas():
    """As sondagens são guardadas no módulo; cada teste começa do zero."""
    hwaccel.forget_probes()
    yield
    hwaccel.forget_probes()


def fingir(**resultados: bool) -> None:
    """Responde as sondagens sem abrir processo nenhum."""
    for kind, ok in resultados.items():
        for family in ("h264", "hevc"):
            encoder = hwaccel._HARDWARE[family].get(kind)
            if encoder is not None:
                hwaccel._probed[encoder.name] = ok


class TestEscolha:
    def test_padrao_e_software(self) -> None:
        # O x264 comprime melhor no mesmo tamanho de arquivo, e esta é a aba de
        # um editor que promete preservar o material.
        assert hwaccel.resolve("h264", hwaccel.SOFTWARE, TOOLS).name == "libx264"

    def test_placa_pedida_e_usada_quando_abre(self) -> None:
        fingir(nvenc=True)
        assert hwaccel.resolve("h264", "nvenc", TOOLS).name == "h264_nvenc"

    def test_placa_que_nao_abre_cai_para_software(self) -> None:
        # Uma exportação que não acontece é pior que uma exportação mais lenta.
        fingir(nvenc=False)
        assert hwaccel.resolve("h264", "nvenc", TOOLS).name == "libx264"

    def test_automatico_pega_a_primeira_que_responde(self) -> None:
        fingir(nvenc=False, qsv=True, amf=False, vaapi=True)
        assert hwaccel.resolve("h264", hwaccel.AUTO, TOOLS).name == "h264_qsv"

    def test_automatico_sem_nenhuma_placa(self) -> None:
        fingir(nvenc=False, qsv=False, amf=False, vaapi=False)
        assert hwaccel.resolve("h264", hwaccel.AUTO, TOOLS).name == "libx264"

    def test_sem_ffmpeg_localizado_nao_sonda_nada(self) -> None:
        assert hwaccel.resolve("h264", "nvenc", None).name == "libx264"

    def test_familia_sem_equivalente_em_placa(self) -> None:
        # VP9 e AV1 por hardware são raros nas builds comuns; pedir placa ali
        # não pode virar um encoder inexistente.
        fingir(nvenc=True)
        assert hwaccel.resolve("vp9", hwaccel.AUTO, TOOLS).name == "libvpx-vp9"

    def test_container_escolhe_a_familia(self) -> None:
        assert hwaccel.family_for("webm") == "vp9"
        assert hwaccel.family_for("mp4") == "h264"
        assert hwaccel.family_for("mkv") == "h264"


class TestArgumentos:
    def test_cada_encoder_leva_a_propria_escala_de_qualidade(self) -> None:
        # "-crf" não tem efeito num encoder de placa: cada família tem a sua.
        fingir(nvenc=True)
        args = hwaccel.encode_args("h264", "nvenc", TOOLS)
        assert args[:2] == ["-c:v", "h264_nvenc"]
        assert "-qp" in args and "-crf" not in args

    def test_software_mantem_o_crf_alto_de_sempre(self) -> None:
        args = hwaccel.encode_args("h264", hwaccel.SOFTWARE, TOOLS)
        assert args[args.index("-crf") + 1] == "18"

    def test_nvenc_declara_o_controle_de_taxa(self) -> None:
        """Sem ``-rc``, o NVENC descarta o número de qualidade em silêncio.

        Este é o teste da regressão que passou despercebida: com só ``-cq``, três
        codificações a 20, 16 e 14 saíram byte a byte com o mesmo tamanho e SSIM
        0,7932 — contra 0,9786 do x264. Nada falhava; só a imagem piorava.
        """
        for family in ("h264", "hevc"):
            quality = hwaccel._HARDWARE[family]["nvenc"].quality
            assert "-rc" in quality, f"{family}: número de qualidade sem controle de taxa"
            assert quality[quality.index("-rc") + 1] == "constqp"

    def test_nenhum_encoder_de_placa_usa_a_escala_do_x264(self) -> None:
        # "-crf" não existe fora dos encoders de software: onde ele aparecesse, o
        # ffmpeg recusaria o argumento ou o ignoraria.
        for family, encoders in hwaccel._HARDWARE.items():
            for kind, encoder in encoders.items():
                assert "-crf" not in encoder.quality, f"{family}/{kind}"

    def test_vaapi_pede_dispositivo_e_envio_do_quadro(self) -> None:
        # Sem o dispositivo e o hwupload, o VAAPI recebe quadros que estão na
        # memória do processador e recusa.
        fingir(vaapi=True)
        encoder = hwaccel.resolve("h264", "vaapi", TOOLS)
        assert "-vaapi_device" in encoder.device
        assert "hwupload" in encoder.filter_suffix

    def test_encoder_de_software_nao_pede_dispositivo(self) -> None:
        encoder = hwaccel.resolve("h264", hwaccel.SOFTWARE, TOOLS)
        assert encoder.device == () and encoder.filter_suffix == ""


class TestTextoDaTela:
    def test_diz_o_que_vai_acontecer_e_nao_o_que_foi_pedido(self) -> None:
        # Ecoar "NVIDIA (NVENC)" esconderia que o driver é antigo demais e que a
        # exportação vai sair em software do mesmo jeito.
        fingir(nvenc=False, qsv=False, amf=False, vaapi=False)
        texto = hwaccel.describe("nvenc", TOOLS)
        assert "Software" in texto and "Nenhuma placa" in texto

    def test_confirma_a_placa_quando_ela_responde(self) -> None:
        fingir(nvenc=True)
        assert "NVIDIA" in hwaccel.describe("nvenc", TOOLS)

    def test_sem_ffmpeg_explica_em_vez_de_prometer(self) -> None:
        assert "ffmpeg" in hwaccel.describe(hwaccel.AUTO, None)


class TestSondagem:
    def test_o_resultado_fica_guardado(self, monkeypatch) -> None:
        chamadas: list[int] = []

        def contar(*_args, **_kwargs):
            chamadas.append(1)
            raise OSError("sem ffmpeg de verdade neste teste")

        monkeypatch.setattr(hwaccel.subprocess, "run", contar)
        encoder = hwaccel._HARDWARE["h264"]["nvenc"]
        assert hwaccel.probe(encoder, TOOLS) is False
        assert hwaccel.probe(encoder, TOOLS) is False
        assert len(chamadas) == 1, "sondar de novo abriria um processo por exportação"

    def test_ffmpeg_que_aborta_conta_como_indisponivel(self, monkeypatch) -> None:
        # O VAAPI desta máquina mata o processo por símbolo ausente na libva;
        # isso é uma resposta, não um erro a propagar.
        class Abortado:
            returncode = -6

        monkeypatch.setattr(hwaccel.subprocess, "run", lambda *a, **k: Abortado())
        assert hwaccel.probe(hwaccel._HARDWARE["h264"]["vaapi"], TOOLS) is False

    def test_a_sondagem_codifica_um_quadro_de_verdade(self) -> None:
        # Perguntar ao ffmpeg se ele "tem" o encoder não serve: ele lista
        # encoders que não abrem nesta máquina.
        comando = hwaccel._probe_command(hwaccel._HARDWARE["h264"]["nvenc"], TOOLS)
        assert comando[comando.index("-frames:v") + 1] == "1"
        assert comando[comando.index("-c:v") + 1] == "h264_nvenc"
        assert comando[-1] == "-", "escreve em lugar nenhum"


class TestSondagemPronta:
    """Se a interface pode responder na hora ou precisa sair da frente.

    A sondagem custa de 0,5 s a 3,4 s nesta máquina, e ela rodava na thread da
    interface: o diálogo de configurações abria congelado por todo esse tempo.
    ``probes_ready`` é o que permite decidir sem descobrir isso do jeito difícil
    — perguntando e travando.
    """

    def test_sem_ffmpeg_nao_ha_o_que_esperar(self) -> None:
        # A frase já está resolvida sem sondar nada, então a tela responde na
        # hora em vez de mostrar "verificando" para sempre.
        assert hwaccel.probes_ready(None) is True

    def test_antes_de_sondar_nao_esta_pronta(self) -> None:
        assert hwaccel.probes_ready(TOOLS) is False

    def test_depois_de_sondar_todos_esta_pronta(self) -> None:
        fingir(**{kind: kind == "nvenc" for kind in hwaccel.ORDER})
        assert hwaccel.probes_ready(TOOLS) is True

    def test_sondar_so_o_preferido_ainda_nao_e_pronto(self) -> None:
        # Ser conservador aqui não custa nada: no máximo a tela vai por um
        # caminho assíncrono que teria sido dispensável.
        fingir(nvenc=True)
        assert hwaccel.probes_ready(TOOLS) is False

    def test_esquecer_volta_a_pedir_sondagem(self) -> None:
        # É o que faz o botão "Testar agora" mostrar o aviso de verificação de
        # novo, em vez de repetir a resposta velha na hora.
        fingir(**{kind: True for kind in hwaccel.ORDER})
        hwaccel.forget_probes()
        assert hwaccel.probes_ready(TOOLS) is False


class TestVaapiDevice:
    def test_find_vaapi_device_returns_valid_path_or_default(self) -> None:
        device = hwaccel.find_vaapi_device()
        assert isinstance(device, str)
        assert device.startswith("/dev/dri/")
