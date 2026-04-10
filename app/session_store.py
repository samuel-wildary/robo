from __future__ import annotations

import json
import redis

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
            "ctwa_clid": existing.get("ctwa_clid")
        }
        
        # Define limite de 24 horas para limpar RAM de sessões abandonadas
        self.redis.setex(key, 86400, json.dumps(updated_data))

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
            self.redis.setex(key, 86400, json.dumps(existing))

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
        self.redis.setex(key, 86400, json.dumps(history))
