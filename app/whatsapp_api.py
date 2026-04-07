from __future__ import annotations

from typing import Any

import requests


class WhatsAppApiClient:
    def __init__(self, base_url: str, instance_token: str, timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.instance_token = instance_token
        self.timeout_seconds = timeout_seconds

    def send_text(self, to: str, text: str) -> dict[str, Any]:
        return self._post("/message/text", {"to": to, "text": text})

    def send_media(self, to: str, media_url: str, caption: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"to": to, "mediaUrl": media_url}
        if caption:
            payload["caption"] = caption
        return self._post("/message/media", payload)

    def send_presence(self, to: str, presence: str) -> dict[str, Any]:
        try:
            return self._post("/message/presence", {"to": to, "presence": presence})
        except Exception:
            return {"ok": False, "error": "ignored presence error"}

    def mark_read(self, chat_id: str) -> dict[str, Any]:
        return self._post("/message/read", {"chatId": chat_id})

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.instance_token:
            raise RuntimeError(
                "WHATSAPP_INSTANCE_TOKEN nao configurado. Defina a variavel no arquivo .env."
            )

        response = requests.post(
            f"{self.base_url}{path}",
            json=payload,
            headers={"X-Instance-Token": self.instance_token},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        if not response.content:
            return {"ok": True}

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()

        return {"ok": True, "raw_response": response.text}
