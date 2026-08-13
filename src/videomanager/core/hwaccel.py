"""Codificação por hardware: escolher a placa quando ela existe, e só então.

**Nada aqui acredita no que o ffmpeg lista.** ``ffmpeg -encoders`` mostra
``h264_nvenc`` em toda build moderna, inclusive onde ele não abre: driver mais
antigo que a build, biblioteca do sistema incompatível, placa ocupada, máquina
virtual sem acesso ao dispositivo. Medido nesta máquina: o encoder aparece na
lista e falha com *"Driver does not support the required nvenc API version"*, e
o VAAPI aborta o processo por um símbolo ausente na ``libva``. Por isso a
disponibilidade é decidida por :func:`probe`, que **manda codificar um quadro de
verdade** e olha o resultado.

**A queda para software é automática e silenciosa na hora de gravar.** Se a
escolha do usuário não abrir — porque ele trocou de máquina, atualizou o driver
ou a placa está ocupada —, a tarefa sai em software em vez de falhar. Uma
exportação que não acontece é pior que uma exportação mais lenta. Quem quiser
saber o que foi usado tem a resposta antes, no diálogo de configurações.

**O padrão é software.** O x264 comprime melhor que qualquer encoder de placa no
mesmo tamanho de arquivo, e esta é a aba de um editor que promete preservar o
material. Velocidade é uma escolha explícita, não uma troca feita por baixo.

**Todo encoder precisa declarar o controle de taxa junto com o número de
qualidade.** Um encoder de placa que recebe só o número o descarta em silêncio e
grava no bitrate padrão dele: o arquivo sai, a tarefa termina sem erro, e a
qualidade despenca sem nada na tela. Foi o que aconteceu com o NVENC aqui, e é
por isso que ``-rc`` viaja junto do ``-qp`` — a regra vale para qualquer encoder
que venha a ser acrescentado.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .binaries import FFmpegTools, subprocess_kwargs

# Preferências que o usuário pode escolher. "auto" tenta as placas na ordem em
# que estão aqui e fica com a primeira que abrir.
SOFTWARE = "software"
AUTO = "auto"


@dataclass(frozen=True)
class Encoder:
    """Um encoder de vídeo, com o que ele exige para funcionar."""

    name: str
    # Qualidade equivalente ao CRF do x264. Cada família tem a sua escala, e
    # usar "-crf" num encoder de placa simplesmente não tem efeito.
    quality: tuple[str, ...] = ()
    # Argumentos de dispositivo, antes das entradas.
    device: tuple[str, ...] = ()
    # Filtros que precisam ser encaixados no fim do vídeo (o VAAPI só aceita
    # quadros que já estão na memória da placa).
    filter_suffix: str = ""
    label: str = ""


# Encoders de software: o que o aplicativo sempre usou.
_SOFTWARE: dict[str, Encoder] = {
    "h264": Encoder(
        "libx264",
        quality=("-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"),
        label="Software (x264)",
    ),
    "hevc": Encoder(
        "libx265", quality=("-crf", "20", "-pix_fmt", "yuv420p"), label="Software (x265)"
    ),
    "vp9": Encoder(
        "libvpx-vp9", quality=("-crf", "30", "-b:v", "0"), label="Software (VP9)"
    ),
    "av1": Encoder("libsvtav1", quality=("-crf", "30",), label="Software (AV1)"),
}

# Por família de codec, os encoders de placa em ordem de preferência.
_HARDWARE: dict[str, dict[str, Encoder]] = {
    "h264": {
        # ``-rc constqp`` não é enfeite: sem declarar o controle de taxa, o NVENC
        # ignora o número de qualidade e cai num bitrate padrão. Medido aqui, num
        # trecho de 30 s a 1080p, codificando com ``-cq 20``, ``-cq 16`` e
        # ``-cq 14``: os três saíram com 58 MB e SSIM 0,7932 — o mesmo resultado,
        # como se o pedido não existisse, e bem longe do 0,9786 do x264. Com o
        # controle de taxa explícito, a placa passa a empatar com o software
        # (SSIM 0,9960 contra 0,9959) gastando um terço do tempo.
        "nvenc": Encoder(
            "h264_nvenc",
            quality=("-preset", "p5", "-rc", "constqp", "-qp", "18", "-pix_fmt", "yuv420p"),
            label="NVIDIA (NVENC)",
        ),
        "qsv": Encoder(
            "h264_qsv",
            quality=("-global_quality", "22", "-pix_fmt", "nv12"),
            label="Intel (Quick Sync)",
        ),
        "amf": Encoder(
            "h264_amf", quality=("-quality", "balanced", "-qp_i", "22", "-qp_p", "22"),
            label="AMD (AMF)",
        ),
        "vaapi": Encoder(
            "h264_vaapi",
            quality=("-qp", "22",),
            device=("-vaapi_device", "/dev/dri/renderD128"),
            filter_suffix="format=nv12,hwupload",
            label="VAAPI",
        ),
    },
    "hevc": {
        "nvenc": Encoder(
            "hevc_nvenc",
            quality=("-preset", "p5", "-rc", "constqp", "-qp", "20", "-pix_fmt", "yuv420p"),
            label="NVIDIA (NVENC)",
        ),
        "qsv": Encoder(
            "hevc_qsv", quality=("-global_quality", "24", "-pix_fmt", "nv12"),
            label="Intel (Quick Sync)",
        ),
        "amf": Encoder("hevc_amf", quality=("-qp_i", "24", "-qp_p", "24"), label="AMD (AMF)"),
        "vaapi": Encoder(
            "hevc_vaapi", quality=("-qp", "24",),
            device=("-vaapi_device", "/dev/dri/renderD128"),
            filter_suffix="format=nv12,hwupload", label="VAAPI",
        ),
    },
}

# Ordem em que "auto" tenta as placas. Dedicada antes de integrada: onde as duas
# existem, é a dedicada que tem o codificador mais rápido.
ORDER = ("nvenc", "qsv", "amf", "vaapi")

# Nome do codec para a tela. Separado do nome do encoder de propósito: quem lê
# "o que vai acontecer" quer saber que sai H.264, não qual biblioteca o gerou.
FAMILY_NAMES = {"h264": "H.264", "hevc": "HEVC", "vp9": "VP9", "av1": "AV1"}


def family_for(container: str) -> str:
    """Família de codec que combina com o container de saída."""
    return "vp9" if container == "webm" else "h264"


def family_label(family: str) -> str:
    return FAMILY_NAMES.get(family, family.upper())


def is_hardware(family: str, preference: str, tools: FFmpegTools | None) -> bool:
    return not resolve(family, preference, tools).name.startswith("lib")

# Nomes para a tela, na ordem em que aparecem na lista de escolha. Curtos de
# propósito: a caixa tem a largura padrão dos campos do diálogo, e o que explica
# cada opção é a dica e a linha de estado logo abaixo dela.
CHOICES: tuple[tuple[str, str], ...] = (
    (SOFTWARE, "Software (melhor compressão)"),
    (AUTO, "Automático (usa a placa)"),
    ("nvenc", "NVIDIA (NVENC)"),
    ("qsv", "Intel (Quick Sync)"),
    ("amf", "AMD (AMF)"),
    ("vaapi", "VAAPI (Linux)"),
)

# Resultado das sondagens já feitas nesta execução: abrir um ffmpeg por
# exportação só para descobrir o que já se sabe seria desperdício, e a resposta
# não muda enquanto o programa está aberto.
_probed: dict[str, bool] = {}


def _probe_command(encoder: Encoder, tools: FFmpegTools) -> list[str]:
    """Codifica **um quadro** de uma imagem gerada na hora, sem tocar em disco."""
    source = "color=c=black:s=320x240:d=0.1"
    chain = f"format=nv12,{encoder.filter_suffix}" if encoder.filter_suffix else "null"
    return [
        tools.ffmpeg_str,
        "-nostdin", "-hide_banner", "-v", "error",
        *encoder.device,
        "-f", "lavfi", "-i", source,
        "-vf", chain,
        "-c:v", encoder.name,
        *encoder.quality,
        "-frames:v", "1",
        "-f", "null", "-",
    ]


def probe(encoder: Encoder, tools: FFmpegTools, *, timeout: int = 20) -> bool:
    """Se este encoder **abre de verdade** nesta máquina.

    O resultado fica guardado: a sondagem custa um processo, e a resposta é a
    mesma até o programa ser reaberto.
    """
    cached = _probed.get(encoder.name)
    if cached is not None:
        return cached

    try:
        proc = subprocess.run(
            _probe_command(encoder, tools),
            timeout=timeout,
            check=False,
            **subprocess_kwargs(),
        )
        ok = proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        # Inclui o caso em que o próprio ffmpeg aborta — o VAAPI desta máquina
        # morre por símbolo ausente na libva, e isso é uma resposta válida.
        ok = False
    _probed[encoder.name] = ok
    return ok


def forget_probes() -> None:
    """Esquece o que foi sondado. Usado ao testar de novo pela interface."""
    _probed.clear()


def probes_ready(tools: FFmpegTools | None, family: str = "h264") -> bool:
    """Se perguntar por esta família já é instantâneo.

    Existe para a interface saber se pode responder na hora ou se precisa sair
    da frente e sondar noutra thread. Ser conservador aqui não custa nada: no
    máximo a tela vai por um caminho assíncrono que teria sido dispensável.
    """
    if tools is None:
        return True
    return all(enc.name in _probed for enc in _HARDWARE.get(family, {}).values())


def software_encoder(family: str) -> Encoder:
    return _SOFTWARE.get(family, _SOFTWARE["h264"])


def resolve(family: str, preference: str, tools: FFmpegTools | None) -> Encoder:
    """Encoder a usar de fato, já com a queda para software embutida.

    Nunca devolve algo que não abre: é isto que faz uma máquina sem placa — ou
    com driver velho demais — continuar exportando, em vez de falhar com uma
    mensagem do ffmpeg no meio da fila.
    """
    fallback = software_encoder(family)
    if preference == SOFTWARE or tools is None:
        return fallback

    candidates = _HARDWARE.get(family, {})
    if not candidates:
        # Família sem equivalente em placa (VP9, AV1 nas builds comuns).
        return fallback

    wanted = ORDER if preference == AUTO else (preference,)
    for kind in wanted:
        encoder = candidates.get(kind)
        if encoder is not None and probe(encoder, tools):
            return encoder
    return fallback


def available(tools: FFmpegTools | None, family: str = "h264") -> list[str]:
    """Placas que funcionam agora, na ordem de preferência."""
    if tools is None:
        return []
    candidates = _HARDWARE.get(family, {})
    return [k for k in ORDER if k in candidates and probe(candidates[k], tools)]


def describe(preference: str, tools: FFmpegTools | None, family: str = "h264") -> str:
    """Frase para a tela dizendo o que **vai** acontecer, não o que se pediu."""
    encoder = resolve(family, preference, tools)
    if preference == SOFTWARE:
        return f"Usando {encoder.label}."
    if encoder.name.startswith("lib"):
        if tools is None:
            return "O ffmpeg ainda não foi localizado; a exportação usará software."
        return (
            "Nenhuma placa disponível respondeu ao teste — a exportação vai usar "
            f"{encoder.label}."
        )
    return f"Placa em uso: {encoder.label}."


def encode_args(family: str, preference: str, tools: FFmpegTools | None) -> list[str]:
    """Argumentos de codificação de vídeo já resolvidos."""
    encoder = resolve(family, preference, tools)
    return ["-c:v", encoder.name, *encoder.quality]


def device_args(family: str, preference: str, tools: FFmpegTools | None) -> list[str]:
    return list(resolve(family, preference, tools).device)


def filter_suffix(family: str, preference: str, tools: FFmpegTools | None) -> str:
    return resolve(family, preference, tools).filter_suffix
