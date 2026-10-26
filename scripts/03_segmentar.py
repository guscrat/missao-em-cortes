"""Lê a transcrição, manda pro Claude e gera JSON com blocos temáticos.

Uso: uv run py scripts/03_segmentar.py <stem> [--reaproveitar]

Os tempos do LLM não são confiáveis em live longa (na de 3h20 do Renan erraram ~10 min na
segunda metade). Por isso cada ponta é ANCORADA PELO TEXTO: a frase literal que o LLM cita
(abertura/encerramento do bloco, frase do cold open, gancho/frase_final do Short) é procurada
no words.json perto do tempo dito (_fronteira.ancorar), e só depois encaixada no fim de frase
+ pausa mais perto (_fronteira.encaixar).

A resposta bruta do LLM fica em segmentacao_bruta.json. --reaproveitar refaz a validação a
partir dela, sem chamar a API ($0): útil quando o 03 barrou a resposta por timestamp inválido.
"""
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from dotenv import load_dotenv
import _custo
import _fronteira as fr
from _paths import achar_pasta, stem_de
from _eventos import evento, upsert_bloco

load_dotenv()

ROOT = Path(__file__).parent.parent
PROMPT = ROOT / "prompts" / "segmentacao.md"
MODELO = "claude-sonnet-4-6"
DESVIO_AVISO_S = 60   # âncora longe disso do tempo do LLM: avisa (o LLM errou o relógio)

args = [a for a in sys.argv[1:] if not a.startswith("--")]
reaproveitar = "--reaproveitar" in sys.argv[1:]
input_arg = args[0] if args else "live_teste"
PASTA = achar_pasta(input_arg)
stem = stem_de(PASTA)
INPUT = PASTA / "transcricao.txt"
OUTPUT = PASTA / "blocos.json"
BRUTA = PASTA / "segmentacao_bruta.json"


JANELA_MIN = 60        # live maior que isso é segmentada em janelas (o LLM perde o relógio)
FOLGA_JANELA_MIN = 10  # até 70 min: uma chamada só
AVANCO_VAZIO_MIN = 45  # janela sem bloco: anda isso e tenta a próxima
RABO_JANELA_MIN = 3    # bloco que termina a menos disso do fim de uma janela (não a última)


def linhas_com_tempo(transcricao: str) -> list[tuple[float, str]]:
    """[(segundos, linha)] da transcrição '[HH:MM:SS] Speaker: texto'."""
    out = []
    for linha in transcricao.splitlines():
        if linha.startswith("[") and "]" in linha:
            try:
                out.append((ts_s(linha[1:linha.index("]")]), linha))
            except ValueError:
                pass
    return out


def janelas(linhas: list[tuple[float, str]], inicio: float) -> tuple[str, float, float, bool]:
    """(texto, ini, fim, é_a_última) da janela que começa em `inicio`."""
    total = linhas[-1][0] if linhas else 0.0
    ultima = total - inicio <= (JANELA_MIN + FOLGA_JANELA_MIN) * 60
    fim = total + 1 if ultima else inicio + JANELA_MIN * 60
    texto = "\n".join(l for t, l in linhas if inicio <= t < fim)
    return texto, inicio, min(fim, total), ultima


def pedir_blocos(client, prompt_sistema: str, texto: str, ini: float, fim: float,
                 ultima: bool, n_janela: int) -> tuple[dict, dict]:
    """Uma chamada (uma janela). O prompt de sistema vai pro cache: as janelas saem em
    sequência, < 5 min entre uma e outra. (data, uso)."""
    contexto = "" if n_janela == 1 and ultima else (
        f"TRECHO DA LIVE: de {fr.segundos_para_ts(ini)[:8]} a {fr.segundos_para_ts(fim)[:8]} "
        f"(a live é longa e é analisada em partes, em sequência).\n"
        + ("Este é o ÚLTIMO trecho.\n" if ultima else
           "REGRA DO TRECHO: só devolva blocos que TERMINAM dentro deste trecho. O último "
           "assunto, se ainda não terminou quando o trecho acaba, NÃO entra: ele será analisado "
           "inteiro no próximo trecho, que começa onde terminar o seu último bloco.\n")
        + "\n")
    response = client.messages.create(
        model=MODELO,
        max_tokens=12000,
        system=[{"type": "text", "text": prompt_sistema, "cache_control": {"type": "ephemeral"}}],
        messages=[
            {
                "role": "user",
                "content": (
                    f"{contexto}Transcrição da live a ser analisada:\n\n{texto}\n\n"
                    "INSTRUÇÃO CRÍTICA: Responda APENAS com o JSON conforme o schema "
                    "especificado no prompt do sistema. Não adicione markdown (```), "
                    "não adicione texto antes ou depois. Comece a resposta diretamente "
                    "com { e termine com }."
                ),
            },
        ],
    )
    return extrair_json(response.content[0].text.strip()), _custo.uso(response, MODELO)


def chamar_llm() -> dict:
    """Segmenta a live inteira: janela a janela, a próxima começando no fim do último bloco
    da anterior (nenhum assunto corta na emenda). Live até 70 min: uma chamada."""
    from anthropic import Anthropic
    prompt_sistema = PROMPT.read_text(encoding="utf-8")
    transcricao = INPUT.read_text(encoding="utf-8")
    linhas = linhas_com_tempo(transcricao)
    words_json = PASTA / "words.json"
    palavras = (json.loads(words_json.read_text(encoding="utf-8")).get("words", [])
                if words_json.exists() else [])
    print(f"Transcrição: {len(transcricao):,} caracteres (~{len(transcricao)//4:,} tokens)")
    client = Anthropic()  # pega ANTHROPIC_API_KEY do .env
    blocos, observacoes, usos = [], [], []
    cursor, n = 0.0, 0
    while True:
        n += 1
        texto, ini, fim, ultima = janelas(linhas, cursor)
        print(f"Chamando Claude (trecho {n}: {fr.segundos_para_ts(ini)[:8]} → "
              f"{fr.segundos_para_ts(fim)[:8]})...")
        data, uso = pedir_blocos(client, prompt_sistema, texto, ini, fim, ultima, n)
        usos.append(uso)
        print(f"  {len(data.get('blocos', []))} bloco(s) · ~${uso['custo_usd']:.2f}")
        novos = [b for b in data.get("blocos", []) if inicio_s(b) >= ini - 60]
        blocos += novos
        if data.get("observacoes"):
            observacoes.append(f"[trecho {n}] {data['observacoes']}")
        if ultima:
            break
        fins = []
        for b in list(novos):   # fim REAL do bloco (âncora pelo texto), não o relógio do LLM
            t = inicio_s({"timestamp_inicio": b.get("timestamp_fim")})
            if t == float("inf"):
                continue
            t = fr.ancorar(palavras, b.get("frase_de_encerramento") or "", t, "fim") or t
            if fim - t < RABO_JANELA_MIN * 60:
                # colado no fim da janela: o assunto provavelmente não acabou (o LLM fecha
                # mesmo assim). Sai daqui e é analisado inteiro na próxima janela.
                blocos.remove(b)
                print(f"  (bloco '{b.get('tema')}' termina colado no fim do trecho — vai pro próximo)")
                continue
            fins.append(t)
        proximo = max(fins) if fins and max(fins) > cursor + 5 * 60 else cursor + AVANCO_VAZIO_MIN * 60
        cursor = min(proximo, fim)
    for i, b in enumerate(blocos, 1):
        b["id"] = i
    uso = _custo.somar(usos)
    print(f"Custo: input {uso['tokens_in']:,} tok · output {uso['tokens_out']:,} tok "
          f"(~${uso['custo_usd']:.2f}){_custo.resumo(uso)} · {n} chamada(s)")
    evento(stem, "03_segmentar", "llm", agente="editor", **uso, mensagem=f"{MODELO} ({n} trecho(s))")
    data = {"blocos": blocos, "observacoes": " ".join(observacoes)}
    # a resposta paga fica guardada antes de qualquer ajuste (--reaproveitar parte dela)
    BRUTA.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def extrair_json(raw: str) -> dict:
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

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        dump = PASTA / "raw_response.txt"
        dump.write_text(raw, encoding="utf-8")
        raise RuntimeError(f"JSON inválido: {e}. Raw salvo em {dump}")
    return data


def ts_s(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def inicio_s(b: dict) -> float:
    try:
        return ts_s(b["timestamp_inicio"])
    except (ValueError, AttributeError, KeyError):
        return float("inf")   # ilegível: entra, e a validação lá embaixo reprova


if reaproveitar:
    if not BRUTA.exists():
        sys.exit(f"[!] --reaproveitar sem {BRUTA.name} — rode o step 3 sem a flag.")
    data = json.loads(BRUTA.read_text(encoding="utf-8"))
    print(f"Reaproveitando {BRUTA.name} (sem chamar a API, $0)")
else:
    data = chamar_llm()

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
dur_video = None
palavras = []
words_json = PASTA / "words.json"
if words_json.exists():
    with words_json.open(encoding="utf-8") as f:
        w = json.load(f)
    dur_video, palavras = w.get("duration"), w.get("words", [])
else:
    print("[aviso] sem words.json: os tempos ficam os do LLM (sem âncora nem encaixe)")


def ancorar_trecho(nome: str, trecho: dict, ini: float, fim: float,
                   frase_ini: str | None, frase_fim: str | None) -> tuple[float, float]:
    """Troca o tempo do LLM pelo tempo real da frase citada (quando acha). Guarda o
    desvio em trecho['ancora'] e avisa quando o LLM errou feio o relógio."""
    if not palavras:
        return ini, fim
    a = fr.ancorar(palavras, frase_ini or "", ini, "inicio")
    z = fr.ancorar(palavras, frase_fim or "", fim, "fim")
    if a is not None and z is not None and z <= a:   # âncoras trocadas: confia em nenhuma
        a = z = None
    novo_ini, novo_fim = a if a is not None else ini, z if z is not None else fim
    trecho["ancora"] = {"inicio": a is not None, "fim": z is not None,
                        "desvio_s": [round(novo_ini - ini, 1), round(novo_fim - fim, 1)]}
    for ponta, d in zip(("início", "fim"), trecho["ancora"]["desvio_s"]):
        if abs(d) > DESVIO_AVISO_S:
            avisos.append(f"{nome}: tempo de {ponta} do LLM errado em {d / 60:+.1f}min — "
                          f"ancorado pelo texto")
    return novo_ini, novo_fim


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


def gravar_duracao(b: dict, ini: float, fim: float) -> None:
    b["duracao_minutos"] = round((fim - ini) / 60, 1)    # a real, não o chute do LLM
    b["faixa_duracao"] = fr.faixa((fim - ini) / 60)


erros, avisos = [], []
validos = []  # (id, ini, fim, bloco) dos blocos parseáveis, pro check de sobreposição
for b in data["blocos"]:
    bid = b["id"]
    try:
        ini, fim = ts_s(b["timestamp_inicio"]), ts_s(b["timestamp_fim"])
    except (ValueError, AttributeError):
        erros.append(f"bloco {bid}: timestamp ilegível "
                     f"({b['timestamp_inicio']!r} -> {b['timestamp_fim']!r})")
        continue
    ini, fim = ancorar_trecho(f"bloco {bid}", b, ini, fim,
                              b.get("frase_de_abertura"), b.get("frase_de_encerramento"))
    if fim <= ini:
        erros.append(f"bloco {bid}: fim <= início ({b['timestamp_inicio']} -> {b['timestamp_fim']})")
        continue

    # A faixa só restringe o encaixe se o bloco já está dentro dela (senão o encaixe
    # não acharia ponto natural perto e ficaria pior)
    dur_llm = fim - ini
    ini, fim, e = encaixar_trecho(
        b, ini, fim, fr.JANELA_BLOCO_S,
        fr.LONGO_MIN * 60 if dur_llm >= fr.LONGO_MIN * 60 else None,
        fr.LONGO_MAX * 60 if dur_llm <= fr.LONGO_MAX * 60 else None)
    for ponta in ("inicio", "fim"):
        if not e[f"{ponta}_ok"]:
            avisos.append(f"bloco {bid}: sem ponto natural de {ponta} a até "
                          f"{fr.JANELA_BLOCO_S:.0f}s (o revisor confere)")
    validos.append((bid, ini, fim, b))

    gravar_duracao(b, ini, fim)
    if b["faixa_duracao"] == "fora":
        avisos.append(f"bloco {bid}: duração de {b['duracao_minutos']:.1f}min (faixa é "
                      f"{fr.LONGO_MIN:.0f}-{fr.LONGO_MAX:.0f}min)")
    if dur_video and fim > dur_video + 5:
        erros.append(f"bloco {bid}: fim ({b['timestamp_fim']}) passa do fim do vídeo "
                     f"({dur_video / 60:.1f}min)")

    # Short: ideia completa (gancho → desenvolvimento → frase de impacto), até 3 min.
    # Problema no short não derruba o bloco: o 10 volta pro cold open.
    sh = b.get("short")
    sh_ok = None   # (ini, fim) do short válido: reserva pro cold open
    if sh:
        try:
            sh_i, sh_f = ts_s(sh["timestamp_inicio"]), ts_s(sh["timestamp_fim"])
        except (ValueError, AttributeError, KeyError):
            sh_i = sh_f = 0.0
        if sh_f > sh_i:
            sh_i, sh_f = ancorar_trecho(f"bloco {bid} (short)", sh, sh_i, sh_f,
                                        sh.get("gancho"), sh.get("frase_final"))
        if sh_f <= sh_i:
            avisos.append(f"bloco {bid}: short com timestamps inválidos — o 10 usa o cold open")
            b.pop("short")
        else:
            sh_i, sh_f, e = encaixar_trecho(sh, sh_i, sh_f, fr.JANELA_TRECHO_S, 20, fr.SHORT_MAX_S)
            sh["duracao_segundos"] = round(sh_f - sh_i, 1)
            if not (ini - 1 <= sh_i < sh_f <= fim + 1):
                avisos.append(f"bloco {bid}: short fora do bloco — o 10 usa o cold open")
                b.pop("short")
            elif sh_f - sh_i > fr.SHORT_MAX_S:
                avisos.append(f"bloco {bid}: short de {sh_f - sh_i:.0f}s passa de 3 min — "
                              f"o 10 usa o cold open")
                b.pop("short")
            else:
                sh_ok = (sh_i, sh_f)
                if not e["fim_ok"]:
                    avisos.append(f"bloco {bid}: short sem fim de frase perto do tempo do LLM")

    co = b.get("cold_open")
    if co:
        try:
            co_i, co_f = ts_s(co["timestamp_inicio"]), ts_s(co["timestamp_fim"])
        except (ValueError, AttributeError, KeyError):
            erros.append(f"bloco {bid}: cold_open com timestamps ilegíveis")
            continue
        co_i, co_f = ancorar_trecho(f"bloco {bid} (cold open)", co, co_i, co_f,
                                    co.get("frase"), co.get("frase"))
        co_i, co_f, _ = encaixar_trecho(co, co_i, co_f, fr.JANELA_TRECHO_S, 12, 35)
        if not (ini <= co_i < co_f <= fim and 8 <= co_f - co_i <= 45) and sh_ok:
            # cold open fora do bloco ou desproporcional: os primeiros ~22s do Short (o
            # gancho dele), encaixados em fim de frase
            co_i, co_f, _ = encaixar_trecho(co, sh_ok[0], sh_ok[0] + 22, fr.JANELA_TRECHO_S, 12, 35)
            co["frase"] = " ".join(w["word"] for w in palavras if co_i <= w["start"] < co_f)
            avisos.append(f"bloco {bid}: cold open do LLM não serviu — usei o gancho do Short")
        co["duracao_segundos"] = round(co_f - co_i, 1)
        if not (ini <= co_i < co_f <= fim):
            erros.append(f"bloco {bid}: cold_open fora do intervalo do bloco")
        elif not 8 <= co_f - co_i <= 45:
            avisos.append(f"bloco {bid}: cold_open de {co_f - co_i:.0f}s (alvo é 15-30s)")

descartados = []


def descartar(b: dict, motivo: str) -> None:
    """Tira o bloco do blocos.json (fica listado em 'descartados', com o motivo)."""
    data["blocos"].remove(b)
    descartados.append({"id": b["id"], "tema": b.get("tema"), "titulo": b.get("titulo_sugerido"),
                        "timestamp_inicio": b.get("timestamp_inicio"),
                        "timestamp_fim": b.get("timestamp_fim"), "motivo": motivo})
    avisos.append(f"bloco {b['id']} descartado: {motivo}")


# Blocos vizinhos com a mesma fronteira: o encaixe puxa o fim de um pra frente e o início
# do outro pra trás. Sobreposição curta → o anterior termina no último fim de frase antes
# do início do seguinte. Sobreposição grande = o mesmo assunto em dois blocos (acontece na
# emenda das janelas): fica o de maior score.
validos.sort(key=lambda v: v[1])
vivos = []
for v in validos:
    if not vivos or v[1] >= vivos[-1][2]:
        vivos.append(v)
        continue
    id_a, ini_a, fim_a, b_a = vivos[-1]
    id_b, ini_b, fim_b, b_b = v
    novo = fr.ajustar_fim(palavras, ini_b, fr.JANELA_BLOCO_S, maximo=ini_b) if palavras else None
    if fim_a - ini_b <= fr.JANELA_BLOCO_S and novo is not None and novo > ini_a:
        b_a["timestamp_fim"] = fr.segundos_para_ts(novo)
        gravar_duracao(b_a, ini_a, novo)
        vivos[-1] = (id_a, ini_a, novo, b_a)
        vivos.append(v)
    elif (b_b.get("score_potencial") or 0) > (b_a.get("score_potencial") or 0):
        descartar(b_a, f"repete o assunto do bloco {id_b} (sobreposição de "
                       f"{(fim_a - ini_b) / 60:.1f}min), que tem score maior")
        vivos[-1] = v
    else:
        descartar(b_b, f"repete o assunto do bloco {id_a} (sobreposição de "
                       f"{(fim_a - ini_b) / 60:.1f}min), que tem score maior")

# Mínimo de 8 min (anúncio no meio depois da monetização): com os tempos reais (âncora pelo
# texto), bloco curto sai. O LLM não sente duração; a regra é do código.
for b in list(data["blocos"]):
    if b in [v[3] for v in vivos] and (b.get("duracao_minutos") or 0) < fr.LONGO_MIN:
        descartar(b, f"{b['duracao_minutos']:.1f}min com os tempos reais (mínimo é "
                     f"{fr.LONGO_MIN:.0f}min)")
fora = {d["id"] for d in descartados}
erros = [e for e in erros if not any(e.startswith(f"bloco {i}:") for i in fora)]
avisos = [a for a in avisos if a.startswith(tuple(f"bloco {i} descartado" for i in fora))
          or not any(a.startswith((f"bloco {i}:", f"bloco {i} (")) for i in fora)]
if descartados:
    data["descartados"] = descartados

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
             f"corrija {BRUTA.name} à mão e rode com --reaproveitar ($0), ou rode o step 3 "
             f"de novo (paga outra chamada).")

# ids em ordem de tempo e sem buraco (viram corte_01, corte_02... nos arquivos)
data["blocos"].sort(key=lambda b: ts_s(b["timestamp_inicio"]))
for i, b in enumerate(data["blocos"], 1):
    b["id"] = i
OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
# duração real de cada corte no banco: o Analista (12) compara retenção por faixa
for b in data["blocos"]:
    upsert_bloco(stem, b["id"], tema=b.get("tema"), titulo=b.get("titulo_sugerido"),
                 texto_thumb=b.get("texto_thumb"), score=b.get("score_potencial"),
                 duracao_min=b.get("duracao_minutos"))
print("Durações: " + " · ".join(f"{b['id']}: {b['duracao_minutos']:.1f}min "
                                f"({b.get('faixa_duracao') or '?'})" for b in data["blocos"]))
print(f"OK Salvo em {OUTPUT}")
