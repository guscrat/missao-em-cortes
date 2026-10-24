"""Custo de uma chamada da API Anthropic, com prompt caching.

O `usage` separa o input em 3 partes cobradas diferente:
  input_tokens                 sem cache (preço cheio)
  cache_creation_input_tokens  escrita no cache de 5 min (1.25x o input)
  cache_read_input_tokens      leitura do cache (0.1x; 0.05x no Opus 5.5)

Preços em US$ por 1M tokens, conferidos em 24/10/2026 em
https://platform.claude.com/docs/en/about-claude/pricing (não confiar na memória: conferir lá
ao trocar de modelo).
"""

# modelo: (input, escrita 5 min, leitura, output)
PRECOS = {
    "claude-opus-5-5":   (4.00, 5.00, 0.20, 20.00),
    "claude-sonnet-4-6": (3.00, 3.75, 0.30, 15.00),
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
