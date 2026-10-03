# A Ponte: um agente A2A com MCP por dentro

Entrega do desafio inicial do MBA Engenharia de Software com IA (curso de MCP e A2A).

Dois processos independentes, em Python, que só conversam por HTTP:

| Processo | Porta | Endpoints | Papel |
|---|---|---|---|
| `servidor-mcp/` | 7301 | `POST /mcp` (Streamable HTTP, MCP `2026-07-28`, stateless, resposta JSON) | 3 tools, resource `politica://uso`, regras de domínio, MRTR |
| `agente/` | 7300 | `GET /.well-known/agent-card.json`, `POST /a2a` (A2A v1.0, JSON-RPC 2.0) | servidor A2A por fora, host MCP por dentro; traduz protocolo, não decide regra de sala |

`dados/`, `validador/` e `exemplos/` são os do starter, sem alteração.

## Como rodar

Pré-requisito: Python 3.10, 3.11 ou 3.12. No Windows o executável costuma ser `python`; no Linux/macOS, `python3`.

### 1. Ambiente e dependências (uma vez, a partir de um clone limpo)

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m pip check
```

Sem ativar a venv, o equivalente é chamar `.venv\Scripts\python.exe` em todos os comandos abaixo, no lugar de `python`.

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

As dependências estão travadas com `==` no `pyproject.toml`. O `pip install -e .` instala só as dependências; os dois processos rodam pelo caminho do script.

### 2. Segredo do requestState

O servidor MCP não sobe sem `REQUEST_STATE_SECRET` (mínimo de 32 bytes). Gere o seu valor e **não o publique**:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Exporte-o no terminal em que o servidor MCP vai rodar:

```powershell
$env:REQUEST_STATE_SECRET="<valor gerado>"      # Windows (PowerShell)
```

```bash
export REQUEST_STATE_SECRET="<valor gerado>"    # Linux/macOS
```

Alternativa: copie `.env.example` para `.env` na raiz e preencha `REQUEST_STATE_SECRET`. O `.env` é lido na subida e está no `.gitignore`.

### 3. Subir os dois processos (um terminal para cada, com a venv ativada)

Terminal 1, servidor MCP (o log de cada request vai para o stderr deste terminal):

```bash
python servidor-mcp/main.py
```

Terminal 2, agente A2A:

```bash
python agente/main.py
```

Portas e URLs podem ser trocadas por ambiente (`MCP_HOST`, `MCP_PORT`, `AGENT_HOST`, `AGENT_PORT`, `MCP_URL`, `AGENT_PUBLIC_URL`; ver `.env.example`). Os padrões são os do validador.

### 4. Validador (terminal 3)

Com os **dois processos recém-iniciados** (as reservas criadas numa execução mudam o resultado da seguinte):

```bash
python validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301
```

## Onde a ponte acontece

**MCP `input_required` → `TASK_STATE_INPUT_REQUIRED`.** Em `agente/bridge.py`, `Ponte.aplicar()` (linha 69) recebe o resultado cru do `tools/call`. O cliente MCP do agente (`agente/mcp_client.py`) não tem callback de elicitation, então o `input_required` chega intacto. Quando `resultType` é `input_required`, `pendencia_de()` (linha 95) extrai a chave do `inputRequests`, o campo e o `enum`/`const` da elicitation. Nas linhas 78-79 o `requestState` é guardado, opaco, em `task.pendente`, junto com a chave, a tool e os `arguments` originais, e a Task vai para `TASK_STATE_INPUT_REQUIRED` com a mensagem exata `alternativas: <ids>`. `task.pendente` é um campo privado da Task (`agente/task_model.py`): `Task.para_json()` não o serializa, e ele é descartado quando a Task chega a um estado terminal.

**`requestState` de volta ao servidor.** O `SendMessage` com `taskId` chega em `Ponte.continuar()` (`agente/bridge.py`, linha 46):
- `escolha=<id>` dentro do enum vira `{"action": "accept", "content": {"sala": <id>}}`;
- `escolha=recusar` vira `{"action": "decline"}`;
- qualquer outra coisa mantém a Task em `INPUT_REQUIRED` e repete a linha de alternativas, sem tocar no MCP.

Na linha 62, o agente refaz o `tools/call` com os mesmos `arguments`, `inputResponses` sob a mesma chave e o `requestState` ecoado sem modificação. O id JSON-RPC é novo porque `ClienteMCP._rpc()` (`agente/mcp_client.py`, linha 59) gera um id para cada request.

**Do lado do servidor**, `reservar_sala` (`servidor-mcp/tools.py`, linha 110) declara o parâmetro `escolha` resolvido por `escolha_de_sala()` (linha 74). Sala livre: o resolver não pergunta nada. Conflito: ele devolve um `Elicit` com as alternativas (linha 93). O SDK `mcp` transforma isso em `input_required`, sela o `requestState` e, no retry, devolve a resposta à tool. Sem alternativas: `isError` com `Sem alternativas disponiveis no intervalo`.

## Decisões técnicas

- **Servidor MCP com o SDK oficial.** `MCPServer` do `mcp` 2.3.0, exposto com `streamable_http_app(json_response=True, stateless_http=True)` (`servidor-mcp/server.py`, `criar_app()`): Streamable HTTP sem sessão, resposta JSON, nenhum estado entre requests além das reservas. As tools vêm de `servidor-mcp/tools.py` e o resource `politica://uso` (conteúdo de `dados/politica-de-uso.md`) de `servidor-mcp/resources.py`.
- **Proteção do `requestState`.** Uso o utilitário oficial do SDK `mcp` 2.3.0, `RequestStateSecurity(keys=[REQUEST_STATE_SECRET], ttl=600)`, em `servidor-mcp/server.py`:
  - **Criptografia e integridade:** o token é AES-256-GCM, com chave derivada por HKDF-SHA256. Ele é cifrado e autenticado, então qualquer adulteração é detectada.
  - **O que fica selado:** o token também amarra o método, a tool e um hash dos `arguments`. Um retry com argumentos diferentes dos selados é rejeitado.
  - **Falha:** adulterado, expirado ou com argumentos divergentes ⇒ `-32602`.
  - **Chave:** vem só do ambiente. Sem ela, ou com menos de 32 bytes, o processo não sobe.
  - **Restart:** com a chave fixa (e não a chave efêmera, que é o padrão do `MCPServer`), um retry continua válido depois de reiniciar o servidor.
  - **Nada em memória:** o servidor não guarda estado entre o `input_required` e o retry.
- **Validade:** 10 minutos (`TTL_REQUEST_STATE = 600` segundos), dentro da faixa de 5 a 30 minutos exigida.
- **Retry depois de restart, com a sala pedida já livre.** Isso acontece quando o conflito era uma reserva em memória que o restart apagou. Num retry, o resolver refaz a mesma pergunta mesmo assim, para que a escolha selada seja respeitada. Se as alternativas mudaram, o SDK pergunta de novo.
- **Estado das Tasks.** Fica em memória no agente: `TaskStore` (`agente/task_store.py`) é um `dict[task_id, Task]`, com um `asyncio.Lock` por Task. A pendência MCP de cada Task (o `requestState`, a chave, as alternativas e os `arguments`) fica dentro da própria Task. Duas Tasks pausadas ao mesmo tempo não compartilham nada.
- **Máquina de estados.** Está em `agente/task_model.py`, com uma tabela de transições permitidas. COMPLETED, FAILED e CANCELED não aceitam nenhuma transição, e um `SendMessage` numa Task terminal é recusado com `-32004` (UnsupportedOperation).
- **Reservas em memória.** `dados/reservas.json` é só o estado inicial, carregado uma vez e nunca regravado. As regras ficam em `servidor-mcp/domain.py`, em funções puras:
  - **Ordem:** sala, intervalo, janela, duração.
  - **Fronteiras:** 08:00 e 20:00 no fuso -03:00 são permitidos, e uma duração de exatamente 2h também.
  - **Conflito:** intervalos que só se encostam na borda não conflitam.
- **Host MCP.**
  - **Descoberta:** o agente faz `tools/list` e lê `politica://uso` no início de cada Task. Escolhe a tool pelo verbo do pedido e pelo `inputSchema` descoberto, sem lista fixa no código. A versão da política vai para o artifact.
  - **Por que um cliente próprio:** o `mcp_client.py` é escrito sobre `httpx2`, a mesma biblioteca HTTP do SDK, e não usa o `mcp.Client`. O `ClientSession` do SDK só declara elicitation quando há um callback, e aí anuncia `{"form":{}, "url":{}}`. O contrato pede exatamente `{"elicitation": {"form": {}}}`, e o agente não pode responder a elicitation sozinho.
  - **Em todo request:** `_meta` completo e os headers espelhados (`MCP-Protocol-Version`, `Mcp-Method` e `Mcp-Name`).
- **traceparent.**
  - **No agente:** extrai o trace-id do header `traceparent` da chamada A2A e o guarda na Task. Todo request MCP daquela Task leva `_meta.traceparent` com o mesmo trace-id e um span-id novo.
  - **No servidor:** registra no stderr `method`, `id` e `traceparent` de cada request, inclusive os que o SDK rejeita, porque o log é feito na borda HTTP.
- **Headers MCP.** O SDK recusa `Mcp-Method` e `Mcp-Name` divergentes do corpo com `-32020`. A borda HTTP do servidor faz o mesmo para `MCP-Protocol-Version`.
- **Sem LLM.** O agente lê um formato fixo (`agente/parser.py`) e decide por regra: o mesmo pedido gera sempre a mesma resposta.
- **A2A à mão.** Implementei sobre Starlette, sem `a2a-sdk`. São só dois métodos, o formato segue `exemplos/wire/07` a `10`, e o validador não envia o header `A2A-Version`.
- **Verificado além das 36 verificações** (auditoria manual, processos recém-iniciados):
  - um único caractere trocado no `requestState` ⇒ HTTP 400, `-32602` (log: `requestState rejected ... seal`);
  - retry com `arguments` diferentes dos selados ⇒ HTTP 400, `-32602` (`request binding`), sem reserva criada;
  - retry depois de 605 s ⇒ HTTP 400, `-32602` (`expired`);
  - restart do MCP com o mesmo segredo e retry ⇒ `complete`; Task A2A pausada, restart do MCP, continuação ⇒ COMPLETED;
  - duas Tasks pausadas, continuadas em ordem inversa e com salas diferentes ⇒ cada retry sai com o trace-id e os `arguments` da sua Task;
  - COMPLETED, FAILED e CANCELED recusam novo `SendMessage` com `-32004` e continuam no mesmo estado no `GetTask`;
  - varredura estrutural de 29 respostas A2A (card, `SendMessage`, `GetTask`, `history`, `status.message`, artifact, erros) sem `requestState`.
- **Mais detalhes.** Arquitetura, contrato das 36 verificações, máquinas de estado e riscos estão em `docs/`.

## Saída do validador

Execução de 2026-10-02 numa cópia limpa do repositório (`C:\AI\mba-a2a-final-test`, venv nova, `pip install -e .`, `pip check` limpo), Windows, Python 3.11.15. Os dois processos foram recém-iniciados, com um `REQUEST_STATE_SECRET` novo só na variável de ambiente. Comando: `.venv\Scripts\python.exe validador\validar.py --agente http://localhost:7300 --mcp http://localhost:7301`. Exit code: 0.

```text
trace-id desta execucao: 393883d49d9a7e5ca756e8180c01e122
procure esse valor no stderr do servidor MCP para conferir a propagacao do traceparent.

PASS 01 tools/list traz as tres tools
PASS 02 toda tool tem inputSchema de objeto
PASS 03 listar_salas devolve structuredContent e o mesmo JSON em texto
PASS 04 _meta sem protocolVersion devolve -32602 e HTTP 400
PASS 05 _meta sem clientCapabilities devolve -32602 e HTTP 400
PASS 06 tool inexistente e recusada, por -32602 ou por isError
PASS 07 resources/read de politica://uso devolve a politica
PASS 08 resources/read de URI inexistente devolve -32602
PASS 09 sala inexistente devolve isError com a mensagem exata
PASS 10 fora da janela devolve isError com a mensagem exata
PASS 11 duracao acima de 2h devolve isError com a mensagem exata
PASS 12 intervalo invertido devolve isError com a mensagem exata
PASS 13 conflito devolve input_required com inputRequests e requestState
PASS 14 a elicitation e form mode e oferece as alternativas na ordem certa
PASS 15 conflito sem a capability elicitation devolve -32021 e HTTP 400
PASS 16 retry com inputResponses e requestState conclui a reserva
PASS 17 requestState adulterado e rejeitado com -32602
PASS 18 argumentos adulterados no retry nao tomam efeito
PASS 19 recusa conclui sem reservar e sem isError
PASS 20 conflito sem alternativa possivel devolve isError com a mensagem exata

PASS 21 agent card responde 200 no well-known com JSON
PASS 22 o card declara a interface JSON-RPC com url e versao 1.0
PASS 23 o card declara a skill reservar-sala
PASS 24 SendMessage com sala livre conclui a Task
PASS 25 o artifact chama reserva e traz a versao da politica
PASS 26 GetTask devolve id, contextId e estado corrente
PASS 27 SendMessage com sala ocupada pausa a Task
PASS 28 a Task pausada lista as alternativas na ordem certa
PASS 29 escolha fora do enum mantem a Task pausada
PASS 30 a continuacao conclui a Task na sala escolhida
PASS 31 SendMessage em Task terminal e recusado
PASS 32 a recusa termina a Task em CANCELED
PASS 33 duas Tasks pausadas ao mesmo tempo concluem cada uma com a sua reserva
PASS 34 nenhuma resposta A2A carrega o requestState
PASS 35 sala inexistente termina a Task em FAILED com a mensagem da tool
PASS 36 o agente e deterministico: o mesmo pedido produz a mesma pausa

resumo: 36 passaram, 0 falharam, de 36 verificacoes
```
