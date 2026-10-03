# Contrato do validador

Engenharia reversa de `validador/validar.py` (commit `263f17e`). Este documento
descreve **o que o validador efetivamente verifica**. Em caso de conflito com o
README ou com `exemplos/wire/`, vale o que está aqui (ver seção *Divergências*).

## 1. Mecânica geral do validador

### 1.1 Requests MCP (função `mcp()`, linhas 80-101)

Todo request ao servidor MCP é um `POST {--mcp}{--caminho-mcp}` (padrão
`http://localhost:7301/mcp`) com:

| Header | Valor |
|---|---|
| `Content-Type` | `application/json` |
| `Accept` | `application/json, text/event-stream` |
| `MCP-Protocol-Version` | `2026-07-28` |
| `Mcp-Method` | o método JSON-RPC (`tools/list`, `tools/call`, `resources/read`) |
| `Mcp-Name` | só em `tools/call` (nome da tool) e `resources/read` (a URI) |

Corpo:

```json
{
  "jsonrpc": "2.0",
  "id": "<token_hex(6), STRING de 12 hex>",
  "method": "<metodo>",
  "params": {
    "...": "...",
    "_meta": {
      "io.modelcontextprotocol/protocolVersion": "2026-07-28",
      "io.modelcontextprotocol/clientCapabilities": {"elicitation": {"form": {}}},
      "traceparent": "<somente quando passado>"
    }
  }
}
```

Fatos críticos derivados do código:

- **Não existe `initialize`.** O primeiro request já é `tools/list`. O servidor
  precisa operar no modelo stateless da revisão `2026-07-28`.
- **O `id` é string** (`secrets.token_hex(6)`), não inteiro.
- **Não há `io.modelcontextprotocol/clientInfo`** no `_meta` (os wire examples
  têm). O servidor não pode exigir `clientInfo`.
- **A resposta precisa ser JSON puro.** `post()` faz `json.loads(bruto)`; se o
  corpo vier como SSE (`text/event-stream`), o parse falha e a resposta vira
  `{"_bruto": ...}`, reprovando quase tudo. ⇒ servidor em modo
  `json_response=True`.
- O status HTTP é capturado tanto em 2xx quanto em `HTTPError` (4xx/5xx), e o
  corpo de erro também é parseado como JSON.
- Timeout de 30 s por request.

### 1.2 Requests A2A (funções `a2a()` / `enviar()`, linhas 128-147)

`POST {--agente}{--caminho-a2a}` (padrão `http://localhost:7300/a2a`), headers:
`Content-Type: application/json` e, quando passado, `traceparent`. **Sem header
`A2A-Version`.**

```json
{
  "jsonrpc": "2.0",
  "id": "<token_hex(6)>",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "msg-<hex>",
      "role": "ROLE_USER",
      "parts": [{"text": "<pedido>"}],
      "taskId": "<somente em continuação>"
    }
  }
}
```

`GetTask`: `params = {"id": "<taskId>"}`.

Leitura da resposta:

- `tarefa_de()`: usa `result.task` se existir, senão `result` (aceita os dois).
- `estado()`: `task.status.state`.
- `mensagem()`: concatena (com espaço) os `text` de `task.status.message.parts`.
- Artifacts: `task.artifacts[0].parts[*].text` concatenados e parseados como JSON.
- Todo corpo devolvido pelo agente é guardado em `R.corpos_a2a` para a
  verificação 34 (vazamento de `requestState`).

### 1.3 Agent Card

`GET {--agente}/.well-known/agent-card.json` com `urllib.request.urlopen`, timeout 15 s.
Se essa chamada lançar exceção, as verificações 21 a 36 falham em cascata.

### 1.4 Ordem e efeito colateral

As verificações rodam em ordem fixa e **compartilham o estado de reservas do
servidor MCP** (o agente usa o mesmo servidor). As alternativas esperadas em
21-36 dependem das reservas criadas em 1-20. Por isso os dois processos precisam
estar recém-iniciados (`validador/README.md`).

Constantes (linhas 22-35):

```text
PROTOCOLO            = "2026-07-28"
POLITICA             = "2026-11-01"
ERRO_SALA            = "Sala inexistente: sala-delorean"
ERRO_JANELA          = "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00"
ERRO_DURACAO         = "Duracao acima do limite: a politica permite no maximo 2 horas"
ERRO_INTERVALO       = "Intervalo invalido: fim deve ser posterior a inicio"
ERRO_SEM_ALTERNATIVA = "Sem alternativas disponiveis no intervalo"
DIA                  = "2026-11-03"   h("HH:MM") -> "2026-11-03THH:MM:00-03:00"
TRACEPARENT          = "00-<trace_id 32hex>-<span 16hex>-01"
```

## 2. Simulação do estado de reservas

Estado inicial (`dados/reservas.json`): `res-0001 garagem 14-15 Marty`,
`res-0002 fusca 16-17 Jennifer`. Capacidades: aquario 4, porao 6, garagem 12,
fusca 12, mirante 20.

| Após verif. | Reserva criada | Observação |
|---|---|---|
| 16 | `res-0003` garagem 16-17 Validador | retry aceito com `sala-garagem` |
| 18 (1º passo) | `res-0004` garagem 09-10 Ocupante | caminho livre |
| 18 (retry) | nenhuma **ou** fusca 09-10 Doc | SDK com *request binding* rejeita (nenhuma) |
| 20 (1º passo) | mirante 11-12 Validador | caminho livre |
| 24 | porao 09-10 Doc | via agente |
| 30 | fusca 14-15 Marty | via agente |
| 33 | mirante 16-17 Lorraine; mirante 14-15 George | via agente |

Alternativas resultantes (regra: capacidade ≥ pedida, livres, ≠ sala pedida,
máx. 3, ordem capacidade↑ e id↑):

| Verif. | Pedido | Alternativas esperadas |
|---|---|---|
| 13 | garagem 14-15 | `sala-fusca, sala-mirante` |
| 16 | fusca 16-17 | `sala-garagem, sala-mirante` |
| 18 | garagem 09-10 | `sala-fusca, sala-mirante` |
| 20 | mirante 11-12 | nenhuma ⇒ erro |
| 27/28 | garagem 14-15 | `sala-fusca, sala-mirante` |
| 32 | garagem 14:30-15:30 | `sala-mirante` (fusca ocupada 14-15 desde a 30) |
| 33a | fusca 16-17 | `sala-mirante` (garagem ocupada 16-17 desde a 16) |
| 33b | garagem 14-15 | `sala-mirante` |
| 36 | porao 09-10 | `sala-mirante` (ou `sala-fusca, sala-mirante` se a 18 não reservar) |

Com **uma única alternativa**, o SDK pode emitir `const` em vez de `enum`. O
validador aceita os dois no MCP (verif. 14). **O agente também precisa aceitar
os dois** (verificações 32 e 33).

---

## 3. Servidor MCP (verificações 01-12)

### 01 — tools/list traz as três tools

```text
ID: 01
Área: Servidor MCP / descoberta
Objetivo: tools/list lista listar_salas, consultar_disponibilidade e reservar_sala
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: padrão MCP; Mcp-Method: tools/list; sem Mcp-Name
JSON-RPC method: tools/list
Request: params = {_meta: {protocolVersion, clientCapabilities(elicitation.form)}}
Campos críticos: result.tools[].name
Resultado esperado: {"listar_salas","consultar_disponibilidade","reservar_sala"} ⊆ nomes
HTTP Status: não verificado (esperado 200)
JSON-RPC result ou error: result
Mensagem literal: —
Arquivos/componentes futuros responsáveis: servidor-mcp/tools.py, servidor-mcp/server.py
Wire example relacionado: 01-tools-list.json
Dependências: servidor stateless sem initialize; resposta JSON (não SSE)
```

### 02 — toda tool tem inputSchema de objeto

```text
ID: 02
Área: Servidor MCP / schemas
Objetivo: inputSchema.type == "object" em todas as tools
Endpoint: POST /mcp (reaproveita a resposta da 01)
HTTP Method: POST
Headers obrigatórios: idem 01
JSON-RPC method: tools/list
Request: idem 01
Campos críticos: tools[*].inputSchema.type
Resultado esperado: todas "object" e lista não vazia
HTTP Status: —
JSON-RPC result ou error: result
Mensagem literal: —
Arquivos/componentes futuros responsáveis: servidor-mcp/tools.py (SDK gera via type hints)
Wire example relacionado: 01-tools-list.json
Dependências: 01
```

### 03 — listar_salas: structuredContent == JSON do bloco de texto

```text
ID: 03
Área: Servidor MCP / tool listar_salas
Objetivo: structuredContent e o texto concatenado de content[] são o mesmo JSON
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Method: tools/call; Mcp-Name: listar_salas
JSON-RPC method: tools/call
Request: params = {name: "listar_salas", arguments: {}}
Campos críticos: result.structuredContent; result.content[].text
Resultado esperado: json.loads(" ".join(textos)) == structuredContent
HTTP Status: —
JSON-RPC result ou error: result
Mensagem literal: —
Arquivos/componentes futuros responsáveis: servidor-mcp/tools.py, servidor-mcp/domain.py
Wire example relacionado: 01-tools-list.json (outputSchema {"salas": [SalaOut]})
Dependências: dados/salas.json
Observação: content deve ter UM bloco de texto (textos são unidos por espaço);
            structuredContent = {"salas": [...]} conforme outputSchema do wire.
```

### 04 — `_meta` sem protocolVersion ⇒ -32602 / HTTP 400

```text
ID: 04
Área: Servidor MCP / validação de _meta
Objetivo: rejeitar request sem io.modelcontextprotocol/protocolVersion no _meta
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: MCP-Protocol-Version: 2026-07-28 (o header CONTINUA presente!)
JSON-RPC method: tools/call (listar_salas)
Request: _meta = {clientCapabilities} apenas
Campos críticos: error.code; status HTTP
Resultado esperado: error.code == -32602 E status == 400
HTTP Status: 400
JSON-RPC result ou error: error -32602
Mensagem literal: livre
Arquivos/componentes futuros responsáveis: servidor-mcp/server.py (SDK) ou middleware em protocol.py
Wire example relacionado: — (nenhum)
Dependências: o servidor não pode cair no header para inferir a versão
```

### 05 — `_meta` sem clientCapabilities ⇒ -32602 / HTTP 400

```text
ID: 05
Área: Servidor MCP / validação de _meta
Objetivo: rejeitar request sem io.modelcontextprotocol/clientCapabilities
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: padrão + Mcp-Name: listar_salas
JSON-RPC method: tools/call (listar_salas)
Request: _meta = {protocolVersion} apenas
Campos críticos: error.code; status HTTP
Resultado esperado: -32602 e HTTP 400
HTTP Status: 400
JSON-RPC result ou error: error -32602
Mensagem literal: livre
Arquivos/componentes futuros responsáveis: idem 04
Wire example relacionado: —
Dependências: —
```

### 06 — tool inexistente é recusada

```text
ID: 06
Área: Servidor MCP / erro de protocolo
Objetivo: tools/call de "voar_delorean" é recusado
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: voar_delorean
JSON-RPC method: tools/call
Request: {name: "voar_delorean", arguments: {}}
Campos críticos: error.code OU result.isError
Resultado esperado: error.code == -32602 OU result.isError is True
HTTP Status: não verificado
JSON-RPC result ou error: qualquer dos dois
Mensagem literal: —
Arquivos/componentes futuros responsáveis: SDK (servidor-mcp/server.py)
Wire example relacionado: —
Dependências: —
Observação: isError precisa ser o booleano True (comparação `is True`).
```

### 07 — resources/read politica://uso

```text
ID: 07
Área: Servidor MCP / resource
Objetivo: devolver o conteúdo de dados/politica-de-uso.md
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Method: resources/read; Mcp-Name: politica://uso
JSON-RPC method: resources/read
Request: {uri: "politica://uso"}
Campos críticos: result.contents[0].text
Resultado esperado: "2026-11-01" contido no texto
HTTP Status: —
JSON-RPC result ou error: result
Mensagem literal: "2026-11-01"
Arquivos/componentes futuros responsáveis: servidor-mcp/resources.py
Wire example relacionado: 05-resources-read-politica.json (mimeType text/markdown)
Dependências: dados/politica-de-uso.md
```

### 08 — resources/read de URI inexistente ⇒ -32602

```text
ID: 08
Área: Servidor MCP / resource
Objetivo: URI desconhecida é erro de protocolo, nunca contents vazio
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: politica://inexistente
JSON-RPC method: resources/read
Request: {uri: "politica://inexistente"}
Campos críticos: error.code
Resultado esperado: error.code == -32602
HTTP Status: não verificado
JSON-RPC result ou error: error -32602
Mensagem literal: livre
Arquivos/componentes futuros responsáveis: SDK / servidor-mcp/resources.py
Wire example relacionado: —
Dependências: —
```

### 09 — sala inexistente ⇒ isError + mensagem exata

```text
ID: 09
Área: Servidor MCP / regras (via reservar_sala)
Objetivo: sala fora de dados/salas.json
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: reservar_sala
JSON-RPC method: tools/call
Request: reservar_sala {sala: "sala-delorean", inicio: 09:00, fim: 10:00, responsavel: "Validador"}
Campos críticos: result.isError (truthy); texto de content[]
Resultado esperado: isError e texto contém a mensagem
HTTP Status: —
JSON-RPC result ou error: result com isError
Mensagem literal: "Sala inexistente: sala-delorean"
Arquivos/componentes futuros responsáveis: servidor-mcp/domain.py
Wire example relacionado: —
Dependências: —
Observação: prefixo do SDK ("Error executing tool ...:") é aceito (checagem por `in`).
```

### 10 — fora da janela ⇒ isError + mensagem exata

```text
ID: 10
Área: Servidor MCP / regras (via consultar_disponibilidade)
Objetivo: inicio 07:00 fora da janela 08:00-20:00
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: consultar_disponibilidade
JSON-RPC method: tools/call
Request: consultar_disponibilidade {sala: "sala-aquario", inicio: 07:00, fim: 08:00}
Campos críticos: isError; texto
Resultado esperado: isError e mensagem contida
HTTP Status: —
JSON-RPC result ou error: result com isError
Mensagem literal: "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00"
Arquivos/componentes futuros responsáveis: servidor-mcp/domain.py
Wire example relacionado: —
Dependências: —
```

### 11 — duração > 2h ⇒ isError + mensagem exata

```text
ID: 11
Área: Servidor MCP / regras
Objetivo: 09:00-12:00 (3h)
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: consultar_disponibilidade
JSON-RPC method: tools/call
Request: consultar_disponibilidade {sala-aquario, 09:00, 12:00}
Campos críticos: isError; texto
Resultado esperado: isError e mensagem contida
HTTP Status: —
JSON-RPC result ou error: result com isError
Mensagem literal: "Duracao acima do limite: a politica permite no maximo 2 horas"
Arquivos/componentes futuros responsáveis: servidor-mcp/domain.py
Wire example relacionado: —
Dependências: —
```

### 12 — intervalo invertido ⇒ isError + mensagem exata

```text
ID: 12
Área: Servidor MCP / regras
Objetivo: fim (09:00) < inicio (10:00)
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: consultar_disponibilidade
JSON-RPC method: tools/call
Request: consultar_disponibilidade {sala-aquario, 10:00, 09:00}
Campos críticos: isError; texto
Resultado esperado: isError e mensagem contida
HTTP Status: —
JSON-RPC result ou error: result com isError
Mensagem literal: "Intervalo invalido: fim deve ser posterior a inicio"
Arquivos/componentes futuros responsáveis: servidor-mcp/domain.py
Wire example relacionado: —
Dependências: —
Observação: a validação de intervalo deve vir ANTES da de duração/janela
            (ordem: sala → intervalo → janela → duração).
```

---

## 4. MRTR (verificações 13-20)

### 13 — conflito ⇒ input_required

```text
ID: 13
Área: MRTR
Objetivo: reserva em intervalo ocupado devolve input_required
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: reservar_sala
JSON-RPC method: tools/call
Request: reservar_sala {sala-garagem, 14:00, 15:00, "Validador"}; _meta.traceparent = TRACEPARENT
Campos críticos: result.resultType; result.inputRequests; result.requestState
Resultado esperado: resultType == "input_required", len(inputRequests) == 1, requestState não vazio
HTTP Status: não verificado (wire: 200)
JSON-RPC result ou error: result
Mensagem literal: "input_required"
Arquivos/componentes futuros responsáveis: servidor-mcp/tools.py (resolver Elicit), servidor-mcp/request_state.py
Wire example relacionado: 03-tools-call-conflito-input-required.json
Dependências: conflito com res-0001
```

### 14 — elicitation em form mode com alternativas na ordem

```text
ID: 14
Área: MRTR
Objetivo: o inputRequest é elicitation form com enum/const correto
Endpoint: (reaproveita a resposta da 13)
HTTP Method: —
Headers obrigatórios: —
JSON-RPC method: —
Request: —
Campos críticos: inputRequests[k].params.mode; .requestedSchema.properties.sala.enum|const
Resultado esperado: mode == "form" e enum == ["sala-fusca", "sala-mirante"]
HTTP Status: —
JSON-RPC result ou error: result
Mensagem literal: "form"; "sala-fusca", "sala-mirante" (nessa ordem)
Arquivos/componentes futuros responsáveis: servidor-mcp/domain.py (alternativas), servidor-mcp/tools.py
Wire example relacionado: 03
Dependências: 13
```

### 15 — conflito sem capability ⇒ -32021 / HTTP 400

```text
ID: 15
Área: MRTR / capability negotiation
Objetivo: não pedir elicitation a cliente que não a declarou
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: reservar_sala
JSON-RPC method: tools/call
Request: reservar_sala {sala-garagem, 14:00, 15:00}; _meta.clientCapabilities = {}
Campos críticos: error.code; error.data.requiredCapabilities; status HTTP
Resultado esperado: code == -32021, "requiredCapabilities" in data, HTTP 400
HTTP Status: 400
JSON-RPC result ou error: error -32021
Mensagem literal: livre (SDK gera "Client did not declare the form elicitation capability ...")
Arquivos/componentes futuros responsáveis: SDK (resolver Elicit) / servidor-mcp/tools.py
Wire example relacionado: 06-erro-32021-sem-elicitation.json
Dependências: 13
```

### 16 — retry conclui a reserva

```text
ID: 16
Área: MRTR
Objetivo: retry com inputResponses + requestState conclui
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: reservar_sala
JSON-RPC method: tools/call (2 requests, ids diferentes)
Request: 1) reservar_sala {sala-fusca, 16:00, 17:00} ⇒ input_required
         2) mesmos arguments + inputResponses {chave: {action: accept, content: {sala: sala-garagem}}} + requestState
Campos críticos: resultType; isError; structuredContent.sala
Resultado esperado: resultType == "complete", isError falsy, structuredContent.sala == "sala-garagem"
HTTP Status: —
JSON-RPC result ou error: result
Mensagem literal: "complete"
Arquivos/componentes futuros responsáveis: servidor-mcp/tools.py, servidor-mcp/reservations.py
Wire example relacionado: 04-tools-call-retry.json
Dependências: 13 (MRTR funcionando); cria res-0003 garagem 16-17
Observação: structuredContent.sala é a sala ESCOLHIDA, não a pedida.
```

### 17 — requestState adulterado ⇒ -32602

```text
ID: 17
Área: MRTR / integridade
Objetivo: detectar adulteração
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: reservar_sala
JSON-RPC method: tools/call
Request: retry da 13 com requestState[:-6] + "AAAAAA" (ou "BBBBBB")
Campos críticos: error.code
Resultado esperado: error.code == -32602
HTTP Status: não verificado
JSON-RPC result ou error: error -32602
Mensagem literal: livre (SDK)
Arquivos/componentes futuros responsáveis: servidor-mcp/request_state.py (RequestStateSecurity do SDK)
Wire example relacionado: 04 (forma do retry)
Dependências: 13
```

### 18 — argumentos adulterados no retry não tomam efeito

```text
ID: 18
Área: MRTR / integridade
Objetivo: arguments do retry não são confiáveis
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: reservar_sala
JSON-RPC method: tools/call (3 requests)
Request: 1) reservar garagem 09-10 "Ocupante" (livre ⇒ cria)
         2) reservar garagem 09-10 "Doc" ⇒ input_required
         3) retry com arguments {sala-mirante, 13:00, 14:00, "Biff"} + accept sala-fusca + requestState de (2)
Campos críticos: error OU structuredContent.inicio/responsavel
Resultado esperado: existe `error` OU (inicio == 09:00 E responsavel == "Doc")
HTTP Status: —
JSON-RPC result ou error: qualquer dos dois
Mensagem literal: —
Arquivos/componentes futuros responsáveis: SDK (request binding) / servidor-mcp/request_state.py
Wire example relacionado: 04
Dependências: 13
Observação: o RequestStateBoundary do SDK 2.3.0 sela um digest dos arguments
            ("request binding") ⇒ rejeição com erro ⇒ PASS.
```

### 19 — recusa conclui sem reservar e sem isError

```text
ID: 19
Área: MRTR / decline
Objetivo: action=decline é conclusão normal
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: reservar_sala
JSON-RPC method: tools/call
Request: retry da 13 (garagem 14-15) com inputResponses {chave: {action: "decline"}} e o requestState ORIGINAL da 13
Campos críticos: resultType; isError; structuredContent.reservado
Resultado esperado: resultType == "complete", isError falsy, structuredContent.reservado is False
HTTP Status: —
JSON-RPC result ou error: result
Mensagem literal: —
Arquivos/componentes futuros responsáveis: servidor-mcp/tools.py
Wire example relacionado: 11-tools-call-retry-recusa.json (motivo: "recusado")
Dependências: 13. O requestState da 13 é usado aqui pela 1ª vez com sucesso
              ⇒ não pode haver "uso único" que o invalide na 17.
```

### 20 — conflito sem alternativa ⇒ isError + mensagem exata

```text
ID: 20
Área: MRTR / regra de alternativas
Objetivo: sem alternativa não há elicitation
Endpoint: POST /mcp
HTTP Method: POST
Headers obrigatórios: Mcp-Name: reservar_sala
JSON-RPC method: tools/call (2 requests)
Request: reservar mirante 11-12 (cria); reservar mirante 11-12 de novo
Campos críticos: result.isError; texto
Resultado esperado: isError e mensagem contida
HTTP Status: —
JSON-RPC result ou error: result com isError
Mensagem literal: "Sem alternativas disponiveis no intervalo"
Arquivos/componentes futuros responsáveis: servidor-mcp/domain.py, tools.py
Wire example relacionado: —
Dependências: nenhuma sala tem capacidade ≥ 20 além do mirante
Observação: o resolver Elicit NÃO pode rodar quando não há alternativas
            (senão viraria input_required ou -32021).
```

---

## 5. Agent como MCP Host

O validador **não verifica por script** os requisitos do agente como host MCP
(tools/list antes de tools/call, traceparent no stderr, capability declarada,
id novo no retry). Eles são verificados:

- indiretamente, porque 24-36 só passam se o agente falar MCP corretamente;
- manualmente, pelo avaliador, no stderr do servidor MCP (README, *Fluxo do avaliador* 5 e 6).

O validador envia `traceparent` nas verificações 24, 27 e 30 e imprime o
trace-id na 1ª linha para essa conferência manual.

---

## 6. A2A (verificações 21-26, 31, 35, 36)

### 21 — Agent Card responde 200 com JSON

```text
ID: 21
Área: A2A / descoberta
Objetivo: card no well-known
Endpoint: GET /.well-known/agent-card.json (porta 7300)
HTTP Method: GET
Headers obrigatórios: nenhum
JSON-RPC method: —
Request: —
Campos críticos: status; corpo JSON não vazio
Resultado esperado: HTTP 200 e JSON objeto não vazio
HTTP Status: 200
JSON-RPC result ou error: —
Mensagem literal: —
Arquivos/componentes futuros responsáveis: agente/agent_card.py, agente/server.py
Wire example relacionado: 07-a2a-agent-card.json
Dependências: — (se falhar, 22-36 falham em cascata)
```

### 22 — interface JSON-RPC com url e versão 1.0

```text
ID: 22
Área: A2A / Agent Card
Objetivo: forma v1.0 de supportedInterfaces
Endpoint: (card da 21)
Campos críticos: supportedInterfaces[].protocolBinding, .url, .protocolVersion
Resultado esperado: algum item com protocolBinding.upper() começando com "JSONRPC",
                    url não vazia e protocolVersion começando com "1.0"
HTTP Status: —
Mensagem literal: "JSONRPC", "1.0"
Arquivos/componentes futuros responsáveis: agente/agent_card.py
Wire example relacionado: 07
Dependências: 21
Observação: NÃO usar interfaces, preferredTransport, additionalInterfaces (v0.x).
```

### 23 — skill reservar-sala

```text
ID: 23
Área: A2A / Agent Card
Objetivo: skill id "reservar-sala"
Campos críticos: skills[].id
Resultado esperado: "reservar-sala" ∈ ids
Mensagem literal: "reservar-sala"
Arquivos/componentes futuros responsáveis: agente/agent_card.py
Wire example relacionado: 07
Dependências: 21
```

### 24 — SendMessage com sala livre conclui a Task

```text
ID: 24
Área: A2A + Bridge (caminho feliz)
Objetivo: reserva livre via agente termina COMPLETED
Endpoint: POST /a2a
HTTP Method: POST
Headers obrigatórios: Content-Type; traceparent: TRACEPARENT
JSON-RPC method: SendMessage
Request: text = "reservar sala=sala-porao inicio=2026-11-03T09:00:00-03:00 fim=2026-11-03T10:00:00-03:00 responsavel=Doc"
Campos críticos: result.task.status.state
Resultado esperado: "TASK_STATE_COMPLETED"
HTTP Status: não verificado (esperado 200)
JSON-RPC result ou error: result.task
Mensagem literal: "TASK_STATE_COMPLETED"
Arquivos/componentes futuros responsáveis: agente/a2a_protocol.py, agente/bridge.py, agente/mcp_client.py
Wire example relacionado: 08 (forma), 10 (forma completed)
Dependências: 21; MCP funcional; SendMessage síncrono (bloqueante)
```

### 25 — artifact "reserva" com politica

```text
ID: 25
Área: A2A / artifact
Objetivo: artifact traz a reserva e a versão da política lida do resource
Campos críticos: task.artifacts[0].name; JSON de parts[*].text
Resultado esperado: name == "reserva", conteudo.politica == "2026-11-01", conteudo.sala == "sala-porao"
Mensagem literal: "reserva", "2026-11-01"
Arquivos/componentes futuros responsáveis: agente/bridge.py (monta artifact), agente/mcp_client.py (resources/read)
Wire example relacionado: 10 (artifactId, name, parts[{text: json}])
Dependências: 24
Observação: o artifact da Task 24 deve ser o artifacts[0].
```

### 26 — GetTask devolve id, contextId e estado

```text
ID: 26
Área: A2A
Objetivo: GetTask reflete a Task concluída
Endpoint: POST /a2a
HTTP Method: POST
Headers obrigatórios: Content-Type
JSON-RPC method: GetTask
Request: params = {id: <id da Task 24>}
Campos críticos: task.id; task.contextId; task.status.state
Resultado esperado: id igual, contextId não vazio, state == "TASK_STATE_COMPLETED"
JSON-RPC result ou error: result (task ou result direto)
Arquivos/componentes futuros responsáveis: agente/a2a_protocol.py, agente/task_store.py
Wire example relacionado: 09-a2a-get-task-input-required.json
Dependências: 24
```

### 31 — SendMessage em Task terminal é recusado

```text
ID: 31
Área: A2A / máquina de estados
Objetivo: Task COMPLETED não volta a WORKING
Endpoint: POST /a2a
JSON-RPC method: SendMessage
Request: text "escolha=sala-mirante", taskId = Task concluída na 30
Campos críticos: presença de "error"
Resultado esperado: bool(resposta.error) == True
HTTP Status: não verificado
JSON-RPC result ou error: error (código livre; ver decisão em architecture.md)
Arquivos/componentes futuros responsáveis: agente/a2a_protocol.py, agente/task_model.py
Wire example relacionado: —
Dependências: 30
```

### 35 — sala inexistente ⇒ FAILED com a mensagem da tool

```text
ID: 35
Área: A2A + Bridge (erro de execução)
Objetivo: isError do MCP vira TASK_STATE_FAILED
Endpoint: POST /a2a
JSON-RPC method: SendMessage
Request: "reservar sala=sala-delorean inicio=...09:00... fim=...10:00... responsavel=Doc"
Campos críticos: status.state; status.message.parts[].text
Resultado esperado: state == "TASK_STATE_FAILED" e "Sala inexistente: sala-delorean" ∈ mensagem
Mensagem literal: "Sala inexistente: sala-delorean"
Arquivos/componentes futuros responsáveis: agente/bridge.py
Wire example relacionado: —
Dependências: 24
Observação: a mensagem precisa estar em status.message (não só no history).
```

### 36 — determinismo: mesmo pedido ⇒ mesma pausa

```text
ID: 36
Área: A2A + Bridge
Objetivo: duas pausas idênticas, byte a byte
Endpoint: POST /a2a
JSON-RPC method: SendMessage (2x, Tasks novas)
Request: "reservar sala=sala-porao inicio=...09:00... fim=...10:00... responsavel=Doc" (porao ocupada desde a 24)
Campos críticos: status.message text
Resultado esperado: m1 == m2 e m1.startswith("alternativas:")
Mensagem literal: "alternativas:" no INÍCIO da mensagem
Arquivos/componentes futuros responsáveis: agente/bridge.py
Wire example relacionado: 08
Dependências: 24
Observação: a status.message precisa ter EXATAMENTE um part com a linha; nada de
            ids aleatórios, saudação ou prefixo no texto.
```

---

## 7. Bridge (verificações 27-30, 32-34)

### 27 — sala ocupada pausa a Task

```text
ID: 27
Área: Bridge
Objetivo: MCP input_required ⇒ TASK_STATE_INPUT_REQUIRED
Endpoint: POST /a2a
Headers obrigatórios: traceparent: TRACEPARENT
JSON-RPC method: SendMessage
Request: "reservar sala=sala-garagem inicio=...14:00... fim=...15:00... responsavel=Marty"
Campos críticos: status.state
Resultado esperado: "TASK_STATE_INPUT_REQUIRED"
Arquivos/componentes futuros responsáveis: agente/bridge.py, agente/task_store.py
Wire example relacionado: 08
Dependências: 24; MCP 13
```

### 28 — Task pausada lista alternativas na ordem

```text
ID: 28
Área: Bridge
Objetivo: linha de alternativas na ordem do enum
Campos críticos: status.message.parts[].text
Resultado esperado: "alternativas: sala-fusca, sala-mirante" contido na mensagem
Mensagem literal: "alternativas: sala-fusca, sala-mirante"
Arquivos/componentes futuros responsáveis: agente/bridge.py
Wire example relacionado: 08 (formato "alternativas: <ids>")
Dependências: 27
```

### 29 — escolha fora do enum mantém a Task pausada

```text
ID: 29
Área: Bridge
Objetivo: validação de escolha contra o enum recebido
JSON-RPC method: SendMessage
Request: "escolha=sala-aquario", taskId da 27 (sem traceparent)
Campos críticos: status.state
Resultado esperado: "TASK_STATE_INPUT_REQUIRED"
Arquivos/componentes futuros responsáveis: agente/parser.py, agente/bridge.py
Wire example relacionado: 10 (forma da continuação)
Dependências: 27
Observação: NÃO chamar o MCP; repetir a linha de alternativas; não consumir o requestState.
```

### 30 — continuação conclui na sala escolhida

```text
ID: 30
Área: Bridge
Objetivo: retry MCP com id novo, inputResponses e requestState
Headers obrigatórios: traceparent: TRACEPARENT
JSON-RPC method: SendMessage
Request: "escolha=sala-fusca", taskId da 27
Campos críticos: status.state; artifacts[0] JSON .sala
Resultado esperado: "TASK_STATE_COMPLETED" e sala == "sala-fusca"
Arquivos/componentes futuros responsáveis: agente/bridge.py, agente/mcp_client.py
Wire example relacionado: 04, 10
Dependências: 27, 29; cria fusca 14-15 Marty
```

### 32 — recusa termina em CANCELED

```text
ID: 32
Área: Bridge
Objetivo: escolha=recusar ⇒ action decline ⇒ CANCELED
JSON-RPC method: SendMessage (2x)
Request: 1) "reservar sala=sala-garagem inicio=...14:30... fim=...15:30... responsavel=Biff" (alternativa única: sala-mirante, possivelmente `const`)
         2) "escolha=recusar", taskId de (1)
Campos críticos: status.state
Resultado esperado: "TASK_STATE_CANCELED"
Arquivos/componentes futuros responsáveis: agente/bridge.py
Wire example relacionado: 11 (retry decline)
Dependências: 30
```

### 33 — duas Tasks pausadas simultaneamente

```text
ID: 33
Área: Bridge / isolamento
Objetivo: requestState por Task
JSON-RPC method: SendMessage (4x)
Request: A = fusca 16-17 Lorraine; B = garagem 14-15 George (ambas pausam, alternativa única sala-mirante);
         depois "escolha=sala-mirante" para A e para B
Campos críticos: estados; artifacts[0].reserva e .inicio
Resultado esperado: A e B pausadas; ambas COMPLETED; reserva(A) != reserva(B); inicio(A) != inicio(B)
Arquivos/componentes futuros responsáveis: agente/task_store.py, agente/bridge.py
Wire example relacionado: 08, 10
Dependências: 30, 32
```

### 34 — nenhuma resposta A2A carrega o requestState

```text
ID: 34
Área: Bridge / opacidade
Objetivo: requestState nunca sai pelo A2A
Campos críticos: todos os corpos devolvidos pelo agente
Resultado esperado: requestState(13)[:40] não aparece em nenhum corpo A2A
Arquivos/componentes futuros responsáveis: agente/task_model.py (pending_mcp fora da serialização)
Wire example relacionado: —
Dependências: 13
```

---

## 8. Validação final

Não existe verificação nº 37. O resultado final é a linha:

```text
resumo: 36 passaram, 0 falharam, de 36 verificacoes
```

e o código de saída `0` (linha 413). Fora do script, o avaliador confere
manualmente (README, *Fluxo do avaliador*): restart do MCP com requestState
válido, traceparent no stderr, ids diferentes no par de `tools/call`.

---

## 9. Matriz resumida

| # | Área | Request | Expected | Código responsável futuramente |
|---|---|---|---|---|
| 01 | MCP | tools/list | 3 tools presentes | servidor-mcp/tools.py |
| 02 | MCP | tools/list | inputSchema.type=object | servidor-mcp/tools.py |
| 03 | MCP | tools/call listar_salas | structuredContent == JSON(text) | servidor-mcp/tools.py |
| 04 | MCP | tools/call sem protocolVersion | -32602 + HTTP 400 | servidor-mcp/server.py |
| 05 | MCP | tools/call sem clientCapabilities | -32602 + HTTP 400 | servidor-mcp/server.py |
| 06 | MCP | tools/call voar_delorean | -32602 ou isError true | SDK |
| 07 | MCP | resources/read politica://uso | texto contém 2026-11-01 | servidor-mcp/resources.py |
| 08 | MCP | resources/read politica://inexistente | -32602 | SDK / resources.py |
| 09 | MCP | reservar sala-delorean | isError + "Sala inexistente: sala-delorean" | servidor-mcp/domain.py |
| 10 | MCP | consultar 07-08 | isError + janela | servidor-mcp/domain.py |
| 11 | MCP | consultar 09-12 | isError + duração | servidor-mcp/domain.py |
| 12 | MCP | consultar 10-09 | isError + intervalo | servidor-mcp/domain.py |
| 13 | MRTR | reservar garagem 14-15 | input_required, 1 inputRequest, requestState | servidor-mcp/tools.py |
| 14 | MRTR | (resp. 13) | mode=form, enum [fusca, mirante] | servidor-mcp/domain.py |
| 15 | MRTR | reservar garagem 14-15, caps {} | -32021 + requiredCapabilities + HTTP 400 | SDK / tools.py |
| 16 | MRTR | fusca 16-17 + retry accept garagem | complete, sala=garagem | tools.py / reservations.py |
| 17 | MRTR | retry com state adulterado | -32602 | request_state.py (SDK) |
| 18 | MRTR | retry com args adulterados | error ou valores selados | SDK request binding |
| 19 | MRTR | retry decline (state da 13) | complete, reservado=false | tools.py |
| 20 | MRTR | mirante 11-12 duas vezes | isError + sem alternativas | domain.py |
| 21 | A2A | GET agent-card.json | 200 + JSON | agente/agent_card.py |
| 22 | A2A | (card) | supportedInterfaces JSONRPC 1.0 + url | agente/agent_card.py |
| 23 | A2A | (card) | skill reservar-sala | agente/agent_card.py |
| 24 | A2A | SendMessage porao 09-10 | COMPLETED | agente/bridge.py |
| 25 | A2A | (resp. 24) | artifact reserva, politica, sala-porao | agente/bridge.py |
| 26 | A2A | GetTask | id, contextId, COMPLETED | agente/a2a_protocol.py |
| 27 | Bridge | SendMessage garagem 14-15 | INPUT_REQUIRED | agente/bridge.py |
| 28 | Bridge | (resp. 27) | "alternativas: sala-fusca, sala-mirante" | agente/bridge.py |
| 29 | Bridge | escolha=sala-aquario | continua INPUT_REQUIRED | agente/parser.py, bridge.py |
| 30 | Bridge | escolha=sala-fusca | COMPLETED, sala-fusca | agente/bridge.py, mcp_client.py |
| 31 | A2A | SendMessage em Task terminal | error | agente/a2a_protocol.py |
| 32 | Bridge | garagem 14:30-15:30 + recusar | CANCELED | agente/bridge.py |
| 33 | Bridge | 2 Tasks pausadas + escolhas | 2 COMPLETED distintas | agente/task_store.py |
| 34 | Bridge | (todas as respostas A2A) | sem requestState | agente/task_model.py |
| 35 | A2A | SendMessage sala-delorean | FAILED + mensagem | agente/bridge.py |
| 36 | A2A | porao 09-10 duas vezes | pausas idênticas, "alternativas:" | agente/bridge.py |

**Total: 36 verificações** — 20 MCP (12 servidor + 8 MRTR), 16 A2A (9 A2A + 7 Bridge).

---

## 10. Divergências encontradas

Prioridade adotada: **validador > wire > README**.

| # | Fontes | Divergência | Decisão |
|---|---|---|---|
| D01 | validar.py:276 × validar.py:267 | No ramo de falha, a verif. 18 se chama "requestState apresentado em outra tool e rejeitado"; no ramo normal, "argumentos adulterados no retry nao tomam efeito". | Só muda o rótulo. Vale o que é checado: argumentos adulterados não tomam efeito. |
| D02 | README:438 × `exemplos/wire/` | O README diz "dez pares de request e response"; existem **11** arquivos (01-11). | Os 11 são contrato. |
| D03 | wire 01-06, 11 × validar.py:82-85 | Os wire têm `io.modelcontextprotocol/clientInfo` no `_meta`; o validador não envia. | `clientInfo` é opcional no servidor. O agente o envia (como no wire). |
| D04 | wire (ids inteiros) × validar.py:100,132 | Wire usa ids numéricos; o validador usa strings hex. | O servidor e o agente aceitam ids string e inteiros. |
| D05 | wire 08/09 × README:396 × validar.py:341 | O wire 08 mostra garagem 14-15 ⇒ `alternativas: sala-mirante`; o README (passo 7) e o validador esperam `sala-fusca, sala-mirante`. | Não é regra diferente: o wire foi capturado com a fusca já ocupada 14-15. Vale a regra de alternativas e o validador. |
| D06 | README:217 × validar.py:341,394 | O README exige "exatamente a linha"; o validador aceita contido (28) e prefixo + igualdade (36). | Seguir o mais estrito: a mensagem é exatamente a linha. |
| D07 | README:323 × wire 10 | Artifact no README tem JSON compacto (`","`); no wire 10, `json.dumps` padrão (`", "`). | O validador faz `json.loads`; ambos passam. Adotar o formato do wire 10 (`json.dumps` padrão). |
| D08 | README:61-71 × wire 01 | `salas.json` é uma lista; o outputSchema/structuredContent de `listar_salas` é `{"salas": [...]}`. | Seguir o wire 01: objeto com chave `salas`. |
| D09 | README:211 × validar.py:358 | "recusado com erro" sem código; o validador só verifica a presença de `error`; não há wire. | Usar o erro JSON-RPC A2A `UnsupportedOperationError` (-32004) com mensagem clara. Decisão em architecture.md. |
| D10 | README:197 × validar.py | O README exige `-32020` para header que não bate com o corpo; o validador não testa. | Implementar (vem do SDK); não é bloqueante para os 36. |
| D11 | README:171,198 × validar.py | Log no stderr, tools/list antes de tools/call, id novo no retry e restart com requestState válido não são verificados pelo script. | Obrigatórios mesmo assim (avaliação manual). |
| D12 | wire 03 × README:181 | O wire mostra o requestState no formato do SDK (`v1.` + base64url, AES-GCM); o README aceita HMAC **ou** AEAD. | Preferir o helper oficial `RequestStateSecurity` (AEAD), com chave de `REQUEST_STATE_SECRET`. |
| D13 | wire 01/05 × validador | `cacheScope`, `ttlMs` e `resultType: complete` aparecem em tools/list e resources/read no wire; não são verificados. | Deixar o SDK emitir; não forçar. |
| D14 | README:54 × Windows | O README usa `python3`; nesta máquina só existe `python` (3.11.15). | Documentar os dois comandos; no Windows, `python validador/validar.py ...`. |
