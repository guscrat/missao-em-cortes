"""Agenda do canal e cobertura: a ÚNICA fonte de "até quando o canal está coberto".

Usada pelo Curador (13, estoque às 17h), pela lista de publicação (_publicacao, datas
sugeridas depois do último agendado) e pelo painel (aba Hoje: "Canal coberto até" e
"Fila no YouTube"). Se um desses mostrar outra coisa, o bug está aqui.

  agenda_canal()  → último longo agendado/publicado + quantos agendados ainda vão sair
  cobertura(...)  → dias cobertos = até o último agendado + prontos a longos_por_dia/dia

Fontes da agenda: state/canal.json (ultimo_longo, gravado pelo 14_canal lendo o canal) e
publish_at dos blocos agendado/publicado no banco. Só longos (Short não vira bloco).
"""
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CANAL_JSON = Path(__file__).parent.parent / "state" / "canal.json"
FUSO = ZoneInfo("America/Sao_Paulo")


def _local(valor: str | None) -> datetime | None:
    """ISO (com ou sem fuso) → horário de Brasília sem tzinfo. Sem fuso = já é local."""
    if not isinstance(valor, str) or not valor:
        return None
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(FUSO).replace(tzinfo=None) if dt.tzinfo else dt


def agenda_canal(agora: datetime | None = None) -> dict:
    """{"ultimo": date | None, "futuros": int}: dia do último longo agendado/publicado (o
    maior entre canal.json e banco) e quantos blocos agendados ainda não saíram."""
    agora = agora or datetime.now(FUSO).replace(tzinfo=None)
    datas, futuros = [], 0
    try:
        ultimo = _local(json.loads(CANAL_JSON.read_text(encoding="utf-8")).get("ultimo_longo"))
        if ultimo:
            datas.append(ultimo)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        from _eventos import conectar
        con = conectar()
        try:
            linhas = con.execute("SELECT status, publish_at FROM blocos WHERE publish_at IS NOT NULL "
                                 "AND status IN ('agendado', 'publicado')").fetchall()
        finally:
            con.close()
        for status, publish_at in linhas:
            quando = _local(publish_at)
            if quando is None:
                continue
            datas.append(quando)
            futuros += status == "agendado" and quando > agora
    except Exception:  # noqa: BLE001 — banco é best-effort
        pass
    return {"ultimo": max(datas).date() if datas else None, "futuros": futuros}


def cobertura(longos: int, longos_por_dia: float, hoje: date | None = None,
              agenda: dict | None = None) -> dict:
    """Dias de canal coberto = dias até o último longo agendado (passado conta 0) +
    longos prontos ÷ longos_por_dia. coberto_ate = hoje + ceil(dias); None se nada cobre
    nem hoje."""
    hoje = hoje or date.today()
    agenda = agenda if agenda is not None else agenda_canal()
    ultimo = agenda["ultimo"]
    dias_agendados = max((ultimo - hoje).days, 0) if ultimo else 0
    dias = dias_agendados + longos / longos_por_dia
    return {"dias_agendados": dias_agendados, "dias": dias,
            "coberto_ate": hoje + timedelta(days=math.ceil(dias))
            if dias or (ultimo and ultimo >= hoje) else None,
            "ultimo_agendado": ultimo, "agendados_futuros": agenda["futuros"]}
