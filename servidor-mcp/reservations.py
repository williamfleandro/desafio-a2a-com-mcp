"""Reservas em memoria. dados/reservas.json e so o estado inicial: nunca e regravado."""

from __future__ import annotations

import json

import config


def _carregar_iniciais() -> list[dict]:
    with open(config.DADOS / "reservas.json", encoding="utf-8") as f:
        return json.load(f)


# Carregado uma vez, quando o processo importa o modulo.
reservas: list[dict] = _carregar_iniciais()


def proximo_id() -> str:
    """res-NNNN seguinte ao maior numero conhecido (nao ao tamanho da lista)."""
    maior = max((int(r["id"].removeprefix("res-")) for r in reservas), default=0)
    return f"res-{maior + 1:04d}"


def criar(sala: str, inicio: str, fim: str, responsavel: str) -> dict:
    reserva = {"id": proximo_id(), "sala": sala, "inicio": inicio, "fim": fim, "responsavel": responsavel}
    reservas.append(reserva)
    return reserva
