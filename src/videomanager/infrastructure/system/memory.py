"""Quanta memória a máquina tem para dar agora.

Existe por causa de uma lição cara: a interpolação reserva memória em função do
tamanho do quadro (1,6 GB a 1080p, 5,6 GB a 4K — ver ``infrastructure/ffmpeg/composer.py``), e uma
exportação interpolada já esgotou a memória desta máquina e derrubou a sessão
pelo OOM killer. Tudo que **multiplica** esse custo — como dividir a
interpolação em trechos paralelos — precisa perguntar antes, e não depois.

A resposta é um palpite honesto, não uma garantia: outro programa pode pedir
memória no segundo seguinte. Por isso quem usa este número reserva só uma fração
dele (ver ``composer.interpolation_segments``).

``None`` significa **não sei**, e é diferente de zero: onde não dá para
perguntar, quem chama tem de escolher o caminho conservador em vez de supor que
há memória sobrando.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

_MEMINFO = Path("/proc/meminfo")


def available_bytes() -> int | None:
    """Memória utilizável agora, ou ``None`` onde não dá para saber."""
    if sys.platform.startswith("linux"):
        return _linux_available()
    if sys.platform.startswith("win"):
        return _windows_available()
    return None


def _linux_available() -> int | None:
    """``MemAvailable`` do ``/proc/meminfo``.

    É o campo certo, e não ``MemFree``: o kernel usa quase toda a memória livre
    como cache de disco, então ``MemFree`` num sistema em uso normal fica perto
    de zero e faria a conta recusar tudo. ``MemAvailable`` é a estimativa do
    próprio kernel do que dá para entregar sem empurrar nada para a swap.
    """
    try:
        texto = _MEMINFO.read_text()
    except OSError:
        return None
    for linha in texto.splitlines():
        if linha.startswith("MemAvailable:"):
            partes = linha.split()
            if len(partes) >= 2 and partes[1].isdigit():
                return int(partes[1]) * 1024  # o arquivo reporta em kB
    return None


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _windows_available() -> int | None:
    """``ullAvailPhys`` do ``GlobalMemoryStatusEx``.

    Memória física livre, e não o arquivo de paginação: o que se quer evitar é
    justamente a máquina começar a paginar, que foi como a sessão travou aqui.
    """
    try:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except (AttributeError, OSError):
        return None
    return int(status.ullAvailPhys)
