"""Non-blocking single-key stdin polling for interactive CLI sessions."""

from __future__ import annotations

import select
import sys
from contextlib import contextmanager
from typing import Iterator, Optional


@contextmanager
def cbreak_stdin() -> Iterator[None]:
    """Put stdin in cbreak mode so keys are readable without Enter (TTY only)."""
    if not sys.stdin.isatty():
        yield
        return

    if sys.platform == "win32":
        yield
        return

    import termios
    import tty

    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def poll_stdin_key(timeout: float) -> Optional[str]:
    """Return a single pressed key within ``timeout`` seconds, or ``None``."""
    if timeout <= 0 or not sys.stdin.isatty():
        return None

    if sys.platform == "win32":
        import msvcrt
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                return ch.lower() if isinstance(ch, str) else ch.decode("utf-8", errors="ignore").lower()
            time.sleep(min(0.05, deadline - time.monotonic()))
        return None

    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    ch = sys.stdin.read(1)
    return ch.lower() if ch else None
