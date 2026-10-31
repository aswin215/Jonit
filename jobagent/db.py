import json
import sqlite3
import time

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,            -- source:slug:external_id
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    remote INTEGER DEFAULT 0,
    description TEXT,
    apply_url TEXT,
    source TEXT,
    posted_at TEXT,
    dedupe_hash TEXT UNIQUE,
    first_seen REAL,
    status TEXT DEFAULT 'new'       -- new, filtered_out, scored, tailored, applied, skipped
);
CREATE TABLE IF NOT EXISTS matches (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id),
    fit_score INTEGER,
    result_json TEXT,
    decision TEXT,                  -- accept, reject, maybe (set by me)
    scored_at REAL
);
CREATE TABLE IF NOT EXISTS resume_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT REFERENCES jobs(id),
    content_json TEXT,
    markdown_path TEXT,
    keyword_coverage REAL,
    verifier_passed INTEGER,
    issues_json TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT REFERENCES jobs(id),
    resume_version_id INTEGER REFERENCES resume_versions(id),
    applied_at REAL,
    status TEXT DEFAULT 'applied',  -- applied, interviewing, offer, rejected, withdrawn
    notes TEXT DEFAULT '',
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS feed_seen (
    url TEXT PRIMARY KEY,           -- apply link from a curated list, handled once
    job_id TEXT,
    outcome TEXT,                   -- added, filtered, too_old
    seen_at REAL
);
CREATE TABLE IF NOT EXISTS crawl_cache (
    url TEXT PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    body TEXT,
    fetched_at REAL
);
CREATE TABLE IF NOT EXISTS host_pauses (
    host TEXT PRIMARY KEY,
    until REAL,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    task TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read INTEGER,
    cache_write INTEGER,
    cost REAL
);
"""

_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)  # dashboard serves from its own thread
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
    return _conn


def log_usage(**row) -> None:
    c = conn()
    c.execute(
        "INSERT INTO llm_usage (ts, task, model, input_tokens, output_tokens, cache_read, cache_write, cost) "
        "VALUES (:ts, :task, :model, :input_tokens, :output_tokens, :cache_read, :cache_write, :cost)",
        {"ts": time.time(), **row},
    )
    c.commit()


APPLICATION_STATUSES = ["applied", "interviewing", "offer", "rejected", "withdrawn"]


def latest_resume(job_id: str):
    return conn().execute(
        "SELECT * FROM resume_versions WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,)
    ).fetchone()


def record_application(job_id: str, resume_version_id: int | None = None) -> int:
    c = conn()
    if resume_version_id is None:
        version = latest_resume(job_id)
        resume_version_id = version["id"] if version else None
    now = time.time()
    cur = c.execute(
        "INSERT INTO applications (job_id, resume_version_id, applied_at, updated_at) VALUES (?, ?, ?, ?)",
        (job_id, resume_version_id, now, now),
    )
    c.execute("UPDATE jobs SET status = 'applied' WHERE id = ?", (job_id,))
    c.commit()
    return cur.lastrowid


def set_application_status(app_id: int, status: str) -> None:
    if status not in APPLICATION_STATUSES:
        raise ValueError(status)
    c = conn()
    c.execute("UPDATE applications SET status = ?, updated_at = ? WHERE id = ?", (status, time.time(), app_id))
    c.commit()


def save_match(job_id: str, score: int, result: dict) -> None:
    c = conn()
    c.execute(
        "INSERT OR REPLACE INTO matches (job_id, fit_score, result_json, scored_at) VALUES (?, ?, ?, ?)",
        (job_id, score, json.dumps(result), time.time()),
    )
    c.execute("UPDATE jobs SET status = 'scored' WHERE id = ?", (job_id,))
    c.commit()
