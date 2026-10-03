"""Task A2A v1.0: estados, transicoes permitidas e serializacao publica."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import Any

SUBMITTED = "TASK_STATE_SUBMITTED"
WORKING = "TASK_STATE_WORKING"
INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
COMPLETED = "TASK_STATE_COMPLETED"
FAILED = "TASK_STATE_FAILED"
CANCELED = "TASK_STATE_CANCELED"

TERMINAIS = frozenset({COMPLETED, FAILED, CANCELED})

TRANSICOES: dict[str | None, frozenset[str]] = {
    None: frozenset({SUBMITTED}),
    SUBMITTED: frozenset({WORKING, FAILED}),
    WORKING: frozenset({INPUT_REQUIRED, COMPLETED, FAILED, CANCELED}),
    INPUT_REQUIRED: frozenset({WORKING, INPUT_REQUIRED}),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
    CANCELED: frozenset(),
}


class TransicaoInvalida(Exception):
    pass


def novo_id(prefixo: str) -> str:
    return f"{prefixo}-{secrets.token_hex(6)}"


@dataclass
class PendenciaMCP:
    """O que o agente guarda de um input_required. Privado: nunca serializado."""

    request_state: str  # opaco: guardado e ecoado, nunca aberto
    chave: str  # chave do inputRequests, devolvida igual no inputResponses
    campo: str  # propriedade do requestedSchema (ex.: "sala")
    alternativas: list[str]  # enum/const recebido, na ordem
    tool: str
    argumentos: dict[str, Any]  # reenviados identicos no retry


@dataclass
class Task:
    id: str
    context_id: str
    estado: str | None = None
    mensagem_status: dict[str, Any] | None = None
    historico: list[dict[str, Any]] = field(default_factory=list)
    artefatos: list[dict[str, Any]] = field(default_factory=list)
    # Privados (fora de para_json):
    trace_id: str | None = None
    politica: str | None = None
    pendente: PendenciaMCP | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def terminal(self) -> bool:
        return self.estado in TERMINAIS

    def mudar(self, novo: str, texto_agente: str | None = None) -> None:
        if novo not in TRANSICOES[self.estado]:
            raise TransicaoInvalida(f"{self.estado} -> {novo}")
        self.estado = novo
        self.mensagem_status = self._mensagem_agente(texto_agente) if texto_agente is not None else None
        if self.mensagem_status is not None:
            self.historico.append(self.mensagem_status)
        if self.terminal:
            self.pendente = None

    def _mensagem_agente(self, texto: str) -> dict[str, Any]:
        return {"messageId": novo_id("msg"), "role": "ROLE_AGENT", "parts": [{"text": texto}],
                "taskId": self.id, "contextId": self.context_id}

    def para_json(self) -> dict[str, Any]:
        """Forma publica (wire 08-10). Campos privados ficam de fora por construcao."""
        status: dict[str, Any] = {"state": self.estado}
        if self.mensagem_status is not None:
            status["message"] = self.mensagem_status
        return {"id": self.id, "contextId": self.context_id, "status": status,
                "history": list(self.historico), "artifacts": list(self.artefatos)}
