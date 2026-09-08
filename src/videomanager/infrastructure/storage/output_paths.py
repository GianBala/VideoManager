"""Reserva exclusiva de nomes, independente do processamento de mídia."""
import os
from pathlib import Path
from videomanager.application.errors import ConversionError
from videomanager.application.jobs.requests import ConversionTarget

def output_path(
    source: Path,
    target: ConversionTarget,
    dest_dir: Path | None = None,
    suffix: str = "",
    custom_stem: str | None = None,
) -> Path:
    """Caminho de saída, evitando sobrescrever o arquivo de origem.

    Converter um ``.mp3`` para ``.mp3`` com outro bitrate é um pedido legítimo, e
    sem o sufixo a origem seria destruída no meio da leitura.

    ``suffix`` distingue saídas que nascem do mesmo arquivo — os vários trechos
    de um recorte — sem depender do contador, que só entra em cena quando o nome
    escolhido já existe.

    **O nome é reservado, não apenas consultado.** Esta função é chamada ao
    *enfileirar*, e o ffmpeg só grava minutos depois: "não existe agora" não diz
    nada sobre o instante da gravação. Enquanto era só uma consulta, enfileirar
    duas vezes a mesma origem devolvia o mesmo caminho para as duas tarefas, e a
    segunda sobrescrevia o resultado já pronto da primeira — em silêncio, e com
    o ``-y`` do ffmpeg contra o qual não havia defesa nenhuma. Criar o arquivo
    vazio com ``O_EXCL`` fecha a janela: o nome deixa de estar livre no ato. O
    arquivo de zero byte é sobrescrito pelo próprio ffmpeg, e a limpeza de saída
    parcial em caso de falha ou cancelamento já existia.
    """
    directory = dest_dir or source.parent
    clean_custom = custom_stem.strip() if custom_stem else ""
    stem = clean_custom if clean_custom else f"{source.stem}{suffix}"
    if any(char in stem for char in ('/', '\\', '\0')) or stem in ('.', '..'):
        raise ConversionError("Use somente um nome de arquivo, sem caminhos ou separadores.")
    candidate = directory / f"{stem}.{target.extension}"
    if candidate.resolve() == source.resolve():
        candidate = directory / f"{stem} (convertido).{target.extension}"

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConversionError(
            f"Não foi possível usar a pasta de destino {directory}: {exc}"
        ) from exc

    counter = 2
    while True:
        try:
            os.close(os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            return candidate
        except FileExistsError:
            candidate = directory / f"{stem} ({counter}).{target.extension}"
            counter += 1
        except OSError as exc:
            raise ConversionError(
                f"Não foi possível criar o arquivo de saída em {directory}: {exc}"
            ) from exc
