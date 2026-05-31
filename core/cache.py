"""Tiny thread-safe TTL cache, shared by the OwnTone client and search."""

import threading
import time
from typing import Any


class TTLCache:
    def __init__(self, ttl: float = 30.0):
        self.ttl = ttl
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._data.get(key)
            if hit and (time.monotonic() - hit[0]) < self.ttl:
                return hit[1]
            if hit:
                self._data.pop(key, None)
            return None

    def set(self, key, value):
        with self._lock:
            self._data[key] = (time.monotonic(), value)

    def clear(self):
        with self._lock:
            self._data.clear()
