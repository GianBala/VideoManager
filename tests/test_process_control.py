"""Cancelamento e prazo sobre processos reais, incluindo filhos que ignoram SIGTERM."""

import os
import subprocess
import sys
import threading

import pytest

from videomanager.application.errors import JobCancelled
from videomanager.infrastructure.system.process import ProcessControl


def test_cancelar_encerra_filho_bloqueado(tmp_path):
    control = ProcessControl()
    started = tmp_path / "started"
    code = (
        "import time, signal, pathlib; "
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN); " if os.name != "nt" else "")
        + f"pathlib.Path({str(started)!r}).touch(); time.sleep(30)"
    )
    errors = []
    def run():
        try:
            control.run([sys.executable, "-c", code])
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        import time
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists()
        control.cancel()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], JobCancelled)
    finally:
        control.cancel()
        thread.join(timeout=2)


def test_prazo_de_subprocesso_e_respeitado():
    with pytest.raises(subprocess.TimeoutExpired):
        ProcessControl().run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)


def test_cancelamento_antes_de_iniciar_nao_abre_processo(monkeypatch):
    control = ProcessControl()
    control.cancel()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("processo iniciado após cancelar"))
    with pytest.raises(JobCancelled):
        control.run([sys.executable, "-V"])
