import json
import sqlite3
from pathlib import Path
from datetime import datetime


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self):
        return sqlite3.connect(self.path)

    def initialize(self):
        with self.connect() as conn:
            rows = conn.execute("PRAGMA table_info(runs)").fetchall()
            columns = {row[1] for row in rows}
            if rows and not {"run_id", "created_at", "file_count", "result_json"}.issubset(columns):
                legacy = f"runs_legacy_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                conn.execute(f'ALTER TABLE runs RENAME TO "{legacy}"')
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    file_count INTEGER NOT NULL,
                    result_json TEXT NOT NULL
                )
            """)

    def save_run_generic(self, result):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, created_at, file_count, result_json) VALUES (?, ?, ?, ?)",
                (
                    result["run_id"],
                    datetime.now().isoformat(timespec="seconds"),
                    sum(len(v) for v in result.get("documents", {}).values()),
                    json.dumps(result, ensure_ascii=False, default=str),
                ),
            )

    def list_runs(self, limit=50):
        with self.connect() as conn:
            return conn.execute(
                "SELECT run_id, created_at, file_count FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def get_run(self, run_id):
        with self.connect() as conn:
            row = conn.execute("SELECT result_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None
