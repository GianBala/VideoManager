"""Mede o arrasto de um bloco com fundo desfocado na prévia: o que aparece enquanto a mão se move.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python scripts/validate_blur_drag.py [--varrer foto|video] [--repeticoes 3]

O bloco é uma imagem de metade vermelha, metade azul e um quadrado branco no
centro, sobre uma trilha de baixo verde. Isso deixa três coisas legíveis em
pixel, a cada passo do gesto:

- ``erro_px``: a distância entre o quadrado branco que a prévia mostra e o
  centro que a caixa de seleção anuncia. Zero é a imagem acompanhando a mão;
  o fundo desfocado reduz o branco abaixo de 235, então só a frente é achada;
- ``margem_errada``: passos em que a faixa descoberta mostra o que não devia.
  Com a opção ligada, o certo é o borrão (vermelho à esquerda, azul à direita)
  e **nunca** o verde da trilha de baixo; com ela desligada, o verde;
- ``assenta_ms``: do último movimento até a prévia mostrar a pose final.

Cada variante é um caminho diferente do arrasto:

- ``sem_fundo_pequeno``: camadas prontas (a textura se move na hora);
- ``fundo_visivel``: o fundo já aparece parado, então o gesto compõe pelo ffmpeg;
- ``fundo_16x9_neutro``: o bloco preenche a tela parado e o fundo só aparece
  quando ele sai do lugar — a regra que decide o caminho olha a pose de
  **antes** do gesto;
- ``sem_fundo_16x9_neutro``: o mesmo bloco sem a opção, para separar o custo do
  fundo do custo de mover um bloco que descobre a tela.

Números absolutos mudam de máquina para máquina: compare as variantes entre si,
na mesma execução.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TELA = (640, 360)
PASSOS, SALTO_PX, INTERVALO_S = 40, 6, 0.016


def _fonte(pasta: Path, tools, tipo: str):
    """Metade vermelha, metade azul, quadrado branco no centro."""
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.domain.project import media_ref
    desenho = ("color=c=red:s=320x180:r=30:d=6,drawbox=x=160:y=0:w=160:h=180:color=blue:t=fill,"
               "drawbox=x=140:y=70:w=40:h=40:color=white:t=fill")
    destino = pasta / ("fonte.png" if tipo == "foto" else "fonte.mp4")
    saida = ["-frames:v", "1"] if tipo == "foto" else ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    subprocess.run([tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", desenho,
                    *saida, str(destino)], check=True)
    verde = pasta / "verde.png"
    subprocess.run([tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=lime:s=320x180", "-frames:v", "1", str(verde)], check=True)
    return media_ref(probe_file(destino, tools)), media_ref(probe_file(verde, tools))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--varrer", choices=("foto", "video"), default="foto")
    parser.add_argument("--repeticoes", type=int, default=3)
    parser.add_argument("--so", help="uma variante só")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="vm-arrasto-fundo-") as pasta_txt:
        pasta = Path(pasta_txt)
        for chave in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            os.environ[chave] = str(pasta / chave)
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from videomanager.app import build_app
        from videomanager.domain.project import Clip, Project, Track, TrackKind
        from videomanager.infrastructure.system.binaries import find_tools

        tools = find_tools()
        fonte, verde = _fonte(pasta, tools, args.varrer)
        tem_fundo = "blur_background" in Clip.__dataclass_fields__
        variantes = {
            "sem_fundo_pequeno": dict(scale_x=.5, scale_y=.5, x=.3),
            "fundo_visivel": dict(scale_x=.5, scale_y=.5, x=.3, fundo=True),
            "fundo_16x9_neutro": dict(fundo=True),
            "sem_fundo_16x9_neutro": dict(),
        }
        app, janela = build_app([], audio_enabled=False)
        painel, previa = janela._edit, janela._edit._preview
        janela.resize(1920, 1080)
        janela._tabs.setCurrentIndex(2)
        janela.show()
        previa.setFixedSize(*TELA)

        def esperar(teste, prazo: float = 15.0) -> bool:
            fim = time.monotonic() + prazo
            while not teste() and time.monotonic() < fim:
                app.processEvents()
                time.sleep(.001)
            return teste()

        def sonda(imagem, x: int, y: int):
            c = imagem.pixelColor(max(0, min(imagem.width() - 1, x)), max(0, min(imagem.height() - 1, y)))
            return c.red(), c.green(), c.blue()

        def quadrado(imagem, cy: int) -> float | None:
            """x do centro do quadrado branco na linha ``cy`` (o borrão nunca passa de 235)."""
            xs = [x for x in range(imagem.width()) if min(sonda(imagem, x, cy)) > 235]
            return sum(xs) / len(xs) if xs else None

        resultado = {}
        for nome, pose in variantes.items():
            if args.so and nome != args.so:
                continue
            fundo = pose.pop("fundo", False)
            if fundo and not tem_fundo:
                resultado[nome] = "indisponível nesta versão"
                continue
            extra = {"blur_background": True} if fundo else {}
            baixo = Clip(verde, 0, 8)
            bloco = Clip(fonte, 0, 6, **pose, **extra)
            projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(bloco,)),
                                      Track(TrackKind.VIDEO, clips=(baixo,))), width=TELA[0], height=TELA[1])
            medidas: dict[str, list] = {"erro_px": [], "paint_ms": [], "assenta_ms": [], "margem_errada": [],
                                        "passos": [], "pecas_no_fim": []}
            for _ in range(args.repeticoes):
                painel._apply(projeto)
                painel._timeline.select(bloco.clip_id)
                esperar(lambda: previa.has_frame and not painel._frame_busy)
                camadas_prontas = esperar(lambda: previa._interaction_layers is not None, 4.0)
                previa.set_snap_enabled(False)
                cx, cy, w, h = previa._clip_geometry(previa._active_clip)
                inicio = QPoint(round(cx), round(cy))
                QTest.mousePress(previa, Qt.MouseButton.LeftButton, pos=inicio)
                erros, errada = [], 0
                for passo in range(1, PASSOS + 1):
                    alvo = inicio + QPoint(passo * SALTO_PX, 0)
                    t0 = time.perf_counter()
                    QTest.mouseMove(previa, alvo)
                    app.processEvents()
                    medidas["paint_ms"].append((time.perf_counter() - t0) * 1000)
                    gx, gy, gw, gh = previa._clip_geometry(previa._active_clip)
                    imagem = previa.grab().toImage()
                    x_visto = quadrado(imagem, round(gy))
                    erros.append(abs(x_visto - gx) if x_visto is not None else 999.0)
                    # Faixa descoberta do lado esquerdo do bloco, a meio da altura da tela.
                    esquerda = gx - gw / 2
                    if esquerda > 24:
                        r, g, b = sonda(imagem, round(esquerda / 2), round(TELA[1] * .15))
                        e_verde = g > 200 and r < 80
                        errada += (e_verde if fundo else not e_verde)
                    time.sleep(INTERVALO_S)
                final = previa._clip_geometry(previa._active_clip)
                t1 = time.perf_counter()
                QTest.mouseRelease(previa, Qt.MouseButton.LeftButton, pos=alvo)
                esperar(lambda: not painel._frame_busy, 10.0)

                def na_pose() -> bool:
                    x_visto = quadrado(previa.grab().toImage(), round(final[1]))
                    return x_visto is not None and abs(x_visto - final[0]) <= 2

                esperar(na_pose, 5.0)
                medidas["assenta_ms"].append((time.perf_counter() - t1) * 1000)
                medidas["erro_px"].extend(erros)
                medidas["margem_errada"].append(errada)
                medidas["passos"].append(PASSOS)
                medidas["pecas_no_fim"].append(bool(camadas_prontas))
            resultado[nome] = {
                "caminho": "camadas prontas" if all(medidas["pecas_no_fim"]) else "ffmpeg por quadro",
                "erro_px_mediana": round(statistics.median(medidas["erro_px"]), 1),
                "erro_px_p95": round(sorted(medidas["erro_px"])[int(len(medidas["erro_px"]) * .95) - 1], 1),
                "paint_ms_mediana": round(statistics.median(medidas["paint_ms"]), 1),
                "margem_errada": f'{sum(medidas["margem_errada"])}/{sum(medidas["passos"])}',
                "assenta_ms_mediana": round(statistics.median(medidas["assenta_ms"]), 0),
            }
        painel.shutdown()
        esperar(lambda: painel._runner.active == 0 and painel._background.active == 0)
        painel._session.mark_saved()
        janela.close()
    print(json.dumps(resultado, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
