# Projeto

MBA A2A/MCP — A Ponte

# Objetivo

36/36 PASS no validador oficial, com exit code 0:

```powershell
python validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301
```

(Nesta máquina Windows o comando é `python`; `python3` não existe.)
Sempre rode com os **dois processos recém-iniciados**: as reservas de uma
execução mudam o resultado da seguinte.

# Arquivos imutáveis

```text
dados/
validador/
exemplos/
```

Nunca modificar, mover, renomear ou reformatar nada neles. O código se adapta ao
validador; nunca o contrário. Conferir com `git diff -- dados validador exemplos`
(saída vazia).

# Documentação de referência

- `docs/validator-contract.md`: as 36 verificações, textos literais e divergências.
- `docs/architecture.md`: componentes, Task Store, requestState, traceparent, decisões.
- `docs/state-machines.md`: estados da Task e transições permitidas.
- `docs/protocol-flow.md`: fluxos A-F.
- `docs/implementation-plan.md`: fases e critérios de pronto.
- `docs/risk-register.md`: riscos R01-R26.

# Fluxo obrigatório antes de programar

Antes de implementar qualquer requisito:

1. ler o requisito correspondente (README e `docs/`);
2. localizar o teste relacionado em `validador/validar.py`;
3. localizar o wire example relacionado em `exemplos/wire/`;
4. definir o contrato (request, response, status, texto literal);
5. implementar a menor mudança possível;
6. executar os testes relevantes;
7. só então avançar.

Prioridade em caso de conflito: **validador > exemplos/wire > README**.

# Restrições permanentes

- Dois processos independentes: MCP Server (`servidor-mcp/`) e A2A Agent (`agente/`).
- O agente fala com o MCP **só por HTTP**. Nunca importar código de
  `servidor-mcp/` dentro de `agente/`.
- Sem LLM no runtime. Sem SDK de provedor de LLM nas dependências.
- Sem banco de dados, ORM, Redis ou arquivo de persistência. Reservas e Tasks em memória.
- Sem sessão de protocolo: nada inferido de request anterior.
- Sem callback MCP esperando usuário (sem `elicitation_callback` no agente).
- Sem lista de tools hardcoded no agente: descobrir via `tools/list`.
- Sem segredo no código.
- Dependências com versão travada (`==`) no `pyproject.toml`.

# Regras de código

- Mudanças pequenas e objetivas.
- Não refatorar código funcional sem necessidade.
- Preservar mensagens literais **byte a byte** (copiar de `validar.py:26-30`).
- Não alterar contrato para adequar a implementação.
- Preferir código simples; evitar abstrações prematuras.
- Funções pequenas; tipagem explícita quando útil.
- Logging técnico sem alterar o stdout esperado.
- Logs do MCP **obrigatoriamente em stderr**: método, id e `traceparent` de cada request.
- Sem `print` de depuração.

# Runtime

```text
MCP Server: localhost:7301  endpoint /mcp  (Streamable HTTP, stateless, resposta JSON)
A2A Agent:  localhost:7300  endpoint /a2a  card /.well-known/agent-card.json
```

Portas e URLs podem vir de variável de ambiente (ver `.env.example`), mas os
padrões são esses.

# Segurança

- Nunca armazenar `REQUEST_STATE_SECRET` no Git (`.env` é ignorado).
- Segredo com no mínimo 32 bytes de aleatoriedade:
  `python -c "import secrets; print(secrets.token_hex(32))"`.
- O MCP não sobe sem o segredo válido.
- Validar a integridade do requestState (`RequestStateSecurity(keys=[segredo])`
  do SDK; nunca o padrão `ephemeral()`, que quebra após restart).
- Validar a expiração (TTL 600 s).
- requestState é entrada não confiável: falha ⇒ `-32602`.
- O agente trata o requestState como **opaco**: guardar, ecoar, nunca abrir,
  interpretar, validar ou reconstruir. Nunca expô-lo em resposta A2A.

# MRTR

`input_required` **NÃO** é callback.

```text
MCP Server
    ↓
retorna input_required (termina a resposta)
    ↓
Agent recebe (call_tool com allow_input_required=True)
    ↓
Task = INPUT_REQUIRED ("alternativas: a, b")
    ↓
cliente A2A responde (SendMessage com taskId, "escolha=...")
    ↓
novo tools/call
    ↓
novo JSON-RPC id
    ↓
mesmos arguments + inputResponses (mesma chave) + requestState (intacto)
```

# Agent

O Agent:

- não contém regras de negócio de sala;
- não calcula conflito;
- não calcula alternativa (usa o `enum`/`const` da elicitation);
- não interpreta o requestState;
- apenas traduz protocolos (A2A ⇄ MCP) e mantém o estado da Task.

# Verificação após cada mudança

- Subir os dois processos do zero e rodar o validador (ou a faixa da fase atual).
- Conferir o stderr do MCP quando a mudança tocar no protocolo.
- `git diff -- dados validador exemplos` precisa continuar vazio.
