"""Binding JSON-RPC 2.0 do A2A v1.0: SendMessage e GetTask."""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

import parser
import traceparent as tp
from bridge import Ponte
from task_model import INPUT_REQUIRED, SUBMITTED, WORKING
from task_store import TaskStore

log = logging.getLogger("agente.a2a")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
TASK_NOT_FOUND = -32001  # A2A TaskNotFoundError
UNSUPPORTED_OPERATION = -32004  # A2A UnsupportedOperationError


class ErroA2A(Exception):
    def __init__(self, codigo: int, mensagem: str) -> None:
        super().__init__(mensagem)
        self.codigo = codigo


class EndpointA2A:
    def __init__(self, store: TaskStore, ponte: Ponte) -> None:
        self.store = store
        self.ponte = ponte

    async def tratar(self, request: Request) -> JSONResponse:
        try:
            corpo = json.loads(await request.body())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _erro(None, PARSE_ERROR, "Parse error")
        if not isinstance(corpo, dict) or corpo.get("jsonrpc") != "2.0" or not isinstance(corpo.get("method"), str):
            return _erro(corpo.get("id") if isinstance(corpo, dict) else None, INVALID_REQUEST, "Invalid Request")
        id_ = corpo.get("id")
        params = corpo.get("params") if isinstance(corpo.get("params"), dict) else {}
        trace_id = tp.trace_id_de(request.headers.get("traceparent"))
        log.info("a2a_request method=%s id=%s traceparent=%s", corpo["method"], id_, request.headers.get("traceparent") or "-")
        try:
            if corpo["method"] == "SendMessage":
                resultado = await self.send_message(params, trace_id)
            elif corpo["method"] == "GetTask":
                resultado = self.get_task(params)
            else:
                raise ErroA2A(METHOD_NOT_FOUND, f"Method not found: {corpo['method']}")
        except ErroA2A as e:
            return _erro(id_, e.codigo, str(e))
        return JSONResponse({"jsonrpc": "2.0", "id": id_, "result": resultado})

    async def send_message(self, params: dict[str, Any], trace_id: str | None) -> dict[str, Any]:
        mensagem = params.get("message")
        if not isinstance(mensagem, dict) or not isinstance(mensagem.get("parts"), list):
            raise ErroA2A(INVALID_PARAMS, "params.message com parts e obrigatorio")
        texto = parser.texto_da_mensagem(mensagem)
        task_id = mensagem.get("taskId")
        if task_id is None:
            task = self.store.criar(mensagem.get("contextId"))
            task.trace_id = trace_id
            task.historico.append(mensagem)
            task.mudar(SUBMITTED)
            task.mudar(WORKING)
            async with task.lock:
                await self.ponte.iniciar(task, texto)
            return {"task": task.para_json()}

        task = self.store.obter(task_id)
        if task is None:
            raise ErroA2A(TASK_NOT_FOUND, f"Task not found: {task_id}")
        async with task.lock:
            if task.terminal:
                raise ErroA2A(UNSUPPORTED_OPERATION, f"Task {task_id} esta em estado terminal ({task.estado})")
            if task.estado != INPUT_REQUIRED:
                raise ErroA2A(UNSUPPORTED_OPERATION, f"Task {task_id} nao aguarda entrada ({task.estado})")
            if trace_id is not None:
                task.trace_id = trace_id
            task.historico.append(mensagem)
            await self.ponte.continuar(task, texto)
        return {"task": task.para_json()}

    def get_task(self, params: dict[str, Any]) -> dict[str, Any]:
        task = self.store.obter(str(params.get("id")))
        if task is None:
            raise ErroA2A(TASK_NOT_FOUND, f"Task not found: {params.get('id')}")
        return {"task": task.para_json()}


def _erro(id_: Any, codigo: int, mensagem: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": id_, "error": {"code": codigo, "message": mensagem}})
