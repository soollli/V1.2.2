from __future__ import annotations
from pathlib import Path
import os


class ProcessLock:
    """Simple cross-platform PID lock to prevent duplicate trading engines."""

    def __init__(self, path: Path):
        self.path = path
        self.acquired = False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                old_pid = int(self.path.read_text(encoding="utf-8").strip())
            except Exception:
                old_pid = -1
            if self._pid_alive(old_pid):
                raise RuntimeError(
                    f"Trading engine already running (pid={old_pid}, lock={self.path}). "
                    "Stop it before starting another copy."
                )
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

        fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, str(os.getpid()).encode("utf-8"))
        finally:
            os.close(fd)
        self.acquired = True
        return self

    def release(self):
        if self.acquired:
            try:
                current = self.path.read_text(encoding="utf-8").strip()
                if current == str(os.getpid()):
                    self.path.unlink(missing_ok=True)
            finally:
                self.acquired = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
