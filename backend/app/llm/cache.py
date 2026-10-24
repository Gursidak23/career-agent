"""Hash-keyed cache for LLM completions.

Identical prompts (same provider chain, system/user text, temperature, and token
budget) return the cached response instead of re-calling the API. This is a big
win during iterative resume tweaking where the same parse/tailor calls repeat.

In-memory by default (with TTL); optionally persisted to a SQLite table so the
cache survives restarts.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path


def make_key(provider_chain: str, system: str, user: str, temperature: float, max_tokens: int) -> str:
    h = hashlib.sha256()
    h.update(provider_chain.encode("utf-8"))
    h.update(b"\x00")
    h.update(system.encode("utf-8"))
    h.update(b"\x00")
    h.update(user.encode("utf-8"))
    h.update(b"\x00")
    h.update(f"{temperature:.4f}|{max_tokens}".encode("utf-8"))
    return h.hexdigest()


class LlmCache:
    """Thread-safe in-memory TTL cache with optional SQLite persistence."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        ttl_seconds: int = 86_400,
        persist_path: str | Path | None = None,
    ) -> None:
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds
        self._mem: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self.hits = 0
        self.misses = 0
        if persist_path:
            self._conn = sqlite3.connect(str(persist_path), check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS llm_cache "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL, created_at REAL NOT NULL)"
            )
            self._conn.commit()

    def get(self, key: str) -> str | None:
        if not self.enabled:
            return None
        now = time.time()
        with self._lock:
            entry = self._mem.get(key)
            if entry is not None:
                created, value = entry
                if now - created <= self.ttl_seconds:
                    self.hits += 1
                    return value
                self._mem.pop(key, None)
            if self._conn is not None:
                row = self._conn.execute(
                    "SELECT value, created_at FROM llm_cache WHERE key = ?", (key,)
                ).fetchone()
                if row is not None:
                    value, created = row[0], row[1]
                    if now - created <= self.ttl_seconds:
                        self._mem[key] = (created, value)
                        self.hits += 1
                        return value
                    self._conn.execute("DELETE FROM llm_cache WHERE key = ?", (key,))
                    self._conn.commit()
        self.misses += 1
        return None

    def set(self, key: str, value: str) -> None:
        if not self.enabled:
            return
        now = time.time()
        with self._lock:
            self._mem[key] = (now, value)
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO llm_cache (key, value, created_at) VALUES (?, ?, ?)",
                    (key, value, now),
                )
                self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            self._mem.clear()
            if self._conn is not None:
                self._conn.execute("DELETE FROM llm_cache")
                self._conn.commit()

    def stats(self) -> dict[str, int | bool]:
        return {"enabled": self.enabled, "hits": self.hits, "misses": self.misses}
