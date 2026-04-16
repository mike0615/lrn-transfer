"""
lrn_transfer/state.py — SQLite state database.

Tracks every file transfer (outbound and inbound) to prevent duplicates
and provide a full audit trail queryable from the CLI.
"""

import hashlib
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS transfers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,           -- Unix timestamp
    direction   TEXT    NOT NULL,           -- 'out' or 'in'
    filename    TEXT    NOT NULL,
    size_bytes  INTEGER,
    sha256      TEXT,
    status      TEXT    NOT NULL,           -- 'ok', 'error', 'skipped'
    message     TEXT,                       -- error detail or notes
    remote_host TEXT
);

CREATE INDEX IF NOT EXISTS idx_direction_filename ON transfers (direction, filename);
CREATE INDEX IF NOT EXISTS idx_ts ON transfers (ts);
"""


class Direction(str, Enum):
    OUT = 'out'
    IN  = 'in'


class Status(str, Enum):
    OK      = 'ok'
    ERROR   = 'error'
    SKIPPED = 'skipped'


class StateDB:

    def __init__(self, db_path: str):
        self._path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def record(
        self,
        direction:   str,
        filename:    str,
        status:      str,
        size_bytes:  Optional[int] = None,
        sha256:      Optional[str] = None,
        message:     Optional[str] = None,
        remote_host: Optional[str] = None,
    ):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO transfers
                   (ts, direction, filename, size_bytes, sha256, status, message, remote_host)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), direction, filename, size_bytes, sha256, status, message, remote_host),
            )
        log.debug("State recorded: %s %s %s", direction, filename, status)

    def already_sent(self, filename: str, sha256: str) -> bool:
        """Return True if this file was already successfully sent outbound."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM transfers WHERE direction='out' AND filename=? AND sha256=? AND status='ok'",
                (filename, sha256),
            ).fetchone()
        return row is not None

    def already_received(self, filename: str) -> bool:
        """Return True if this filename was already successfully received inbound."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM transfers WHERE direction='in' AND filename=? AND status='ok'",
                (filename,),
            ).fetchone()
        return row is not None

    def recent(self, limit: int = 50) -> List[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM transfers ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()

    def stats(self) -> dict:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE direction='out' AND status='ok')  AS sent_ok,
                    COUNT(*) FILTER (WHERE direction='out' AND status='error') AS sent_err,
                    COUNT(*) FILTER (WHERE direction='in'  AND status='ok')  AS recv_ok,
                    COUNT(*) FILTER (WHERE direction='in'  AND status='error') AS recv_err
                FROM transfers
            """).fetchone()
        return dict(row) if row else {}


def sha256_file(path: str, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while data := f.read(chunk):
            h.update(data)
    return h.hexdigest()
