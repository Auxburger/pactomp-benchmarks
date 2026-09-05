"""Child-process bookkeeping: every process this driver starts is terminated
on exit, whether the sweep finishes or a signal cuts it short.
"""

from __future__ import annotations

import signal
import subprocess
import sys

CHILDREN: "list[subprocess.Popen]" = []


def register(proc: subprocess.Popen) -> subprocess.Popen:
    CHILDREN.append(proc)
    return proc


def unregister(proc: subprocess.Popen) -> None:
    if proc in CHILDREN:
        CHILDREN.remove(proc)


def terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def install_signal_handlers(log, on_signal=None) -> None:
    """Terminate every registered child on SIGINT/SIGTERM.

    `on_signal` runs first, for drivers that have their own worker threads to
    stop before the children go away.
    """

    def handler(signum, _frame):
        log(f"received signal {signum}, terminating {len(CHILDREN)} child process(es)")
        if on_signal is not None:
            on_signal()
        for proc in list(CHILDREN):
            try:
                terminate(proc)
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass
        sys.exit(128 + signum)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
