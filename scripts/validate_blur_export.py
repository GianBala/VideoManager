"""Mede o que o fundo desfocado custa na exportação: tempo, pico de memória e o arquivo que sai.

    PYTHONPATH=src python scripts/validate_blur_export.py [--tela 1080|2160] [--segundos 5] [--repeticoes 3]
                                                         [--casos mp4,mp4_interpolado,gif,serial,paralelo,fluxo]

Cada caso exporta o **mesmo** bloco 4:3 numa tela 16:9 — com laterais, então o
fundo aparece — sem e com a opção, em rodadas alternadas (a ordem fixa
favorece quem roda segundo, com o disco e a memória já quentes). Cada
exportação roda num processo próprio: o pico de memória é o ``ru_maxrss`` do
processo filho e dos que ele esperou, ou seja o do ffmpeg, que é quem pesa — o
do **maior** processo, e não a soma: nos trechos paralelos cada ffmpeg tem o
seu, e a soma é o número de trechos vezes este.

Por caso, a mediana de:

- ``tempo_s`` e ``pico_mb``;
- ``quadros`` e ``duracao_s`` do arquivo (``ffprobe -count_frames``): têm de
  ser iguais com e sem o fundo;
- ``anunciado_mb``: o que ``render_cost.interpolation_bytes`` promete antes de
  a exportação entrar na fila — só nos casos interpolados. O fundo não passa
  pelo ``minterpolate``, então o número não pode mudar.

``fluxo`` não exporta: gera o fluxo de quadros da **reprodução** da mesma
montagem de ``validate_playback.py`` (``montagem_reduzida``, sem o texto, com e
sem o fundo nos dois vídeos) e mede quanto o ffmpeg leva para produzir 9 s de mídia, que é
a folga da reprodução em tempo real — um número sem a oscilação dos
``rajadas`` e ``engasgos`` da interface.

``mp4_interpolado`` e ``paralelo`` sobem a taxa de 24 para 60 fps com o
``minterpolate``, que pede **1,6 GB a 1080p e 5,6 GB a 4K** por trecho: este
script se recusa a rodá-los em 4K, e a 1080p confere a memória livre antes.
Para ``serial`` × ``paralelo`` o número de trechos é forçado (1 e 2), e a
verificação é a mesma duração e os mesmos quadros nos dois.
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

CASOS = ("mp4", "mp4_interpolado", "gif", "serial", "paralelo", "fluxo")


def _memoria_livre_mb() -> int:
    for linha in Path("/proc/meminfo").read_text().splitlines():
        if linha.startswith("MemAvailable:"):
            return int(linha.split()[1]) // 1024
    return 0


def _filho(args: argparse.Namespace) -> int:
    """Uma exportação, num processo só: o pai mede o que ela custou."""
    from videomanager.domain.composition import Composition
    from videomanager.domain.project import Clip, Project, Track, TrackKind, media_ref
    from videomanager.infrastructure.ffmpeg import converter as conversor
    from videomanager.infrastructure.ffmpeg.converter import Converter, probe_file
    from videomanager.infrastructure.system.binaries import find_tools

    tools = find_tools()
    config = json.loads(args.filho)
    if config["formato"] == "fluxo":
        return _filho_fluxo(config, tools)
    media = media_ref(probe_file(Path(config["fonte"]), tools))
    extra = {"blur_background": True} if config["fundo"] else {}
    projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(media, 0.0, config["segundos"], **extra),)),),
                      width=config["largura"], height=config["altura"], fps=config["fps"])
    if config["trechos"]:
        conversor.plan_segments = lambda _composicao, n=config["trechos"]: n
    destino = Path(config["saida"])
    composicao = Composition(projeto, config["formato"], interpolate=config["interpolar"])
    inicio = time.perf_counter()
    Converter(probe_file(Path(config["fonte"]), tools), composicao, destino, tools).run()
    print(json.dumps({"tempo_s": time.perf_counter() - inicio}))
    return 0


def _filho_fluxo(config: dict, tools) -> int:
    """O fluxo da reprodução da montagem, de 3 s até o fim, despejado no vazio."""
    from videomanager.domain.keyframe import Keyframe
    from videomanager.domain.project import Clip, MediaKind, MediaRef, Project, Track, TrackKind, media_ref
    from videomanager.infrastructure.ffmpeg.composer import playback_command
    from videomanager.infrastructure.ffmpeg.converter import probe_file
    from videomanager.infrastructure.system.binaries import subprocess_kwargs

    a, b, foto = (media_ref(probe_file(Path(config[n]), tools)) for n in ("fonte", "fonte_b", "fonte_foto"))
    extra = {"scale": .7, "scale_x": .7, "scale_y": .7}
    if config["fundo"]:
        extra["blur_background"] = True
    ca, cb = Clip(a, 0.0, 6.0, **extra), Clip(b, 6.0, 6.0, in_point=1.0, **extra)
    transicao = Clip(MediaRef(Path("Transição_x"), MediaKind.IMAGE, duration=1.0), 5.5, 1.0, overlay_type="transition",
                     transition_name="dissolve", transition_left_id=ca.clip_id, transition_right_id=cb.clip_id)
    animacao = (Keyframe(0.0, x=0.2, y=0.3, scale_x=0.3, scale_y=0.3, opacity=0.2),
                Keyframe(4.0, x=0.8, y=0.6, scale_x=0.5, scale_y=0.5, opacity=1.0, rotation=40))
    cfoto = Clip(foto, 1.0, 9.0, keyframes=animacao, x=0.2, y=0.3, scale=0.3, scale_x=0.3, scale_y=0.3)
    # Sem o texto da cena do ``validate_playback.py``: a imagem dele sai do Qt, que este roteiro não abre.
    projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(cfoto,)),
                              Track(TrackKind.VIDEO, clips=(ca, transicao, cb))), width=1920, height=1080, fps=30.0)
    comando = playback_command(projeto, 3.0, (config["largura"], config["altura"]), tools, fps=30.0)
    inicio = time.perf_counter()
    subprocess.run(comando, check=True, **{**subprocess_kwargs(), "stdout": subprocess.DEVNULL})
    print(json.dumps({"tempo_s": time.perf_counter() - inicio, "midia_s": projeto.duration - 3.0}))
    return 0


def _contar(arquivo: Path, tools_ffprobe: str) -> tuple[int, float]:
    saida = subprocess.run(
        [tools_ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
         "stream=nb_read_frames:format=duration", "-of", "json", str(arquivo)],
        capture_output=True, text=True, check=True).stdout
    dados = json.loads(saida)
    return int(dados["streams"][0]["nb_read_frames"]), float(dados["format"]["duration"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tela", type=int, choices=(1080, 2160), default=1080)
    parser.add_argument("--segundos", type=float, default=5.0)
    parser.add_argument("--repeticoes", type=int, default=3)
    parser.add_argument("--casos", default=",".join(CASOS))
    parser.add_argument("--filho", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.filho:
        return _filho(args)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from videomanager.infrastructure.system.binaries import find_tools, subprocess_kwargs
    tools = find_tools()
    casos = [c for c in args.casos.split(",") if c]
    pasta = Path(tempfile.mkdtemp(prefix="vm-export-fundo-"))
    altura = args.tela
    largura = altura * 16 // 9
    fonte_w = altura * 4 // 3

    def fonte(nome: str, fps: int) -> Path:
        destino = pasta / nome
        subprocess.run([tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"testsrc2=s={fonte_w}x{altura}:r={fps}:d={args.segundos + 1}", "-c:v", "libx264",
                        "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(destino)], check=True,
                       **subprocess_kwargs())
        return destino

    resultado: dict[str, dict] = {}
    for caso in casos:
        interpolado = caso in ("mp4_interpolado", "serial", "paralelo")
        if interpolado and args.tela == 2160:
            resultado[caso] = "recusado: o minterpolate pede 5,6 GB por trecho a 4K"
            continue
        if interpolado and _memoria_livre_mb() < 5000:
            resultado[caso] = f"recusado: só há {_memoria_livre_mb()} MB livres e o caso pede cerca de 5000"
            continue
        if caso == "fluxo":
            fontes = {"fonte": ("testsrc2=s=1920x1080:r=30:d=12", "a.mp4"), "fonte_b": ("mandelbrot=s=1280x720:r=30", "b.mp4")}
            caminhos = {}
            for chave, (filtro, nome) in fontes.items():
                caminhos[chave] = str(pasta / nome)
                subprocess.run([tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", filtro,
                                *(["-t", "10"] if chave == "fonte_b" else []), "-c:v", "libx264", "-preset", "veryfast",
                                "-g", "60", str(caminhos[chave])], check=True, **subprocess_kwargs())
            caminhos["fonte_foto"] = str(pasta / "foto.png")
            subprocess.run([tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=orange:s=800x600", "-frames:v", "1", str(caminhos["fonte_foto"])], check=True,
                           **subprocess_kwargs())
            medidas = {False: [], True: []}
            for rodada in range(args.repeticoes):
                for fundo in ((False, True) if rodada % 2 == 0 else (True, False)):
                    config = dict(caminhos, fundo=fundo, formato="fluxo", largura=1920, altura=1080)
                    processo = subprocess.Popen([sys.executable, __file__, "--filho", json.dumps(config)],
                                                stdout=subprocess.PIPE, text=True,
                                                env={**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "src")})
                    _, estado, uso = os.wait4(processo.pid, 0)
                    if estado != 0:
                        raise SystemExit(f"o fluxo falhou (estado {estado}) com fundo={fundo}")
                    medidas[fundo].append({**json.loads(processo.stdout.read()), "pico_mb": uso.ru_maxrss / 1024})
            linha = {nome: {"tempo_s": round(statistics.median(m["tempo_s"] for m in medidas[f]), 2),
                            "tempo_s_todos": [round(m["tempo_s"], 2) for m in medidas[f]],
                            "pico_mb": round(statistics.median(m["pico_mb"] for m in medidas[f]), 1)}
                     for f, nome in ((False, "sem"), (True, "com"))}
            midia = medidas[True][0]["midia_s"]
            for nome in ("sem", "com"):
                linha[nome]["vezes_tempo_real"] = round(midia / linha[nome]["tempo_s"], 2)
            linha["custo"] = {"tempo_pct": round(100 * (linha["com"]["tempo_s"] / linha["sem"]["tempo_s"] - 1), 1),
                              "pico_mb": round(linha["com"]["pico_mb"] - linha["sem"]["pico_mb"], 1)}
            resultado[caso] = linha
            continue
        formato = "gif" if caso == "gif" else "mp4"
        fps_tela = 15 if caso == "gif" else 60 if interpolado else 30
        origem = fonte(f"fonte_{caso}.mp4", 24 if interpolado or caso == "gif" else 30)
        # O GIF de 1080p não existe de verdade: o app limita a paleta e o tamanho.
        l, a = (640, 360) if caso == "gif" else (largura, altura)
        if caso == "gif":
            origem = pasta / f"fonte_{caso}.mp4"
            subprocess.run([tools.ffmpeg_str, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"testsrc2=s=480x360:r=24:d={args.segundos + 1}", "-c:v", "libx264",
                            "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(origem)], check=True,
                           **subprocess_kwargs())
        medidas: dict[bool, list[dict]] = {False: [], True: []}
        for rodada in range(args.repeticoes):
            for fundo in ((False, True) if rodada % 2 == 0 else (True, False)):
                saida = pasta / f"saida_{caso}_{int(fundo)}_{rodada}.{formato}"
                config = dict(fonte=str(origem), saida=str(saida), fundo=fundo, segundos=args.segundos,
                              largura=l, altura=a, fps=fps_tela, formato=formato, interpolar=interpolado,
                              trechos={"serial": 1, "paralelo": 2}.get(caso, 0))
                comando = [sys.executable, __file__, "--filho", json.dumps(config)]
                processo = subprocess.Popen(comando, stdout=subprocess.PIPE, text=True,
                                            env={**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "src")})
                _, estado, uso = os.wait4(processo.pid, 0)
                texto = processo.stdout.read()
                if estado != 0:
                    resultado[caso] = f"falhou (estado {estado}) com fundo={fundo}"
                    break
                quadros, duracao = _contar(saida, tools.ffprobe_str)
                medidas[fundo].append(dict(tempo_s=json.loads(texto)["tempo_s"], pico_mb=uso.ru_maxrss / 1024,
                                           quadros=quadros, duracao_s=duracao))
                saida.unlink(missing_ok=True)
            else:
                continue
            break
        else:
            linha = {}
            for fundo, nome in ((False, "sem"), (True, "com")):
                linha[nome] = {k: round(statistics.median(m[k] for m in medidas[fundo]), 2)
                               for k in ("tempo_s", "pico_mb", "duracao_s")}
                linha[nome]["quadros"] = sorted({m["quadros"] for m in medidas[fundo]})
            linha["custo"] = {
                "tempo_s": round(linha["com"]["tempo_s"] - linha["sem"]["tempo_s"], 2),
                "tempo_pct": round(100 * (linha["com"]["tempo_s"] / linha["sem"]["tempo_s"] - 1), 1),
                "pico_mb": round(linha["com"]["pico_mb"] - linha["sem"]["pico_mb"], 1),
                "mesmos_quadros": linha["com"]["quadros"] == linha["sem"]["quadros"],
                "mesma_duracao": abs(linha["com"]["duracao_s"] - linha["sem"]["duracao_s"]) < 0.05,
            }
            if interpolado:
                from videomanager.domain.project import Clip, Project, Track, TrackKind, media_ref
                from videomanager.domain.render_cost import interpolation_bytes
                from videomanager.infrastructure.ffmpeg.converter import probe_file
                media = media_ref(probe_file(origem, tools))
                for fundo, nome in ((False, "sem"), (True, "com")):
                    extra = {"blur_background": True} if fundo else {}
                    projeto = Project(tracks=(Track(TrackKind.VIDEO, clips=(Clip(media, 0.0, args.segundos, **extra),)),),
                                      width=l, height=a, fps=fps_tela)
                    linha[nome]["anunciado_mb"] = round(interpolation_bytes(projeto) / 2**20)
            resultado[caso] = linha
    print(json.dumps(resultado, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
