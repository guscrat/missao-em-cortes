"""Lê a transcrição, manda pro Claude e gera JSON com blocos temáticos."""
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
import _custo
import _fronteira as fr
from _paths import achar_pasta, stem_de
from _eventos import evento, upsert_bloco

load_dotenv()

ROOT = Path(__file__).parent.parent
PROMPT = ROOT / "prompts" / "segmentacao.md"

input_arg = sys.argv[1] if len(sys.argv) > 1 else "live_teste"
PASTA = achar_pasta(input_arg)
stem = stem_de(PASTA)
INPUT = PASTA / "transcricao.txt"
OUTPUT = PASTA / "blocos.json"

prompt_sistema = PROMPT.read_text(encoding="utf-8")
transcricao = INPUT.read_text(encoding="utf-8")

print(f"Transcrição: {len(transcricao):,} caracteres (~{len(transcricao)//4:,} tokens)")

client = Anthropic()  # pega ANTHROPIC_API_KEY do .env

print("Chamando Claude...")
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=12000,
    system=prompt_sistema,
    messages=[
        {
            "role": "user",
            "content": (
                f"Transcrição da live a ser analisada:\n\n{transcricao}\n\n"
                "INSTRUÇÃO CRÍTICA: Responda APENAS com o JSON conforme o schema "
                "especificado no prompt do sistema. Não adicione markdown (```), "
                "não adicione texto antes ou depois. Comece a resposta diretamente "
                "com { e termine com }."
            ),
        },
    ],
)

raw = response.content[0].text.strip()
print(f"Resposta: {len(raw):,} caracteres")
uso = _custo.uso(response, "claude-sonnet-4-6")
print(f"Custo: input {uso['tokens_in']:,} tok · output {uso['tokens_out']:,} tok (~${uso['custo_usd']:.2f})")
evento(stem, "03_segmentar", "llm", agente="editor", **uso, mensagem="claude-sonnet-4-6")

# Limpa markdown code blocks se vier (defensivo)
if raw.startswith("```"):
    raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    raw = raw.rsplit("```", 1)[0].strip()

# Se ainda tem texto antes/depois do JSON, extrai só o objeto
if not raw.startswith("{"):
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start : end + 1]

# Parse e validação
try:
    data = json.loads(raw)
except json.JSONDecodeError as e:
    dump = PASTA / "raw_response.txt"
    dump.write_text(raw, encoding="utf-8")
    raise RuntimeError(f"JSON inválido: {e}. Raw salvo em {dump}")

# Validação mínima
assert "blocos" in data, "Resposta sem chave 'blocos'"
print(f"\nOK {len(data['blocos'])} blocos identificados:\n")

for b in data["blocos"]:
    for campo in ["timestamp_inicio", "timestamp_fim", "tema", "titulo_sugerido", "score_potencial"]:
        assert campo in b, f"Bloco {b.get('id')} sem campo '{campo}'"
    print(f"  [{b['timestamp_inicio']} -> {b['timestamp_fim']}] "
          f"({b['duracao_minutos']:.1f}min - score {b['score_potencial']}/10)")
    print(f"    {b['tema']}")
    print(f"    -> {b['titulo_sugerido']}\n")


# ── Sanidade dos timestamps (o prompt proíbe inventar, mas confiar seria bug) ──
def ts_s(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)

dur_video = None
palavras = []
words_json = PASTA / "words.json"
if words_json.exists():
    with words_json.open(encoding="utf-8") as f:
        w = json.load(f)
    dur_video, palavras = w.get("duration"), w.get("words", [])
else:
    print("[aviso] sem words.json: os tempos ficam os do LLM (sem encaixe no fim de frase)")


def encaixar_trecho(trecho: dict, ini: float, fim: float, janela: float,
                    dur_min: float | None, dur_max: float | None) -> tuple[float, float, dict]:
    """Coerência acima da duração: leva início/fim pro fim de frase + pausa mais perto
    (words.json) e grava os tempos exatos no trecho. Sem words.json, não mexe."""
    if not palavras:
        return ini, fim, {"inicio_ok": True, "fim_ok": True}
    e = fr.encaixar(palavras, ini, fim, janela, dur_min, dur_max)
    trecho["timestamp_inicio"] = fr.segundos_para_ts(e["inicio"])
    trecho["timestamp_fim"] = fr.segundos_para_ts(e["fim"])
    return e["inicio"], e["fim"], e


erros, avisos = [], []
validos = []  # (id, ini, fim) dos blocos parseáveis, pro check de sobreposição
for b in data["blocos"]:
    bid = b["id"]
    try:
        ini, fim = ts_s(b["timestamp_inicio"]), ts_s(b["timestamp_fim"])
    except (ValueError, AttributeError):
        erros.append(f"bloco {bid}: timestamp ilegível "
                     f"({b['timestamp_inicio']!r} -> {b['timestamp_fim']!r})")
        continue
    if fim <= ini:
        erros.append(f"bloco {bid}: fim <= início ({b['timestamp_inicio']} -> {b['timestamp_fim']})")
        continue

    # A faixa só restringe o encaixe se o LLM já mandou dentro dela (senão o encaixe
    # não acharia ponto natural perto e ficaria pior)
    dur_llm = fim - ini
    ini, fim, e = encaixar_trecho(
        b, ini, fim, fr.JANELA_BLOCO_S,
        fr.LONGO_MIN * 60 if dur_llm >= fr.LONGO_MIN * 60 else None,
        fr.LONGO_MAX * 60 if dur_llm <= fr.LONGO_MAX * 60 else None)
    for ponta in ("inicio", "fim"):
        if not e[f"{ponta}_ok"]:
            avisos.append(f"bloco {bid}: sem ponto natural de {ponta} a até "
                          f"{fr.JANELA_BLOCO_S:.0f}s do tempo do LLM (o revisor confere)")
    validos.append((bid, ini, fim))

    dur_min = (fim - ini) / 60
    b["duracao_minutos"] = round(dur_min, 1)        # a real, não o chute do LLM
    b["faixa_duracao"] = fr.faixa(dur_min)
    if b["faixa_duracao"] == "fora":
        avisos.append(f"bloco {bid}: duração de {dur_min:.1f}min (faixa é "
                      f"{fr.LONGO_MIN:.0f}-{fr.LONGO_MAX:.0f}min)")
    if dur_video and fim > dur_video + 5:
        erros.append(f"bloco {bid}: fim ({b['timestamp_fim']}) passa do fim do vídeo "
                     f"({dur_video / 60:.1f}min)")

    co = b.get("cold_open")
    if co:
        try:
            co_i, co_f = ts_s(co["timestamp_inicio"]), ts_s(co["timestamp_fim"])
        except (ValueError, AttributeError, KeyError):
            erros.append(f"bloco {bid}: cold_open com timestamps ilegíveis")
            continue
        co_i, co_f, _ = encaixar_trecho(co, co_i, co_f, fr.JANELA_TRECHO_S, 12, 35)
        co["duracao_segundos"] = round(co_f - co_i, 1)
        if not (ini <= co_i < co_f <= fim):
            erros.append(f"bloco {bid}: cold_open fora do intervalo do bloco")
        elif not 8 <= co_f - co_i <= 45:
            avisos.append(f"bloco {bid}: cold_open de {co_f - co_i:.0f}s (alvo é 15-30s)")

    # Short: ideia completa (gancho → desenvolvimento → frase de impacto), até 3 min.
    # Problema no short não derruba o bloco: o 10 volta pro cold open.
    sh = b.get("short")
    if sh:
        try:
            sh_i, sh_f = ts_s(sh["timestamp_inicio"]), ts_s(sh["timestamp_fim"])
        except (ValueError, AttributeError, KeyError):
            sh_i = sh_f = 0.0
        if sh_f <= sh_i:
            avisos.append(f"bloco {bid}: short com timestamps inválidos — o 10 usa o cold open")
            b.pop("short")
            continue
        sh_i, sh_f, e = encaixar_trecho(sh, sh_i, sh_f, fr.JANELA_TRECHO_S, 20, fr.SHORT_MAX_S)
        sh["duracao_segundos"] = round(sh_f - sh_i, 1)
        if not (ini - 1 <= sh_i < sh_f <= fim + 1):
            avisos.append(f"bloco {bid}: short fora do bloco — o 10 usa o cold open")
            b.pop("short")
        elif sh_f - sh_i > fr.SHORT_MAX_S:
            avisos.append(f"bloco {bid}: short de {sh_f - sh_i:.0f}s passa de 3 min — "
                          f"o 10 usa o cold open")
            b.pop("short")
        elif not e["fim_ok"]:
            avisos.append(f"bloco {bid}: short sem fim de frase perto do tempo do LLM")

validos.sort(key=lambda v: v[1])
for (id_a, _, fim_a), (id_b, ini_b, _) in zip(validos, validos[1:]):
    if ini_b < fim_a:
        avisos.append(f"blocos {id_a} e {id_b} se sobrepõem")

faixas = [b.get("faixa_duracao") for b in data["blocos"] if b.get("faixa_duracao")]
if len(faixas) >= 3 and len(set(faixas)) == 1:
    avisos.append(f"todos os {len(faixas)} blocos na faixa '{faixas[0]}': a regra pede variar "
                  f"(curtos 8-12, médios 12-20, longos 20-30)")

for a in avisos:
    print(f"[aviso] {a}")
if erros:
    dump = PASTA / "blocos_invalido.json"
    dump.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[!] Timestamps inválidos vindos do LLM:")
    for e in erros:
        print(f"   - {e}")
    sys.exit(f"\nResposta salva em {dump} pra inspeção. blocos.json NÃO foi gravado — "
             f"rode o step 3 de novo (ou corrija o JSON à mão e renomeie).")

OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
# duração real de cada corte no banco: o Analista (12) compara retenção por faixa
for b in data["blocos"]:
    upsert_bloco(stem, b["id"], tema=b.get("tema"), titulo=b.get("titulo_sugerido"),
                 texto_thumb=b.get("texto_thumb"), score=b.get("score_potencial"),
                 duracao_min=b.get("duracao_minutos"))
print("Durações: " + " · ".join(f"{b['id']}: {b['duracao_minutos']:.1f}min "
                                f"({b.get('faixa_duracao') or '?'})" for b in data["blocos"]))
print(f"OK Salvo em {OUTPUT}")