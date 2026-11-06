"""Critério de atualidade (06/11/2026): trecho cujo valor depende de algo que JÁ SE RESOLVEU
não vira corte nem Short. Ex.: previsão de resultado já conhecido, debate de eleição
encerrada, apuração ao vivo, pesquisa superada.

Onde a regra mora: prompts/segmentacao.md (03, score baixo e não vira bloco), o critério
`datado` do 11_revisor (→ descartado) e este helper, que o 09 chama antes de subir cada
Short: o Short sai dias depois do longo, então a atualidade é checada de novo NA DATA DE
PUBLICAÇÃO. Datado → `"arquivado": true` + `"motivo"` no shorts.json (só o Short; o bloco do
longo publicado fica como está). Custo: ~US$ 0,002 por Short (Sonnet 5.5, ~1K tokens).
"""
import json
from datetime import date
from pathlib import Path

import _custo
from _eventos import evento

MODELO = "claude-sonnet-5-5"

CRITERIO = """Um trecho é DATADO quando o valor dele depende de algo que, na data de \
publicação, já terá se resolvido: previsão ou aposta sobre um resultado que já terá saído \
(eleição, votação, julgamento, jogo), debate de uma eleição já encerrada, apuração ou \
cobertura ao vivo de resultado, pesquisa de intenção de voto já superada pelo resultado. \
NÃO é datado: opinião, análise ou crítica que continua valendo depois do resultado (balanço \
de uma derrota, lição tirada dela, tese sobre um político, crítica a partido), mesmo que \
cite a eleição. Na dúvida, NÃO é datado."""

SISTEMA = f"""Você checa se um Short do canal "Missão em Cortes" (cortes de lives do Partido \
Missão) ainda faz sentido na data em que vai ao ar.

{CRITERIO}

Responda só o JSON pedido. motivo: uma frase curta em português (vazio "" se não é datado)."""

SCHEMA = {
    "type": "object",
    "properties": {"datado": {"type": "boolean"}, "motivo": {"type": "string"}},
    "required": ["datado", "motivo"],
    "additionalProperties": False,
}

_client = None


def _cliente():
    global _client
    if _client is None:
        import anthropic
        from dotenv import load_dotenv
        load_dotenv()
        _client = anthropic.Anthropic()
    return _client


def data_da_live(pasta: Path) -> date | None:
    """A pasta é <AAAA-MM-DD>_<stem>: a data em que a live foi processada (≈ a da live)."""
    try:
        return date.fromisoformat(pasta.name[:10])
    except ValueError:
        return None


def _segundos(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def texto_do_short(pasta: Path, bid: int) -> str:
    """A fala do Short: o trecho `short` do bloco (o `cold_open` nos antigos), pelo words.json."""
    blocos = {b["id"]: b for b in json.loads(
        (pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"]}
    b = blocos[bid]
    trecho = b.get("short") or b.get("cold_open") or {}
    if trecho.get("timestamp_inicio") and trecho.get("timestamp_fim"):
        try:
            palavras = json.loads((pasta / "words.json").read_text(encoding="utf-8"))
            palavras = palavras.get("words", palavras) if isinstance(palavras, dict) else palavras
            ini, fim = _segundos(trecho["timestamp_inicio"]), _segundos(trecho["timestamp_fim"])
            texto = " ".join(str(p.get("word", "")).strip() for p in palavras
                             if ini <= p.get("start", -1) < fim)
            if texto.strip():
                return texto
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
    return trecho.get("frase") or b.get("resumo") or ""


def checar_short(stem: str, pasta: Path, bid: int, publicacao: date,
                 titulo: str = "") -> tuple[bool, str]:
    """(datado, motivo) do Short do bloco `bid` publicado em `publicacao`. Chamada paga:
    passa pelo orçamento da live e registra o evento `llm` (agente revisor)."""
    _custo.checar_orcamento(stem, "09_atualidade")
    live = data_da_live(pasta)
    texto = texto_do_short(pasta, bid)
    pedido = (f"DATA DA LIVE (aprox.): {live:%d/%m/%Y}\n" if live else "") + \
             f"DATA DE PUBLICAÇÃO DO SHORT: {publicacao:%d/%m/%Y}\n" \
             f"TÍTULO DO SHORT: {titulo}\n\nFALA DO SHORT:\n{texto}"
    resp = _cliente().messages.create(
        model=MODELO,
        max_tokens=1000,
        system=SISTEMA,
        messages=[{"role": "user", "content": pedido}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    uso = _custo.uso(resp, MODELO)
    evento(stem, "09_atualidade", "llm", agente="revisor", bloco_id=bid, **uso,
           mensagem=f"{MODELO} Short {bid:02d} em {publicacao:%d/%m}")
    if resp.stop_reason == "refusal":   # na dúvida não publica: o 09 trata como falha
        raise RuntimeError("o modelo recusou checar a atualidade")
    texto_resp = next((b.text for b in resp.content if b.type == "text"), "{}")
    dados = json.loads(texto_resp)
    return bool(dados.get("datado")), (dados.get("motivo") or "").strip()
