"""Portão de política (22/11/2026): o canal corta SÓ a confusão do mundo político brasileiro.
Live sem esse tipo de tema não vira corte nenhum, e a decisão vem ANTES das etapas pagas.

Caso real: o podcast do Arthur do Val com o Fernando Gil (162 min) gastou US$ 3,48 e virou
cortes sobre Flamengo, swing e traição. A transcrição (02) é grátis; este portão roda no começo
do 03, antes da segmentação paga: o Haiku lê a transcrição inteira (compactada por minuto) e
diz se tem pelo menos um trecho do tipo que dá view. Não passou → o 03 sai com
EXIT_SEM_POLITICA, o pipeline para sem falha e o Curador descarta a sugestão.

Custo: ~US$ 0,005-0,01 por live de 2-3 h (Haiku 5.5, ~50K tokens). A resposta fica em
<pasta>/politica.json com o hash da transcrição e do critério: rodar de novo não paga.
Pular o portão (o Gu quer a live mesmo assim): `03_segmentar.py <stem> --sem-portao`
(ou `pipeline.py <stem> --sem-portao`).

O mesmo CRITERIO entra no Curador (13, antes de sugerir), no 03 (blocos) e no 11 (revisor).
"""
import hashlib
import json
import re
from pathlib import Path

import _custo
from _eventos import evento

MODELO = "claude-haiku-5-5"
ARQUIVO = "politica.json"
EXIT_SEM_POLITICA = 4     # código de saída do 03 quando a live não passa no portão
MAX_CHARS = 280_000       # ~70K tokens: fica abaixo da faixa cara do Haiku (100K)
# O código também decide (o modelo é generoso: no podcast do Gil disse "passa" com 25 de 162
# min). Passa só com o "passa" do modelo E minutos de política >= os dois limites. Chute.
FRACAO_MIN = 0.4          # parte da live que precisa ser política
MINUTOS_MIN = 15

CRITERIO = """O canal corta SÓ a confusão do mundo político brasileiro, que é o que dá \
visualização: brigas e rachas entre políticos e partidos, problemas internos de partido, \
escândalos, crimes e corrupção de políticos, prisões e solturas (ex.: "Daniel Vorcaro vai ser \
solto?", "Bolsonaro sai da prisão?"), investigações, votações polêmicas, eleição e candidatos, \
crise do governo e previsões concretas de crise ("Lula terá colapso fiscal em 2027?").

NÃO conta como política pro canal, mesmo que o assunto encoste em política: teoria e \
ideologia abstrata (o que é o comunismo, liberalismo na filosofia), história, economia de \
livro, comportamento e costumes, vida pessoal, relacionamento, futebol, religião, \
entretenimento, humor, histórias de vida do convidado."""

SISTEMA = f"""Você é o portão de entrada do canal "Missão em Cortes" (cortes de lives do \
Partido Missão e do MBL). Antes de pagar pela segmentação, você lê a transcrição de uma live \
e decide se ela tem material pro canal.

{CRITERIO}

Seja rígido: o dono do canal prefere perder uma live a pagar por cortes fora da régua.
minutos: quantos minutos da live são sobre esse tipo de tema, com a conversa realmente nele \
(não menção de passagem). NÃO conte história (eleição de 1989, ditadura, Collor), teoria \
(comunismo, liberalismo), economia de livro ou histórica (hiperinflação, milagre econômico), \
nem o convidado contando a vida dele, mesmo que cite políticos.
passa = true só se a live é PREDOMINANTEMENTE sobre esse tipo de tema (uma live de análise \
política, entrevista sobre política). Podcast de variedades, bate-papo ou entrevista de vida \
com alguns trechos políticos: passa = false.
temas: os assuntos que contam e renderiam corte, no máximo 8, cada um em poucas palavras e \
concreto ("racha no PL sobre a candidatura do Flávio"); vazio se não há nenhum.
motivo: uma frase curta em português que aparece no painel pro dono do canal."""

SCHEMA = {
    "type": "object",
    "properties": {
        "passa": {"type": "boolean"},
        "temas": {"type": "array", "items": {"type": "string"}},
        "minutos": {"type": "integer"},
        "motivo": {"type": "string"},
    },
    "required": ["passa", "temas", "minutos", "motivo"],
    "additionalProperties": False,
}

RE_LINHA = re.compile(r"^\[(\d+):(\d{2}):\d{2}\]\s*(?:[^:]{1,30}:\s*)?(.*)$")

_client = None


def _cliente():
    global _client
    if _client is None:
        import anthropic
        from dotenv import load_dotenv
        load_dotenv()
        _client = anthropic.Anthropic()
    return _client


def compactar(transcricao: str, max_chars: int = MAX_CHARS) -> str:
    """Uma linha por minuto ("[73] texto..."), sem o relógio e o "Speaker:" de cada frase
    (corta ~30% dos tokens). Passou de max_chars: amostra minutos espalhados pela live
    inteira (o portão precisa ver o começo, o meio e o fim, não só o começo)."""
    minutos: dict[int, list[str]] = {}
    for linha in transcricao.splitlines():
        m = RE_LINHA.match(linha.strip())
        if m and m.group(3).strip():
            minutos.setdefault(int(m.group(1)) * 60 + int(m.group(2)), []).append(m.group(3).strip())
    linhas = [f"[{mi}] {' '.join(txt)}" for mi, txt in sorted(minutos.items())]
    texto = "\n".join(linhas)
    if len(texto) <= max_chars or not linhas:
        return texto
    passo = len(texto) / max_chars                     # pega 1 a cada `passo` minutos
    escolhidas = [linhas[int(i * passo)] for i in range(int(len(linhas) / passo))]
    return "\n".join(escolhidas)[:max_chars]


def duracao_min(transcricao: str) -> int:
    """Último minuto com fala na transcrição (≈ duração da live)."""
    ultimo = 0
    for linha in transcricao.splitlines():
        m = RE_LINHA.match(linha.strip())
        if m:
            ultimo = max(ultimo, int(m.group(1)) * 60 + int(m.group(2)))
    return ultimo


def decidir(dados: dict, duracao: int) -> dict:
    """Veredito final: o "passa" do modelo E minutos de política acima dos dois limites."""
    minutos = int(dados.get("minutos") or 0)
    minimo = max(MINUTOS_MIN, round(FRACAO_MIN * duracao))
    motivo = (dados.get("motivo") or "").strip()
    passa = bool(dados.get("passa")) and minutos >= minimo
    if dados.get("passa") and not passa:
        motivo = (f"só ~{minutos} de {duracao} min são política (mínimo {minimo})"
                  + (f": {motivo}" if motivo else ""))
    return {"passa": passa, "temas": [str(t) for t in dados.get("temas") or []][:8],
            "minutos": minutos, "duracao_min": duracao, "motivo": motivo}


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def assinatura(transcricao: str) -> dict:
    return {"transcricao": _hash(transcricao), "criterio": _hash(SISTEMA), "modelo": MODELO}


def ler(pasta: Path) -> dict | None:
    """Veredito salvo (ou None). O Curador usa pra saber se o pipeline parou no portão."""
    try:
        dados = json.loads((pasta / ARQUIVO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dados if isinstance(dados, dict) and "passa" in dados else None


def marcar_sem_politica(pasta: Path, motivo: str) -> None:
    """O portão deixou passar, mas a segmentação não achou nenhum bloco político: grava o
    veredito como reprovado (o Curador lê isso e descarta a sugestão em vez de acusar falha)."""
    veredito = ler(pasta) or {"temas": [], "minutos": 0}
    veredito.update(passa=False, motivo=motivo)
    (pasta / ARQUIVO).write_text(json.dumps(veredito, ensure_ascii=False, indent=2),
                                 encoding="utf-8")


def checar(stem: str, pasta: Path) -> dict:
    """{passa, temas, minutos, motivo} da live. Mesma transcrição e critério de uma checagem
    anterior: reaproveita ($0). Senão é chamada paga: orçamento da live + evento `llm`."""
    transcricao = (pasta / "transcricao.txt").read_text(encoding="utf-8")
    sig = assinatura(transcricao)
    salvo = ler(pasta)
    if salvo and salvo.get("_assinatura") == sig:
        return salvo
    _custo.checar_orcamento(stem, "03_politica")
    texto = compactar(transcricao)
    resp = _cliente().messages.create(
        model=MODELO,
        max_tokens=1000,
        system=SISTEMA,
        messages=[{"role": "user", "content":
                   f"Transcrição da live (uma linha por minuto, [minuto] fala):\n\n{texto}"}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    uso = _custo.uso(resp, MODELO)
    print(f"  portão de política: {uso['tokens_in']:,} tokens · ~US$ {uso['custo_usd']:.3f}")
    evento(stem, "03_politica", "llm", agente="curador", mensagem=MODELO, **uso)
    if resp.stop_reason == "refusal":   # sem veredito: falha alto (o Gu decide no painel)
        raise RuntimeError("o modelo recusou avaliar a política da live")
    bruto = next((b.text for b in resp.content if b.type == "text"), "{}")
    dados = json.loads(bruto)
    veredito = decidir(dados, duracao_min(transcricao))
    veredito["_assinatura"] = sig
    (pasta / ARQUIVO).write_text(json.dumps(veredito, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    return veredito
