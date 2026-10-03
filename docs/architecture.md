# Arquitetura — A Ponte

## 1. Visão geral

```text
                    ┌─────────────────────┐
                    │      A2A Client     │   (validador, curl, outro agente)
                    └──────────┬──────────┘
                               │
                    JSON-RPC 2.0 sobre HTTP (A2A v1.0)
                    header traceparent
                               │
                               ▼
                 ┌──────────────────────────┐
                 │       A2A Agent          │
                 │         :7300            │
                 │                          │
                 │ Agent Card (well-known)  │
                 │ Task State Machine       │
                 │ Task Store (memória)     │
                 │ MCP Host / Client        │
                 │ Bridge                   │
                 └────────────┬─────────────┘
                              │
                 Streamable HTTP (MCP 2026-07-28, stateless,
                 resposta JSON; _meta por request; headers espelhados)
                              │
                              ▼
                 ┌──────────────────────────┐
                 │       MCP Server         │
                 │          :7301           │
                 │                          │
                 │ tools (3)                │
                 │ resource politica://uso  │
                 │ MRTR (input_required)    │
                 │ requestState selado      │
                 │ regras de domínio        │
                 │ reservas em memória      │
                 └────────────┬─────────────┘
                              │ leitura na subida
                              ▼
                          dados/ (somente leitura)
```

**A2A Agent = tradução de protocolo e orquestração.**
**MCP Server = regras de negócio.**

Os dois são processos independentes. Eles só se comunicam por HTTP. O agente
nunca importa código de `servidor-mcp/`.

## 2. Responsabilidades

### 2.1 MCP Server (`servidor-mcp/`, porta 7301, `/mcp`)

| Responsabilidade | Detalhe |
|---|---|
| Transporte | Streamable HTTP, endpoint único `/mcp`, **stateless** e **JSON response** (o validador faz `json.loads` do corpo e não lê SSE). |
| Validação de `_meta` | Sem `protocolVersion` ou `clientCapabilities` ⇒ `-32602`, HTTP 400. Nunca inferir de request anterior. |
| Headers espelhados | `MCP-Protocol-Version`, `Mcp-Method` e `Mcp-Name` precisam bater com o corpo; senão `-32020` (SDK). |
| Tools | `listar_salas`, `consultar_disponibilidade`, `reservar_sala`, com `inputSchema` e `outputSchema`, `structuredContent` e o mesmo JSON em um bloco de texto. |
| Resource | `politica://uso`, `text/markdown`, conteúdo de `dados/politica-de-uso.md`. URI desconhecida ⇒ `-32602`. |
| Regras | Sala existe → intervalo válido → janela 08-20 (-03:00) → duração ≤ 2h → conflito → alternativas. |
| MRTR | Conflito com alternativas ⇒ `input_required` + elicitation form + `requestState` selado. Sem alternativas ⇒ `isError`. Sem capability ⇒ `-32021`. |
| Estado | Reservas em memória (carregadas de `dados/reservas.json` na subida). Nenhum estado entre `input_required` e o retry. |
| Log | stderr: método, id e `traceparent` de **todo** request. stdout fica livre. |

### 2.2 A2A Agent (`agente/`, porta 7300)

| Responsabilidade | Detalhe |
|---|---|
| Agent Card | `GET /.well-known/agent-card.json`, forma v1.0 (`supportedInterfaces[]` com `protocolBinding: JSONRPC`, `protocolVersion: 1.0`, `url`), skill `reservar-sala`. |
| Endpoint A2A | `POST /a2a`, JSON-RPC 2.0, métodos `SendMessage` e `GetTask`. `SendMessage` é **bloqueante**: responde com a Task já no estado final ou em `INPUT_REQUIRED`. |
| Parser | Formato fixo: `reservar sala=<id> inicio=<iso> fim=<iso> responsavel=<nome>` e `escolha=<id>\|recusar`. Determinístico, sem LLM. |
| Task State Machine | SUBMITTED → WORKING → {COMPLETED, FAILED, CANCELED, INPUT_REQUIRED}; terminais são definitivos. |
| Task Store | `dict[task_id, Task]` em memória, com `pending_mcp` privado por Task. |
| MCP Host | Cliente MCP por HTTP, `tools/list` em runtime, `resources/read politica://uso`, `_meta` completo, capability `{"elicitation": {"form": {}}}`, `traceparent`. |
| Bridge | Converte `input_required` em `TASK_STATE_INPUT_REQUIRED` e a continuação em retry MCP com id novo. |

O agente **não** decide conflito, política nem alternativas, e **não** abre o
`requestState`. A única validação que ele faz sobre a escolha é sintática:
confere se ela está no `enum`/`const` que o próprio servidor mandou na
elicitation. Isso é tradução de protocolo (validar resposta contra o
`requestedSchema`), não regra de sala.

## 3. O ciclo que dá nome ao desafio

```text
MCP input_required
        ↓
A2A TASK_STATE_INPUT_REQUIRED
        ↓
SendMessage continuação (taskId + "escolha=...")
        ↓
MCP retry (id novo, inputResponses, requestState ecoado)
```

Em detalhe:

1. `SendMessage` sem `taskId` ⇒ o agente cria a Task (SUBMITTED), faz o parse
   do pedido e passa para WORKING.
2. Garante a descoberta: `tools/list` (ver §8) e `resources/read politica://uso` (§9).
3. `tools/call reservar_sala` com `allow_input_required=True` no cliente do SDK.
   Assim o cliente devolve o `InputRequiredResult` cru, em vez de tentar
   responder sozinho por callback.
4. Resultado:
   - `complete` sem `isError` e `reservado: true` ⇒ artifact `reserva`, COMPLETED;
   - `complete` com `isError` ⇒ FAILED, com o texto da tool em `status.message`;
   - `input_required` ⇒ guarda `pending_mcp` na Task; status.message =
     `alternativas: <enum unido por ", ">`; INPUT_REQUIRED.
5. `SendMessage` com `taskId`:
   - Task terminal ⇒ erro JSON-RPC (não toca na Task);
   - Task INPUT_REQUIRED e escolha fora do enum (e diferente de `recusar`) ⇒
     continua INPUT_REQUIRED e repete a mesma linha de alternativas, sem chamar o MCP;
   - escolha válida ⇒ WORKING; retry `tools/call` com **novo id**, os mesmos
     `arguments` originais, `inputResponses {chave: {action: accept, content: {sala}}}`
     e o `requestState` intacto;
   - `recusar` ⇒ retry com `{action: "decline"}`; resultado `reservado: false` ⇒ CANCELED.
6. O `pending_mcp` é descartado quando a Task chega a um estado terminal.

**`input_required` não é callback.** O servidor termina a resposta. O retry é
um request independente, com id próprio. Nada fica aberto esperando o usuário.

## 4. Task Store

```python
tasks: dict[str, Task]   # task_id -> Task, em memória, por processo
```

```text
Task
├── id, context_id            (públicos)
├── state                     (TASK_STATE_*)
├── status_message            (Message do agente)
├── history: list[Message]
├── artifacts: list[Artifact]
├── trace_id                  (privado; ver §7)
└── pending_mcp               (privado; nunca serializado)
    ├── request_state         (str opaca, ecoada sem modificação)
    ├── input_request_key     (chave do inputRequests, ex.: "__main__:escolha_de_sala")
    ├── allowed_choices       (enum/const recebido, na ordem)
    ├── tool_name             (nome descoberto via tools/list)
    └── original_arguments    (dict exato enviado no 1º tools/call)
```

Regras:

- A serialização A2A da Task é uma função explícita que monta `id`,
  `contextId`, `status`, `history` e `artifacts`, e **nunca** inclui
  `pending_mcp`. É isso que garante a verificação 34.
- `requestState` é opaco: o agente não faz decode, não valida, não interpreta e
  não altera.
- `original_arguments` precisa ser reenviado **idêntico** no retry. O SDK
  2.3.0 sela um digest dos `arguments` ("request binding") e rejeita divergência.
- Concorrência: as Tasks são isoladas por chave. Um `asyncio.Lock` por Task
  evita que duas continuações simultâneas da mesma Task disparem dois retries.
- Sem persistência: um restart do agente perde as Tasks. Isso é aceito.

## 5. requestState

### 5.1 Decisão: usar o helper oficial do SDK (confirmado no `mcp` 2.3.0)

O SDK Python `mcp` 2.3.0 traz `mcp.server.request_state`:

- `RequestStateSecurity(keys=[secret], ttl=600.0)` usa o codec embutido
  `AESGCMRequestStateCodec`: AES-256-GCM com chave derivada por HKDF-SHA256 e
  token `v1.<base64url>` (a mesma forma vista no wire 03).
- O `RequestStateBoundary` sela todo `requestState` que sai e verifica todo eco
  que entra. Ele checa expiração, **request binding** (método, alvo e digest
  SHA-256 dos `arguments`), audience (nome do servidor) e principal (sem auth,
  `None`).
- Uma falha vira `-32602` (INVALID_PARAMS), e o motivo fica só no log.
- **Sem `request_state_security=`, o `MCPServer` usa `ephemeral()`**: uma chave
  aleatória por processo. Isso quebra o requisito de restart (avaliador, passo
  12). Portanto é **obrigatório** passar
  `RequestStateSecurity(keys=[REQUEST_STATE_SECRET])`.

Isso atende o README: "assinar é obrigatório, cifrar é opcional". AEAD assina e
cifra.

### 5.2 Conteúdo selado

Com resolvers (`Resolve(fn)` + `Elicit[T]`), o SDK sela a resposta registrada
de cada pergunta. Os argumentos originais ficam protegidos pelo digest de
binding, e o retry traz os mesmos `arguments`. A reconstrução do pedido usa os
`arguments` verificados pelo binding mais o outcome selado. Nada fica em
memória do servidor.

Exemplo conceitual (se for preciso um codec próprio; ver §5.3):

```json
{
  "version": 1,
  "sala": "sala-garagem",
  "inicio": "2026-11-03T14:00:00-03:00",
  "fim": "2026-11-03T15:00:00-03:00",
  "responsavel": "Marty",
  "alternativas": ["sala-fusca", "sala-mirante"],
  "inputRequestKey": "...",
  "iat": 0,
  "exp": 0
}
```

### 5.3 Alternativa de reserva (só se o helper falhar em algum teste)

Payload JSON compacto + `iat`/`exp` + HMAC-SHA256 com chave de
`REQUEST_STATE_SECRET` + Base64URL (`v1.<payload>.<mac>`), verificado com
`hmac.compare_digest`. Em caso de falha ⇒ `-32602`. O caminho preferido
continua sendo o helper oficial. **Decisão pendente da Fase 5**: confirmar, com
o SDK instalado, que o fluxo resolver/Elicit + `RequestStateSecurity` passa
13-20 e o teste manual de restart.

### 5.4 Expiração

`ttl = 600 s` (10 min, padrão do SDK, dentro da faixa exigida de 5-30 min). O
validador roda em segundos, então não há risco de expirar durante a execução.

### 5.5 Segredo

- `REQUEST_STATE_SECRET` vem do ambiente. Sem ele, ou com menos de 32 bytes, o
  servidor **não sobe** (fail-fast com mensagem no stderr).
- Para gerar: `python -c "import secrets; print(secrets.token_hex(32))"`
  (64 hex = 32 bytes de aleatoriedade).
- Nunca versionado: `.env` está no `.gitignore` e `.env.example` não tem valor.

## 6. inputRequests / inputResponses

Recebido (wire 03):

```json
"inputRequests": {
  "<chave>": {
    "method": "elicitation/create",
    "params": {
      "mode": "form",
      "message": "A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa.",
      "requestedSchema": {"type": "object", "properties": {"sala": {"type": "string", "enum": [...]}}, "required": ["sala"]}
    }
  }
}
```

O agente:

- exige exatamente uma entrada e `method == "elicitation/create"`; senão ⇒ FAILED;
- lê `properties.sala.enum`, ou `[const]` quando vier `const`;
- guarda a chave sem interpretar o texto dela.

Enviado no retry (wire 04 / 11):

```json
"inputResponses": {"<mesma chave>": {"action": "accept", "content": {"sala": "<escolha>"}}}
"inputResponses": {"<mesma chave>": {"action": "decline"}}
```

## 7. Propagação de traceparent

```text
A2A HTTP header traceparent
       ↓
Agent (lê o header da request A2A atual)
       ↓
extrai o trace-id (32 hex) — guardado na Task na criação
       ↓
gera span-id novo (16 hex) por request MCP
       ↓
MCP params._meta.traceparent = "00-<trace-id>-<span-id novo>-<flags>"
       ↓
MCP Server registra no stderr
```

Regras:

- O trace-id é preservado; o span-id pode mudar.
- O trace-id da Task é fixado no `SendMessage` que a cria. Na continuação, usa
  o header da continuação se houver; senão, o trace-id da Task. Assim "todos os
  requests MCP daquela Task" carregam o mesmo trace-id, mesmo quando a
  continuação vem sem header (verificação 29 não envia).
- Header inválido (formato W3C errado) ⇒ ignorado; segue sem traceparent.
- `tools/list` e `resources/read` feitos para a Task também levam o traceparent.

## 8. Descoberta via tools/list

- Antes do primeiro `tools/call`, o agente executa `tools/list`.
- **Decisão:** executar `tools/list` no início de cada Task nova. É barato, deixa
  no stderr do MCP um `tools/list` com o trace-id do validador logo antes do
  `tools/call` e elimina a questão de cache. (Cache em memória é permitido, mas
  não traz ganho aqui.)
- A seleção da tool é feita a partir do resultado: o agente procura, na lista
  descoberta, a tool cujo `inputSchema.required` cobre os campos do pedido
  (`sala`, `inicio`, `fim`, `responsavel`) e cujo nome corresponde ao verbo
  `reservar` (`reservar_sala`). Se não achar ⇒ FAILED com mensagem técnica. O
  agente não carrega a lista de tools no código.

## 9. Leitura do resource politica://uso

- `resources/read {uri: "politica://uso"}`, uma vez por Task, junto com a descoberta.
- Primeira linha: `versao: 2026-11-01` ⇒ regex `^versao:\s*(\S+)`.
- O valor entra no artifact: `{"reserva","sala","inicio","fim","responsavel","politica"}`.
- A versão do artifact vem do resource, não do `structuredContent.politica` do
  servidor (que existe, mas não cumpre o requisito "o agente lê o resource").

## 10. Mapeamento de resultados MCP → Task A2A

| Resultado MCP | Task | status.message |
|---|---|---|
| `complete`, `reservado: true` | COMPLETED + artifact `reserva` | `Reserva <id> confirmada na <sala>.` (wire 10) |
| `complete`, `isError: true` | FAILED | texto da tool (ex.: `Sala inexistente: sala-delorean`) |
| `input_required` | INPUT_REQUIRED | `alternativas: a, b` (exatamente essa linha) |
| `complete`, `reservado: false` (decline) | CANCELED | `Reserva recusada.` |
| erro JSON-RPC / falha HTTP | FAILED | mensagem técnica curta (sem requestState) |
| pedido A2A não parseável | FAILED | mensagem de formato esperado |

## 11. Erros A2A

| Situação | Erro JSON-RPC |
|---|---|
| Método desconhecido | `-32601` Method not found |
| params inválidos | `-32602` |
| `taskId` desconhecido (SendMessage/GetTask) | `-32001` TaskNotFoundError |
| SendMessage em Task terminal | `-32004` UnsupportedOperationError (validador só exige `error`) |
| JSON inválido | `-32700` |

## 12. Decisões de stack

| Item | Decisão | Motivo |
|---|---|---|
| Python | ≥ 3.10 (máquina: 3.11.15; comando `python`, não `python3`) | README |
| MCP | `mcp==2.3.0` (pacote oficial v2, dep. `mcp-types==2.3.0`) | tem MRTR (resolvers `Elicit`, `InputRequiredResult`), `RequestStateSecurity`, cliente com `allow_input_required=True`, headers espelhados |
| Servidor MCP | `MCPServer` + `streamable_http_app(json_response=True, stateless_http=True)` + uvicorn | resposta JSON exigida pelo validador |
| Cliente MCP | **Revisado na Fase 6:** cliente próprio sobre `httpx2==2.13.1` (a biblioteca HTTP do SDK), sem callback de elicitation | O `ClientSession` do SDK só declara elicitation quando há callback, e então anuncia `{"form":{},"url":{}}`; o contrato pede exatamente `{"elicitation":{"form":{}}}` e o `input_required` cru |
| A2A | **Decidido na Fase 7:** Starlette + JSON-RPC à mão (sem `a2a-sdk`) | Superfície pequena (2 métodos). O validador não envia `A2A-Version`, e não foi confirmado como o a2a-sdk trata a ausência do header (risco R17). O SDK puxa protobuf, google-api-core etc. O README não obriga SDK A2A. |
| HTTP server agente | Starlette + uvicorn (já vêm como deps do `mcp`) | sem dependência nova |
| Versões | travadas (`==`) no `pyproject.toml` | README |

## 13. Estrutura de código planejada

> Planejamento. Os arquivos Python **não** foram criados na Fase 0.

```text
.
├── README.md                 (substituído na Fase 10)
├── CLAUDE.md
├── pyproject.toml            (Fase 1)
├── .env.example
├── .gitignore
│
├── dados/                    (imutável)
├── exemplos/                 (imutável)
├── validador/                (imutável)
│
├── servidor-mcp/
│   ├── __init__.py
│   ├── main.py               entrypoint: lê config, sobe uvicorn em 7301
│   ├── config.py             env: host, porta, REQUEST_STATE_SECRET (fail-fast)
│   ├── server.py             MCPServer, RequestStateSecurity, app Starlette
│   ├── protocol.py           middleware de log stderr e validação de _meta, se o SDK não cobrir
│   ├── tools.py              3 tools + resolver de escolha de sala
│   ├── resources.py          politica://uso
│   ├── domain.py             validações, conflito, alternativas, mensagens literais
│   ├── reservations.py       repositório em memória + gerador res-NNNN
│   ├── request_state.py      fábrica do RequestStateSecurity (ou codec HMAC de reserva)
│   └── logging_utils.py      logger stderr
│
├── agente/
│   ├── __init__.py
│   ├── main.py               entrypoint: sobe uvicorn em 7300
│   ├── config.py             env: host, porta, MCP_URL, URL pública do card
│   ├── server.py             rotas Starlette (/a2a, well-known)
│   ├── agent_card.py         card v1.0
│   ├── a2a_protocol.py       dispatch JSON-RPC, erros A2A, serialização
│   ├── task_store.py         dict em memória + lock por Task
│   ├── task_model.py         Task, Message, Artifact, estados e transições
│   ├── parser.py             "reservar ..." e "escolha=..."
│   ├── mcp_client.py         host MCP: tools/list, resources/read, tools/call, retry
│   ├── bridge.py             MCP result ⇄ Task
│   └── traceparent.py        parse/geração de traceparent (não `trace.py`: sombrearia o módulo `trace` da stdlib)
│
└── docs/
```

Observações sobre o desenho:

- `servidor-mcp/protocol.py` e `logging_utils.py` só existem se o SDK não
  cobrir validação de `_meta` e log de request (a Fase 2 confirma). Se o SDK
  cobrir, os dois se fundem em um middleware fino ou somem.
- `servidor-mcp/request_state.py` pode virar só a construção de
  `RequestStateSecurity` dentro de `server.py`. Ele fica separado apenas se o
  codec de reserva (§5.3) for necessário.
- `servidor-mcp/` tem hífen: não é um pacote importável. Executar com
  `python servidor-mcp/main.py` (imports relativos ao diretório via `sys.path`
  do script) ou ajustar na Fase 1. O agente **não** deve importar nada de lá de
  qualquer forma.
