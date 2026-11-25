"""Process-shared local locks. These do not claim distributed Azure protection."""

from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .contracts import LabError, sha256

if os.name == "nt":
    import msvcrt
else:
    import fcntl


@contextmanager
def resource_locks(root: Path, keys: list[str], timeout: float = 5) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    held = []
    deadline = time.monotonic() + timeout
    try:
        for key in sorted(set(keys)):
            stream = (root / (sha256(key.encode("utf-8")) + ".lock")).open("a+b")
            try:
                if stream.seek(0, os.SEEK_END) == 0:
                    stream.write(b"\0")
                    stream.flush()
                while True:
                    stream.seek(0)
                    try:
                        if os.name == "nt":
                            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                            raise
                        if time.monotonic() >= deadline:
                            raise LabError("Resource lock timeout") from exc
                        time.sleep(0.01)
                held.append(stream)
            finally:
                if stream not in held:
                    stream.close()
        yield
    finally:
        for stream in reversed(held):
            try:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()
