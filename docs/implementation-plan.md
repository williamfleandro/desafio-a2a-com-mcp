# Plano de implementação

Cada fase é pequena, verificável e termina com os testes relacionados passando.
Referências: `docs/validator-contract.md` (números das verificações) e
`docs/risk-register.md` (Rxx).

Execução do validador no Windows:

```powershell
python validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301
```

Nas fases intermediárias, as verificações A2A falham em cascata enquanto o
agente não existir. O critério de cada fase considera só a sua faixa.

---

## FASE 0 — Análise

**Status: COMPLETA.**

- Objetivo: clonar o starter, fazer a engenharia reversa do validador, dos
  exemplos de wire e do README, e produzir arquitetura, contrato, riscos e regras.
- Arquivos: `docs/*.md`, `CLAUDE.md`, `.env.example`, `.gitignore`.
- Dependências: —
- Critério de pronto: documentos criados; `git diff -- dados validador exemplos` vazio.
- Testes relacionados: todos (mapeados).
- Riscos relacionados: todos (registrados).

---

## FASE 1 — Scaffold Python

**Status: COMPLETA.** Dependências: `mcp==2.3.0`, `mcp-types==2.3.0`,
`starlette==1.7.0`, `uvicorn==0.54.0`, `python-dotenv==1.2.4` (build:
`setuptools==80.9.0`). `httpx` ficou de fora porque o `mcp` 2.3.0 usa `httpx2`
(transitivo). Execução por caminho: `python servidor-mcp/main.py` e
`python agente/main.py`. A exigência de `REQUEST_STATE_SECRET`
(`config.exigir_segredo`) fica preparada para a Fase 5; o scaffold sobe sem o
segredo.

- **Objetivo:** projeto instalável com dependências travadas, entrypoints e
  config. Os dois processos sobem e respondem, sem domínio.
- **Arquivos:**
  - `pyproject.toml` (Python ≥ 3.10, `mcp==2.3.0`, `mcp-types==2.3.0`,
    `uvicorn==…`, `starlette==…`, `httpx==…`, todos com `==`)
  - `servidor-mcp/__init__.py`, `servidor-mcp/main.py`, `servidor-mcp/config.py`
  - `agente/__init__.py`, `agente/main.py`, `agente/config.py`
  - opcional: `scripts/` de subida
- **Dependências:** Fase 0.
- **Critério de pronto:**
  - `python -m venv .venv` + `pip install -e .` funcionam em clone limpo;
  - o MCP sobe em 7301 e falha rápido (stderr) sem `REQUEST_STATE_SECRET` ou
    com segredo < 32 bytes;
  - o agente sobe em 7300;
  - nenhum import de `servidor-mcp` dentro de `agente`.
  - Decidir aqui como os diretórios com hífen são executados.
- **Testes relacionados:** nenhum ainda (o validador roda e falha em 01 sem travar).
- **Riscos relacionados:** R16, R25.

## FASE 2 — MCP mínimo

**Status: COMPLETA.** Validador: PASS 01-08. O SDK já cobre `_meta`
incompleto (HTTP 400/-32602), URI desconhecida (-32602) e tool desconhecida
(`isError: true`). O log fica num wrapper ASGI (`LogDeRequest` em
`servidor-mcp/server.py`), na borda HTTP, para registrar também os requests que o
SDK rejeita antes do dispatch. `consultar_disponibilidade` e `reservar_sala`
só têm o `inputSchema`; o corpo levanta `ToolError` e o `outputSchema` chega nas
Fases 3/4.

- **Objetivo:** `/mcp` stateless em JSON, `tools/list` com as 3 tools
  (`listar_salas` funcional; as outras duas com schema e corpo provisório),
  `resources/read politica://uso`, validação de `_meta`, log em stderr.
- **Arquivos:** `servidor-mcp/server.py`, `tools.py`, `resources.py`,
  `domain.py` (carga de salas), `logging_utils.py`, `protocol.py` (se o SDK não
  cobrir log ou status 400).
- **Dependências:** Fase 1.
- **Critério de pronto:** respostas comparadas com os wire 01 e 05; stderr
  mostra método, id e traceparent de cada request.
- **Testes relacionados:** 01, 02, 03, 04, 05, 06, 07, 08.
- **Riscos relacionados:** R01, R14, R15, R17, R21.

## FASE 3 — Regras

**Status: COMPLETA.** Validador: 12/36 PASS (01-12). As regras ficam em
`servidor-mcp/domain.py`, como funções puras; as reservas em memória ficam em
`servidor-mcp/reservations.py`. `reservar_sala` já aplica as validações
comuns; o caminho feliz chega na Fase 4. Fronteiras adotadas: 08:00 e 20:00
inclusivos, duração de 2h exatas aceita, intervalos que só encostam na borda
não conflitam, e a janela é medida no dia do início, no fuso -03:00.

- **Objetivo:** `consultar_disponibilidade` completa. Validações de sala,
  intervalo, janela e duração, com as mensagens exatas, compartilhadas com a
  reserva.
- **Arquivos:** `servidor-mcp/domain.py`, `servidor-mcp/reservations.py`
  (leitura de `dados/reservas.json` para memória), `servidor-mcp/tools.py`.
- **Dependências:** Fase 2.
- **Critério de pronto:** mensagens copiadas literalmente de `validar.py:26-30`;
  ordem sala → intervalo → janela → duração; conversão de fuso para -03:00;
  saída conforme o outputSchema do wire 01 (`sala`, `livre`, `conflitos[]`).
- **Testes relacionados:** 09 (via reserva), 10, 11, 12.
- **Riscos relacionados:** R13, R22.

## FASE 4 — Reserva

**Status: COMPLETA.** O caminho feliz cria `res-NNNN` a partir do maior id conhecido; o `structuredContent` e o texto são idênticos ao wire 02. O validador não tem verificação de reserva livre isolada (todas as de `reservar_sala` entre 13 e 20 envolvem conflito), então o caminho feliz foi coberto por testes manuais.

- **Objetivo:** `reservar_sala` no caminho feliz, reservas em memória, ids
  `res-NNNN` sequenciais a partir de `res-0003`, `structuredContent` do wire 02
  (inclui `politica` e `motivo: null`).
- **Arquivos:** `servidor-mcp/tools.py`, `reservations.py`, `domain.py`.
- **Dependências:** Fase 3.
- **Critério de pronto:** resposta igual ao wire 02 (exceto ids); reserva
  criada aparece no `consultar_disponibilidade` seguinte; erros de regra iguais
  aos da consulta.
- **Testes relacionados:** 09; pré-requisito de 16, 18, 20.
- **Riscos relacionados:** R13.

## FASE 5 — MRTR

**Status: COMPLETA.** Validador 20/20 no bloco MCP. Resolver `escolha_de_sala` (`Resolve` + `Elicit` do SDK) e `RequestStateSecurity(keys=[REQUEST_STATE_SECRET], ttl=600)`. A verificação 18 passa pela rejeição do *request binding*. O retry continua válido depois de restart. Num retry, o resolver refaz a pergunta mesmo que a sala pedida tenha ficado livre, para honrar a escolha selada.

- **Objetivo:** conflito ⇒ `input_required` com elicitation form e alternativas
  (regra: capacidade ≥, livres, máx. 3, capacidade↑ e id↑);
  `RequestStateSecurity(keys=[REQUEST_STATE_SECRET], ttl=600)`; `-32021` sem
  capability; retry accept/decline; sem alternativas ⇒ `isError`.
- **Arquivos:** `servidor-mcp/tools.py` (resolver), `domain.py` (alternativas),
  `server.py` / `request_state.py`.
- **Dependências:** Fase 4.
- **Critério de pronto:**
  - respostas iguais aos wire 03, 04, 06 e 11 (exceto token/ids);
  - **decisão pendente resolvida:** helper oficial (preferido) ou codec HMAC de reserva;
  - teste manual de restart: `input_required` → reiniciar o MCP → retry ⇒ `complete`;
  - nada guardado em memória entre `input_required` e retry.
- **Testes relacionados:** 13, 14, 15, 16, 17, 18, 19, 20 (com 01-12: **20/20 no bloco MCP**).
- **Riscos relacionados:** R02, R04, R05, R06, R23.

## FASE 6 — MCP Host (cliente)

**Status: COMPLETA.** Cliente próprio sobre `httpx2` (`agente/mcp_client.py`): o `ClientSession` do SDK anuncia `{"form":{},"url":{}}` só com callback, e o contrato pede exatamente `{"elicitation":{"form":{}}}`. `trace.py` virou `traceparent.py` para não sombrear o módulo `trace` da biblioteca padrão. `httpx2==2.13.1` passou a ser dependência direta.

- **Objetivo:** cliente MCP do agente, ainda sem A2A: script/função que faz
  `tools/list`, `resources/read`, `tools/call` com `allow_input_required=True`,
  extrai a chave, o enum/const e o requestState, e faz o retry com id novo.
- **Arquivos:** `agente/mcp_client.py`, `agente/traceparent.py`.
- **Dependências:** Fase 5.
- **Critério de pronto:**
  - stderr do MCP mostra `tools/list` antes de `tools/call`, o traceparent com
    o trace-id informado, ids diferentes no par inicial/retry, e a capability
    `elicitation.form` em todos os requests;
  - sem `elicitation_callback`;
  - sem lista de tools no código.
- **Testes relacionados:** nenhum direto (pré-requisito de 24-36); verificação manual do avaliador, passos 5 e 6.
- **Riscos relacionados:** R03, R07, R08, R14, R20, R26.

## FASE 7 — A2A

**Status: COMPLETA.** A2A escrito à mão em Starlette, sem `a2a-sdk`. O card é idêntico ao wire 07. Terminal ⇒ `-32004`, Task inexistente ⇒ `-32001`. Ao fim da fase: 29/36 PASS.

- **Objetivo:** Agent Card v1.0, `/a2a` JSON-RPC com `SendMessage` (sala livre
  e erro) e `GetTask`, máquina de estados, Task Store, artifact.
- **Arquivos:** `agente/server.py`, `agent_card.py`, `a2a_protocol.py`,
  `task_model.py`, `task_store.py`, `parser.py`, parte de `bridge.py`.
- **Dependências:** Fase 6.
- **Critério de pronto:**
  - **decisão pendente resolvida:** A2A à mão (recomendado) × a2a-sdk (R19);
  - card igual ao wire 07 (url configurável, padrão `http://127.0.0.1:7300/a2a`);
  - respostas com a forma `result.task` do wire 08-10;
  - erro em Task terminal.
- **Testes relacionados:** 21, 22, 23, 24, 25, 26, 31 (precisa da 30 para o cenário exato), 35.
- **Riscos relacionados:** R10, R19.

## FASE 8 — Bridge

**Status: COMPLETA.** 36/36 PASS, exit 0. `Ponte.aplicar` / `Ponte.continuar` em `agente/bridge.py`.

- **Objetivo:** `input_required` ⇒ INPUT_REQUIRED com a linha
  `alternativas: ...`; continuação; retry; recusa ⇒ CANCELED; escolha inválida;
  isolamento entre Tasks.
- **Arquivos:** `agente/bridge.py`, `task_store.py` (lock por Task), `task_model.py`.
- **Dependências:** Fase 7.
- **Critério de pronto:** fluxos B, C e D de `docs/protocol-flow.md` reproduzidos
  com os corpos dos wire 08, 09 e 10 via curl; `requestState` ausente de toda
  resposta A2A.
- **Testes relacionados:** 27, 28, 29, 30, 31, 32, 33, 34, 36.
- **Riscos relacionados:** R09, R11, R12, R20.

## FASE 9 — Robustez

**Status: COMPLETA.** A borda HTTP do MCP passa a recusar `MCP-Protocol-Version` divergente com `-32020` (o SDK já cobria `Mcp-Method`/`Mcp-Name`). Expiração testada com TTL de 1 s ⇒ `-32602`. Restart do MCP com uma Task pausada no agente ⇒ COMPLETED na sala escolhida. Nenhuma resposta A2A contém o requestState.

- **Objetivo:** cobrir o que o validador não testa, mas o avaliador confere ou o
  README exige: adulteração, restart, escolha inválida, Tasks terminais,
  capability ausente, header divergente (`-32020`), traceparent ausente ou
  inválido, taskId inexistente, JSON inválido.
- **Arquivos:** ajustes pontuais nos módulos existentes; opcional `tests/` com
  testes automatizados próprios (pytest), sem tocar em `validador/`.
- **Dependências:** Fase 8.
- **Critério de pronto:** todos os 13 passos do *Fluxo do avaliador* (README)
  executados manualmente com sucesso.
- **Testes relacionados:** 15, 17, 18, 29, 31, 34 + passos manuais 5, 6, 11, 12 e 13.
- **Riscos relacionados:** R04, R08, R14, R15, R18, R21.

## FASE 10 — Validação e entrega

**Status: COMPLETA** (sem commit e sem push, por instrução). Auditoria final de 2026-10-02:

- Repositório de trabalho, processos recém-iniciados, `.venv\Scripts\python.exe` explícito, segredo só no ambiente: 36/36, exit 0.
- Cópia limpa em `C:\AI\mba-a2a-final-test`, com venv nova, `pip install -e .` e `pip check` limpo: 36/36, exit 0. Essa saída está no README. A cópia contém os 49 arquivos que um commit levaria (`git ls-files --cached --others --exclude-standard`), porque ainda não há commit; `.env` e `.venv` ficaram de fora.
- Verificações manuais, todas conferidas também no stderr do MCP:
  - um caractere trocado no `requestState` ⇒ 400/`-32602` (`seal`);
  - argumentos trocados no retry ⇒ 400/`-32602` (`request binding`), sem reserva;
  - retry após 605 s ⇒ 400/`-32602` (`expired`);
  - restart do MCP com o mesmo segredo ⇒ `complete`, e a Task A2A pausada ⇒ COMPLETED;
  - quando o restart muda as alternativas, a Task volta a INPUT_REQUIRED com a lista nova e conclui na escolha seguinte;
  - isolamento de duas Tasks continuadas em ordem inversa;
  - estados terminais recusam `SendMessage` com `-32004`;
  - 29 respostas A2A varridas sem `requestState`.
- `git diff -- dados validador exemplos` vazio.

- **Objetivo:** 36/36 PASS, exit code 0, README final, teste de clone limpo.
- **Arquivos:** `README.md` (Como rodar; Onde a ponte acontece; Decisões
  técnicas; Saída do validador).
- **Dependências:** Fase 9.
- **Critério de pronto:**
  - os dois processos recém-iniciados ⇒ `resumo: 36 passaram, 0 falharam, de 36 verificacoes`, exit 0;
  - clone limpo em outra pasta seguindo só o README ⇒ mesmo resultado;
  - `git diff <commit-base> -- dados validador exemplos` vazio;
  - nenhuma dependência de LLM no `pyproject.toml`;
  - README sem o valor do segredo.
- **Testes relacionados:** 01-36.
- **Riscos relacionados:** R16, R24, R25.

---

## Resumo de rastreabilidade

| Fase | Verificações |
|---|---|
| 2 | 01-08 |
| 3 | 10-12 |
| 4 | 09 |
| 5 | 13-20 |
| 6 | (pré-requisito de 24-36) |
| 7 | 21-26, 31, 35 |
| 8 | 27-30, 32-34, 36 |
| 9 | reforço de 15, 17, 18, 29, 31, 34 + passos manuais |
| 10 | 01-36 |
