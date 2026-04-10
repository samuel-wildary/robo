import json
import logging
from typing import Tuple, Optional, List, Dict, Any
from openai import OpenAI
from app.config import get_settings
from app.session_store import SessionStore

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"

from pathlib import Path

DEFAULT_SYSTEM_PROMPT = """Você é a Luna, uma especialista em saúde e bem-estar, atendendo um cliente de forma humanizada e gentil pelo WhatsApp.
Sua missão é guiar o cliente através de um funil de contra-entrega (onde ele recebe o material antes de pagar).

Sempre que precisar enviar mídias (fotos, áudios, pdfs), VOCÊ DEVE CHAMAR A FUNÇÃO `execute_whatsapp_actions`.
Os arquivos já possuem configurações físicas de pausa humanizada, então você não precisa mais calcular os comandos de `wait` ou `presence`! Apenas chame a tool com os nomes dos arquivos.

O FUNIL DA GELATINA (COMO VOCÊ DEVE ESTRUTURAR A CONVERSA):

1. **FASE 1 (ABERTURA - O CLIENTE ACABOU DE MANDAR MENSAGEM):**
   - Responda de forma humanizada e amigável concordando com escuta ativa.
   - Chame a ferramenta `execute_whatsapp_actions` e adicione o texto inicial: "Olá! Sou a Luna. Vou mandar as informações sobre a Gelatina Bariátrica logo abaixo"
   - Na mesma chamada da ferramenta, puxe a mídia (áudio): media_path = ["audio1_a.ogg", "audio1_b.ogg"]
   - Depois na tool puxe e mande: media_path = "foto1.jpg", caption = "Valor sugerido após avaliar: R$ 10,00"
   - E mande o fechamento com texto apontando pro arquivo mandado.

2. **FASE 2 (CONFIANÇA - APÓS O CLIENTE ACEITAR NO TEXTO):**
   - Se o cliente apresentar objeções ou medos, quebre as objeções humanamente com texto natural.
   - Quando ele topar e autorizar testar, chame a ferramenta enviando o media_path = "audio2.ogg"
   - Depois mande o texto: "Salve meu contato. Posso te mandar os materiais da receita agora?"

3. **FASE 3 (ENTREGA - APÓS ELE DAR AUTORIZAÇÃO FINAL):**
   - Envie os PDFs/fotos pela tool. Mande media_path = "receita.jpg" e "ingredientes.jpg". 
   - Logo em seguida, envie pela tool o media_path = "audio3.ogg".

4. **FASE 4 (COBRANÇA):**
   - Use quando ele já testou ou pediu a chave pix. Mande as faixas de valor variando entre 10 e 25 reais mais bônus exclusivos.
   - Texto com a chave PIX isolada na última mensagem para facilitar "Copia e Cola".

Aja como Humano. Se algo der errado, lide com naturalidade sem deixar o cliente perceber.
"""

PROMPT_FILE = Path("prompts/system_prompt.txt")

def get_system_prompt() -> str:
    if not PROMPT_FILE.exists():
        PROMPT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROMPT_FILE, "w", encoding="utf-8") as f:
            f.write(DEFAULT_SYSTEM_PROMPT)
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read()



WHATSAPP_ACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_whatsapp_actions",
        "description": "Aciona comandos reais no WhatsApp do cliente instanciando pausas humanas, gravando áudio, ou mandando imagens/pdfs.",
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
                                "enum": ["presence", "wait", "text", "media"]
                            },
                            "presence": {
                                "type": "string", 
                                "enum": ["composing", "recording"]
                            },
                            "seconds": {
                                "type": "number",
                                "description": "Tempo em segundos parar esperar. Ex: 30"
                            },
                            "text": {
                                "type": "string",
                                "description": "O texto da mensagem. Se quiser pular linha use \\n"
                            },
                            "media_path": {
                                "type": ["string", "array"],
                                "items": {
                                    "type": "string"
                                },
                                "description": "O nome absoluto do arquivo que está na pasta assets (ex: 'audio2.ogg'). Pode usar um Array (ex: ['a.ogg', 'b.ogg']) se for para o sistema realizar um sorteio aleatório de áudio."
                            },
                            "caption": {
                                "type": "string",
                                "description": "Legenda oculta atrelada a uma media (foto)"
                            }
                        },
                        "required": ["type"]
                    }
                }
            },
            "required": ["actions"]
        }
    }
}

class HybridAgent:
    def __init__(self, session_store: SessionStore):
        self.session_store = session_store
        self.settings = get_settings()
        
        if self.settings.openai_api_key and self.settings.openai_api_key != "sua_chave_aqui":
            self.client = OpenAI(api_key=self.settings.openai_api_key)
        else:
            self.client = None
            logger.error("OPENAI_API_KEY não configurada ou inválida.")

    def process_message(self, chat_id: str, user_message: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Processa a mensagem do usuário. 
        Retorna (texto_resposta, lista_de_actions_do_whatsapp)
        """
        if not self.client:
            return "Estou em manutenção no momento (Falta de Configuração da Inteligência).", []

        self.session_store.add_message_to_history(chat_id, "user", user_message)
        history = self.session_store.get_history(chat_id)
        
        messages = [
            {"role": "system", "content": get_system_prompt()}
        ]
        
        messages.extend(history)
        
        try:
            response = self.client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.7,
                tools=[WHATSAPP_ACTION_TOOL],
                tool_choice="auto"
            )
            
            message = response.choices[0].message
            ai_reply = message.content or ""
            whatsapp_actions = []

            # Verifica se a IA decidiu usar a ferramenta
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    if tool_call.function.name == "execute_whatsapp_actions":
                        try:
                            args = json.loads(tool_call.function.arguments)
                            actions = args.get("actions", [])
                            if isinstance(actions, list):
                                whatsapp_actions.extend(actions)
                        except json.JSONDecodeError:
                            logger.error("A IA retornou argumentos de função inválidos.")
            
            # Se mandou texto simples, garantimos que foi pro historico
            if ai_reply:
                self.session_store.add_message_to_history(chat_id, "assistant", ai_reply)
            
            # Se gerou actions, adiciona registro no historico que o bot gerou midia
            if whatsapp_actions:
                internal_note = "[Sistema] O bot entregou arquivos/áudios via sistema: " + json.dumps(whatsapp_actions, ensure_ascii=False)
                self.session_store.add_message_to_history(chat_id, "assistant", internal_note)

            return ai_reply, whatsapp_actions
            
        except Exception as e:
            logger.exception("Erro ao chamar OpenAI")
            return "Tive um probleminha aqui na conexão... pode repetir?", []
