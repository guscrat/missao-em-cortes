"""Custo de uma chamada da API Anthropic, com prompt caching.

O `usage` separa o input em 3 partes cobradas diferente:
  input_tokens                 sem cache (preço cheio)
  cache_creation_input_tokens  escrita no cache: 1.25x o input no de 5 min, 2x no de 1 h
                               (usage.cache_creation.ephemeral_1h_input_tokens separa)
  cache_read_input_tokens      leitura do cache (0.1x; 0.05x no Opus 5.5)

Preços em US$ por 1M tokens, conferidos em 24/10/2026 em
https://platform.claude.com/docs/en/about-claude/pricing (não confiar na memória: conferir lá
ao trocar de modelo).

Orçamento por live: `checar_orcamento(stem, etapa)` vai antes de toda chamada paga de uma live.
Passou de trava_live_usd (config/painel.json, padrão US$ 2) → para e pede liberação:
    uv run py scripts/_custo.py liberar <stem> [--ate=4]
O painel acende o alerta a partir de alerta_live_usd (padrão US$ 1).
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_PAINEL = ROOT / "config" / "painel.json"
LIBERADAS = ROOT / "state" / "orcamento_lives.json"   # {stem: teto liberado em US$}
ALERTA_LIVE_USD, TRAVA_LIVE_USD = 1.0, 2.0            # padrão; config/painel.json manda

# modelo: (input, escrita 5 min, leitura, output)
PRECOS = {
    "claude-opus-5-5":   (4.00, 5.00, 0.20, 20.00),
    "claude-sonnet-4-6": (3.00, 3.75, 0.30, 15.00),
    "claude-sonnet-5-5": (2.00, 2.50, 0.10, 10.00),
    "claude-haiku-5-5":  (0.10, 0.125, 0.01, 0.50),
}
# Haiku 5.5 com prompt (sem cache + escrita + leitura) acima de 100K tokens: tudo mais caro
HAIKU_LONGO = 100_000
PRECOS_HAIKU_LONGO = (0.50, 0.625, 0.05, 2.50)


def _n(usage, campo: str) -> int:
    return getattr(usage, campo, 0) or 0   # o SDK devolve None quando não houve cache


def _escrita_1h(usage) -> int:
    return getattr(getattr(usage, "cache_creation", None), "ephemeral_1h_input_tokens", 0) or 0


def uso(resp, modelo: str) -> dict:
    """{tokens_in, tokens_out, cache_escrita, cache_leitura, custo_usd} de uma resposta.
    tokens_in é o input TOTAL (sem cache + escrita + leitura), comparável ao de antes do
    cache. Usa resp.model quando ele está na tabela (o fallback de refusal pode trocar o modelo)."""
    u = resp.usage
    sem_cache, escrita, leitura = _n(u, "input_tokens"), _n(u, "cache_creation_input_tokens"), \
        _n(u, "cache_read_input_tokens")
    tout = _n(u, "output_tokens")
    modelo = getattr(resp, "model", None) if getattr(resp, "model", None) in PRECOS else modelo
    if modelo not in PRECOS:   # custo é best-effort: não derruba o pipeline
        print(f"[aviso] _custo: {modelo} fora da tabela de preços; usando o do Opus 5.5",
              file=sys.stderr)
        modelo = "claude-opus-5-5"
    p_in, p_escrita, p_leitura, p_out = PRECOS[modelo]
    total_in = sem_cache + escrita + leitura
    if modelo == "claude-haiku-5-5" and total_in > HAIKU_LONGO:
        p_in, p_escrita, p_leitura, p_out = PRECOS_HAIKU_LONGO
    e1h = min(_escrita_1h(u), escrita)   # cache de 1 h: escrita a 2x o input
    usd = (sem_cache * p_in + (escrita - e1h) * p_escrita + e1h * 2 * p_in
           + leitura * p_leitura + tout * p_out) / 1e6
    return {"tokens_in": total_in, "tokens_out": tout, "cache_escrita": escrita,
            "cache_leitura": leitura, "custo_usd": usd}


def cache(resp) -> dict:
    """{cache_escrita, cache_leitura} pra passar direto no evento(..., **cache(resp))."""
    return {"cache_escrita": _n(resp.usage, "cache_creation_input_tokens"),
            "cache_leitura": _n(resp.usage, "cache_read_input_tokens")}


def somar(usos: list[dict]) -> dict:
    """Soma vários `uso()` (ex: o 04b loga um evento só pro vídeo inteiro)."""
    chaves = ("tokens_in", "tokens_out", "cache_escrita", "cache_leitura", "custo_usd")
    return {k: sum(u[k] for u in usos) for k in chaves}


def taxa_acerto(cache_leitura: int, tokens_in: int) -> float:
    """Fração do input servida do cache (0 a 1)."""
    return cache_leitura / tokens_in if tokens_in else 0.0


def resumo(u: dict) -> str:
    """Pedaço da linha de custo no terminal."""
    if not (u["cache_escrita"] or u["cache_leitura"]):
        return ""
    return (f" · cache: {u['cache_leitura']:,} lidos, {u['cache_escrita']:,} escritos "
            f"({taxa_acerto(u['cache_leitura'], u['tokens_in']):.0%} do input)")


# ── orçamento por live ──────────────────────────────────────────────────────

def _ler_json(path: Path) -> dict:
    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def limites_live() -> tuple[float, float]:
    """(alerta, trava) em US$ por live, do config/painel.json."""
    cfg = _ler_json(CONFIG_PAINEL)
    return (float(cfg.get("alerta_live_usd", ALERTA_LIVE_USD)),
            float(cfg.get("trava_live_usd", TRAVA_LIVE_USD)))


def liberadas() -> dict[str, float]:
    return {k: float(v) for k, v in _ler_json(LIBERADAS).items() if isinstance(v, (int, float))}


def gasto_live(stem: str) -> float | None:
    """Soma do custo_usd de todos os eventos da live. None se o banco falhou (não trava)."""
    import _eventos   # lido na hora: os testes trocam o DB_PATH
    if not _eventos.DB_PATH.exists():
        return 0.0
    try:
        con = sqlite3.connect(f"file:{_eventos.DB_PATH}?mode=ro", uri=True, timeout=5)
        try:
            return float(con.execute("SELECT COALESCE(SUM(custo_usd), 0) FROM eventos "
                                     "WHERE stem = ?", (stem,)).fetchone()[0])
        finally:
            con.close()
    except sqlite3.Error as e:
        print(f"[aviso] _custo: não li o custo da live ({e}); seguindo sem a trava",
              file=sys.stderr)
        return None


def descrever_erro(e: Exception) -> str:
    """Erro da API em pt-BR pro painel: o limite mensal da conta vira texto claro, não só
    'BadRequestError' (29/10: o limite estourou no meio da live e ninguém entendeu)."""
    texto = str(e).lower()
    if "usage limit" in texto:
        return ("limite de uso da API atingido — suba em platform.claude.com "
                "(Settings > Limits) e rode de novo")
    if "credit balance" in texto:
        return "sem crédito na API — recarregue em platform.claude.com e rode de novo"
    return type(e).__name__


class OrcamentoEstourado(SystemExit):
    """A live passou do teto: o script para (exit com a mensagem) até o Gu liberar."""


def checar_orcamento(stem: str, etapa: str) -> None:
    """Antes de cada chamada paga da live. Gasto >= teto (trava ou o liberado) → para."""
    gasto = gasto_live(stem)
    if gasto is None:
        return
    _, trava = limites_live()
    teto = max(trava, liberadas().get(stem, 0.0))
    if gasto < teto:
        return
    from _eventos import evento
    evento(stem, etapa, "aviso", mensagem=f"orçamento da live: US$ {gasto:.2f} >= teto "
                                          f"US$ {teto:.2f} — parado até liberar")
    raise OrcamentoEstourado(
        f"\n[!] A live '{stem}' já custou US$ {gasto:.2f} de API (teto US$ {teto:.2f}). "
        f"Parei antes de gastar mais ({etapa}).\n    Pra seguir: uv run py scripts/_custo.py "
        f"liberar {stem}   (libera mais US$ {trava:.2f}; --ate=X pra outro teto) e rode de novo.")


def liberar(stem: str, ate: float | None = None) -> float:
    """Sobe o teto da live (padrão: gasto atual + trava). Devolve o teto novo."""
    _, trava = limites_live()
    teto = ate if ate is not None else (gasto_live(stem) or 0.0) + trava
    dados = _ler_json(LIBERADAS)
    dados[stem] = round(teto, 2)
    LIBERADAS.parent.mkdir(parents=True, exist_ok=True)
    LIBERADAS.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    return teto


# ── medição: quanto o cache economizou num vídeo ────────────────────────────

def modelo_do_evento(mensagem: str | None) -> str | None:
    """Os eventos llm gravam resp.model no começo da mensagem (ex: 'claude-opus-5-5 (thumb)')."""
    return next((m for m in PRECOS if (mensagem or "").startswith(m)), None)


def sem_cache_usd(ev: dict) -> float:
    """Quanto o evento custaria com os mesmos tokens e sem cache (tudo a preço cheio)."""
    modelo = modelo_do_evento(ev.get("mensagem"))
    if not modelo:
        return ev["custo_usd"]
    p_in, p_escrita, p_leitura, _ = PRECOS[modelo]
    return ev["custo_usd"] + ((ev.get("cache_escrita") or 0) * (p_in - p_escrita)
                              + (ev.get("cache_leitura") or 0) * (p_in - p_leitura)) / 1e6


def economia(eventos: list[dict]) -> dict:
    """{etapa: {chamadas, custo, sem_cache, taxa}} + '_total', dos eventos llm de um vídeo."""
    saida: dict[str, dict] = {}
    for ev in eventos:
        e = saida.setdefault(ev["etapa"], {"chamadas": 0, "custo": 0.0, "sem_cache": 0.0,
                                           "leitura": 0, "tokens_in": 0})
        e["chamadas"] += 1
        e["custo"] += ev["custo_usd"]
        e["sem_cache"] += sem_cache_usd(ev)
        e["leitura"] += ev.get("cache_leitura") or 0
        e["tokens_in"] += ev.get("tokens_in") or 0
    saida["_total"] = {k: sum(e[k] for e in saida.values())
                       for k in ("chamadas", "custo", "sem_cache", "leitura", "tokens_in")}
    for e in saida.values():
        e["taxa"] = taxa_acerto(e.pop("leitura"), e.pop("tokens_in"))
    return saida


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    from _eventos import DB_PATH
    if len(sys.argv) < 2:
        sys.exit("uso: uv run py scripts/_custo.py <stem>   (custo real x sem cache do vídeo)\n"
                 "     uv run py scripts/_custo.py liberar <stem> [--ate=X]   (destrava a live)")
    if sys.argv[1] == "liberar":
        if len(sys.argv) < 3:
            sys.exit("uso: uv run py scripts/_custo.py liberar <stem> [--ate=X]")
        ate = next((float(a.split("=", 1)[1]) for a in sys.argv[3:] if a.startswith("--ate=")), None)
        teto = liberar(sys.argv[2], ate)
        print(f"Live '{sys.argv[2]}' liberada até US$ {teto:.2f} "
              f"(gasto até agora: US$ {gasto_live(sys.argv[2]) or 0:.2f})")
        sys.exit(0)
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    linhas = [dict(r) for r in con.execute(
        "SELECT * FROM eventos WHERE stem = ? AND status = 'llm' ORDER BY ts", (sys.argv[1],))]
    if not linhas:
        sys.exit(f"nenhum evento llm do stem {sys.argv[1]!r}")
    print(f"{'etapa':<14}{'chamadas':>9}{'real':>10}{'sem cache':>11}{'economia':>10}{'acerto':>8}")
    for etapa, e in economia(linhas).items():
        print(f"{etapa:<14}{e['chamadas']:>9}{e['custo']:>10.4f}{e['sem_cache']:>11.4f}"
              f"{e['sem_cache'] - e['custo']:>10.4f}{e['taxa']:>8.0%}")
