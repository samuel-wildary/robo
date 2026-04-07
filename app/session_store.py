from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class SessionStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._lock = threading.Lock()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    chat_id TEXT PRIMARY KEY,
                    flow_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.commit()

    def get_session(self, chat_id: str) -> dict[str, str] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT chat_id, flow_id, step_id FROM sessions WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()

        if not row:
            return None

        return {
            "chat_id": row[0],
            "flow_id": row[1],
            "step_id": row[2],
        }

    def set_session(self, chat_id: str, flow_id: str, step_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (chat_id, flow_id, step_id, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id) DO UPDATE SET
                    flow_id = excluded.flow_id,
                    step_id = excluded.step_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (chat_id, flow_id, step_id),
            )
            connection.commit()

    def clear_session(self, chat_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)
