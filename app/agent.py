import json
import logging
import secrets
from pathlib import Path
from typing import Any, Dict, List, Tuple

from openai import OpenAI

from app.config import get_settings
from app.session_store import SessionStore

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"
FLOW_CONFIG_FILE = Path("app/data/flow_config.json")
ASSETS_DIR = Path("assets")
DEFAULT_SYSTEM_DIRECTIVE = (
    "Voce e uma atendente comercial no WhatsApp. "
    "Converse de forma humana, entenda o que o cliente precisa, "
    "use os arquivos enviados quando fizer sentido e conduza a conversa para a venda."
)


def _default_agent_config() -> dict[str, Any]:
    return {
        "system_directive": DEFAULT_SYSTEM_DIRECTIVE,
        "cards": [],
    }


def _load_agent_config() -> dict[str, Any]:
    if not FLOW_CONFIG_FILE.exists():
        return _default_agent_config()

    try:
        with FLOW_CONFIG_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as exc:
        logger.error("Erro ao carregar flow_config.json: %s", exc)
        return _default_agent_config()

    if not isinstance(data, dict):
        return _default_agent_config()

    return normalize_agent_config(data)


def _normalize_tool(tool: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(tool, dict):
        return None

    kind = str(tool.get("kind") or tool.get("type") or "").strip().lower()
    if kind not in {"text", "media"}:
        return None

    normalized = {
        "id": str(tool.get("id") or secrets.token_hex(4)),
        "kind": kind,
        "label": str(tool.get("label") or "").strip(),
    }

    if kind == "text":
        normalized["content"] = str(tool.get("content") or tool.get("text") or "").strip()
        if not normalized["label"]:
            normalized["label"] = "Texto via tool"
    else:
        normalized["asset"] = str(tool.get("asset") or tool.get("media_path") or "").strip()
        if not normalized["label"]:
            normalized["label"] = normalized["asset"] or "Arquivo"

    return normalized


def _phase_to_card(phase: dict[str, Any]) -> dict[str, Any]:
    actions = phase.get("actions", [])
    tools = []
    for action in actions:
        normalized_tool = _normalize_tool(action)
        if normalized_tool:
            tools.append(normalized_tool)

    return {
        "id": str(phase.get("id") or secrets.token_hex(4)),
        "title": str(phase.get("name") or "Novo card").strip(),
        "trigger": str(phase.get("trigger") or "").strip(),
        "instruction": str(phase.get("instruction") or "").strip(),
        "output_guidance": str(phase.get("post_text") or "").strip(),
        "tools": tools,
    }


def _normalize_card(card: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(card, dict):
        return {
            "id": secrets.token_hex(4),
            "title": "Novo card",
            "trigger": "",
            "instruction": "",
            "output_guidance": "",
            "tools": [],
        }

    if any(key in card for key in {"name", "post_text", "actions"}):
        card = _phase_to_card(card)

    tools = []
    raw_tools = card.get("tools", [])
    if not raw_tools and card.get("actions"):
        raw_tools = card.get("actions", [])

    if isinstance(raw_tools, list):
        for tool in raw_tools:
            normalized_tool = _normalize_tool(tool)
            if normalized_tool:
                tools.append(normalized_tool)

    return {
        "id": str(card.get("id") or secrets.token_hex(4)),
        "title": str(card.get("title") or card.get("name") or "Novo card").strip(),
        "trigger": str(card.get("trigger") or "").strip(),
        "instruction": str(card.get("instruction") or "").strip(),
        "output_guidance": str(card.get("output_guidance") or card.get("post_text") or "").strip(),
        "tools": tools,
    }


def normalize_agent_config(data: dict[str, Any] | None) -> dict[str, Any]:
    base = _default_agent_config()
    if not isinstance(data, dict):
        return base

    raw_cards = data.get("cards")
    if not isinstance(raw_cards, list):
        raw_cards = data.get("phases", [])

    cards = []
    if isinstance(raw_cards, list):
        cards = [_normalize_card(card) for card in raw_cards]

    return {
        "system_directive": str(data.get("system_directive") or base["system_directive"]).strip(),
        "cards": cards,
    }


def _describe_available_assets() -> str:
    if not ASSETS_DIR.exists():
        return "Nenhum arquivo foi enviado para a pasta assets ate agora."

    files = sorted(file.name for file in ASSETS_DIR.iterdir() if file.is_file())
    if not files:
        return "Nenhum arquivo foi enviado para a pasta assets ate agora."

    lines = [
        "ARQUIVOS DISPONIVEIS PARA ENVIO VIA TOOL:",
        "Use exatamente estes nomes em media_path e nunca invente nomes de arquivos.",
    ]
    for name in files:
        lines.append(f"- {name}")
    return "\n".join(lines)


def get_system_prompt() -> str:
    data = _load_agent_config()
    prompt = data.get("system_directive", "").strip() or DEFAULT_SYSTEM_DIRECTIVE

    prompt += "\n\n"
    prompt += (
        "REGRAS DE OPERACAO:\n"
        "- Voce esta atuando como um agente de atendimento, nao como uma automacao fixa.\n"
        "- Quando quiser enviar audio, imagem, video ou documento, use obrigatoriamente a ferramenta execute_whatsapp_actions.\n"
        "- Nao prometa um arquivo se voce nao for chamar a tool de verdade.\n"
        "- Os delays e status humanos dos arquivos sao aplicados automaticamente pela plataforma.\n"
        "- Se um arquivo ajudar a explicar, comprovar ou vender, voce pode enviar esse arquivo por conta propria.\n"
        "- Se nao houver arquivo adequado, responda normalmente em texto.\n\n"
    )
    prompt += _describe_available_assets() + "\n\n"

    cards = data.get("cards", [])
    if cards:
        prompt += "CARDS DE ORIENTACAO DO ATENDIMENTO:\n\n"
        for index, card in enumerate(cards, start=1):
            prompt += f"--- CARD {index}: {card.get('title', 'Bloco sem nome')} ---\n"
            prompt += f"Quando ativar: {card.get('trigger', '')}\n"
            if card.get("instruction"):
                prompt += f"Instrucao: {card.get('instruction', '').replace(chr(10), ' ')}\n"

            prompt += "Ferramentas conectadas neste card:\n"
            tools = card.get("tools", [])
            if not tools:
                prompt += " - Nenhuma ferramenta conectada.\n"

            for tool in tools:
                if tool.get("kind") == "text":
                    text_value = str(tool.get("content") or "").replace("\n", " ")
                    prompt += f" - text: \"{text_value}\""
                    if tool.get("label"):
                        prompt += f" | label: {tool.get('label')}"
                    prompt += "\n"
                elif tool.get("kind") == "media":
                    prompt += f" - media: media_path = \"{tool.get('asset', '')}\""
                    if tool.get("label"):
                        prompt += f" | label: {tool.get('label')}"
                    prompt += "\n"

            if card.get("output_guidance"):
                closing_text = str(card.get("output_guidance") or "").replace("\n", " ")
                prompt += f"Saida desejada apos esse card: \"{closing_text}\"\n"

            prompt += "\n"

    return prompt


WHATSAPP_ACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_whatsapp_actions",
        "description": "Executa acoes reais no WhatsApp como texto, presence, espera e envio de arquivos.",
        "parameters": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["presence", "wait", "text", "media"],
                            },
                            "presence": {
                                "type": "string",
                                "enum": ["composing", "recording"],
                            },
                            "seconds": {
                                "type": "number",
                                "description": "Tempo em segundos para esperar.",
                            },
                            "text": {
                                "type": "string",
                                "description": "Texto da mensagem. Use \\n para quebra de linha.",
                            },
                            "media_path": {
                                "type": ["string", "array"],
                                "items": {"type": "string"},
                                "description": (
                                    "Nome do arquivo existente em assets, por exemplo 'audio2.ogg'. "
                                    "Tambem pode ser um array para sorteio aleatorio."
                                ),
                            },
                            "caption": {
                                "type": "string",
                                "description": "Legenda opcional para a midia.",
                            },
                        },
                        "required": ["type"],
                    },
                }
            },
            "required": ["actions"],
        },
    },
}


class HybridAgent:
    def __init__(self, session_store: SessionStore):
        self.session_store = session_store
        self.settings = get_settings()

        if self.settings.openai_api_key and self.settings.openai_api_key != "sua_chave_aqui":
            self.client = OpenAI(api_key=self.settings.openai_api_key)
        else:
            self.client = None
            logger.error("OPENAI_API_KEY nao configurada ou invalida.")

    def process_message(self, chat_id: str, user_message: str) -> Tuple[str, List[Dict[str, Any]]]:
        if not self.client:
            return "Estou em manutencao no momento por falta de configuracao da inteligencia.", []

        self.session_store.add_message_to_history(chat_id, "user", user_message)
        history = self.session_store.get_history(chat_id)

        messages = [{"role": "system", "content": get_system_prompt()}]
        messages.extend(history)

        try:
            response = self.client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.7,
                tools=[WHATSAPP_ACTION_TOOL],
                tool_choice="auto",
            )

            message = response.choices[0].message
            ai_reply = message.content or ""
            whatsapp_actions: list[dict[str, Any]] = []

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    if tool_call.function.name != "execute_whatsapp_actions":
                        continue
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        logger.error("A IA retornou argumentos de funcao invalidos.")
                        continue

                    actions = args.get("actions", [])
                    if isinstance(actions, list):
                        whatsapp_actions.extend(actions)

            if ai_reply:
                self.session_store.add_message_to_history(chat_id, "assistant", ai_reply)

            if whatsapp_actions:
                internal_note = "[Sistema] O bot entregou arquivos via sistema: "
                internal_note += json.dumps(whatsapp_actions, ensure_ascii=False)
                self.session_store.add_message_to_history(chat_id, "assistant", internal_note)

            return ai_reply, whatsapp_actions

        except Exception:
            logger.exception("Erro ao chamar OpenAI")
            return "Tive um probleminha aqui na conexao. Pode repetir?", []
