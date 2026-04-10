from __future__ import annotations

import logging
import mimetypes
import os
import shutil
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from app.config import get_settings
from app.flow_engine import FlowEngine
from app.session_store import SessionStore
from app.whatsapp_api import WhatsAppApiClient
from app.agent import HybridAgent, get_system_prompt, PROMPT_FILE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
session_store = SessionStore(settings.redis_url)
api_client = WhatsAppApiClient(
    base_url=settings.whatsapp_api_base_url,
    instance_token=settings.whatsapp_instance_token,
    timeout_seconds=settings.request_timeout_seconds,
)
agent = HybridAgent(session_store=session_store)
flow_engine = FlowEngine(
    flow_file=settings.flow_file,
    session_store=session_store,
    client=api_client,
    public_base_url=settings.public_base_url,
    agent=agent,
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
STATIC_DIR = Path("app/static")
DATA_DIR = Path("app/data")
ASSETS_CONFIG_FILE = DATA_DIR / "assets_config.json"

app = FastAPI(title="Robo de Atendimento WhatsApp")
security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, settings.admin_user)
    correct_password = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Autenticação Incorreta",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# --- ADMIN ENDPOINTS (Protegidos) ---

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(username: str = Depends(verify_credentials)):
    """Serve a Interface Gráfica Administrativa."""
    html_file = STATIC_DIR / "admin.html"
    if not html_file.exists():
        raise HTTPException(status_code=404, detail="Painel não encontrado. Crie app/static/admin.html")
    with open(html_file, "r", encoding="utf-8") as f:
        return f.read()

class PromptUpdate(BaseModel):
    prompt: str

class AssetConfigPayload(BaseModel):
    config: dict
    prompt: str

@app.get("/api/prompt", dependencies=[Depends(verify_credentials)])
def get_prompt():
    return {"prompt": get_system_prompt()}

@app.post("/api/prompt", dependencies=[Depends(verify_credentials)])
def update_prompt(payload: PromptUpdate):
    try:
        PROMPT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROMPT_FILE, "w", encoding="utf-8") as f:
            f.write(payload.prompt)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/assets", dependencies=[Depends(verify_credentials)])
def list_assets():
    if not ASSETS_DIR.exists():
        return {"files": []}
    files = []
    
    # carrega config atual
    config = {}
    if ASSETS_CONFIG_FILE.exists():
        import json
        with open(ASSETS_CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

    for f in ASSETS_DIR.iterdir():
        if f.is_file():
            # append config to each file
            file_meta = config.get("files", {}).get(f.name, {})
            files.append({
                "name": f.name, 
                "size": f.stat().st_size,
                "delay_seconds": file_meta.get("delay_seconds", 0),
                "presence": file_meta.get("presence", "")
            })
    return {
        "files": files,
        "global_initial_delay": config.get("global_initial_delay", 0)
    }

@app.post("/api/asset-config", dependencies=[Depends(verify_credentials)])
def update_asset_config(payload: AssetConfigPayload):
    import json
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(ASSETS_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(payload.config, f, ensure_ascii=False, indent=2)
    return {"status": "success"}

@app.post("/api/assets/upload", dependencies=[Depends(verify_credentials)])
def upload_asset(file: UploadFile = File(...)):
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = ASSETS_DIR / file.filename
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"status": "success", "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/assets/{filename}", dependencies=[Depends(verify_credentials)])
def delete_asset(filename: str):
    file_path = ASSETS_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    file_path.unlink()
    return {"status": "deleted"}


# --- PUBLIC ENDPOINTS ---

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
    # Garante que as pastas cruciais existam
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    get_system_prompt() # Cria o arquivo txt se não existir
    logger.info("Robo inicializado com fluxo em %s", settings.flow_file)
    logger.info("Admin Area at /admin")


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

    if data.get("fromMe"):
        return {"status": "ignored", "reason": "mensagem propria (fromMe)"}

    message_type = data.get("type")
    if message_type not in {"chat", "conversation", "text"}:
        return {"status": "ignored", "reason": f"tipo {message_type!r} nao tratado"}

    # Usa resolvedPhone (telefone real) para enviar mensagens
    # Usa 'from' (LID) apenas como chave de sessão
    phone = data.get("resolvedPhone") or data.get("from", "")
    session_id = data.get("from", "")
    message_text = data.get("body", "")

    # CTWA (Click to WhatsApp) ad tracking
    ctwa_clid = data.get("ctwaClid", "")
    if ctwa_clid:
        logger.info("📢 CTWA Click ID detectado: %s | Telefone: %s", ctwa_clid, phone)
        entry_source = data.get("entryPointConversionSource", "")
        entry_app = data.get("entryPointConversionApp", "")
        ad_title = data.get("adTitle", "")
        logger.info("   ↳ Origem: %s | App: %s | Anúncio: %s", entry_source, entry_app, ad_title)

    if not phone:
        raise HTTPException(status_code=400, detail="Payload sem telefone do remetente.")

    logger.info("Telefone real: %s | Sessao: %s | Mensagem: %s", phone, session_id, message_text)

    try:
        background_tasks.add_task(
            flow_engine.handle_incoming_message,
            chat_id=session_id,
            phone=phone,
            message_text=message_text,
            ctwa_clid=ctwa_clid,
        )
    except Exception as exc:  # pragma: no cover - log de runtime
        logger.exception("Erro ao colocar webhoook processing task in background")
        return {"status": "error", "detail": str(exc)}

    return {"status": "processed"}
