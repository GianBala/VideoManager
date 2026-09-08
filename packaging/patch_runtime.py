#!/usr/bin/env python3
"""Adapta runtimes x86_64 compatíveis para auto-extração, inclusive sem libfuse2 ou fusermount instalados (ex: Ubuntu 22.04+, Debian 12+, Fedora, WSL2, Docker).

O runtime Type 2 clássico falha com 'Cannot mount AppImage, please check your FUSE setup'
quando FUSE 2 não está disponível no sistema. Este patch ajusta o runtime para executar em
modo extração automática transparente (extract-and-run) sem exigir que o usuário passe flags manuais.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def patch_runtime(path: Path) -> bool:
    """Modifica o runtime (ou o cabeçalho de um AppImage) para auto-extração."""
    if not path.is_file():
        print(f"Erro: arquivo não encontrado: {path}", file=sys.stderr)
        return False

    with open(path, "rb") as f:
        data = bytearray(f.read())

    target_str = b"APPIMAGE_EXTRACT_AND_RUN\0"
    str_offset = data.find(target_str)
    if str_offset == -1:
        print(f"Aviso: string de controle não encontrada em {path}", file=sys.stderr)
        return False

    # Procura a instrução LEA (48 8d 3d disp32) que aponta para a string
    found: list[int] = []
    search_limit = min(len(data) - 7, 2 * 1024 * 1024)
    for i in range(search_limit):
        if data[i : i + 3] == b"\x48\x8d\x3d":
            disp = int.from_bytes(data[i + 3 : i + 7], "little", signed=True)
            if (i + 7 + disp) == str_offset:
                found.append(i)

    if len(found) != 1:
        print(f"Aviso: instrução de referência ambígua ou ausente em {path}", file=sys.stderr)
        return False

    lea_idx = found[0]
    # Estrutura esperada:
    #   lea ... (%rdi)       (7 bytes)
    #   call getenv          (5 bytes)
    #   test %rax, %rax      (3 bytes: 48 85 c0)
    #   jne <target>         (6 bytes: 0f 85 disp32)
    after_call = lea_idx + 7 + 5
    if data[after_call : after_call + 3] != b"\x48\x85\xc0":
        print(f"Aviso: sequência de teste pós-chamada inesperada em {path}", file=sys.stderr)
        return False

    jne_idx = after_call + 3
    if data[jne_idx : jne_idx + 2] == b"\x0f\x85":
        disp = int.from_bytes(data[jne_idx + 2 : jne_idx + 6], "little", signed=True)
        # Substitui jne (6 bytes: 0f 85 disp32) por jmp (5 bytes: e9 disp32+1) + nop (1 byte: 90)
        new_disp = disp + 1
        data[jne_idx] = 0xE9
        data[jne_idx + 1 : jne_idx + 5] = new_disp.to_bytes(4, "little", signed=True)
        data[jne_idx + 5] = 0x90

        mode = os.stat(path).st_mode
        tmp_target = path.with_name(f"{path.name}.patch_tmp")
        try:
            with open(tmp_target, "wb") as f_out:
                f_out.write(data)
            os.chmod(tmp_target, mode)
            os.replace(tmp_target, path)
        finally:
            if tmp_target.exists():
                tmp_target.unlink(missing_ok=True)

        print(f"--> Patch aplicado com sucesso em {path.name} (auto-extração ativa).")
        return True
    elif data[jne_idx] == 0xE9 and data[jne_idx + 5] == 0x90:
        print(f"--> {path.name} já possui o patch de auto-extração.")
        return True
    else:
        print(f"Aviso: instrução de desvio desconhecida em {path}", file=sys.stderr)
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Uso: {sys.argv[0]} <arquivo_runtime_ou_appimage> [...]", file=sys.stderr)
        return 2

    success = True
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not patch_runtime(p):
            success = False

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
