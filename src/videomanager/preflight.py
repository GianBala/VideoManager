"""Verificação de bibliotecas do sistema antes de iniciar a interface.

Existe por causa de um modo de falha particularmente ingrato no Linux: quando uma
biblioteca que o plugin ``xcb`` do Qt exige não está instalada, o Qt escreve uma
mensagem em inglês e chama ``abort()``. O processo morre **dentro** da criação do
``QApplication``, antes de qualquer código nosso rodar, e não há exceção a
capturar — nem oportunidade de mostrar um diálogo explicando o problema.

Por isso a checagem precisa vir antes, e usa ``ctypes`` para tentar carregar as
bibliotecas diretamente. É barato (milissegundos) e transforma um abort
incompreensível numa linha dizendo qual pacote instalar.

O caso concreto que motivou isto: o PySide6 6.11 pede ``libxcb-cursor.so.0``, que
o Ubuntu/Zorin não instala por padrão.

Também mora aqui a defesa contra o cache de fontes envenenado
(:func:`font_cache_isolation`), pela mesma razão: o defeito derruba o processo
sem exceção e sem mensagem, e a única chance de evitá-lo é antes do Qt.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from videomanager import APP_NAME
from videomanager.domain.i18n import register, t

# Aqui, e não no catálogo de uma camada: a mensagem sai antes de qualquer
# camada ser importada, e este módulo só pode depender da biblioteca padrão.
register({
    "PREFLIGHT_MISSING_ONE": (
        "O Video Manager não pôde abrir: falta biblioteca de sistema que a interface gráfica (Qt) exige.",
        "Video Manager could not start: a system library required by the graphical interface (Qt) is missing.",
    ),
    "PREFLIGHT_MISSING_MANY": (
        "O Video Manager não pôde abrir: falta bibliotecas de sistema que a interface gráfica (Qt) exige.",
        "Video Manager could not start: system libraries required by the graphical interface (Qt) are missing.",
    ),
    "PREFLIGHT_INSTALL": (
        "Instale com:\n\n    sudo apt install -y {packages}\n\nDepois abra o aplicativo novamente.\n\n"
        "Em distribuições que não usam apt, procure o equivalente a {first}.\n"
        "Para apenas testar sem interface gráfica, use QT_QPA_PLATFORM=offscreen.",
        "Install with:\n\n    sudo apt install -y {packages}\n\nThen open the application again.\n\n"
        "On distributions that don't use apt, look for the equivalent of {first}.\n"
        "To just test without a graphical interface, use QT_QPA_PLATFORM=offscreen.",
    ),
})

# Biblioteca -> pacote que a fornece no Debian/Ubuntu/Zorin. Somente as que o
# plugin xcb do Qt 6 exige e que costumam faltar numa instalação enxuta.
_REQUIRED: tuple[tuple[str, str], ...] = (
    ("libxcb-cursor.so.0", "libxcb-cursor0"),
    ("libxcb-xinerama.so.0", "libxcb-xinerama0"),
    ("libxkbcommon-x11.so.0", "libxkbcommon-x11-0"),
    ("libxcb-icccm.so.4", "libxcb-icccm4"),
    ("libxcb-image.so.0", "libxcb-image0"),
    ("libxcb-keysyms.so.1", "libxcb-keysyms1"),
    ("libxcb-render-util.so.0", "libxcb-render-util0"),
    ("libxcb-xkb.so.1", "libxcb-xkb1"),
)

# Plataformas Qt que não passam pelo plugin xcb e portanto não precisam disso.
_NON_XCB_PLATFORMS = {"offscreen", "minimal", "wayland", "wayland-egl", "vnc", "linuxfb", "eglfs"}


def missing_system_libraries() -> list[str]:
    """Pacotes ausentes necessários ao plugin xcb. Lista vazia se estiver tudo ok."""
    if sys.platform != "linux":
        return []

    requested = os.environ.get("QT_QPA_PLATFORM", "").strip().lower()
    if requested in _NON_XCB_PLATFORMS:
        return []

    # Sessão Wayland pura (sem XWayland) não carrega o plugin xcb.
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return []

    missing: list[str] = []
    for library, package in _REQUIRED:
        try:
            ctypes.CDLL(library)
        except OSError:
            missing.append(package)
    return missing


def format_instructions(packages: list[str]) -> str:
    """Mensagem de erro acionável, no idioma das preferências."""
    head = t("PREFLIGHT_MISSING_MANY" if len(packages) > 1 else "PREFLIGHT_MISSING_ONE")
    return f"{head}\n\n" + t("PREFLIGHT_INSTALL", packages=" ".join(packages), first=packages[0])


def check_or_explain() -> str | None:
    """``None`` se estiver tudo certo; senão, a mensagem a exibir antes de sair."""
    missing = missing_system_libraries()
    return format_instructions(missing) if missing else None


# Todo cache do fontconfig começa com FC_CACHE_MAGIC_MMAP (0xFC02FC04, em
# little-endian) e, logo depois, a versão do formato — que também é o sufixo do
# nome do arquivo (``<hash>-le64.cache-9``). ``le64``: só Linux little-endian
# importa aqui.
_FC_MAGIC = b"\x04\xfc\x02\xfc"
_FC_CACHE_NAME = re.compile(r"\.cache-(\d+)$")

_LOG = logging.getLogger(__name__)


def _cache_home() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")


def poisoned_font_caches(directory: Path) -> list[Path]:
    """Caches cujo nome anuncia uma versão do formato e cujo conteúdo é de outra.

    O fontconfig só confere que a versão gravada é **maior ou igual** à que ele
    entende, então um ``cache-9`` que na verdade é formato 12 é aceito e lido
    com o desenho de estruturas antigo: o processo cai com SIGSEGV em
    ``FcCharSetHasChar``, na primeira vez que o Qt monta texto com fonte de
    reserva. Quem fabrica isso é o fontconfig embutido num navegador Chromium
    (medido com o Brave), que grava o formato novo e aponta ``cache-9/10/11``
    para ele — daí olhar o cabeçalho, que pega o link e também uma cópia.
    """
    poisoned: list[Path] = []
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return poisoned
    for entry in entries:
        named = _FC_CACHE_NAME.search(entry.name)
        if named is None:
            continue
        try:
            with open(entry, "rb") as handle:  # abre o alvo do link; link quebrado cai no except
                header = handle.read(8)
        except OSError:
            continue
        if header[:4] == _FC_MAGIC and int.from_bytes(header[4:8], "little") != int(named.group(1)):
            poisoned.append(entry)
    return poisoned


@contextmanager
def font_cache_isolation() -> Iterator[bool]:
    """Enquanto vale, o fontconfig usa um cache só do aplicativo, não o do usuário.

    Só entra em ação quando :func:`poisoned_font_caches` acha algo: sem veneno
    nada muda, nem o lugar do cache. Entra por ``XDG_CACHE_HOME`` porque é a
    única forma de o fontconfig trocar a pasta do cache do usuário sem reescrever
    o ``fonts.conf`` do sistema — e a variável é devolvida ao sair, para que
    yt-dlp, platformdirs e os processos filhos continuem enxergando a verdadeira.

    Devolve ``True`` quando o desvio está valendo. Quem cria o ``QApplication``
    precisa então **forçar a leitura da lista de fontes dentro do bloco**: o Qt
    só a carrega quando alguém pergunta, e uma leitura adiada para depois da
    saída iria direto ao cache envenenado.
    """
    if not sys.platform.startswith("linux"):
        yield False
        return
    try:
        home = _cache_home()
        poisoned = poisoned_font_caches(home / "fontconfig")
        private = home / APP_NAME / "xdg"
        if poisoned:
            private.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError):  # sem HOME ou sem onde gravar: segue como antes
        poisoned = []
    if not poisoned:
        yield False
        return

    _LOG.warning(
        "O cache de fontes do usuário tem %d arquivo(s) de outra versão do formato (em geral links "
        "criados por um navegador); usando um cache próprio em %s.", len(poisoned), private)
    previous = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_CACHE_HOME"] = str(private)
    try:
        yield True
    finally:
        if previous is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = previous
