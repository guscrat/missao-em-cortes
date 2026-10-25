"""Custo de uma chamada da API Anthropic, com prompt caching.

O `usage` separa o input em 3 partes cobradas diferente:
  input_tokens                 sem cache (preço cheio)
  cache_creation_input_tokens  escrita no cache de 5 min (1.25x o input)
  cache_read_input_tokens      leitura do cache (0.1x; 0.05x no Opus 5.5)

Preços em US$ por 1M tokens, conferidos em 24/10/2026 em
https://platform.claude.com/docs/en/about-claude/pricing (não confiar na memória: conferir lá
ao trocar de modelo).
"""
import sys

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
    usd = (sem_cache * p_in + escrita * p_escrita + leitura * p_leitura + tout * p_out) / 1e6
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
    import sqlite3
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    from _eventos import DB_PATH
    if len(sys.argv) < 2:
        sys.exit("uso: uv run py scripts/_custo.py <stem>   (custo real x sem cache do vídeo)")
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
