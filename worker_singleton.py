"""Cross-process singleton locks for room-managed workers."""

from __future__ import annotations

import atexit
import hashlib
import os
import re
import sys
from pathlib import Path


class WorkerAlreadyRunning(RuntimeError):
    """Raised when another process already owns a room worker identity."""


class WorkerLock:
    def __init__(self, agent: str, data_dir: Path):
        self.agent = agent
        self.data_dir = data_dir.resolve()
        self._handle = None
        self._file = None
        self._released = False

    def acquire(self) -> "WorkerLock":
        if sys.platform == "win32":
            self._acquire_windows()
        else:
            self._acquire_unix()
        atexit.register(self.release)
        return self

    def _lock_key(self) -> str:
        identity = f"{self.data_dir}\0{self.agent.lower()}".encode("utf-8")
        return hashlib.sha256(identity).hexdigest()

    def _acquire_windows(self) -> None:
        import ctypes

        error_already_exists = 183
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_bool

        name = f"Local\\AgentChattrWorker-{self._lock_key()}"
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "Could not create worker mutex")
        if ctypes.get_last_error() == error_already_exists:
            kernel32.CloseHandle(handle)
            raise WorkerAlreadyRunning(f"{self.agent} is already running")
        self._handle = (kernel32, handle)

    def _acquire_unix(self) -> None:
        import fcntl

        lock_dir = self.data_dir / "worker-locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        safe_agent = re.sub(r"[^a-zA-Z0-9_.-]+", "-", self.agent).strip("-") or "worker"
        lock_file = open(lock_dir / f"{safe_agent}-{self._lock_key()[:12]}.lock", "a+", encoding="utf-8")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            raise WorkerAlreadyRunning(f"{self.agent} is already running") from None
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        self._file = lock_file

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._handle is not None:
            kernel32, handle = self._handle
            kernel32.CloseHandle(handle)
            self._handle = None
        if self._file is not None:
            import fcntl

            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None

    def __enter__(self) -> "WorkerLock":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


def acquire_worker_lock(agent: str, data_dir: Path) -> WorkerLock:
    """Acquire and retain the singleton lock for one room worker identity."""
    return WorkerLock(agent, data_dir).acquire()
