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

import glob
import os
import subprocess
import threading
from dataclasses import dataclass, replace

from videomanager.application.capabilities import FFmpegTools
from videomanager.infrastructure.system.binaries import subprocess_kwargs

from videomanager.application.encoding import SOFTWARE as SOFTWARE
from videomanager.application.encoding import AUTO as AUTO
from videomanager.application.encoding import QUALITY_BALANCED as QUALITY_BALANCED
from videomanager.application.encoding import QUALITY_HIGH as QUALITY_HIGH
from videomanager.application.encoding import QUALITY_ECONOMY as QUALITY_ECONOMY
from videomanager.application.encoding import DEFAULT_QUALITY as DEFAULT_QUALITY
from videomanager.application.encoding import QUALITY_LABELS as QUALITY_LABELS
from videomanager.application.encoding import quality_label as quality_label
from videomanager.application.encoding import FAMILY_NAMES as FAMILY_NAMES
from videomanager.application.encoding import family_for as family_for
from videomanager.application.encoding import family_label as family_label
from videomanager.application.encoding import CHOICES as CHOICES

# Preferências que o usuário pode escolher. "auto" tenta as placas na ordem em
# que estão aqui e fica com a primeira que abrir.

# Níveis de qualidade de codificação de vídeo


# Mapeamento de argumentos de qualidade por encoder e nível de qualidade.
# O padrão recomendado é QUALITY_BALANCED (CRF 23 / QP 23), que produz excelente
# fidelidade visual a uma taxa de bits muito mais eficiente (~35-45 MB por minuto em 1080p).
_ENCODER_QUALITY: dict[str, dict[str, tuple[str, ...]]] = {
    # Software
    "libx264": {
        QUALITY_HIGH: ("-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"),
        QUALITY_BALANCED: ("-crf", "23", "-preset", "medium", "-pix_fmt", "yuv420p"),
        QUALITY_ECONOMY: ("-crf", "28", "-preset", "medium", "-pix_fmt", "yuv420p"),
    },
    "libx265": {
        QUALITY_HIGH: ("-crf", "20", "-pix_fmt", "yuv420p"),
        QUALITY_BALANCED: ("-crf", "25", "-pix_fmt", "yuv420p"),
        QUALITY_ECONOMY: ("-crf", "30", "-pix_fmt", "yuv420p"),
    },
    # O ``-pix_fmt`` é obrigatório aqui, como no x264/x265: a composição chega
    # com alfa (RGBA), e a partir do ffmpeg 9 o libvpx-vp9 recusa o quadro em
    # vez de converter — a exportação .webm terminava sem escrever nada.
    "libvpx-vp9": {
        QUALITY_HIGH: ("-crf", "25", "-b:v", "0", "-pix_fmt", "yuv420p"),
        QUALITY_BALANCED: ("-crf", "31", "-b:v", "0", "-pix_fmt", "yuv420p"),
        QUALITY_ECONOMY: ("-crf", "38", "-b:v", "0", "-pix_fmt", "yuv420p"),
    },
    "libsvtav1": {
        QUALITY_HIGH: ("-crf", "26",),
        QUALITY_BALANCED: ("-crf", "32",),
        QUALITY_ECONOMY: ("-crf", "38",),
    },
    # NVIDIA NVENC
    "h264_nvenc": {
        QUALITY_HIGH: ("-preset", "p5", "-rc", "constqp", "-qp", "18", "-pix_fmt", "yuv420p"),
        QUALITY_BALANCED: ("-preset", "p5", "-rc", "constqp", "-qp", "23", "-pix_fmt", "yuv420p"),
        QUALITY_ECONOMY: ("-preset", "p5", "-rc", "constqp", "-qp", "28", "-pix_fmt", "yuv420p"),
    },
    "hevc_nvenc": {
        QUALITY_HIGH: ("-preset", "p5", "-rc", "constqp", "-qp", "20", "-pix_fmt", "yuv420p"),
        QUALITY_BALANCED: ("-preset", "p5", "-rc", "constqp", "-qp", "25", "-pix_fmt", "yuv420p"),
        QUALITY_ECONOMY: ("-preset", "p5", "-rc", "constqp", "-qp", "30", "-pix_fmt", "yuv420p"),
    },
    # Intel Quick Sync
    "h264_qsv": {
        QUALITY_HIGH: ("-global_quality", "18", "-pix_fmt", "nv12"),
        QUALITY_BALANCED: ("-global_quality", "23", "-pix_fmt", "nv12"),
        QUALITY_ECONOMY: ("-global_quality", "28", "-pix_fmt", "nv12"),
    },
    "hevc_qsv": {
        QUALITY_HIGH: ("-global_quality", "20", "-pix_fmt", "nv12"),
        QUALITY_BALANCED: ("-global_quality", "25", "-pix_fmt", "nv12"),
        QUALITY_ECONOMY: ("-global_quality", "30", "-pix_fmt", "nv12"),
    },
    # AMD AMF
    "h264_amf": {
        QUALITY_HIGH: ("-quality", "quality", "-qp_i", "18", "-qp_p", "18"),
        QUALITY_BALANCED: ("-quality", "balanced", "-qp_i", "23", "-qp_p", "23"),
        QUALITY_ECONOMY: ("-quality", "speed", "-qp_i", "28", "-qp_p", "28"),
    },
    "hevc_amf": {
        QUALITY_HIGH: ("-quality", "quality", "-qp_i", "20", "-qp_p", "20"),
        QUALITY_BALANCED: ("-quality", "balanced", "-qp_i", "25", "-qp_p", "25"),
        QUALITY_ECONOMY: ("-quality", "speed", "-qp_i", "30", "-qp_p", "30"),
    },
    # Linux VAAPI
    "h264_vaapi": {
        QUALITY_HIGH: ("-qp", "18",),
        QUALITY_BALANCED: ("-qp", "23",),
        QUALITY_ECONOMY: ("-qp", "28",),
    },
    "hevc_vaapi": {
        QUALITY_HIGH: ("-qp", "20",),
        QUALITY_BALANCED: ("-qp", "25",),
        QUALITY_ECONOMY: ("-qp", "30",),
    },
}


def encoder_quality(encoder_name: str, quality: str = QUALITY_BALANCED) -> tuple[str, ...]:
    """Retorna argumentos de qualidade para um determinado encoder."""
    by_enc = _ENCODER_QUALITY.get(encoder_name)
    if by_enc:
        return by_enc.get(quality, by_enc.get(QUALITY_BALANCED, ()))
    return ()


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


# Encoders de software: com qualidade equilibrada (CRF 23) por padrão.
_SOFTWARE: dict[str, Encoder] = {
    "h264": Encoder(
        "libx264",
        quality=encoder_quality("libx264", QUALITY_BALANCED),
        label="Software (x264)",
    ),
    "hevc": Encoder(
        "libx265",
        quality=encoder_quality("libx265", QUALITY_BALANCED),
        label="Software (x265)",
    ),
    "vp9": Encoder(
        "libvpx-vp9",
        quality=encoder_quality("libvpx-vp9", QUALITY_BALANCED),
        label="Software (VP9)",
    ),
    "av1": Encoder(
        "libsvtav1",
        quality=encoder_quality("libsvtav1", QUALITY_BALANCED),
        label="Software (AV1)",
    ),
}

# Por família de codec, os encoders de placa em ordem de preferência.
_HARDWARE: dict[str, dict[str, Encoder]] = {
    "h264": {
        # ``-rc constqp`` não é enfeite: sem declarar o controle de taxa, o NVENC
        # ignora o número de qualidade e cai num bitrate padrão.
        "nvenc": Encoder(
            "h264_nvenc",
            quality=encoder_quality("h264_nvenc", QUALITY_BALANCED),
            label="NVIDIA (NVENC)",
        ),
        "qsv": Encoder(
            "h264_qsv",
            quality=encoder_quality("h264_qsv", QUALITY_BALANCED),
            label="Intel (Quick Sync)",
        ),
        "amf": Encoder(
            "h264_amf",
            quality=encoder_quality("h264_amf", QUALITY_BALANCED),
            label="AMD (AMF)",
        ),
        "vaapi": Encoder(
            "h264_vaapi",
            quality=encoder_quality("h264_vaapi", QUALITY_BALANCED),
            device=("-vaapi_device", "/dev/dri/renderD128"),
            filter_suffix="format=nv12,hwupload",
            label="VAAPI",
        ),
    },
    "hevc": {
        "nvenc": Encoder(
            "hevc_nvenc",
            quality=encoder_quality("hevc_nvenc", QUALITY_BALANCED),
            label="NVIDIA (NVENC)",
        ),
        "qsv": Encoder(
            "hevc_qsv",
            quality=encoder_quality("hevc_qsv", QUALITY_BALANCED),
            label="Intel (Quick Sync)",
        ),
        "amf": Encoder(
            "hevc_amf",
            quality=encoder_quality("hevc_amf", QUALITY_BALANCED),
            label="AMD (AMF)",
        ),
        "vaapi": Encoder(
            "hevc_vaapi",
            quality=encoder_quality("hevc_vaapi", QUALITY_BALANCED),
            device=("-vaapi_device", "/dev/dri/renderD128"),
            filter_suffix="format=nv12,hwupload",
            label="VAAPI",
        ),
    },
}

# Ordem em que "auto" tenta as placas. Dedicada antes de integrada: onde as duas
# existem, é a dedicada que tem o codificador mais rápido.
ORDER = ("nvenc", "qsv", "amf", "vaapi")

# Nome do codec para a tela. Separado do nome do encoder de propósito: quem lê
# "o que vai acontecer" quer saber que sai H.264, não qual biblioteca o gerou.

# Nomes para a tela, na ordem em que aparecem na lista de escolha. Curtos de
# propósito: a caixa tem a largura padrão dos campos do diálogo, e o que explica
# cada opção é a dica e a linha de estado logo abaixo dela.

# Resultado das sondagens já feitas nesta execução: abrir um ffmpeg por
# exportação só para descobrir o que já se sabe seria desperdício, e a resposta
# não muda enquanto o programa está aberto.
_probed: dict[str, bool] = {}
# Uma sondagem por encoder de cada vez. Sem isto, as oito threads de uma
# exportação em trechos paralelos chegam juntas ao cache frio e abrem oito
# sondagens do mesmo encoder — e a mais cara delas é justamente a que falha,
# porque o VAAPI desta máquina **aborta** o processo, o que demora mais que uma
# recusa. O trinco é por encoder, então sondar a placa não segura quem já tem
# resposta em cache.
_probe_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def find_vaapi_device() -> str:
    """Encontra o primeiro nó de renderização VAAPI acessível no Linux."""
    for node in sorted(glob.glob("/dev/dri/renderD*")):
        if os.access(node, os.R_OK | os.W_OK):
            return node
    return "/dev/dri/renderD128"


def _probe_command(encoder: Encoder, tools: FFmpegTools) -> list[str]:
    """Codifica **um quadro** de uma imagem gerada na hora, sem tocar em disco."""
    source = "color=c=black:s=320x240:d=0.1"
    chain = f"format=nv12,{encoder.filter_suffix}" if encoder.filter_suffix else "null"
    device_args = encoder.device
    if encoder.name.endswith("_vaapi"):
        device_args = ("-vaapi_device", find_vaapi_device())
    return [
        tools.ffmpeg_str,
        "-nostdin", "-hide_banner", "-v", "error",
        *device_args,
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

    with _lock_for(encoder.name):
        # Conferido de novo com o trinco na mão: quem esperou aqui já pode ter
        # a resposta que a outra thread acabou de gravar.
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
            # Inclui o caso em que o próprio ffmpeg aborta — o VAAPI desta
            # máquina morre por símbolo ausente na libva, e isso é uma resposta
            # válida.
            ok = False
        _probed[encoder.name] = ok
        return ok


def _lock_for(name: str) -> threading.Lock:
    with _locks_guard:
        return _probe_locks.setdefault(name, threading.Lock())


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


def resolve(
    family: str,
    preference: str,
    tools: FFmpegTools | None,
    quality: str = QUALITY_BALANCED,
) -> Encoder:
    """Encoder a usar de fato, já com a queda para software embutida.

    Nunca devolve algo que não abre: é isto que faz uma máquina sem placa — ou
    com driver velho demais — continuar exportando, em vez de falhar com uma
    mensagem do ffmpeg no meio da fila.
    """
    fallback = software_encoder(family)
    chosen = fallback
    if preference != SOFTWARE and tools is not None:
        candidates = _HARDWARE.get(family, {})
        if candidates:
            wanted = ORDER if preference == AUTO else (preference,)
            for kind in wanted:
                encoder = candidates.get(kind)
                if encoder is not None:
                    if encoder.name.endswith("_vaapi"):
                        encoder = replace(encoder, device=("-vaapi_device", find_vaapi_device()))
                    if probe(encoder, tools):
                        chosen = encoder
                        break

    q_args = encoder_quality(chosen.name, quality)
    if q_args:
        return replace(chosen, quality=q_args)
    return chosen


def available(tools: FFmpegTools | None, family: str = "h264") -> list[str]:
    """Placas que funcionam agora, na ordem de preferência."""
    if tools is None:
        return []
    candidates = _HARDWARE.get(family, {})
    return [k for k in ORDER if k in candidates and probe(candidates[k], tools)]


def describe(
    preference: str,
    tools: FFmpegTools | None,
    family: str = "h264",
    quality: str = QUALITY_BALANCED,
) -> str:
    """Frase para a tela dizendo o que **vai** acontecer, não o que se pediu."""
    encoder = resolve(family, preference, tools, quality=quality)
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


def encode_args(
    family: str,
    preference: str,
    tools: FFmpegTools | None,
    quality: str = QUALITY_BALANCED,
) -> list[str]:
    """Argumentos de codificação de vídeo já resolvidos."""
    encoder = resolve(family, preference, tools, quality=quality)
    return ["-c:v", encoder.name, *encoder.quality]


def device_args(
    family: str,
    preference: str,
    tools: FFmpegTools | None,
    quality: str = QUALITY_BALANCED,
) -> list[str]:
    return list(resolve(family, preference, tools, quality=quality).device)


def filter_suffix(
    family: str,
    preference: str,
    tools: FFmpegTools | None,
    quality: str = QUALITY_BALANCED,
) -> str:
    return resolve(family, preference, tools, quality=quality).filter_suffix


__all__ = [
    'FFmpegTools',
    'SOFTWARE',
    'AUTO',
    'QUALITY_BALANCED',
    'QUALITY_HIGH',
    'QUALITY_ECONOMY',
    'DEFAULT_QUALITY',
    'QUALITY_LABELS',
    'quality_label',
    'FAMILY_NAMES',
    'family_for',
    'family_label',
    'CHOICES',
]
