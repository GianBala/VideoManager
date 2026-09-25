"""Mede a reprodução do editor: pré-carga, ritmo, velocidade da mídia e emenda do loop.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python scripts/validate_playback.py [--repeticoes 3]

Gera vídeos sintéticos e toca duas cenas — um arquivo só, e uma montagem com
transição, foto animada e texto — sem placa de som, então o relógio é o fluxo
de quadros. Para cada cena, a mediana das repetições de:

- ``pre_carga_pronta`` e ``primeiro_quadro_ms``: o play depois da busca, com o
  fluxo já preparado; ``primeiro_quadro_frio_ms``, o play logo depois da busca;
- ``quadros_em_4s`` e ``midia_em_4s``: contados até exatamente 4 s depois do
  play. A 30 q/s são 120 quadros e 3,967 s de mídia — menos é quadro perdido,
  mais é rajada;
- ``intervalo_mediana_ms``/``intervalo_p95_ms``, ``rajadas`` (< 20 ms) e
  ``engasgos`` (> 66 ms) entre quadros;
- ``emenda_loop_ms``: o intervalo no quadro em que o loop volta ao começo.

Com ``--trocar-idioma``, cada reprodução medida troca a interface para o
inglês 1 s depois do play e de volta 1,5 s depois: a troca não pode parar o
fluxo nem abrir outro, e o que ela custa aparece nas mesmas medidas — compare
com uma execução sem a opção.

Números absolutos mudam de máquina para máquina: compare com a base, na mesma
máquina e sem outra carga. Uma contagem que não termina num instante fixo mede
a espera do próprio script — foi o que fez 127 × 120 quadros parecer regressão.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _midia(pasta: Path, tools) -> dict[str, Path]:
    from videomanager.infrastructure.system.binaries import subprocess_kwargs
    receitas = {
        "a.mp4": ["-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=12", "-c:v", "libx264",
                  "-preset", "veryfast", "-g", "60"],
        "b.mp4": ["-f", "lavfi", "-i", "mandelbrot=s=1280x720:r=30", "-t", "10", "-c:v", "libx264",
                  "-preset", "veryfast", "-g", "60"],
        "foto.png": ["-f", "lavfi", "-i", "color=c=orange:s=800x600", "-frames:v", "1"],
    }
    for nome, args in receitas.items():
        subprocess.run([tools.ffmpeg_str, "-nostdin", "-v", "error", "-y", *args, str(pasta / nome)],
                       check=True, **subprocess_kwargs())
    return {nome: pasta / nome for nome in receitas}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeticoes", type=int, default=3)
    parser.add_argument("--trocar-idioma", action="store_true",
                        help="troca o idioma durante cada reprodução medida (1 s e 2,5 s depois do play)")
    args = parser.parse_args()
    perfil = Path(tempfile.mkdtemp(prefix="vm-reproducao-"))
    for chave in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        os.environ[chave] = str(perfil / chave)

    from PySide6.QtCore import QEventLoop, QTimer
    from videomanager.app import build_app
    from videomanager.application.media.preview import playback_clock
    from videomanager.domain.keyframe import Keyframe
    from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, media_ref
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.system.binaries import find_tools

    tools = find_tools()
    if tools is None:
        print("ffmpeg não encontrado.", file=sys.stderr)
        return 2
    arquivos = _midia(perfil, tools)
    A, B, FOTO = (media_ref(probe_file(arquivos[n], tools)) for n in ("a.mp4", "b.mp4", "foto.png"))
    app, janela = build_app([], audio_enabled=False)
    janela.resize(1920, 1040)
    janela.show()
    janela._tabs.setCurrentIndex(2)
    painel = janela._edit

    def rodar(ms: int) -> None:
        laco = QEventLoop()
        QTimer.singleShot(ms, laco.quit)
        laco.exec()

    def esperar(condicao, prazo: float = 20.0) -> bool:
        fim = time.perf_counter() + prazo
        while not condicao() and time.perf_counter() < fim:
            rodar(5)
        return condicao()

    mostrados: list[tuple[float, float, bool]] = []
    original = painel._show_frame

    def espiao(quadro):
        mostrados.append((playback_clock(), quadro.seconds, painel._playing))
        original(quadro)

    painel._show_frame = espiao

    def cena(nome: str) -> Project:
        if nome == "simples":
            return Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(A, 0.0, 12.0),)),), width=1920, height=1080,
                           fps=30.0)
        a, b = Clip(A, 0.0, 6.0), Clip(B, 6.0, 6.0, in_point=1.0)
        transicao = Clip(MediaRef(Path("Transição_x"), MediaKind.IMAGE, duration=1.0), 5.5, 1.0,
                         overlay_type="transition", transition_name="dissolve",
                         transition_left_id=a.clip_id, transition_right_id=b.clip_id)
        animacao = (Keyframe(0.0, x=0.2, y=0.3, scale_x=0.3, scale_y=0.3, opacity=0.2),
                    Keyframe(4.0, x=0.8, y=0.6, scale_x=0.5, scale_y=0.5, opacity=1.0, rotation=40))
        foto = Clip(FOTO, 1.0, 9.0, keyframes=animacao, x=0.2, y=0.3, scale=0.3, scale_x=0.3, scale_y=0.3)
        texto = Clip(MediaRef(Path("Texto_x"), MediaKind.IMAGE, duration=10.0), 0.5, 10.0, overlay_type="text",
                     text_content="Título de teste", font_size=64)
        return Project(tracks=(Track(TrackKind.ADDITIONAL, clips=(texto,)), Track(TrackKind.VIDEO, clips=(foto,)),
                               Track(TrackKind.VIDEO, clips=(a, transicao, b))), width=1920, height=1080, fps=30.0)

    resultado = {}
    for nome in ("simples", "montagem"):
        painel.install_project(cena(nome), None, [A, B, FOTO], {})
        rodar(300)
        medidas: dict[str, list] = {}
        for _ in range(args.repeticoes):
            painel._loop.setChecked(False)
            painel._seek_to(3.0)
            pronta = esperar(lambda: painel._primed_ready and not painel._frame_busy)
            rodar(200)
            mostrados.clear()
            inicio = playback_clock()
            painel._toggle_play()
            if args.trocar_idioma:
                from videomanager.domain import i18n
                from videomanager.presentation.qt.i18n import apply_language
                QTimer.singleShot(1000, lambda: apply_language(i18n.ENGLISH))
                QTimer.singleShot(2500, lambda: apply_language(i18n.PORTUGUESE))
            rodar(4200)
            painel._toggle_play()
            tocando = [(t - inicio, s) for t, s, p in mostrados if p]
            janela_4s = [(t, s) for t, s in tocando if t <= 4.0]
            intervalos = [(b[0] - a[0]) * 1000 for a, b in zip(tocando, tocando[1:])]
            # Sem pré-carga: play logo depois da busca.
            painel._seek_to(1.0)
            mostrados.clear()
            inicio_frio = playback_clock()
            painel._toggle_play()
            esperar(lambda: any(p for _, _, p in mostrados), 10)
            frio = next(((t - inicio_frio) * 1000 for t, _, p in mostrados if p), None)
            rodar(500)
            painel._toggle_play()
            # Emenda do loop: começa 2 s antes do fim e atravessa a volta.
            painel._loop.setChecked(True)
            painel._seek_to(painel._loop_end - 2.0)
            esperar(lambda: painel._primed_ready and not painel._frame_busy)
            rodar(200)
            mostrados.clear()
            painel._toggle_play()
            rodar(3500)
            painel._toggle_play()
            painel._loop.setChecked(False)
            volta = [(t, s) for t, s, p in mostrados if p]
            emenda = next(((volta[i][0] - volta[i - 1][0]) * 1000 for i in range(1, len(volta))
                           if volta[i][1] < volta[i - 1][1] - 1.0), None)
            for chave, valor in (("pre_carga_pronta", pronta),
                                 ("primeiro_quadro_ms", tocando[0][0] * 1000 if tocando else None),
                                 ("primeiro_quadro_frio_ms", frio),
                                 ("quadros_em_4s", len(janela_4s)),
                                 ("midia_em_4s", (janela_4s[-1][1] - 3.0) if janela_4s else None),
                                 ("intervalo_mediana_ms", statistics.median(intervalos) if intervalos else None),
                                 ("intervalo_p95_ms", sorted(intervalos)[int(len(intervalos) * 0.95)] if intervalos else None),
                                 ("rajadas", sum(1 for i in intervalos if i < 20)),
                                 ("engasgos", sum(1 for i in intervalos if i > 66)),
                                 ("emenda_loop_ms", emenda)):
                medidas.setdefault(chave, []).append(valor)
        resultado[nome] = {
            chave: (all(valores) if chave == "pre_carga_pronta"
                    else round(statistics.median([v for v in valores if v is not None]), 3)
                    if any(v is not None for v in valores) else None)
            for chave, valores in medidas.items()
        }
    painel.shutdown()
    janela.close()
    print(json.dumps(resultado, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
