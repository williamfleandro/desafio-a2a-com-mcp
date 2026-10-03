# Registro de riscos

Escala: Impacto e Probabilidade de 1 (baixo) a 5 (alto).

| ID | Risco | Impacto | Probabilidade | Mitigação |
|---|---|---:|---:|---|
| R01 | SDK MCP divergir dos wire examples (nomes de campo, `resultType`, forma do erro `-32021`) | 4 | 3 | Os wire examples foram capturados de uma execução real com o SDK Python (chave `__main__:escolha_de_sala`, token `v1.`). Travar `mcp==2.3.0` e conferir cada resposta com o wire correspondente nas Fases 2-5. Só os campos que o validador lê são bloqueantes. |
| R02 | Interpretação errada de MRTR (achar que o servidor pergunta e espera) | 5 | 2 | Usar resolver `Resolve(fn)` + `Elicit[T]` do SDK: em `2026-07-28`, ele vira `InputRequiredResult`. Testar 13-19 direto no MCP antes de existir agente. |
| R03 | Callback de elicitation fechar o ciclo dentro do agente (a Task nunca pausa) | 5 | 3 | Não registrar `elicitation_callback`; chamar `call_tool(..., allow_input_required=True)`. Verificações 27/28 detectam. |
| R04 | requestState depender de memória (`RequestStateSecurity.ephemeral()` é o padrão do `MCPServer`) | 5 | 4 | Passar sempre `RequestStateSecurity(keys=[REQUEST_STATE_SECRET])`. Teste manual: gerar `input_required`, reiniciar o MCP, fazer o retry ⇒ complete. |
| R05 | requestState adulterável (JSON base64 sem MAC) | 5 | 1 | Helper AES-GCM do SDK. Verificação 17. |
| R06 | requestState expirar incorretamente (TTL curto demais ou relógio) | 3 | 1 | `ttl=600` (10 min, faixa 5-30). Não usar valor por env sem limites. |
| R07 | Retry reutilizar o JSON-RPC id | 4 | 2 | O cliente SDK gera id novo por request. Logar o id no stderr do MCP e conferir o par de `tools/call` (avaliador, passo 6). |
| R08 | trace-id não preservado (span novo gerado com trace novo, ou continuação sem header) | 3 | 3 | `agente/trace.py`: trace-id guardado na Task, span novo por request. Conferir no stderr o trace-id impresso pelo validador. |
| R09 | Agent implementar regra de domínio (calcular alternativas/conflito) | 4 | 2 | O agente só lê o `enum`/`const` da elicitation. Revisão de `bridge.py` contra a CLAUDE.md. |
| R10 | Estado terminal voltar a WORKING | 4 | 2 | Tabela de transições em `task_model.py` com exceção em transição inválida. Verificação 31. |
| R11 | Escolha inválida alterar a Task (consumir requestState, chamar MCP, mudar estado) | 4 | 2 | Validar a escolha contra `allowed_choices` antes de qualquer efeito. Verificação 29 seguida da 30 (a mesma Task precisa concluir depois). |
| R12 | Mistura de requestState entre Tasks concorrentes | 5 | 2 | `pending_mcp` dentro da Task, busca por `taskId`, lock por Task, sem variáveis globais de "última pausa". Verificação 33. |
| R13 | Texto literal divergente (acento, ponto final, espaços) | 5 | 3 | Constantes únicas em `servidor-mcp/domain.py`, copiadas de `validar.py:26-30`. Linha `alternativas: ` com `", ".join(enum)`. Verificações 9-12, 20, 28, 35, 36. |
| R14 | Headers MCP divergirem do corpo (`Mcp-Name` em resources/read deve ser a URI) | 3 | 2 | Usar o cliente do SDK, que espelha os headers. O servidor recusa com `-32020` (SDK). |
| R15 | stdout/stderr interferir no avaliador (logs no stdout, prints) | 2 | 3 | Logger único para stderr nos dois processos; proibido `print` de depuração. |
| R16 | Dependências sem versão travada | 3 | 3 | `==` no `pyproject.toml`, incluindo `mcp-types`, `uvicorn`, `starlette`, `httpx`. Teste de clone limpo na Fase 10. |
| R17 | Resposta MCP em SSE em vez de JSON (o validador faz `json.loads`) | 5 | 3 | `json_response=True` + `stateless_http=True` no `streamable_http_app`. Verificação 01 detecta logo. |
| R18 | Sala escolhida ficar ocupada entre a pausa e o retry | 2 | 1 | Fora do escopo do validador. O servidor revalida no retry (resolver re-executa). |
| R19 | a2a-sdk tratar a ausência do header `A2A-Version` como v0.3 (o validador não envia) | 4 | 3 | Recomendação: A2A à mão em Starlette (2 métodos). Se usar o SDK, testar sem o header na Fase 7. |
| R20 | Uma única alternativa vir como `const` e o agente só ler `enum` | 4 | 4 | O parser da elicitation aceita `enum` ou `const`. Verificações 32 e 33 têm alternativa única. |
| R21 | `_meta` inválido não devolver HTTP 400 (só o código -32602) | 4 | 3 | Confirmar o comportamento do SDK na Fase 2; se faltar, um middleware ajusta o status. Verificações 4, 5 e 15. |
| R22 | Ordem das validações de regra (intervalo invertido dar "duração" ou "janela") | 3 | 2 | Ordem fixa: sala → intervalo → janela → duração. Verificação 12. |
| R23 | Conflito sem alternativas cair no resolver Elicit (vira `input_required` ou `-32021`) | 4 | 2 | Calcular as alternativas antes; se a lista estiver vazia ⇒ `isError` sem elicitation. Verificação 20. |
| R24 | Validador rodado sem reiniciar os processos (estado sujo) | 3 | 4 | Script/README com a ordem: subir os dois do zero e então validar. |
| R25 | Windows: `python3` inexistente; encoding da saída do stderr | 2 | 4 | Documentar `python`; arquivos UTF-8; mensagens literais são ASCII. |
| R26 | Request binding do SDK rejeitar retry legítimo do agente se os `arguments` forem reconstruídos (ordem/tipo diferente) | 4 | 2 | Guardar o dict original e reenviá-lo tal como foi; o digest usa `sort_keys`, então a ordem não importa, mas valores precisam ser idênticos. |
