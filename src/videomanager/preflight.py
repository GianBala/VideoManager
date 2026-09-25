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
"""

from __future__ import annotations

import ctypes
import os
import sys

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
