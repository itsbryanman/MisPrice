"""SQLite storage layer for historical pipeline results.

Replaces flat-file JSON storage with a relational database for
efficient querying and historical result tracking.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default database path (data/misprice.db alongside results.json)
_DEFAULT_DB_PATH = Path(__file__).resolve().parent / "misprice.db"


def _db_path_from_url(url: str) -> str:
    """Extract the file path from a ``sqlite:///`` URL."""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        return url[len(prefix):]
    return url


class ResultStore:
    """Thin wrapper around SQLite for storing pipeline run results.

    Each pipeline run is stored as a JSON blob tagged with a timestamp
    and an optional label.  Individual divergence records are also
    inserted into a normalised table for efficient querying.
    """

    def __init__(self, database_url: str | None = None) -> None:
        if database_url is None:
            from config import DATABASE_URL
            database_url = DATABASE_URL

        self._db_path = _db_path_from_url(database_url)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at      TEXT    NOT NULL,
                label       TEXT,
                result_json TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS divergences (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      INTEGER NOT NULL REFERENCES pipeline_runs(id),
                ticker      TEXT    NOT NULL,
                category    TEXT    NOT NULL,
                title       TEXT,
                kalshi_price       REAL,
                model_probability  REAL,
                divergence         REAL,
                direction          TEXT,
                model_confidence   TEXT,
                recorded_at        TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_divergences_category
                ON divergences(category);
            CREATE INDEX IF NOT EXISTS idx_divergences_run
                ON divergences(run_id);
            """
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save_run(
        self,
        result: dict[str, Any],
        label: str | None = None,
    ) -> int:
        """Persist a full pipeline result and return the ``run_id``."""
        conn = self._connect()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO pipeline_runs (run_at, label, result_json) VALUES (?, ?, ?)",
            (now, label, json.dumps(result, default=str)),
        )
        run_id = cur.lastrowid
        assert run_id is not None

        # Also insert individual divergences for fast querying
        active = result.get("active", [])
        for rec in active:
            conn.execute(
                """
                INSERT INTO divergences
                    (run_id, ticker, category, title, kalshi_price,
                     model_probability, divergence, direction,
                     model_confidence, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    rec.get("ticker", ""),
                    rec.get("category", ""),
                    rec.get("title", ""),
                    rec.get("kalshi_price"),
                    rec.get("model_probability"),
                    rec.get("divergence"),
                    rec.get("direction"),
                    rec.get("model_confidence"),
                    now,
                ),
            )

        conn.commit()
        logger.info("Saved pipeline run %d with %d divergences", run_id, len(active))
        return run_id

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_latest_run(self) -> dict[str, Any] | None:
        """Return the most recent pipeline result, or *None*."""
        conn = self._connect()
        row = conn.execute(
            "SELECT result_json FROM pipeline_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["result_json"])

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        """Return a specific pipeline result by *run_id*."""
        conn = self._connect()
        row = conn.execute(
            "SELECT result_json FROM pipeline_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["result_json"])

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return metadata (without full JSON) for recent runs."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, run_at, label FROM pipeline_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_divergences(
        self,
        category: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query divergence records across all runs."""
        conn = self._connect()
        query = "SELECT * FROM divergences"
        params: list[Any] = []
        if category:
            query += " WHERE category = ?"
            params.append(category)
        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def count_divergences(self, category: str | None = None) -> int:
        """Return total divergence count (for pagination metadata)."""
        conn = self._connect()
        if category:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM divergences WHERE category = ?",
                (category,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM divergences").fetchone()
        return row["cnt"] if row else 0
