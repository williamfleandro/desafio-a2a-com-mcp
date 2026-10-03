"""Regras de dominio das salas: funcoes puras, mensagens literais do contrato."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

# Mensagens literais: validador/validar.py e README ("Regras de negocio").
ERRO_SALA = "Sala inexistente: {sala}"
ERRO_JANELA = "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00"
ERRO_DURACAO = "Duracao acima do limite: a politica permite no maximo 2 horas"
ERRO_INTERVALO = "Intervalo invalido: fim deve ser posterior a inicio"
ERRO_SEM_ALTERNATIVA = "Sem alternativas disponiveis no intervalo"

MAXIMO_ALTERNATIVAS = 3

FUSO_POLITICA = timezone(timedelta(hours=-3))  # Sao Paulo, -03:00, fixo pela politica
ABERTURA = time(8, 0)
FECHAMENTO = time(20, 0)
DURACAO_MAXIMA = timedelta(hours=2)


class ErroDeRegra(Exception):
    """Pedido viola uma regra de dominio. A mensagem e literal do contrato."""


def para_datetime(valor: str) -> datetime:
    """ISO 8601 -> datetime com fuso. Sem offset, assume o fuso da politica."""
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        raise ErroDeRegra(f"Data/hora invalida: {valor}") from None
    return dt if dt.tzinfo else dt.replace(tzinfo=FUSO_POLITICA)


def validar_sala(sala: str, salas: list[dict]) -> None:
    if not any(s["id"] == sala for s in salas):
        raise ErroDeRegra(ERRO_SALA.format(sala=sala))


def validar_intervalo(inicio: datetime, fim: datetime) -> None:
    if fim <= inicio:
        raise ErroDeRegra(ERRO_INTERVALO)


def validar_janela(inicio: datetime, fim: datetime) -> None:
    """O intervalo inteiro precisa caber em [08:00, 20:00] do dia do inicio, no fuso -03:00."""
    inicio_local = inicio.astimezone(FUSO_POLITICA)
    dia = inicio_local.date()
    abertura = datetime.combine(dia, ABERTURA, FUSO_POLITICA)
    fechamento = datetime.combine(dia, FECHAMENTO, FUSO_POLITICA)
    if inicio < abertura or fim > fechamento:
        raise ErroDeRegra(ERRO_JANELA)


def validar_duracao(inicio: datetime, fim: datetime) -> None:
    if fim - inicio > DURACAO_MAXIMA:
        raise ErroDeRegra(ERRO_DURACAO)


def validar_pedido(sala: str, inicio: str, fim: str, salas: list[dict]) -> tuple[datetime, datetime]:
    """Ordem fixa do contrato: sala -> intervalo -> janela -> duracao. Devolve o intervalo parseado."""
    validar_sala(sala, salas)
    ini, fi = para_datetime(inicio), para_datetime(fim)
    validar_intervalo(ini, fi)
    validar_janela(ini, fi)
    validar_duracao(ini, fi)
    return ini, fi


def intervalos_sobrepostos(a_inicio: datetime, a_fim: datetime, b_inicio: datetime, b_fim: datetime) -> bool:
    """Intervalos semiabertos: encostar na borda nao e conflito."""
    return a_inicio < b_fim and a_fim > b_inicio


def conflitos(sala: str, inicio: datetime, fim: datetime, reservas: list[dict]) -> list[dict]:
    """Reservas da sala que se sobrepoem ao intervalo, na ordem em que estao guardadas."""
    return [
        r
        for r in reservas
        if r["sala"] == sala and intervalos_sobrepostos(inicio, fim, para_datetime(r["inicio"]), para_datetime(r["fim"]))
    ]


def alternativas(sala: str, inicio: datetime, fim: datetime, salas: list[dict], reservas: list[dict]) -> list[str]:
    """Salas livres no intervalo com capacidade >= a pedida; ate 3, por capacidade e depois id."""
    capacidade = next(s["capacidade"] for s in salas if s["id"] == sala)
    livres = [
        s
        for s in salas
        if s["id"] != sala and s["capacidade"] >= capacidade and not conflitos(s["id"], inicio, fim, reservas)
    ]
    livres.sort(key=lambda s: (s["capacidade"], s["id"]))
    return [s["id"] for s in livres[:MAXIMO_ALTERNATIVAS]]
