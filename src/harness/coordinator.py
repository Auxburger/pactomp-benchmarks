"""The DRM coordinator, run for one thread count at a time as test_all.sh does."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from . import children
from .logging_utils import fmt_cpus, log, now


class Coordinator:
    """Start the coordinator with POMP_CAPACITY=<threads> and stop it on exit."""

    def __init__(self, binary: Path, capacity: int, cpus: "list[int]", log_path: Path, socket: Path):
        self.binary = binary
        self.capacity = capacity
        self.cpus = cpus
        self.log_path = log_path
        self.socket = socket
        self.proc: "subprocess.Popen | None" = None
        self._log_file = None

    def __enter__(self) -> "Coordinator":
        if self.socket.exists():
            self.socket.unlink()

        env = os.environ.copy()
        env["POMP_CAPACITY"] = str(self.capacity)
        env["POMP_CPU_LIST"] = fmt_cpus(self.cpus)
        env.setdefault("RUST_LOG", "info")

        self._log_file = self.log_path.open("a", encoding="utf-8")
        self._log_file.write(
            f"Starting DRM at {now()}, capacity={self.capacity}, cpu_pool={env['POMP_CPU_LIST']}\n"
        )
        self._log_file.flush()

        self.proc = children.register(
            subprocess.Popen(
                [str(self.binary)],
                env=env,
                stdout=self._log_file,
                stderr=subprocess.STDOUT,
                preexec_fn=lambda: os.nice(15),
            )
        )
        self._await_socket()
        log(f"DRM up: capacity={self.capacity} cpu_pool={env['POMP_CPU_LIST']}")
        return self

    def _await_socket(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.socket.exists():
                return
            if self.proc is not None and self.proc.poll() is not None:
                raise SystemExit(f"DRM exited immediately (see {self.log_path})")
            time.sleep(0.05)
        log(f"WARNING: {self.socket} did not appear within {timeout}s")

    def __exit__(self, *exc) -> None:
        if self.proc is not None:
            children.terminate(self.proc)
            children.unregister(self.proc)
        if self._log_file is not None:
            self._log_file.write(f"DRM stopped at {now()}, was capacity={self.capacity}\n")
            self._log_file.close()


class NoCoordinator:
    """Stand-in for --no-drm, so the sweep keeps one code path."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc) -> None:
        return None
