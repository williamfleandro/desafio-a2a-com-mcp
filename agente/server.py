"""Montagem do agente: Agent Card, endpoint A2A e o cliente MCP compartilhado."""

from __future__ import annotations

from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import config
from a2a_protocol import EndpointA2A
from agent_card import agent_card
from bridge import Ponte
from mcp_client import ClienteMCP
from task_store import TaskStore


def criar_app(cfg: config.Config) -> Starlette:
    cliente = ClienteMCP(cfg.mcp_url)
    endpoint = EndpointA2A(TaskStore(), Ponte(cliente))
    card = agent_card(cfg.public_url)

    async def card_endpoint(_: Request) -> JSONResponse:
        return JSONResponse(card)

    @asynccontextmanager
    async def ciclo_de_vida(_: Starlette):
        yield
        await cliente.fechar()

    return Starlette(
        routes=[
            Route("/.well-known/agent-card.json", card_endpoint, methods=["GET"]),
            Route("/a2a", endpoint.tratar, methods=["POST"]),
        ],
        lifespan=ciclo_de_vida,
    )
