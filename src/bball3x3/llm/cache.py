import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


def request_key(request: dict[str, Any]) -> str:
    # sha256 of the canonical json request, so key order does not matter
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

# sqlite response cache keyed by request hash (debug/pilot only)
class LLMCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, value TEXT)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def get(self, key: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute("SELECT value FROM responses WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO responses (key, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
