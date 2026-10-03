"""W3C traceparent: preserva o trace-id, gera span-id novo por request MCP."""

from __future__ import annotations

import re
import secrets

_FORMATO = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def trace_id_de(traceparent: str | None) -> str | None:
    """Extrai o trace-id de um header traceparent valido; None se ausente ou invalido."""
    m = _FORMATO.match((traceparent or "").strip().lower())
    if not m or m.group(1) == "0" * 32 or m.group(2) == "0" * 16:
        return None
    return m.group(1)


def filho(trace_id: str | None) -> str | None:
    """traceparent para um request MCP: mesmo trace-id, span-id novo."""
    if trace_id is None:
        return None
    return f"00-{trace_id}-{secrets.token_hex(8)}-01"
