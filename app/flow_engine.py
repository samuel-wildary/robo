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


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip().lower()
    return cleaned


def extract_phone(chat_id: str) -> str:
    digits = re.sub(r"\D", "", chat_id or "")
    return digits


class FlowEngine:
    def __init__(
        self,
        flow_file: Path,
        session_store: SessionStore,
        client: WhatsAppApiClient,
        public_base_url: str,
    ) -> None:
        self.flow_file = Path(flow_file)
        self.session_store = session_store
        self.client = client
        self.public_base_url = public_base_url.rstrip("/")
        self.flow_definition: dict[str, Any] = {}

    def load(self) -> None:
        with self.flow_file.open("r", encoding="utf-8") as file:
            self.flow_definition = json.load(file)

    def reload(self) -> None:
        self.load()

    def handle_incoming_message(self, chat_id: str, message_text: str, phone: str | None = None, ctwa_clid: str = "") -> None:
        # phone = numero real para enviar mensagens
        # chat_id = identificador de sessao (LID)
        resolved_phone = phone or chat_id
        normalized_message = normalize_text(message_text)
        existing_session = self.session_store.get_session(chat_id)

        # Salva ctwa_clid na sessão se veio de um anúncio (só salva uma vez)
        if ctwa_clid and existing_session:
            self.session_store.set_ctwa_clid(chat_id, ctwa_clid)

        if existing_session:
            if existing_session.get("is_executing") is True:
                logger.info("Bot está executando fluxo para %s. Ignorando mensagem concorrente.", chat_id)
                return

            if existing_session.get("flow_id") == "__COMPLETED__":
                logger.info("Sessao ja concluida para %s. Ignorando mensagem.", chat_id)
                return

            flow = self._get_flow_by_id(existing_session["flow_id"])
            if flow:
                current_step = self._get_step(flow, existing_session["step_id"])
                if current_step:
                    next_step = self._resolve_transition(current_step, normalized_message)
                    if next_step:
                        self._execute_step(flow, next_step, chat_id, resolved_phone)
                        return

                    fallback_actions = current_step.get("fallback_actions") or []
                    if fallback_actions:
                        self._execute_actions(fallback_actions, chat_id, resolved_phone)
                        return

        flow = self._match_flow(normalized_message)
        if flow:
            self._execute_step(flow, flow["entry_step"], chat_id, resolved_phone)
            # Salva ctwa_clid após criar a sessão (caso seja a primeira mensagem)
            if ctwa_clid:
                self.session_store.set_ctwa_clid(chat_id, ctwa_clid)
            return

        default_actions = self.flow_definition.get("default_actions") or []
        if default_actions:
            self._execute_actions(default_actions, chat_id, resolved_phone)

    def _match_flow(self, normalized_message: str) -> dict[str, Any] | None:
        for flow in self.flow_definition.get("flows", []):
            for trigger in flow.get("triggers", []):
                trigger_text = normalize_text(trigger)
                if trigger_text and trigger_text in normalized_message:
                    return flow
        return None

    def _get_flow_by_id(self, flow_id: str) -> dict[str, Any] | None:
        for flow in self.flow_definition.get("flows", []):
            if flow.get("id") == flow_id:
                return flow
        return None

    def _get_step(self, flow: dict[str, Any], step_id: str) -> dict[str, Any] | None:
        return flow.get("steps", {}).get(step_id)

    def _resolve_transition(self, step: dict[str, Any], normalized_message: str) -> str | None:
        transitions = step.get("transitions")
        if isinstance(transitions, dict):
            return transitions.get(normalized_message) or transitions.get("*")

        if isinstance(transitions, list):
            for rule in transitions:
                when_values = rule.get("when", [])
                if isinstance(when_values, str):
                    when_values = [when_values]

                for value in when_values:
                    if normalize_text(value) == normalized_message:
                        return rule.get("next_step")

                if rule.get("contains"):
                    needle = normalize_text(rule["contains"])
                    if needle and needle in normalized_message:
                        return rule.get("next_step")

                if rule.get("default"):
                    default_step = rule.get("next_step")
                    if default_step:
                        return default_step

        return None

    def _execute_step(self, flow: dict[str, Any], step_id: str, chat_id: str, phone: str) -> None:
        step = self._get_step(flow, step_id)
        if not step:
            logger.warning("Step '%s' nao encontrado no fluxo '%s'.", step_id, flow.get("id"))
            self.session_store.clear_session(chat_id)
            return

        self.session_store.set_session(chat_id, flow["id"], step_id, is_executing=True)

        self._execute_actions(step.get("actions", []), chat_id, phone)

        if step.get("end"):
            logger.info("Fluxo concluido para %s. Marcando estado como COMPLETED.", chat_id)
            self.session_store.set_session(chat_id, "__COMPLETED__", "__COMPLETED__", is_executing=False)
            return

        next_waiting_step = step.get("next_step", step_id)
        self.session_store.set_session(chat_id, flow["id"], next_waiting_step, is_executing=False)

    def _execute_actions(self, actions: list[dict[str, Any]], chat_id: str, phone: str) -> None:
        to = extract_phone(phone or chat_id)
        logger.info("Executando acoes para telefone: %s", to)
        for action in actions:
            action_type = action.get("type")

            if action_type == "wait":
                delay_seconds = float(action.get("seconds", 1))
                time.sleep(delay_seconds)
                continue

            if action_type == "presence":
                self.client.send_presence(to=to, presence=action.get("presence", "composing"))
                continue

            if action_type == "text":
                import random
                text_val = action.get("text", "")
                if isinstance(text_val, list):
                    text_val = random.choice(text_val)

                self.client.send_text(to=to, text=text_val)
                continue

            if action_type == "media":
                import random
                action_to_resolve = action.copy()
                if isinstance(action.get("media_path"), list):
                    action_to_resolve["media_path"] = random.choice(action["media_path"])

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
        """Detecta o tipo de midia pela extensao do arquivo."""
        path = action.get("media_path", "") or action.get("media_url", "")
        path_lower = path.lower()

        if path_lower.endswith((".ogg", ".mp3", ".wav", ".aac", ".m4a", ".opus")):
            return "audio"
        if path_lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            return "image"
        if path_lower.endswith((".mp4", ".avi", ".mov", ".mkv")):
            return "video"
        return "document"
