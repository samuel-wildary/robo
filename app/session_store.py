from __future__ import annotations

import psycopg2
import threading

class SessionStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._lock = threading.Lock()

    def initialize(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        chat_id VARCHAR PRIMARY KEY,
                        flow_id VARCHAR NOT NULL,
                        step_id VARCHAR NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cursor.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS is_executing BOOLEAN DEFAULT FALSE")
                cursor.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS ctwa_clid VARCHAR DEFAULT NULL")
            connection.commit()

    def get_session(self, chat_id: str) -> dict[str, str] | None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT chat_id, flow_id, step_id, is_executing, ctwa_clid FROM sessions WHERE chat_id = %s",
                    (chat_id,),
                )
                row = cursor.fetchone()

        if not row:
            return None

        return {
            "chat_id": row[0],
            "flow_id": row[1],
            "step_id": row[2],
            "is_executing": row[3],
            "ctwa_clid": row[4],
        }

    def set_session(self, chat_id: str, flow_id: str, step_id: str, is_executing: bool = False) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO sessions (chat_id, flow_id, step_id, is_executing, updated_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        flow_id = EXCLUDED.flow_id,
                        step_id = EXCLUDED.step_id,
                        is_executing = EXCLUDED.is_executing,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (chat_id, flow_id, step_id, is_executing),
                )
            connection.commit()

    def clear_session(self, chat_id: str) -> None:
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM sessions WHERE chat_id = %s", (chat_id,))
            connection.commit()

    def set_ctwa_clid(self, chat_id: str, ctwa_clid: str) -> None:
        """Salva o ctwa_clid (Click to WhatsApp Client ID) na sessão.
        Só sobrescreve se o valor atual for NULL (preserva o primeiro clique)."""
        with self._lock, self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE sessions SET ctwa_clid = %s
                    WHERE chat_id = %s AND (ctwa_clid IS NULL OR ctwa_clid = '')
                    """,
                    (ctwa_clid, chat_id),
                )
            connection.commit()

    def _connect(self):
        return psycopg2.connect(self.database_url)
