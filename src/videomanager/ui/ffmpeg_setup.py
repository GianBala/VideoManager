"""Fluxo de primeira execução: garantir ffmpeg antes de qualquer download.

Chamado na abertura da janela. Se o ffmpeg já existe — empacotado, baixado antes
ou instalado no sistema — não aparece nada na tela.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from ..core import binaries
from ..core.binaries import FFmpegTools
from ..core.humanize import format_size
from ..workers.engine_worker import FFmpegSetupWorker
from ..workers.runner import WorkerRunner
from . import strings

# Tamanho aproximado do download, só para a mensagem de confirmação.
_APPROX_SIZE = 130 * 1024 * 1024


def ensure_ffmpeg(parent: QWidget) -> FFmpegTools | None:
    """Devolve o ffmpeg pronto, baixando com consentimento se preciso.

    ``None`` significa que o usuário recusou ou o download falhou. A aplicação
    continua aberta nesse caso: analisar URLs e ver os formatos funciona sem
    ffmpeg — o que não funciona é juntar vídeo com áudio e converter.
    """
    existing = binaries.find_tools()
    if existing:
        return existing

    # "Baixar agora" em vez de "Sim": o botão diz o que vai acontecer, que é o
    # que se lê primeiro numa caixa de confirmação.
    box = QMessageBox(parent)
    box.setWindowTitle(strings.DIALOG_FFMPEG_TITLE)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(strings.DIALOG_FFMPEG_BODY.format(size=format_size(_APPROX_SIZE)))
    download = box.addButton(
        strings.DIALOG_FFMPEG_DOWNLOAD, QMessageBox.ButtonRole.AcceptRole
    )
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    if box.clickedButton() is not download:
        return None

    dialog = QProgressDialog(
        strings.DIALOG_FFMPEG_PROGRESS.format(done="0 B", total="…"),
        strings.QUEUE_CANCEL, 0, 100, parent,
    )
    dialog.setWindowTitle(strings.DIALOG_FFMPEG_TITLE)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setAutoClose(False)
    dialog.setMinimumDuration(0)

    outcome: dict[str, object] = {}

    def on_progress(received: int, total: int | None) -> None:
        if dialog.wasCanceled():
            return
        dialog.setLabelText(
            strings.DIALOG_FFMPEG_PROGRESS.format(
                done=format_size(received),
                total=format_size(total) if total else "…",
            )
        )
        if total:
            dialog.setValue(int(received * 100 / total))

    def on_finished(tools: object) -> None:
        outcome["tools"] = tools
        dialog.reset()

    def on_failed(message: str) -> None:
        outcome["error"] = message
        dialog.reset()

    worker = FFmpegSetupWorker()
    worker.signals.progress.connect(on_progress)
    worker.signals.finished.connect(on_finished)
    worker.signals.failed.connect(on_failed)
    worker.signals.cancelled.connect(dialog.reset)
    # O botão de cancelar precisa cancelar de verdade: sem isto ele só escondia
    # o diálogo, e o download de 130 MB seguia até o fim numa thread invisível.
    dialog.canceled.connect(worker.cancel)
    # O runner precisa sobreviver ao retorno desta função, então fica pendurado
    # no diálogo, cujo tempo de vida cobre todo o download.
    runner = WorkerRunner()
    dialog._worker_runner = runner  # noqa: SLF001 - ancoragem de tempo de vida
    runner.start(
        worker, worker.signals.finished, worker.signals.failed, worker.signals.cancelled
    )

    # exec() mantém a interface responsiva enquanto o worker trabalha, e o
    # reset() de dentro dos callbacks encerra o laço.
    dialog.exec()

    if "error" in outcome:
        QMessageBox.critical(
            parent,
            strings.DIALOG_FFMPEG_TITLE,
            strings.DIALOG_FFMPEG_FAILED.format(error=outcome["error"]),
        )
        return None

    tools = outcome.get("tools")
    return tools if isinstance(tools, FFmpegTools) else None
