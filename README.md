# Robo de atendimento WhatsApp em Python

Este projeto cria um robo de atendimento com webhook para receber mensagens do WhatsApp e responder usando a API informada.

Ele ja vem com:

- servidor `FastAPI` para receber o webhook
- integracao com os endpoints `/message/text`, `/message/media`, `/message/presence` e `/message/read`
- fluxo configuravel por JSON
- memoria simples de conversa por `SQLite`
- suporte a imagem, audio, documento e qualquer arquivo servido pela pasta `assets/`

## Como funciona

1. O WhatsApp envia um evento para `POST /webhook`.
2. O servidor identifica quem enviou a mensagem.
3. O motor de fluxo decide a proxima resposta com base em `flows/flows.json`.
4. O robo envia texto, audio, imagem ou documento usando a sua API.

## Estrutura

```text
app/
  config.py
  flow_engine.py
  main.py
  session_store.py
  whatsapp_api.py
assets/
flows/
  flows.json
```

## Instalacao

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edite o arquivo `.env`:

```env
WHATSAPP_INSTANCE_TOKEN=seu_token_da_instancia
PUBLIC_BASE_URL=https://seu-dominio-publico.com
```

`PUBLIC_BASE_URL` precisa ser um endereco publico porque a API de midia envia arquivos por URL.

## Rodando

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Depois configure o webhook da sua instancia apontando para:

```text
https://seu-dominio.com/webhook
```

## Como editar o fluxo

O arquivo [flows/flows.json](C:\Users\Samuel Wildary\Desktop\robo\flows\flows.json) controla o atendimento.

### Gatilho inicial

```json
{
  "id": "atendimento_inicial",
  "triggers": ["oi", "ola", "menu"],
  "entry_step": "boas_vindas"
}
```

Se a pessoa mandar uma mensagem contendo um dos gatilhos, o fluxo comeca.

### Acoes disponiveis

#### Texto

```json
{
  "type": "text",
  "text": "Sua mensagem aqui"
}
```

#### Presenca

```json
{
  "type": "presence",
  "presence": "composing"
}
```

Valores aceitos: `composing`, `recording`, `available`, `unavailable`

#### Espera

```json
{
  "type": "wait",
  "seconds": 2
}
```

#### Midia por arquivo local

```json
{
  "type": "media",
  "media_path": "audio-exemplo.mp3",
  "caption": "Mensagem em audio"
}
```

#### Midia por URL direta

```json
{
  "type": "media",
  "media_url": "https://seu-site.com/arquivo.pdf",
  "caption": "Documento"
}
```

### Transicoes

```json
"transitions": {
  "1": "enviar_catalogo",
  "2": "enviar_audio",
  "*": "resposta_invalida"
}
```

Quando o usuario responde `1`, o robo vai para o passo `enviar_catalogo`.

## Endpoints locais

- `GET /health`: verifica se a API local esta no ar
- `POST /webhook`: recebe mensagens da plataforma
- `POST /admin/reload-flows`: recarrega o JSON de fluxo sem reiniciar o servidor

## Observacoes importantes

- A documentacao que voce passou usa o header `X-Instance-Token`, e isso ja esta configurado no cliente.
- O campo `to` da API recebe apenas o numero. O sistema remove automaticamente `@c.us` e outros sufixos.
- Para enviar arquivos locais, coloque os arquivos na pasta `assets/`.
- Para producao, o servidor precisa estar publicado em um dominio com HTTPS.

## Proximo passo recomendado

Se voce quiser, no proximo passo eu posso adaptar esse projeto para um fluxo real do seu negocio, por exemplo:

- cliente pede tabela de precos
- cliente escolhe produto
- robo envia PDF, audio e imagem
- robo transfere para humano quando necessario
