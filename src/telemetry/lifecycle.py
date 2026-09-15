"""Graceful-shutdown gate used by HTTP and worker entry points."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Condition


class ShutdownGate:
    """Stop admission of new work and wait for safe in-flight steps."""

    def __init__(self) -> None:
        self._condition = Condition()
        self._accepting = True
        self._active = 0

    @property
    def accepting(self) -> bool:
        with self._condition:
            return self._accepting

    def stop_accepting(self) -> None:
        with self._condition:
            self._accepting = False
            self._condition.notify_all()

    @contextmanager
    def admission(self) -> Iterator[bool]:
        with self._condition:
            if not self._accepting:
                yield False
                return
            self._active += 1
        try:
            yield True
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def wait_for_idle(self, timeout: float) -> bool:
        if timeout < 0:
            raise ValueError("timeout must not be negative")
        with self._condition:
            return self._condition.wait_for(lambda: self._active == 0, timeout=timeout)


__all__ = ["ShutdownGate"]
