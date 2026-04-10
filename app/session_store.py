from __future__ import annotations

import json
import redis

SESSION_TTL_SECONDS = 86400
EXECUTION_LOCK_TTL_SECONDS = 1800


class SessionStore:
    def __init__(self, redis_url: str) -> None:
        # A pool de conexões do Redis já funciona de forma automática e thread-safe.
        self.redis = redis.from_url(redis_url, decode_responses=True)

    def initialize(self) -> None:
        # Testa a conexão
        self.redis.ping()

    def get_session(self, chat_id: str) -> dict[str, str] | None:
        data = self.redis.get(f"session:{chat_id}")
        if data:
            return json.loads(data)
        return None

    def set_session(self, chat_id: str, flow_id: str, step_id: str, is_executing: bool = False) -> None:
        key = f"session:{chat_id}"
        existing = self.get_session(chat_id) or {}

        updated_data = {
            "chat_id": chat_id,
            "flow_id": flow_id,
            "step_id": step_id,
            "is_executing": is_executing,
            "ctwa_clid": existing.get("ctwa_clid"),
        }

        # Define limite de 24 horas para limpar RAM de sessões abandonadas
        self.redis.setex(key, SESSION_TTL_SECONDS, json.dumps(updated_data))

    def clear_session(self, chat_id: str) -> None:
        self.redis.delete(f"session:{chat_id}")

    def set_ctwa_clid(self, chat_id: str, ctwa_clid: str) -> None:
        """Salva o ctwa_clid (Click to WhatsApp Client ID) na sessão.
        Só sobrescreve se o valor atual for NULL (preserva o primeiro clique)."""
        key = f"session:{chat_id}"
        existing = self.get_session(chat_id) or {}

        if not existing.get("ctwa_clid"):
            existing["chat_id"] = chat_id
            existing["ctwa_clid"] = ctwa_clid
            self.redis.setex(key, SESSION_TTL_SECONDS, json.dumps(existing))

    def get_history(self, chat_id: str) -> list[dict[str, str]]:
        key = f"history:{chat_id}"
        data = self.redis.get(key)
        if data:
            return json.loads(data)
        return []

    def add_message_to_history(self, chat_id: str, role: str, content: str) -> None:
        key = f"history:{chat_id}"
        history = self.get_history(chat_id)
        history.append({"role": role, "content": content})
        # Keep only the last 20 messages for context
        if len(history) > 20:
            history = history[-20:]
        self.redis.setex(key, SESSION_TTL_SECONDS, json.dumps(history))

    def enqueue_incoming_message(
        self,
        chat_id: str,
        message_text: str,
        phone: str | None = None,
        ctwa_clid: str = "",
    ) -> int:
        key = f"incoming_buffer:{chat_id}"
        payload = json.dumps(
            {
                "message_text": message_text,
                "phone": phone or "",
                "ctwa_clid": ctwa_clid,
            }
        )
        queue_size = self.redis.rpush(key, payload)
        self.redis.expire(key, SESSION_TTL_SECONDS)
        return int(queue_size)

    def pop_next_incoming_message(self, chat_id: str) -> dict[str, str] | None:
        key = f"incoming_buffer:{chat_id}"
        item = self.redis.lpop(key)
        if not item:
            return None
        return json.loads(item)

    def get_pending_message_count(self, chat_id: str) -> int:
        return int(self.redis.llen(f"incoming_buffer:{chat_id}"))

    def try_acquire_execution_lock(self, chat_id: str) -> bool:
        return bool(
            self.redis.set(
                f"execution_lock:{chat_id}",
                "1",
                nx=True,
                ex=EXECUTION_LOCK_TTL_SECONDS,
            )
        )

    def release_execution_lock(self, chat_id: str) -> None:
        self.redis.delete(f"execution_lock:{chat_id}")
