from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class WhatsAppApiClient:
    def __init__(self, base_url: str, instance_token: str, timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.instance_token = instance_token
        self.timeout_seconds = timeout_seconds

    def send_text(self, to: str, text: str) -> dict[str, Any]:
        return self._post("/message/text", {"to": to, "text": text})

    def send_media(self, to: str, media_url: str, caption: str | None = None, media_type: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"to": to, "mediaUrl": media_url}
        if caption:
            payload["caption"] = caption
        return self._post("/message/media", payload)

    def send_presence(self, to: str, presence: str) -> dict[str, Any]:
        try:
            return self._post("/message/presence", {"to": to, "presence": presence})
        except Exception:
            logger.warning("Presence ignorado (API nao suporta ou erro).")
            return {"ok": False, "error": "ignored presence error"}

    def mark_read(self, chat_id: str) -> dict[str, Any]:
        return self._post("/message/read", {"chatId": chat_id})

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.instance_token:
            raise RuntimeError(
                "WHATSAPP_INSTANCE_TOKEN nao configurado. Defina a variavel no arquivo .env."
            )

        url = f"{self.base_url}{path}"
        logger.info(">>> ENVIANDO para %s | payload: %s", url, payload)

        response = requests.post(
            url,
            json=payload,
            headers={"X-Instance-Token": self.instance_token},
            timeout=self.timeout_seconds,
        )

        if not response.ok:
            logger.error(
                "<<< ERRO %s de %s | corpo: %s",
                response.status_code,
                url,
                response.text[:500],
            )
            response.raise_for_status()

        logger.info("<<< OK %s | resposta: %s", response.status_code, response.text[:200])

        if not response.content:
            return {"ok": True}

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()

        return {"ok": True, "raw_response": response.text}
