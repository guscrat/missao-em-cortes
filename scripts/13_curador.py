"""Agente CURADOR: acha lives/vídeos novos dos canais monitorados, escolhe os que valem
virar corte e dispara o pipeline neles (agente="curador", off-pipeline, roda 1x/dia).

Uso: uv run py scripts/13_curador.py [--dry-run] [--sem-pipeline] [--forcar]

  --dry-run       só lista, filtra e mostra o estoque (sem LLM, sem baixar)
  --sem-pipeline  avalia e põe na fila, mas não baixa nem processa
  --forcar        processa 1 vídeo da fila mesmo com estoque cheio

Fluxo:
  1. Lê config/canais.json e lista as abas streams + videos de cada canal (yt-dlp, flat,
     data aproximada). Filtro grátis: idade <= dias, duração entre duracao_min e
     duracao_max, sem live em andamento, sem vídeo já visto (inputs/*.url, banco ou
     state/curadoria.json).
  2. Busca título original (pt) e data exata dos que passaram e manda pro Claude
     (claude-opus-5-5, effort low, ~US$ 0,02-0,05/rodada): vale a pena? prioridade? motivo?
  3. Todo vídeo que vale entra na FILA (state/curadoria.json). Só processa quando o
     ESTOQUE pronto pra publicar cai abaixo de estoque.dias_minimos (config): dias de
     estoque = min(longos aprovados / longos_por_dia, Shorts prontos / shorts_por_dia).
     Aí processa 1 vídeo só, o de maior prioridade (empate: o mais recente):
     01_baixar → pipeline.py --polir → 11_revisor → 10_shorts (aprovados) → publicacao.txt.
     ~US$ 0,65 por vídeo. Fila com mais de DIAS_ARQUIVAR dias expira.
     Thumb colagem (config/thumb.json): "teste" roda o 07b_colagem no fim, em thumbs/colagem/
     (~US$ 0,15/vídeo, não mexe nas thumbs que sobem); "padrao" roda com --aplicar antes do revisor.
  4. Resumo em state/curador_resumo.md (cortes prontos pra publicar, recusados com motivo,
     avisos) e decisões em state/curadoria.json. Tudo também vira evento no painel.

Canal com zoom no config: o zoom é copiado pro config/zoom.json do stem novo (como o
calibrar_zoom --salvar). Canal sem zoom: processa sem e o resumo pede pra calibrar.
"""
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

from _eventos import evento, upsert_video, conectar
from sincronizar_estado import DIAS_ARQUIVAR    # janela do conteúdo antigo (15 dias)

ROOT = Path(__file__).parent.parent
SCRIPTS = Path(__file__).parent
CONFIG = ROOT / "config" / "canais.json"
ZOOM_JSON = ROOT / "config" / "zoom.json"
INPUTS = ROOT / "inputs"
OUTPUTS = ROOT / "outputs"
ESTADO = ROOT / "state" / "curadoria.json"
RESUMO = ROOT / "state" / "curador_resumo.md"
TRAVA = ROOT / "state" / "curador.lock"
TRAVA_HORAS = 12             # rodada mais velha que isso = morreu no meio: libera
MAX_TENTATIVAS = 3           # falhou antes de baixar: volta pra fila até isso, depois desiste

MODELO = "claude-opus-5-5"
PRECO_IN, PRECO_OUT = 4.0, 20.0        # US$ por 1M tokens (opus 5.5)
CUSTO_POR_VIDEO = 0.65                 # segmentação + polimento + revisor, só pra estimativa
AO_VIVO = {"is_live", "is_upcoming"}

SCHEMA = {
    "type": "object",
    "properties": {
        "avaliacoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "vale": {"type": "boolean"},
                    "prioridade": {"type": "integer"},
                    "motivo": {"type": "string"},
                },
                "required": ["id", "vale", "prioridade", "motivo"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["avaliacoes"],
    "additionalProperties": False,
}

SISTEMA = """Você é o curador do canal "Missão em Cortes", que publica cortes de 5-7 min \
de lives, entrevistas e debates do Partido Missão (legenda 14, direita liberal, ligado ao \
MBL): Renan Santos, Kim Kataguiri, Arthur do Val, Guto Zacarias e Amanda Vettorazzo.

Você recebe vídeos novos dos canais monitorados e decide quais valem virar cortes.

Vale (prioridade alta) quando:
- uma dessas figuras fala bastante: análise política, eleição, escândalo, debate, \
entrevista, podcast com convidado relevante
- o tema é quente agora (rende cliques nos próximos dias)
- tem cara de render vários blocos de 5-7 min com um ponto forte cada

Não vale quando:
- jingle, paródia, trailer, aviso, corte já editado, compilação ou reprise
- o assunto é fora de política (jogos, religião pessoal, entretenimento) ou a figura do \
partido quase não fala
- é o mesmo conteúdo de outro vídeo da lista (fique com o mais completo)

prioridade: 1 a 10 (10 = processar primeiro). motivo: uma frase curta em português, \
específica (cite o tema/quem fala), que aparece no painel pro dono do canal.
Avalie TODOS os ids recebidos, um item por id."""


# --- config, estado e trava -------------------------------------------------------------

def carregar_config() -> dict:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    for chave, padrao in (("dias", 3), ("duracao_min", 20), ("duracao_max", 240),
                          ("por_canal", 8)):
        cfg.setdefault(chave, padrao)
    cfg["estoque"] = {"dias_minimos": 2, "longos_por_dia": 1, "shorts_por_dia": 2,
                      **cfg.get("estoque", {})}
    return cfg


def ler_estado() -> dict:
    """{video_id: {decisao: escolhido|recusado|fila, motivo, titulo, canal, ...}}"""
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def gravar_estado(estado: dict) -> None:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def pegar_trava() -> bool:
    """Evita duas rodadas ao mesmo tempo (o agendador do Windows + uma manual)."""
    TRAVA.parent.mkdir(parents=True, exist_ok=True)
    if TRAVA.exists():
        idade = datetime.now() - datetime.fromtimestamp(TRAVA.stat().st_mtime)
        if idade < timedelta(hours=TRAVA_HORAS):
            return False
        TRAVA.unlink(missing_ok=True)               # rodada que morreu no meio
    try:                                            # O_EXCL: criação atômica
        fd = os.open(TRAVA, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}\n")
    return True


def soltar_trava() -> None:
    TRAVA.unlink(missing_ok=True)


# --- o que já foi visto -------------------------------------------------------------------

ID_RE = re.compile(r"(?:v=|youtu\.be/|/live/|/shorts/)([\w-]{11})")


def id_do_url(url: str) -> str | None:
    m = ID_RE.search(url or "")
    return m.group(1) if m else None


def ids_ja_processados() -> set[str]:
    """Vídeos que já viraram stem: inputs/*.url + fonte_url no banco."""
    ids = {id_do_url(p.read_text(encoding="utf-8")) for p in INPUTS.glob("*.url")}
    try:
        con = conectar()
        try:
            ids |= {id_do_url(r["fonte_url"]) for r in con.execute(
                "SELECT fonte_url FROM videos WHERE fonte_url IS NOT NULL")}
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 — banco é best-effort
        print(f"[aviso] não li o banco ({e}); uso só os inputs/*.url", file=sys.stderr)
    return ids - {None}


# --- listagem (yt-dlp) ------------------------------------------------------------------

class _Mudo:
    """yt-dlp imprime ERROR no stderr mesmo com quiet; o Curador trata os erros ele mesmo."""
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def _ydl(opcoes: dict):
    import yt_dlp
    return yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                             "logger": _Mudo(), **opcoes})


def listar_canal(canal: dict, n: int) -> list[dict]:
    """Itens recentes das abas streams + videos (flat: rápido, data aproximada).
    Aba que não existe no canal (ex: TV do MBL não tem 'videos') é ignorada."""
    opcoes = {"extract_flat": "in_playlist", "playlistend": n,
              # data aproximada ("2 days ago") só funciona com a página em inglês
              "extractor_args": {"youtubetab": {"approximate_date": [""]}}}
    itens = []
    for aba in ("streams", "videos"):
        try:
            info = _ydl(opcoes).extract_info(f"{canal['url'].rstrip('/')}/{aba}", download=False)
        except Exception as e:  # noqa: BLE001 — yt-dlp levanta DownloadError genérico
            if "does not have" not in str(e):
                print(f"   [aviso] {canal['nome']}/{aba}: {e}")
            continue
        for e in info.get("entries") or []:
            if not e or not e.get("id"):
                continue
            ts = e.get("timestamp")
            itens.append({
                "id": e["id"], "url": f"https://www.youtube.com/watch?v={e['id']}",
                "titulo": e.get("title") or "", "duracao_s": e.get("duration") or 0,
                "data": date.fromtimestamp(ts).isoformat() if ts else None,
                "live_status": e.get("live_status"), "canal": canal["nome"],
                "prefixo": canal["prefixo"], "zoom": canal.get("zoom"),
            })
    return itens


def detalhar(item: dict) -> dict:
    """Título original (pt), data exata e começo da descrição de UM vídeo (~3s)."""
    try:
        info = _ydl({"extractor_args": {"youtube": {"lang": ["pt"]}}}).extract_info(
            item["url"], download=False)
    except Exception as e:  # noqa: BLE001
        print(f"   [aviso] não detalhei {item['id']}: {e}")
        return item
    up = info.get("upload_date")
    return {**item, "titulo": info.get("title") or item["titulo"],
            "duracao_s": info.get("duration") or item["duracao_s"],
            "data": f"{up[:4]}-{up[4:6]}-{up[6:]}" if up else item["data"],
            "live_status": info.get("live_status") or item["live_status"],
            "descricao": (info.get("description") or "")[:300]}


def motivo_filtro(item: dict, cfg: dict, hoje: date, vistos: set[str]) -> str | None:
    """Por que o item fica de fora sem nem ir pro LLM (None = passa)."""
    if item["id"] in vistos:
        return "já processado"
    if item.get("live_status") in AO_VIVO:
        return "ao vivo/agendado (volta amanhã)"
    minutos = (item.get("duracao_s") or 0) / 60
    if minutos < cfg["duracao_min"]:
        return f"curto ({minutos:.0f} min)"
    if minutos > cfg["duracao_max"]:
        return f"longo demais ({minutos:.0f} min)"
    if item.get("data") and (hoje - date.fromisoformat(item["data"])).days > cfg["dias"]:
        return f"antigo ({item['data']})"
    return None


# --- escolha (LLM) ------------------------------------------------------------------------

def montar_pedido(itens: list[dict]) -> str:
    linhas = [f"Hoje é {date.today():%d/%m/%Y}. Vídeos novos:"]
    for x in itens:
        linhas.append(f"- id={x['id']} | canal: {x['canal']} | {x['data'] or '?'} | "
                      f"{x['duracao_s'] // 60} min | título: {x['titulo']}"
                      + (f" | descrição: {x['descricao']!r}" if x.get("descricao") else ""))
    return "\n".join(linhas)


def avaliar(client, itens: list[dict]) -> tuple[dict[str, dict], tuple[int, int, float]]:
    """({id: {vale, prioridade, motivo}}, (tokens_in, tokens_out, custo))."""
    resp = client.beta.messages.create(
        model=MODELO,
        max_tokens=8000,
        system=SISTEMA,
        messages=[{"role": "user", "content": montar_pedido(itens)}],
        output_config={"effort": "low",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
    )
    tin, tout = resp.usage.input_tokens, resp.usage.output_tokens
    custo = (tin, tout, tin / 1e6 * PRECO_IN + tout / 1e6 * PRECO_OUT)
    if resp.stop_reason == "refusal":
        return {}, custo
    texto = next((b.text for b in resp.content if b.type == "text"), None)
    if texto is None:
        raise ValueError(f"resposta sem texto (stop_reason={resp.stop_reason})")
    ids = {x["id"] for x in itens}
    return {a["id"]: a for a in json.loads(texto)["avaliacoes"] if a["id"] in ids}, custo


# --- estoque ------------------------------------------------------------------------------

def _data_pasta(nome: str) -> date | None:
    try:
        return date.fromisoformat(nome[:10])
    except ValueError:
        return None


def ler_shorts(pasta: Path) -> dict:
    try:
        dados = json.loads((pasta / "shorts" / "shorts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in dados.items() if isinstance(v, dict)} if isinstance(dados, dict) else {}


def calcular_estoque(cfg: dict, hoje: date | None = None) -> dict:
    """O que está pronto e ainda não foi pro ar, de lives dos últimos DIAS_ARQUIVAR dias.
    Longo = bloco 'aprovado' (coluna "Pronto para publicar"). Short = short_NN gerado de
    bloco aprovado/agendado/publicado que ainda não foi marcado como postado
    (pelo 14_canal, que lê o canal)."""
    hoje = hoje or date.today()
    try:
        con = conectar()
        try:
            linhas = [dict(r) for r in con.execute(
                "SELECT b.stem, b.bloco_id, b.status, v.pasta FROM blocos b "
                "LEFT JOIN videos v ON v.stem = b.stem "
                "WHERE b.status IN ('aprovado', 'agendado', 'publicado')")]
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 — banco é best-effort
        print(f"[aviso] não li o estoque no banco ({e}): considerando vazio", file=sys.stderr)
        linhas = []
    longos = shorts = 0
    cache: dict[Path, dict] = {}
    for r in linhas:
        pasta = OUTPUTS / r["pasta"] if r["pasta"] else \
            next(iter(sorted(OUTPUTS.glob(f"*_{r['stem']}"))), None)
        data = _data_pasta(pasta.name) if pasta else None
        if data is None or (hoje - data).days > DIAS_ARQUIVAR:
            continue
        if r["status"] == "aprovado":
            longos += 1
        if pasta not in cache:
            cache[pasta] = ler_shorts(pasta)
        sh = cache[pasta].get(f"{r['bloco_id']:02d}")
        if sh and sh.get("arquivo") and not sh.get("postado") and \
                (pasta / "shorts" / sh["arquivo"]).exists():
            shorts += 1
    est = cfg["estoque"]
    dias = min(longos / est["longos_por_dia"], shorts / est["shorts_por_dia"])
    return {"longos": longos, "shorts": shorts, "dias": dias}


# --- processamento ------------------------------------------------------------------------

def _slug(texto: str, max_palavras: int = 5, max_chars: int = 40) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    palavras = re.findall(r"[a-z0-9]+", sem_acento.lower())
    palavras = [p for p in palavras if len(p) > 2 or p.isdigit()][:max_palavras]
    return "_".join(palavras)[:max_chars].rstrip("_") or "video"


def montar_stem(prefixo: str, titulo: str, reservados: set[str] = frozenset()) -> str:
    """renan_possivel_que_lula_vire; colisão com inputs/outputs ou com outro escolhido
    da mesma rodada (reservados) ganha _2, _3..."""
    base = f"{prefixo}_{_slug(titulo)}"
    stem, n = base, 2
    while stem in reservados or (INPUTS / f"{stem}.mp4").exists() or any(OUTPUTS.glob(f"*_{stem}")):
        stem, n = f"{base}_{n}", n + 1
    return stem


def cadastrar_zoom(stem: str, zoom: str | None) -> bool:
    """Copia o zoom padrão do canal pro stem (não sobrescreve). True se o stem tem zoom."""
    dados = json.loads(ZOOM_JSON.read_text(encoding="utf-8")) if ZOOM_JSON.exists() else {}
    if stem in dados:
        return True
    if not zoom:
        return False
    dados[stem] = zoom
    ZOOM_JSON.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def modo_colagem() -> str:
    """config/thumb.json → 'desligado' | 'teste' | 'padrao' (sem arquivo: desligado)."""
    try:
        modo = json.loads((ROOT / "config" / "thumb.json").read_text(encoding="utf-8")).get("colagem")
    except (OSError, ValueError):
        return "desligado"
    return modo if modo in ("teste", "padrao") else "desligado"


def rodar(script: str, *args: str) -> bool:
    print(f"\n>> {script} {' '.join(args)}", flush=True)
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          cwd=ROOT).returncode == 0


def processar(item: dict) -> dict:
    """Baixa, roda o pipeline com polimento + legenda, revisa e gera a lista de publicação."""
    from _paths import achar_pasta
    from _publicacao import aprovados, gerar

    stem = item["stem"]
    res = {"stem": stem, "titulo": item["titulo"], "canal": item["canal"],
           "ok": False, "aprovados": 0, "publicacao": None, "avisos": []}
    if not cadastrar_zoom(stem, item.get("zoom")):
        res["avisos"].append(f"{stem}: canal sem zoom calibrado — confira os overlays "
                             f"(calibrar_zoom.py, depois pipeline.py {stem} --desde=4)")
    upsert_video(stem, fonte_url=item["url"], status="curadoria")
    colagem = modo_colagem()
    etapas = [("01_baixar.py", item["url"], stem),
              ("pipeline.py", stem, "--polir"),
              ("11_revisor.py", stem)]
    for script, *args in etapas:
        if script == "11_revisor.py" and colagem == "padrao":   # revisor já avalia a colagem
            if not rodar("07b_colagem.py", stem, "--aplicar"):
                res["avisos"].append(f"{stem}: thumb colagem falhou, ficou o template atual")
        if not rodar(script, *args):
            res["erro"] = f"{script} falhou"
            evento(stem, "curador_pipeline", "falha", agente="curador", mensagem=res["erro"])
            return res
    pasta = achar_pasta(stem)
    for bloco in aprovados(pasta):                 # Short só de corte aprovado ($0, ~1 min cada)
        if not rodar("10_shorts.py", stem, f"--bloco={bloco['id']}"):
            res["avisos"].append(f"{stem}: Short do bloco {bloco['id']} falhou "
                                 f"(10_shorts.py {stem} --bloco={bloco['id']})")
    if colagem == "teste":                         # ~US$ 0.03/bloco; não mexe nas thumbs que sobem
        if rodar("07b_colagem.py", stem):
            res["colagem"] = str(pasta / "thumbs" / "colagem")
        else:
            res["avisos"].append(f"{stem}: thumb colagem (teste) falhou (07b_colagem.py {stem})")
    caminho, lista = gerar(pasta)
    res.update(ok=True, aprovados=len(lista), publicacao=str(caminho) if caminho else None)
    evento(stem, "curador_pipeline", "ok", agente="curador",
           mensagem=f"{len(lista)} corte(s) pronto(s) pra publicar")
    return res


def processar_seguro(item: dict) -> dict:
    """processar() sem derrubar a rodada: erro de um vídeo vira falha dele e segue."""
    try:
        return processar(item)
    except (Exception, SystemExit) as e:  # noqa: BLE001 — achar_pasta ambíguo dá SystemExit
        erro = f"{type(e).__name__}: {e}"[:300]
        evento(item["stem"], "curador_pipeline", "falha", agente="curador", mensagem=erro)
        return {"stem": item["stem"], "titulo": item["titulo"], "canal": item["canal"],
                "ok": False, "aprovados": 0, "publicacao": None, "avisos": [], "erro": erro}


# --- resumo -------------------------------------------------------------------------------

def escrever_resumo(rodada: dict) -> str:
    est = rodada.get("estoque") or {"longos": 0, "shorts": 0, "dias": 0}
    linhas = [f"# Curador — {rodada['quando']}", "",
              f"Custo de curadoria: US$ {rodada['custo']:.3f} · "
              f"{len(rodada['processados'])} vídeo(s) processado(s)",
              f"Estoque no início: {est['longos']} longo(s) + {est['shorts']} Short(s) = "
              f"{est['dias']:.1f} dia(s)"]
    if rodada.get("estoque_depois"):
        d = rodada["estoque_depois"]
        linhas.append(f"Estoque no fim: {d['longos']} longo(s) + {d['shorts']} Short(s) = "
                      f"{d['dias']:.1f} dia(s)")
    linhas.append("")
    prontos = [p for p in rodada["processados"] if p.get("aprovados")]
    if prontos:
        linhas.append("## Prontos pra publicar")
        linhas += [f"- **{p['aprovados']} corte(s)** de {p['canal']}: {p['titulo']} → "
                   f"`{p['publicacao']}`" for p in prontos]
        linhas.append("")
    colagens = [p for p in rodada["processados"] if p.get("colagem")]
    if colagens:
        linhas.append("## Thumb colagem (teste)")
        linhas += [f"- {p['canal']}: {p['titulo']} → `{p['colagem']}` (3 variantes por bloco; "
                   "compare com as thumbs atuais antes de virar padrão)" for p in colagens]
        linhas.append("")
    zerados = [p for p in rodada["processados"] if p["ok"] and not p.get("aprovados")]
    if zerados:
        linhas.append("## Processados sem corte aprovado")
        linhas += [f"- {p['canal']}: {p['titulo']} (veja o revisao.json de {p['stem']})"
                   for p in zerados]
        linhas.append("")
    falhas = [p for p in rodada["processados"] if not p["ok"]]
    if falhas:
        linhas.append("## Falhas")
        linhas += [f"- {p['stem']}: {p['erro']}" for p in falhas]
        linhas.append("")
    for titulo, chave in (("Escolhidos", "escolhidos"), ("Entraram na fila", "fila"),
                          ("Recusados", "recusados")):
        if rodada[chave]:
            linhas.append(f"## {titulo}")
            linhas += [f"- {x['canal']}: {x['titulo']} — {x['motivo']}" for x in rodada[chave]]
            linhas.append("")
    avisos = [a for p in rodada["processados"] for a in p["avisos"]]
    if rodada.get("aviso_canal"):
        avisos.insert(0, rodada["aviso_canal"])
    if rodada.get("falha_llm"):
        avisos.insert(0, f"avaliação dos vídeos novos falhou ({rodada['falha_llm']}); "
                         "eles voltam amanhã")
    if avisos:
        linhas.append("## Avisos")
        linhas += [f"- {a}" for a in avisos]
    texto = "\n".join(linhas).rstrip() + "\n"
    RESUMO.parent.mkdir(parents=True, exist_ok=True)
    RESUMO.write_text(texto, encoding="utf-8")
    return texto


# --- main ---------------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    dry_run = "--dry-run" in argv
    sem_pipeline = "--sem-pipeline" in argv
    forcar = "--forcar" in argv
    cfg = carregar_config()

    if not dry_run and not pegar_trava():
        print(f"[!] Outra rodada do Curador em andamento ({TRAVA.name}). Saindo.")
        return 1
    try:
        return _rodada(cfg, dry_run, sem_pipeline, forcar)
    finally:
        if not dry_run:
            soltar_trava()


def _canal_de(cfg: dict, nome: str) -> dict:
    return next((c for c in cfg["canais"] if c["nome"] == nome), {})


def proximo_da_fila(estado: dict) -> str | None:
    """Id da fila com maior prioridade; empate = o mais recente."""
    fila = [(k, v) for k, v in estado.items() if v.get("decisao") == "fila"]
    if not fila:
        return None
    return max(fila, key=lambda kv: (kv[1].get("prioridade", 0), kv[1].get("data") or ""))[0]


def expirar_fila(estado: dict, hoje: date) -> list[str]:
    """Fila mais velha que DIAS_ARQUIVAR vira 'expirado' (mesma regra do conteúdo antigo)."""
    expirados = []
    for k, v in estado.items():
        data = _data_pasta(v.get("data") or "")        # data malformada: não expira (nem quebra)
        if v.get("decisao") == "fila" and data and (hoje - data).days > DIAS_ARQUIVAR:
            v["decisao"] = "expirado"
            expirados.append(k)
    return expirados


def sincronizar_canal(dry_run: bool = False) -> str | None:
    """14_canal: marca o que já está publicado/agendado no NOSSO canal (só leitura, US$ 0).
    Nunca abre o navegador (roda pelo Agendador) e nunca derruba a rodada: devolve o aviso."""
    try:
        import importlib
        res = importlib.import_module("14_canal").sincronizar(interativo=False, dry=dry_run)
    except Exception as e:  # noqa: BLE001 — sem canal, o estoque fica como estava
        print(f"[aviso] não li o canal ({e}): estoque sem o que subiu desde a última leitura",
              file=sys.stderr)
        return f"não li o canal do YouTube ({str(e)[:200]}); rode `uv run py scripts/14_canal.py`"
    print(f"Canal: {len(res['longos'])} longo(s) e {len(res['shorts'])} Short(s) marcados "
          f"como agendado/publicado")
    if res["sem_match"]:
        return (f"{len(res['sem_match'])} vídeo(s) recente(s) do canal sem bloco correspondente "
                f"(título editado no Studio?): " + "; ".join(x["titulo"][:50] for x in res["sem_match"]))
    return None


def _rodada(cfg: dict, dry_run: bool, sem_pipeline: bool, forcar: bool) -> int:
    hoje = date.today()
    estado = ler_estado()
    vistos = ids_ja_processados() | set(estado)     # já avaliado nunca volta pro LLM
    print(f"Curador · {len(cfg['canais'])} canais · últimos {cfg['dias']} dias · "
          f"{cfg['duracao_min']}-{cfg['duracao_max']} min")

    novos = []
    for canal in cfg["canais"]:
        itens = listar_canal(canal, cfg["por_canal"])
        print(f"\n{canal['nome']}: {len(itens)} item(ns) recente(s)")
        for item in itens:
            motivo = motivo_filtro(item, cfg, hoje, vistos)
            if motivo is None:                      # data/título exatos só pra quem passou
                item = detalhar(item)
                motivo = motivo_filtro(item, cfg, hoje, vistos)
            if motivo:
                print(f"   - {item['titulo'][:60]} ({motivo})")
            elif item["id"] not in {c["id"] for c in novos}:
                novos.append(item)
                print(f"   + {item['titulo'][:60]} ({item['duracao_s'] // 60} min, {item['data']})")

    aviso_canal = sincronizar_canal(dry_run)        # antes do estoque: o que já subiu sai dele
    estoque = calcular_estoque(cfg)
    minimo = cfg["estoque"]["dias_minimos"]
    precisa = forcar or estoque["dias"] < minimo
    print(f"\nEstoque: {estoque['longos']} longo(s) + {estoque['shorts']} Short(s) prontos = "
          f"{estoque['dias']:.1f} dia(s) (mínimo {minimo}) → "
          f"{'processa 1 vídeo' if precisa else 'não processa hoje'}")
    na_fila = sum(1 for v in estado.values() if v.get("decisao") == "fila")
    print(f"{len(novos)} novo(s) pro Claude, {na_fila} na fila")
    if dry_run:
        print("(dry-run: nada foi enviado nem baixado)")
        return 0

    agora = datetime.now().isoformat(timespec="seconds")
    rodada = {"quando": agora, "custo": 0.0, "estoque": estoque, "escolhidos": [],
              "fila": [], "recusados": [], "processados": [], "aviso_canal": aviso_canal}
    if novos:
        from anthropic import Anthropic
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        evento(None, "curadoria", "inicio", agente="curador",
               mensagem=f"{len(novos)} vídeo(s) novo(s)")
        try:
            avaliacoes, custo = avaliar(Anthropic(), novos)
        except Exception as e:  # noqa: BLE001 — avaliação falhou: a fila de antes ainda roda
            evento(None, "curadoria", "falha", agente="curador", mensagem=str(e)[:300])
            print(f"[!] Avaliação dos novos falhou ({e}); sigo só com a fila")
            rodada["falha_llm"] = str(e)[:300]
            avaliacoes = {}
        else:
            rodada["custo"] = custo[2]
            evento(None, "curadoria", "llm", agente="curador", tokens_in=custo[0],
                   tokens_out=custo[1], custo_usd=custo[2], mensagem=MODELO)
            print(f"Claude: {custo[0]:,} tok in · {custo[1]:,} tok out · US$ {custo[2]:.3f}")
        for c in novos:
            a = avaliacoes.get(c["id"])
            if a is None:                           # recusa do modelo/id faltando: tenta amanhã
                continue
            registro = {"titulo": c["titulo"], "canal": c["canal"], "url": c["url"],
                        "data": c["data"], "prefixo": c["prefixo"], "zoom": c.get("zoom"),
                        "prioridade": a["prioridade"], "motivo": a["motivo"],
                        "avaliado_em": agora, "tentativas": 0,
                        "decisao": "fila" if a["vale"] else "recusado"}
            estado[c["id"]] = registro
            if a["vale"]:
                rodada["fila"].append(registro)
            else:
                rodada["recusados"].append(registro)
                evento(None, "curadoria", "recusado", agente="curador",
                       mensagem=f"{c['canal']}: {c['titulo']} — {a['motivo']}")
    expirar_fila(estado, hoje)
    gravar_estado(estado)

    vid = proximo_da_fila(estado) if precisa and not sem_pipeline else None
    if vid:
        e = estado[vid]
        canal = _canal_de(cfg, e["canal"])
        item = {"id": vid, "url": e["url"], "titulo": e["titulo"], "canal": e["canal"],
                "prefixo": e.get("prefixo") or canal.get("prefixo", "video"),
                "zoom": e.get("zoom", canal.get("zoom"))}
        item["stem"] = e.get("stem") or montar_stem(item["prefixo"], item["titulo"])
        e.update(decisao="escolhido", stem=item["stem"])
        gravar_estado(estado)
        rodada["escolhidos"].append(e)
        rodada["fila"] = [x for x in rodada["fila"] if x is not e]
        evento(item["stem"], "curadoria", "ok", agente="curador",
               mensagem=f"escolhido (prioridade {e['prioridade']}, estoque "
                        f"{estoque['dias']:.1f} dia(s)): {e['motivo']}")
        print(f"\nProcessando: {item['titulo']} (~US$ {CUSTO_POR_VIDEO:.2f})")
        res = processar_seguro(item)
        rodada["processados"].append(res)
        if not res["ok"] and not (INPUTS / f"{item['stem']}.url").exists():
            # nem baixou: volta pra fila (sem nova chamada de LLM) até MAX_TENTATIVAS
            e["tentativas"] = e.get("tentativas", 0) + 1
            e["decisao"] = "fila" if e["tentativas"] < MAX_TENTATIVAS else "falhou"
            gravar_estado(estado)
        rodada["estoque_depois"] = calcular_estoque(cfg)

    print("\n" + escrever_resumo(rodada))
    ok = all(p["ok"] for p in rodada["processados"]) and not rodada.get("falha_llm")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
