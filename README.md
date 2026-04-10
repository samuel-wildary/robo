# Agente de Atendimento WhatsApp em Python

Este projeto funciona como um agente de atendimento, nao como uma automacao fixa por passos. O agente recebe mensagens do WhatsApp, interpreta o contexto com IA e pode responder com texto, audio, imagem, video ou documento usando os arquivos enviados no painel.

## O que o projeto faz

- sobe uma API `FastAPI` para receber eventos do WhatsApp
- mantem sessao e historico de conversa em `Redis`
- usa a OpenAI para decidir a melhor resposta
- permite ao agente enviar arquivos da pasta `assets/` com delays e presencas configuradas
- traz um painel administrativo para subir arquivos e editar o guia operacional do agente

## Como funciona

1. O WhatsApp envia um evento para `POST /webhook`.
2. O servidor identifica o telefone real do cliente.
3. O agente consulta o historico da conversa no `Redis`.
4. A IA responde em texto ou chama a tool `execute_whatsapp_actions`.
5. Quando a tool pede uma midia, o sistema envia o arquivo certo da pasta `assets/`.

## Estrutura

```text
app/
  agent.py
  config.py
  flow_engine.py
  main.py
  session_store.py
  whatsapp_api.py
  static/
    admin.html
assets/
```

## Instalacao

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## Variaveis de ambiente

Preencha pelo menos:

```env
WHATSAPP_INSTANCE_TOKEN=seu_token_da_instancia
PUBLIC_BASE_URL=https://seu-dominio-publico.com
OPENAI_API_KEY=sua_chave_openai
REDIS_URL=redis://localhost:6379/0
```

`PUBLIC_BASE_URL` precisa ser publico porque os arquivos enviados ao WhatsApp sao servidos por URL.

## Rodando

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Depois configure sua instancia para apontar o webhook para:

```text
https://seu-dominio.com/webhook
```

## Painel admin

Abra:

```text
http://localhost:8000/admin
```

No painel voce pode:

- enviar audios, imagens, PDFs e outros arquivos
- definir delay e presence por arquivo
- configurar o atraso da primeira resposta
- editar a diretriz mestre do agente
- cadastrar blocos de atendimento para orientar a IA

## Endpoints

- `GET /health`: status da API
- `GET /admin`: abre o painel administrativo
- `GET /assets/{filename}`: serve os arquivos do painel
- `POST /webhook`: recebe mensagens da plataforma
- `GET /api/flow-config`: carrega o guia operacional do agente
- `POST /api/flow-config`: salva o guia operacional do agente
- `GET /api/assets`: lista arquivos e configuracoes
- `POST /api/assets/upload`: envia novos arquivos
- `DELETE /api/assets/{filename}`: remove arquivos
- `POST /api/asset-config`: salva delays e presencas

## Observacoes

- O cliente HTTP da sua integracao usa o header `X-Instance-Token`.
- O sistema remove sufixos como `@c.us` antes de enviar mensagens.
- O agente so deve enviar arquivos que realmente existirem na pasta `assets/`.
- Os delays e presencas configurados no painel sao aplicados automaticamente no envio.
