"""Non-blocking single-key stdin polling for interactive CLI sessions."""

from __future__ import annotations

import select
import sys
import time
from contextlib import contextmanager
from typing import Iterator, Optional

# Returned by ``poll_stdin_event`` for scroll gestures (arrows / wheel).
SCROLL_UP = "__scroll_up__"
SCROLL_DOWN = "__scroll_down__"
SCROLL_BOTTOM = "__scroll_bottom__"


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


def _read_stdin_chunk(timeout: float) -> Optional[str]:
    if timeout <= 0 or not sys.stdin.isatty():
        return None

    if sys.platform == "win32":
        import msvcrt

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                return ch if isinstance(ch, str) else ch.decode("utf-8", errors="ignore")
            time.sleep(min(0.05, deadline - time.monotonic()))
        return None

    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    return sys.stdin.read(1)


def _read_esc_sequence(timeout: float = 0.02) -> str:
    """Read bytes following ESC (CSI, SS3, or SGR mouse)."""
    parts: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ch = _read_stdin_chunk(max(0.0, deadline - time.monotonic()))
        if ch is None:
            break
        parts.append(ch)
        joined = "".join(parts)
        # CSI final byte: @ through ~
        if len(joined) >= 2 and joined[0] == "[" and joined[-1].isalpha() and joined[-1] != "<":
            if joined[-1] == "M" and not joined.startswith("[<"):
                break
            if joined[-1] != "M":
                break
        if len(joined) >= 2 and joined[0] == "O" and joined[-1].isalpha():
            break
        if joined.startswith("[<") and joined.endswith("M"):
            break
        if len(joined) > 24:
            break
    return "".join(parts)


def _parse_mouse_wheel(seq: str) -> Optional[str]:
    """Parse SGR mouse sequences (xterm / iTerm / modern VTE)."""
    if not seq.startswith("[<") or not seq.endswith("M"):
        return None
    try:
        payload = seq[2:-1]
        button, _, _ = payload.partition(";")
        code = int(button)
    except ValueError:
        return None
    # 64 = wheel up, 65 = wheel down (SGR extension)
    if code == 64:
        return SCROLL_UP
    if code == 65:
        return SCROLL_DOWN
    return None


def _parse_escape(timeout: float = 0.02) -> str:
    """Map bytes following ESC to scroll tokens or bare escape."""
    rest = _read_esc_sequence(timeout)
    wheel = _parse_mouse_wheel(rest)
    if wheel is not None:
        return wheel
    if rest in ("[A", "OA"):
        return SCROLL_UP
    if rest in ("[B", "OB"):
        return SCROLL_DOWN
    if rest in ("[F", "OF"):
        return SCROLL_BOTTOM
    if rest == "[62~":
        return SCROLL_UP
    if rest == "[63~":
        return SCROLL_DOWN
    return "\x1b"


def poll_stdin_event(timeout: float) -> Optional[str]:
    """Return a key char, scroll token, or ``None`` on timeout."""
    ch = _read_stdin_chunk(timeout)
    if ch is None:
        return None
    if ch == "\x1b":
        return _parse_escape()
    if ch.isalpha():
        return ch.lower()
    return ch


def poll_stdin_key(timeout: float) -> Optional[str]:
    """Return a single pressed key within ``timeout`` seconds, or ``None``."""
    event = poll_stdin_event(timeout)
    if event in (SCROLL_UP, SCROLL_DOWN, SCROLL_BOTTOM):
        return event
    return event
