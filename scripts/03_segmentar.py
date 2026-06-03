"""Lê a transcrição, manda pro Claude e gera JSON com blocos temáticos."""
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
from _paths import achar_pasta, stem_de

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
    max_tokens=8000,
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
print(f"Custo: input {response.usage.input_tokens:,} tok · output {response.usage.output_tokens:,} tok")

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

OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"OK Salvo em {OUTPUT}")