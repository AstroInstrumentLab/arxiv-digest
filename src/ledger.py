"""SQLite 台账：跨天去重、状态跟踪、运行记录。"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    arxiv_id    TEXT PRIMARY KEY,
    title       TEXT,
    submitted   TEXT,
    first_seen  TEXT,
    score       INTEGER,
    channel     TEXT,
    status      TEXT,
    tier        TEXT,
    payload     TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT,
    finished_at TEXT,
    fetched     INTEGER,
    candidates  INTEGER,
    reported    INTEGER,
    endpoint    TEXT,
    status      TEXT,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_papers_submitted ON papers(submitted);
"""


class Ledger:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def known_ids(self) -> set[str]:
        return {row[0] for row in self.conn.execute("SELECT arxiv_id FROM papers")}

    def last_success(self) -> dt.datetime | None:
        row = self.conn.execute(
            "SELECT finished_at FROM runs WHERE status='ok' ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
        if not row or not row[0]:
            return None
        return dt.datetime.fromisoformat(row[0])

    def record_paper(self, paper: dict, score: int, channel: str, status: str) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO papers (arxiv_id, title, submitted, first_seen, score, channel, status, tier, payload)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(arxiv_id) DO UPDATE SET
                   score=excluded.score, channel=excluded.channel, payload=excluded.payload""",
            (paper["arxiv_id"], paper.get("title", ""), paper.get("published", ""), now,
             score, channel, status, None, json.dumps(paper, ensure_ascii=False)),
        )

    def record_run(self, run_id: str, started: str, fetched: int, candidates: int,
                   reported: int, status: str, error: str = "", endpoint: str = "") -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, started_at, finished_at, fetched, candidates, reported, endpoint, status, error)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (run_id, started, dt.datetime.now(dt.timezone.utc).isoformat(), fetched,
             candidates, reported, endpoint, status, error),
        )
        self.conn.commit()

    def stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        reported = self.conn.execute("SELECT COUNT(*) FROM papers WHERE status='reported'").fetchone()[0]
        runs = self.conn.execute("SELECT COUNT(*) FROM runs WHERE status='ok'").fetchone()[0]
        return {"papers": total, "reported": reported, "ok_runs": runs}

    def close(self) -> None:
        self.conn.close()