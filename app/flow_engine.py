from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.session_store import SessionStore
from app.whatsapp_api import WhatsAppApiClient

logger = logging.getLogger(__name__)

ASSETS_CONFIG_FILE = Path("app/data/assets_config.json")
AGENT_FLOW_ID = "__AGENT__"
AGENT_STEP_ID = "attending"


def extract_phone(chat_id: str) -> str:
    return re.sub(r"\D", "", chat_id or "")


def load_assets_config() -> dict[str, Any]:
    if not ASSETS_CONFIG_FILE.exists():
        return {}

    try:
        with ASSETS_CONFIG_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as exc:  # pragma: no cover
        logger.error("Erro ao carregar assets_config.json: %s", exc)
        return {}


class FlowEngine:
    def __init__(
        self,
        session_store: SessionStore,
        client: WhatsAppApiClient,
        public_base_url: str,
        agent=None,
    ) -> None:
        self.session_store = session_store
        self.client = client
        self.public_base_url = public_base_url.rstrip("/")
        self.agent = agent

    def handle_incoming_message(
        self,
        chat_id: str,
        message_text: str,
        phone: str | None = None,
        ctwa_clid: str = "",
    ) -> None:
        had_existing_session = self.session_store.get_session(chat_id) is not None
        queue_size = self.session_store.enqueue_incoming_message(
            chat_id=chat_id,
            message_text=message_text,
            phone=phone,
            ctwa_clid=ctwa_clid,
        )

        if not self.session_store.try_acquire_execution_lock(chat_id):
            logger.info(
                "Atendimento em andamento para %s. Mensagem adicionada ao buffer. Itens pendentes: %s",
                chat_id,
                queue_size,
            )
            return

        self.session_store.set_session(chat_id, AGENT_FLOW_ID, AGENT_STEP_ID, is_executing=True)

        try:
            should_apply_initial_delay = not had_existing_session
            while True:
                pending_message = self.session_store.pop_next_incoming_message(chat_id)
                if not pending_message:
                    break

                resolved_phone = pending_message.get("phone") or phone or chat_id
                buffered_ctwa_clid = pending_message.get("ctwa_clid", "")
                if buffered_ctwa_clid:
                    self.session_store.set_ctwa_clid(chat_id, buffered_ctwa_clid)

                if should_apply_initial_delay:
                    self._apply_initial_delay(chat_id, resolved_phone)
                    should_apply_initial_delay = False

                self._process_buffered_message(
                    chat_id=chat_id,
                    resolved_phone=resolved_phone,
                    message_text=pending_message.get("message_text", ""),
                )
        finally:
            self.session_store.set_session(chat_id, AGENT_FLOW_ID, AGENT_STEP_ID, is_executing=False)
            self.session_store.release_execution_lock(chat_id)

    def _apply_initial_delay(self, chat_id: str, resolved_phone: str) -> None:
        assets_config = load_assets_config()
        initial_delay = assets_config.get("global_initial_delay", 0)
        if initial_delay <= 0:
            return

        time.sleep(1)
        self.client.send_presence(to=resolved_phone, presence="composing")
        logger.info(
            "Aplicando global_initial_delay de %s segundos para %s",
            initial_delay,
            chat_id,
        )
        time.sleep(initial_delay)

    def _process_buffered_message(
        self,
        chat_id: str,
        resolved_phone: str,
        message_text: str,
    ) -> None:
        reply_text = ""
        whatsapp_actions: list[dict[str, Any]] = []
        if self.agent:
            reply_text, whatsapp_actions = self.agent.process_message(chat_id, message_text)

        if reply_text:
            delay = min(max(len(reply_text) * 0.03, 2), 6)
            time.sleep(0.5)
            self.client.send_presence(to=resolved_phone, presence="composing")
            time.sleep(delay)
            self.client.send_text(to=resolved_phone, text=reply_text)

        if whatsapp_actions:
            self._execute_actions(whatsapp_actions, chat_id, resolved_phone)

    def _execute_actions(self, actions: list[dict[str, Any]], chat_id: str, phone: str) -> None:
        to = extract_phone(phone or chat_id)
        logger.info("Executando acoes do agente para telefone: %s", to)

        for action in actions:
            action_type = action.get("type")

            if action_type == "wait":
                time.sleep(float(action.get("seconds", 1)))
                continue

            if action_type == "presence":
                self.client.send_presence(to=to, presence=action.get("presence", "composing"))
                continue

            if action_type == "text":
                text_val = action.get("text", "")
                if isinstance(text_val, list) and text_val:
                    import random

                    text_val = random.choice(text_val)
                self.client.send_text(to=to, text=text_val)
                continue

            if action_type == "media":
                action_to_resolve = action.copy()
                media_path_raw = action.get("media_path", "")
                media_path_val = media_path_raw

                if isinstance(media_path_raw, list) and media_path_raw:
                    import random

                    media_path_val = random.choice(media_path_raw)
                    action_to_resolve["media_path"] = media_path_val

                assets_config = load_assets_config()
                if media_path_val:
                    file_meta = assets_config.get("files", {}).get(media_path_val, {})
                    presence = file_meta.get("presence")
                    delay_seconds = file_meta.get("delay_seconds", 0)

                    if presence:
                        self.client.send_presence(to=to, presence=presence)
                    if delay_seconds > 0:
                        logger.info(
                            "Aplicando delay de %s segundos e presence %s para %s",
                            delay_seconds,
                            presence,
                            media_path_val,
                        )
                        time.sleep(delay_seconds)

                media_url = self._resolve_media_url(action_to_resolve)
                media_type = self._detect_media_type(action_to_resolve)
                self.client.send_media(
                    to=to,
                    media_url=media_url,
                    caption=action_to_resolve.get("caption"),
                    media_type=media_type,
                )
                continue

            if action_type == "read":
                self.client.mark_read(chat_id=chat_id)
                continue

            logger.warning("Tipo de acao nao suportado: %s", action_type)

    def _resolve_media_url(self, action: dict[str, Any]) -> str:
        if action.get("media_url"):
            return action["media_url"]

        if action.get("media_path"):
            media_path = quote(action["media_path"].lstrip("/"))
            return f"{self.public_base_url}/assets/{media_path}"

        raise ValueError("Acao de media precisa de 'media_url' ou 'media_path'.")

    @staticmethod
    def _detect_media_type(action: dict[str, Any]) -> str:
        path = action.get("media_path", "") or action.get("media_url", "")
        path_lower = path.lower()

        if path_lower.endswith((".ogg", ".mp3", ".wav", ".aac", ".m4a", ".opus")):
            return "audio"
        if path_lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            return "image"
        if path_lower.endswith((".mp4", ".avi", ".mov", ".mkv")):
            return "video"
        return "document"
