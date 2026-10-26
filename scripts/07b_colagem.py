"""Thumb "colagem" (estilo canal de react) — 3 variantes a/b/c por bloco pro "Testar e comparar".

Layout e fontes de imagem: ver _colagem.py. Por bloco:
  1. fila de frames do 07 (thumbs/candidatos_NN.json) → até 6 frames com rosto bom do apresentador
  2. cenas da tela compartilhada da live (caixa de react ou frame sem o apresentador)
  3. Haiku (visão, ~US$ 0.0005) ordena as expressões e escolhe cena do assunto + de contexto,
     descrevendo cada uma só pelo que está escrito nela (nunca reconhece rosto)
  4. faltou cena: completa com o banco de personagens citados no bloco (assets/personagens/)
  5. editor (opus, ~US$ 0.03) escreve 3 textos de 2 linhas (*amarelo*, [nome] em vermelho);
     o nome só sai se for de quem leva o círculo/seta
  6. rembg recorta o apresentador; a = círculo, b = seta, c = outra expressão/texto
Sem rosto bom, sem recorte ou sem 2 cenas → o bloco fica com a thumb do template atual (07).

Modo (config/thumb.json → "colagem"):
  - "teste": grava em thumbs/colagem/ e NÃO mexe nas thumbs que sobem
  - "ab" (agora): com --ab, só as variantes b/c viram thumb_NN_b/c (a fica no template do 07),
    pro "Testar e comparar" do Studio medir template x colagem (resultado: 16_thumb_ab.py);
    o crédito da foto do banco entra na descrição
  - "padrao": com --aplicar, copia pra thumbs/thumb_NN_a/b/c.png e põe o crédito da foto do
    banco na descrição do bloco (descricoes.txt)
Nunca mexe em bloco agendado/publicado/arquivado (nem em teste), a não ser com --saida=<pasta>
(prévia fora do outputs/).

Uso: uv run py scripts/07b_colagem.py <stem> [--bloco=N] [--sem-llm] [--sem-editor] [--aplicar | --ab] [--saida=DIR]
  --sem-editor: texto = texto_thumb do bloco (o 11 usa pra refazer a colagem depois de reescrever)
  Com --bloco=N, sai com 2 se a colagem do bloco não saiu (ou não foi aplicada).
Custo: ~US$ 0.03 por bloco (~US$ 0.15 por live, medido em 22/10/2026). Logado com agente="editor".
"""
import json
import shutil
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import _colagem as col
import _custo
import _editor
import _grafias
import _thumb_rosto as tr
from _descricoes import ler_descricoes, trocar_creditos
from _eventos import evento, ler_bloco
from _legenda import hhmmss_para_segundos, palavras_na_janela
from _paths import achar_pasta, stem_de

ROOT = Path(__file__).parent.parent
CANAIS = ROOT / "config" / "canais.json"
NAO_MEXER = {"agendado", "publicado", "arquivado"}
LETRAS = ("a", "b", "c")
MARCADORES = {"a": "circulo", "b": "seta", "c": "circulo"}
LETRAS_AB = ("b", "c")              # modo ab: a fica no template (07)


def apresentador(stem: str) -> str:
    """Nome do canal pelo prefixo do stem (ex.: arthur → 'Mamãefalei (Arthur do Val)'): a foto
    dele mesmo não vira cena."""
    try:
        canais = json.loads(CANAIS.read_text(encoding="utf-8"))["canais"]
    except (OSError, ValueError, KeyError):
        return ""
    prefixo = stem.split("_", 1)[0]
    return next((c["nome"] for c in canais if c.get("prefixo") == prefixo), "")


def ler_fila(pasta: Path, bid: int) -> dict | None:
    try:
        return json.loads((pasta / "thumbs" / f"candidatos_{bid:02d}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def fila_em_memoria(pasta: Path, bid: int, corte: Path) -> dict:
    """Live processada antes da fila do 07 existir: ranqueia aqui, sem gravar nada."""
    cold = next(iter(sorted((pasta / "cortes").glob(f"cold_{bid:02d}_*.mp4"))), None)
    cands = tr.ranquear(cold, corte)
    overlays = tr.detectar_overlays(corte, [c["rosto"] for c in cands if c.get("rosto")])
    return {"candidatos": tr.rebaixar_manchas(cands, overlays), "overlays": overlays}


def frame_pil(pasta: Path, cand: dict):
    f = tr.ler_frame(pasta / "cortes" / cand["video"], cand["t"])
    return col._pil(f) if f is not None else None


def corte_do_bloco(pasta: Path, bid: int) -> Path | None:
    ms = [m for m in (pasta / "cortes").glob(f"corte_{bid:02d}_*.mp4") if "_polido" not in m.stem]
    return sorted(ms)[0] if ms else None


def textos(client, stem, b, titulo, transcricao, finais, sem_llm,
           sem_editor=False) -> tuple[list[list[str]], float]:
    """3 textos de 2 linhas. Editor; na falta (sem LLM, --sem-editor, recusa, erro), o
    texto_thumb quebrado (o 11 usa --sem-editor pra refazer com o texto que ele vai reavaliar)."""
    reserva = col.quebrar_em_2(_grafias.corrigir(b.get("texto_thumb") or b.get("tema", "")))
    if sem_llm or sem_editor:
        return [reserva] * 3, 0.0
    try:
        opcoes, resp = _editor.texto_colagem(client, _editor.montar_pedido_colagem(
            titulo, b.get("texto_thumb", ""), *destacada(finais), transcricao))
    except Exception as e:  # noqa: BLE001 — falha do editor não derruba a thumb
        print(f"  [aviso] editor falhou ({type(e).__name__}): usando o texto_thumb")
        return [reserva] * 3, 0.0
    tin, tout, usd = _editor.custo(resp)
    evento(stem, "07b_colagem", "llm", agente="editor", bloco_id=b["id"], tokens_in=tin,
           tokens_out=tout, custo_usd=usd, mensagem=f"{resp.model} (texto colagem)",
           **_custo.cache(resp))
    if not opcoes:
        print("  [aviso] editor sem opção válida: usando o texto_thumb")
        opcoes = [reserva]
    return [opcoes[k % len(opcoes)] for k in range(3)], usd


def escolher_imagens(client, stem, bid, rostos, cenas, tema, sem_llm,
                     pessoas=()) -> tuple[dict, float]:
    if sem_llm or not client:
        return col.escolha_sem_llm(len(rostos), len(cenas)), 0.0
    try:
        escolha, resp = col.escolher(client, rostos, [c["imagem"] for c in cenas], tema, pessoas)
    except Exception as e:  # noqa: BLE001
        print(f"  [aviso] escolha por visão falhou ({type(e).__name__}): ordem da nota")
        return col.escolha_sem_llm(len(rostos), len(cenas)), 0.0
    tin, tout, usd = col.custo(resp)
    evento(stem, "07b_colagem", "llm", agente="editor", bloco_id=bid, tokens_in=tin,
           tokens_out=tout, custo_usd=usd, mensagem=f"{resp.model} (expressão + cenas)",
           **_custo.cache(resp))
    return escolha or col.escolha_sem_llm(len(rostos), len(cenas)), usd


def montar_cenas(escolha: dict, cenas: list[dict], personagens: list[dict]) -> list[dict]:
    """[assunto, contexto]: as escolhidas da live primeiro; o que faltar vem do banco."""
    saida = []
    for chave, desc in (("cena_assunto", "assunto_descricao"), ("cena_contexto", "contexto_descricao")):
        i = escolha[chave]
        if i >= 0:
            img = cenas[i]["imagem"]
            saida.append({"imagem": img, "rosto": col.rosto_de(img), "origem": cenas[i]["origem"],
                          "descricao": escolha.get(desc, "")})
    from PIL import Image
    for p in personagens:
        if len(saida) >= 2:
            break
        saida.append({"imagem": Image.open(col.PERSONAGENS / p["arquivo"]).convert("RGBA"),
                      "rosto": tuple(p["rosto"]) if p.get("rosto") else None,
                      "origem": f"banco: {p['nome']}", "credito": p["credito"],
                      "descricao": f"foto de {p['nome']}"})
    return saida


def destacada(finais: list[dict]) -> tuple[str, str]:
    """(descrição da cena com círculo/seta, da outra). O marcador vai no rosto da cena 1; sem
    rosto nela, no da cena 2 (mesma regra do col.compor)."""
    a, b = finais
    if a["rosto"] or not b["rosto"]:
        return (a["descricao"] if a["rosto"] else ""), b["descricao"]
    return b["descricao"], a["descricao"]


def processar_bloco(client, pasta, stem, b, titulo, transcricao, saida_dir, sem_llm, excluir,
                    sem_editor=False) -> dict:
    bid, nn = b["id"], f"{b['id']:02d}"
    reg = {"status": "fallback", "custo_usd": 0.0}
    corte = corte_do_bloco(pasta, bid)
    if not corte:
        reg["motivo"] = "sem corte (rode o step 4 antes)"
        return reg
    fila = ler_fila(pasta, bid) or fila_em_memoria(pasta, bid, corte)
    exps = col.expressoes(fila)
    frames = [frame_pil(pasta, c) for c in exps]
    exps = [(c, f) for c, f in zip(exps, frames) if f is not None]
    if not exps:
        reg["motivo"] = "sem frame com rosto bom do apresentador"
        return reg
    cenas = col.cenas_do_video(corte, fila, [f for _, f in exps])
    print(f"  {len(exps)} expressão(ões), {len(cenas)} cena(s) da live")
    rostos = [col.rosto_ampliado(f, tuple(c["rosto"])) for c, f in exps]
    # pessoas citadas (grafia oficial): quem não tem foto no banco ainda pode aparecer numa cena
    # da live com o nome escrito, e o Haiku prefere essa cena
    pessoas = _grafias.citados(col.campos_de_nomes(b), excluir)
    escolha, usd = escolher_imagens(client, stem, bid, rostos, cenas, b.get("tema", ""), sem_llm, pessoas)
    reg["custo_usd"] += usd
    reg["escolha"] = escolha
    finais = montar_cenas(escolha, cenas, col.personagens_do_bloco(b, excluir))
    if len(finais) < 2:
        reg["motivo"] = f"só {len(finais)} cena (sem tela compartilhada útil nem personagem no banco)"
        return reg
    linhas, usd = textos(client, stem, b, titulo, transcricao, finais, sem_llm, sem_editor)
    reg["custo_usd"] += usd

    recortes = {}
    ordem = escolha["expressoes"] + [i for i in range(len(exps)) if i not in escolha["expressoes"]]

    def recorte_de(i):
        if i not in recortes:
            c, f = exps[i]
            recortes[i] = col.recortar(f, tuple(c["rosto"]))
        return recortes[i]

    variantes = {}
    for k, letra in enumerate(LETRAS):
        candidatos = ordem[k % len(escolha["expressoes"]):] + ordem
        i = next((i for i in candidatos if recorte_de(i)), None)
        if i is None:
            reg["motivo"] = "rembg não separou o apresentador em nenhum frame"
            return reg
        recorte, rosto_rel = recortes[i]
        c1, c2 = finais
        img = col.compor(c1["imagem"], c1["rosto"], c2["imagem"], c2["rosto"], recorte, rosto_rel,
                         linhas[k], MARCADORES[letra])
        destino = saida_dir / f"thumb_{nn}_{letra}.png"
        img.save(destino)
        variantes[letra] = {"arquivo": destino.name, "expressao": f"{exps[i][0]['video']} @ {exps[i][0]['t']:.1f}s",
                            "texto": linhas[k], "marcador": MARCADORES[letra]}
        print(f"    {letra}: {' / '.join(linhas[k])} · {MARCADORES[letra]} · {variantes[letra]['expressao']}")
    reg.update(status="ok", variantes=variantes, cenas=[c["origem"] for c in finais],
               creditos=[c["credito"] for c in finais if c.get("credito")])
    reg.pop("motivo", None)
    return reg


def aplicar(pasta: Path, saida_dir: Path, bid: int, reg: dict, letras=LETRAS) -> None:
    """Modo padrão (a/b/c) ou ab (só b/c): a colagem vira a thumb do bloco e o crédito da foto
    entra na descrição."""
    for letra, v in reg["variantes"].items():
        if letra not in letras:
            continue
        shutil.copyfile(saida_dir / v["arquivo"], pasta / "thumbs" / f"thumb_{bid:02d}_{letra}.png")
    desc = pasta / "descricoes.txt"
    if desc.exists():               # troca (não só acrescenta): colagem refeita com outra foto
        texto = desc.read_text(encoding="utf-8")
        desc.write_text(trocar_creditos(texto, bid, reg.get("creditos", [])), encoding="utf-8")


def main(argv: list[str]) -> int:
    pos = [a for a in argv if not a.startswith("--")]
    flags = dict(a[2:].split("=", 1) if "=" in a else (a[2:], True) for a in argv if a.startswith("--"))
    if not pos:
        print(__doc__)
        return 1
    sem_llm, modo_ab = bool(flags.get("sem-llm")), bool(flags.get("ab"))
    aplicar_padrao = bool(flags.get("aplicar")) or modo_ab
    letras = LETRAS_AB if modo_ab else LETRAS
    sem_editor = bool(flags.get("sem-editor"))
    so_bloco = int(flags["bloco"]) if "bloco" in flags else None
    pasta = achar_pasta(pos[0])
    stem = stem_de(pasta)
    previa = "saida" in flags
    saida_dir = Path(flags["saida"]) if previa else pasta / "thumbs" / "colagem"
    if flags.get("aplicar") and modo_ab:
        sys.exit("[!] --aplicar (a/b/c) e --ab (só b/c) não combinam")
    if aplicar_padrao and previa:
        sys.exit("[!] --aplicar/--ab e --saida não combinam (prévia não mexe nas thumbs do bloco)")
    saida_dir.mkdir(parents=True, exist_ok=True)

    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"]
    words = pasta / "words.json"
    todas = json.loads(words.read_text(encoding="utf-8"))["words"] if words.exists() else []
    desc = pasta / "descricoes.txt"
    descricoes = ler_descricoes(desc.read_text(encoding="utf-8")) if desc.exists() else {}
    excluir = apresentador(stem)

    client = None
    if not sem_llm:
        import anthropic
        from dotenv import load_dotenv
        load_dotenv()
        client = anthropic.Anthropic()

    registro_path = saida_dir / "colagem.json"
    try:
        registro = json.loads(registro_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        registro = {}
    total, ok, aplicados = 0.0, 0, 0
    print(f"Thumb colagem de '{stem}' → {saida_dir}" + (" (aplicando em b/c: teste A/B)" if modo_ab else " (aplicando como padrão)" if aplicar_padrao else ""))
    for b in blocos:
        bid = b["id"]
        if so_bloco is not None and bid != so_bloco:
            continue
        status = (ler_bloco(stem, bid) or {}).get("status")
        if status in NAO_MEXER and not previa:
            print(f"[Bloco {bid}] já {status}: colagem não mexe")
            continue
        print(f"[Bloco {bid}] {b.get('tema', '')}")
        t0 = time.time()
        evento(stem, "07b_colagem", "inicio", agente="editor", bloco_id=bid)
        titulo = descricoes.get(bid, {}).get("titulo") or b.get("titulo_sugerido", "")
        transcricao = " ".join(w["word"] for w in palavras_na_janela(
            todas, hhmmss_para_segundos(b["timestamp_inicio"]), hhmmss_para_segundos(b["timestamp_fim"])))
        try:
            reg = processar_bloco(client, pasta, stem, b, titulo, transcricao, saida_dir, sem_llm, excluir,
                                  sem_editor)
        except Exception as e:  # noqa: BLE001 — um bloco não derruba os outros; fica o template atual
            reg = {"status": "fallback", "motivo": f"erro: {type(e).__name__}: {e}"[:300], "custo_usd": 0.0}
        total += reg["custo_usd"]
        registro[str(bid)] = reg
        if reg["status"] == "ok":
            ok += 1
            if aplicar_padrao:
                try:
                    aplicar(pasta, saida_dir, bid, reg, letras)
                    aplicados += 1
                except OSError as e:
                    print(f"  [aviso] não aplicou a colagem ({e}): fica a thumb atual")
                    evento(stem, "07b_colagem", "aviso", agente="editor", bloco_id=bid,
                           mensagem=f"colagem não aplicada: {e}"[:300])
            evento(stem, "07b_colagem", "ok", agente="editor", bloco_id=bid,
                   duracao_s=time.time() - t0, mensagem=f"cenas: {'; '.join(reg['cenas'])}"[:300])
        else:
            print(f"  → template atual ({reg['motivo']})")
            evento(stem, "07b_colagem", "aviso", agente="editor", bloco_id=bid,
                   mensagem=f"colagem não saiu: {reg['motivo']}"[:300])
    registro_path.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{ok} bloco(s) com colagem · US$ {total:.4f} · {registro_path}")
    # --bloco=N que não saiu (ou não foi aplicado) → 2: o editor (11) volta pro template atual
    if so_bloco is not None and (not ok or (aplicar_padrao and not aplicados)):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
