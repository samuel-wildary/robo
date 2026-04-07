from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.flow_engine import FlowEngine
from app.session_store import SessionStore
from app.whatsapp_api import WhatsAppApiClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
session_store = SessionStore(settings.database_path)
api_client = WhatsAppApiClient(
    base_url=settings.whatsapp_api_base_url,
    instance_token=settings.whatsapp_instance_token,
    timeout_seconds=settings.request_timeout_seconds,
)
flow_engine = FlowEngine(
    flow_file=settings.flow_file,
    session_store=session_store,
    client=api_client,
    public_base_url=settings.public_base_url,
)

# Registrar MIME types corretos para audio
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/mp4", ".m4a")

app = FastAPI(title="Robo de Atendimento WhatsApp")
app.mount("/assets", StaticFiles(directory=Path("assets")), name="assets")


@app.on_event("startup")
def startup_event() -> None:
    session_store.initialize()
    flow_engine.load()
    logger.info("Robo inicializado com fluxo em %s", settings.flow_file)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/admin/reload-flows")
def reload_flows() -> dict[str, str]:
    flow_engine.reload()
    return {"status": "reloaded"}


@app.post("/webhook")
def webhook(payload: dict[str, Any]) -> dict[str, Any]:
    logger.info("=== WEBHOOK PAYLOAD COMPLETO === %s", payload)
    event_name = payload.get("event")
    data = payload.get("data") or {}

    if event_name != "message":
        return {"status": "ignored", "reason": f"evento {event_name!r} nao tratado"}

    if data.get("isGroup"):
        return {"status": "ignored", "reason": "mensagem de grupo"}

    if data.get("from", "").endswith("@g.us"):
        return {"status": "ignored", "reason": "mensagem de grupo"}

    message_type = data.get("type")
    if message_type not in {"chat", "conversation", "text"}:
        return {"status": "ignored", "reason": f"tipo {message_type!r} nao tratado"}

    # Usa resolvedPhone (telefone real) para enviar mensagens
    # Usa 'from' (LID) apenas como chave de sessão
    phone = data.get("resolvedPhone") or data.get("from", "")
    session_id = data.get("from", "")
    message_text = data.get("body", "")

    if not phone:
        raise HTTPException(status_code=400, detail="Payload sem telefone do remetente.")

    logger.info("Telefone real: %s | Sessao: %s | Mensagem: %s", phone, session_id, message_text)

    try:
        flow_engine.handle_incoming_message(chat_id=session_id, phone=phone, message_text=message_text)
    except Exception as exc:  # pragma: no cover - log de runtime
        logger.exception("Erro ao processar webhook")
        return {"status": "error", "detail": str(exc)}

    return {"status": "processed"}
