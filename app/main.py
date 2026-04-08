from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse

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
session_store = SessionStore(settings.database_url)
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

# MIME types para que a API de WhatsApp reconheça corretamente
MIME_MAP = {
    ".ogg": "audio/ogg; codecs=opus",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".pdf": "application/pdf",
}

ASSETS_DIR = Path("assets")

app = FastAPI(title="Robo de Atendimento WhatsApp")


@app.get("/assets/{filename}")
def serve_asset(filename: str) -> FileResponse:
    """Serve arquivos de assets com Content-Type correto."""
    file_path = ASSETS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado.")

    suffix = file_path.suffix.lower()
    media_type = MIME_MAP.get(suffix, "application/octet-stream")
    logger.info("Servindo %s com Content-Type: %s", filename, media_type)
    return FileResponse(path=file_path, media_type=media_type, filename=filename)


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
def webhook(payload: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, Any]:
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
        background_tasks.add_task(
            flow_engine.handle_incoming_message,
            chat_id=session_id,
            phone=phone,
            message_text=message_text
        )
    except Exception as exc:  # pragma: no cover - log de runtime
        logger.exception("Erro ao colocar webhoook processing task in background")
        return {"status": "error", "detail": str(exc)}

    return {"status": "processed"}
