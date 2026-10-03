"""Parser deterministico do formato fixo de pedido. Sem LLM.

    reservar sala=<id> inicio=<iso8601> fim=<iso8601> responsavel=<nome>
    escolha=<id da sala> | escolha=recusar
"""

from __future__ import annotations

import re

CAMPOS = ("sala", "inicio", "fim", "responsavel")
_PEDIDO = re.compile(r"^(?P<verbo>[a-z_]+)\s+(?P<resto>.+)$", re.S)
_CHAVE = re.compile(r"(?:^|\s)(" + "|".join(CAMPOS) + r")=")
_ESCOLHA = re.compile(r"^escolha=(\S+)$")


def texto_da_mensagem(mensagem: dict) -> str:
    partes = mensagem.get("parts") or []
    return " ".join(p.get("text", "") for p in partes if isinstance(p, dict)).strip()


def parse_pedido(texto: str) -> tuple[str, dict[str, str]] | None:
    """('reservar', {sala, inicio, fim, responsavel}) ou None. O valor vai ate a proxima chave."""
    m = _PEDIDO.match(texto.strip())
    if not m:
        return None
    resto = m.group("resto")
    marcas = list(_CHAVE.finditer(resto))
    campos: dict[str, str] = {}
    for i, marca in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(resto)
        campos[marca.group(1)] = resto[marca.end():fim].strip()
    if set(campos) != set(CAMPOS) or not all(campos.values()):
        return None
    return m.group("verbo"), {c: campos[c] for c in CAMPOS}


def parse_escolha(texto: str) -> str | None:
    m = _ESCOLHA.match(texto.strip())
    return m.group(1) if m else None
