"""Polimento dos cortes: re-transcreve word-level + Claude conservador + jump cut.

Pra cada corte_NN_*.mp4 ja gerado pelo 04_cortar.py:
  1. Re-transcreve com faster-whisper + word_timestamps=True
  2. Envia palavras com timestamps pro Claude (postura conservadora)
  3. Claude devolve intervalos pra REMOVER (silencios >3s, fillers extremos, problemas tecnicos)
  4. Aplica jump cut via ffmpeg filter_complex select/aselect
  5. Salva como corte_NN_<slug>_polido.mp4 na mesma pasta

Uso: uv run py scripts/04b_polir.py outputs/<stem>_blocos.json

Custo estimado: ~$0.10-0.15/live (depende do tamanho dos cortes)
"""
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

# Fix Windows: adiciona DLLs do CUDA ao path (igual 02_transcribe.py)
if os.name == "nt":
    venv_nvidia = Path(__file__).parent.parent / ".venv" / "Lib" / "site-packages" / "nvidia"
    for sub in ["cublas", "cudnn"]:
        bin_path = venv_nvidia / sub / "bin"
        if bin_path.exists():
            os.add_dll_directory(str(bin_path))

import json
import subprocess
from faster_whisper import WhisperModel
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = [a for a in sys.argv[1:] if a.startswith("--")]
only_bloco = None
for f in flags:
    if f.startswith("--bloco="):
        only_bloco = int(f.split("=", 1)[1])
# --reaplicar: reusa os intervalos já salvos no polimento.json e só re-aplica o
# jump cut aos cortes (sem whisper, sem API). Útil após re-cortar (ex: mudou o zoom),
# já que os intervalos são por tempo/áudio e não mudam com o enquadramento.
reaplicar = "--reaplicar" in flags

input_arg = args[0] if args else str(ROOT / "outputs" / "live_teste_blocos.json")
BLOCOS_JSON = Path(input_arg)
stem = BLOCOS_JSON.stem.replace("_blocos", "")
CORTES_DIR = ROOT / "outputs" / "cortes" / stem
OUT_JSON = ROOT / "outputs" / f"{stem}_polimento.json"
WORDS_JSON = ROOT / "outputs" / f"{stem}_words.json"  # do 02_transcribe: evita re-transcrever
DEBUG_DIR = ROOT / "outputs" / "_debug"

# Devem casar com os paddings do 04_cortar.py (pra mapear timestamp global -> relativo ao corte)
PADDING_INICIO_S = 1.0
PADDING_FIM_S    = 2.0

PROMPT_SISTEMA = """Você é um editor de vídeo do canal Missão em Cortes.

Recebe a transcrição word-level (cada linha: [start-end] palavra) de um corte.
Sua tarefa: identificar TRECHOS pra REMOVER que melhorem o fluxo SEM perder contexto.

CRITÉRIOS (SEJA CONSERVADOR — prefira deixar passar a cortar demais):
1. Silêncios > 3 segundos detectáveis pela ausência de palavras na transcrição (problemas técnicos, hesitações longas, pausas pra ler tela)
2. Problemas técnicos óbvios ditos pelo speaker ("ah, espera, deixa eu arrumar a câmera", "sumiu o som", "a internet caiu")
3. Cadeias longas de fillers que atrapalham ("éééé éééé éééé éééé", "hmmm hmmm hmmm" prolongados)
4. Trechos onde o speaker está visivelmente procurando conteúdo sem falar nada relevante (rolando feed, abrindo link)

NUNCA REMOVA:
- Pausas curtas (<3s) — fazem parte do ritmo
- Fillers naturais isolados ("né", "tá", "então") — humanizam
- Estrutura argumentativa, mesmo que com repetições estilísticas
- Os primeiros 30s do corte (podem ser cold open, importantes pro gancho)
- Frases incompletas que continuam logo em seguida

FORMATO DE RESPOSTA — JSON PURO, NADA MAIS:
- Resposta começa com { e termina com }
- Sem markdown, sem comentários, sem texto antes ou depois
- Apenas UM objeto JSON na resposta

Schema:
{
  "intervalos_remover": [
    {"t_inicio": 45.2, "t_fim": 52.8, "motivo": "silêncio de 7s arrumando câmera"},
    {"t_inicio": 312.0, "t_fim": 318.5, "motivo": "rolando feed sem falar"}
  ]
}

REGRAS DA LISTA:
- Inclua APENAS intervalos que você EFETIVAMENTE quer remover
- NÃO inclua intervalos com motivo "ignorar", "manter", "abaixo do limiar" ou similares — se decidiu não cortar, simplesmente OMITA da lista
- Se nada precisar ser removido, retorne {"intervalos_remover": []}
- Timestamps são FLOATS em segundos, relativos ao INÍCIO do corte (não do vídeo original)
- NÃO invente intervalos
"""

client = Anthropic()

# Whisper carregado sob demanda: só é preciso no fallback (quando falta o words.json)
_model = None


def get_model():
    global _model
    if _model is None:
        print("Carregando whisper medium (word-level)...")
        _model = WhisperModel("medium", device="cuda", compute_type="int8_float16")
    return _model


def hhmmss_para_segundos(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def duracao_video(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True
    ).stdout.strip()
    return float(out)


def transcrever_word_level(video_path):
    segments, info = get_model().transcribe(
        str(video_path),
        language="pt",
        vad_filter=True,
        beam_size=2,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    palavras = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                palavras.append({
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                })
    return palavras, info.duration


def palavras_para_texto(palavras):
    return "\n".join(f"[{w['start']:7.2f}-{w['end']:7.2f}] {w['word']}" for w in palavras)


def palavras_do_corte(bloco, corte):
    """Devolve (palavras_relativas_ao_corte, duracao_s).

    Reaproveita os word-timestamps globais do 02_transcribe (words.json), fatiando
    pelo intervalo do bloco e remapeando os tempos pra relativos ao início do corte.
    Sem o words.json, cai pro fallback de re-transcrever o corte com whisper.

    Obs: assume que o corte_NN.mp4 não foi cortado/encurtado manualmente (CapCut com
    zoom mantém o tempo alinhado; trim manual desalinharia — nesse caso apague o
    words.json pra forçar a re-transcrição).
    """
    dur = duracao_video(corte)

    if WORDS_JSON.exists():
        with WORDS_JSON.open(encoding="utf-8") as f:
            todas = json.load(f).get("words", [])
        inicio_s = max(0, hhmmss_para_segundos(bloco["timestamp_inicio"]) - PADDING_INICIO_S)
        fim_s    = hhmmss_para_segundos(bloco["timestamp_fim"]) + PADDING_FIM_S
        palavras = [
            {"word": w["word"],
             "start": max(0.0, w["start"] - inicio_s),
             "end":   max(0.0, w["end"] - inicio_s)}
            for w in todas if inicio_s <= w["start"] < fim_s
        ]
        print(f"  {len(palavras)} palavras reaproveitadas do words.json (sem re-transcrever)")
        return palavras, dur

    print(f"  words.json ausente — re-transcrevendo o corte (fallback)")
    palavras, _ = transcrever_word_level(corte)
    return palavras, dur


PALAVRAS_FILTRO = ("ignorar", "manter", "abaixo do limiar", "abaixo do limite",
                   "pequeno demais", "dentro do limite", "limítrofe")


def chamar_claude(palavras, duracao, bloco_id):
    texto = palavras_para_texto(palavras)
    user_msg = (
        f"Duração total do corte: {duracao:.1f} segundos\n"
        f"Número de palavras transcritas: {len(palavras)}\n\n"
        f"Transcrição word-level:\n{texto}\n\n"
        "Identifique intervalos pra remover seguindo os critérios do sistema."
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=PROMPT_SISTEMA,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0].strip()
    # Extrai o PRIMEIRO objeto JSON válido a partir do primeiro '{', ignorando
    # texto/objetos extras que o modelo às vezes adiciona depois (ex: ele "pensa em
    # voz alta" e cospe outro JSON). raw_decode para no fim do 1º objeto completo.
    start = raw.find("{")
    try:
        if start == -1:
            raise json.JSONDecodeError("nenhum '{' na resposta", raw, 0)
        data, _ = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError as e:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        dump = DEBUG_DIR / f"raw_polimento_{stem}_b{bloco_id:02d}.txt"
        dump.write_text(raw, encoding="utf-8")
        raise RuntimeError(f"JSON inválido: {e}. Raw salvo em {dump}")

    intervalos = data.get("intervalos_remover", [])
    # Filtra defensivamente intervalos que o LLM marcou como "ignorar/manter"
    filtrados = [
        iv for iv in intervalos
        if not any(p in iv.get("motivo", "").lower() for p in PALAVRAS_FILTRO)
    ]
    descartados = len(intervalos) - len(filtrados)
    if descartados:
        print(f"  ({descartados} intervalo(s) descartados por motivo 'ignorar/manter')")
    return filtrados, response.usage


def aplicar_jumpcut(input_mp4, output_mp4, intervalos):
    if not intervalos:
        # Sem cortes: copia direto (rápido, sem reencode)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(input_mp4), "-c", "copy",
             "-loglevel", "warning", str(output_mp4)],
            check=True
        )
        return

    parts = [f"between(t,{iv['t_inicio']:.3f},{iv['t_fim']:.3f})" for iv in intervalos]
    expr = "not(" + "+".join(parts) + ")"
    fc = (
        f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[v];"
        f"[0:a]aselect='{expr}',asetpts=N/SR/TB[a]"
    )
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(input_mp4),
        "-filter_complex", fc,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23",
        "-b:v", "0", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        "-loglevel", "warning",
        str(output_mp4),
    ], check=True)


def encontrar_corte(bloco_id):
    for p in CORTES_DIR.glob(f"corte_{bloco_id:02d}_*.mp4"):
        if "_polido" not in p.stem:
            return p
    return None


with BLOCOS_JSON.open(encoding="utf-8") as f:
    data = json.load(f)

# Se já existe polimento prévio, carrega pra preservar blocos não tocados
if OUT_JSON.exists():
    with OUT_JSON.open(encoding="utf-8") as f:
        polimento = json.load(f)
else:
    polimento = {"blocos": []}

# Intervalos já salvos, por id (usado pelo --reaplicar)
salvos_por_id = {pb["id"]: pb.get("intervalos_remover", []) for pb in polimento["blocos"]}

if reaplicar and not salvos_por_id:
    print(f"[!] --reaplicar sem polimento.json salvo em {OUT_JSON.name}. "
          f"Rode primeiro sem --reaplicar pra gerar os intervalos.")
    sys.exit(1)

if only_bloco is not None and not reaplicar:
    print(f"Modo --bloco={only_bloco}: processando só esse bloco")
    polimento["blocos"] = [b for b in polimento["blocos"] if b["id"] != only_bloco]

total_in_tokens = 0
total_out_tokens = 0

for b in data["blocos"]:
    if only_bloco is not None and b["id"] != only_bloco:
        continue
    print(f"\n[Bloco {b['id']}] {b['tema']}")
    corte = encontrar_corte(b["id"])
    if not corte:
        print(f"  AVISO: corte_{b['id']:02d}_*.mp4 nao encontrado em {CORTES_DIR}")
        continue

    if reaplicar:
        if b["id"] not in salvos_por_id:
            print(f"  AVISO: bloco {b['id']} não está no polimento.json salvo — pulando")
            continue
        intervalos = salvos_por_id[b["id"]]
        dur = duracao_video(corte)
        print(f"  Reaplicando {len(intervalos)} intervalo(s) salvos (sem API)")
    else:
        palavras, dur = palavras_do_corte(b, corte)
        print(f"  corte tem {dur:.1f}s de vídeo")

        print(f"  Chamando Claude (conservador)...")
        try:
            intervalos, usage = chamar_claude(palavras, dur, b["id"])
            total_in_tokens += usage.input_tokens
            total_out_tokens += usage.output_tokens
        except Exception as e:
            print(f"  ERRO Claude: {e}. Pulando este bloco.")
            continue

    if not intervalos:
        print(f"  Nenhum trecho pra cortar — copiando original")
    else:
        tempo_removido = sum(iv["t_fim"] - iv["t_inicio"] for iv in intervalos)
        print(f"  {len(intervalos)} trechos ({tempo_removido:.1f}s, {tempo_removido/dur*100:.1f}% do corte):")
        for iv in intervalos:
            print(f"    [{iv['t_inicio']:.1f}-{iv['t_fim']:.1f}] {iv['motivo']}")

    saida = corte.with_name(corte.stem + "_polido.mp4")
    print(f"  Aplicando jump cut -> {saida.name}")
    try:
        aplicar_jumpcut(corte, saida, intervalos)
        size_mb = saida.stat().st_size / (1024 * 1024)
        print(f"  OK polido: {saida.name} ({size_mb:.1f} MB)")
    except Exception as e:
        print(f"  ERRO ffmpeg: {e}")
        continue

    if not reaplicar:
        polimento["blocos"].append({
            "id": b["id"],
            "tema": b["tema"],
            "corte_original": corte.name,
            "corte_polido": saida.name,
            "duracao_original_s": dur,
            "tempo_removido_s": sum(iv["t_fim"] - iv["t_inicio"] for iv in intervalos),
            "intervalos_remover": intervalos,
        })

if reaplicar:
    print(f"\nOK Jump cut reaplicado a partir de {OUT_JSON.name} (sem chamada de API)")
else:
    OUT_JSON.write_text(json.dumps(polimento, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nOK Polimento salvo em {OUT_JSON}")
    custo_usd = (total_in_tokens / 1_000_000) * 3 + (total_out_tokens / 1_000_000) * 15
    print(f"Custo total: input {total_in_tokens:,} tok · output {total_out_tokens:,} tok (~${custo_usd:.2f})")
