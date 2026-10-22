"""Banco de fotos dos personagens recorrentes (políticos/apresentadores) pra thumb colagem.

Só imagem de LICENÇA ABERTA do Wikimedia Commons, com licença e crédito conferidos pela API e
registrados em assets/personagens/licencas.json. Nunca baixa de buscador, jornal ou rede social.

  uv run py scripts/personagens.py lista                    # nomes que mais aparecem nos blocos
  uv run py scripts/personagens.py baixar "Lula" "Flávio Bolsonaro"
  uv run py scripts/personagens.py baixar --top=12          # os 12 primeiros da lista
  uv run py scripts/personagens.py baixar "Fulano" --arquivo="File:Fulano 2024.jpg"  # foto escolhida à mão

Como acha a foto: o nome vira um item do Wikidata (só pessoa: P31 = ser humano); tenta a imagem
oficial do item (P18) e, se a licença não servir, as fotos da categoria dele no Commons (P373).
Licenças aceitas: CC0, domínio público e CC BY (com crédito). CC BY-SA fica de fora por padrão
(a thumb inteira teria que sair em CC BY-SA); --aceitar-sa libera.
A foto precisa ter UM rosto (OpenCV); o fundo sai com o rembg (local) e o PNG fica em
assets/personagens/<slug>.webp. Custo: US$ 0.
"""
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from io import BytesIO
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import _colagem as col
import _thumb_rosto as tr

ROOT = Path(__file__).parent.parent
OUTPUTS = ROOT / "outputs"
UA = "MissaoEmCortes/1.0 (https://github.com/guscrat/missao-em-cortes; thumbs com crédito)"
WIKIDATA = "https://www.wikidata.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
HUMANO = "Q5"
LARGURA_FOTO = 1000
MAX_CATEGORIA = 40
DOMINANTE = 4.0            # rosto principal >= 4x a área do 2º maior
LARGURA_MIN = 400          # foto menor fica borrada no painel da thumb (as do TSE têm 161 px)
ALTURA_MAX = 900           # recorte salvo com no máximo isso de altura

# tags com grafia errada ou apelido → nome que o Wikidata conhece
# (também viram apelidos no licencas.json: é por eles que o bloco "Quem manda se Flávio perder"
# acha a foto do Flávio Bolsonaro. Só nome curto sem ambiguidade: "André" ou "Renan" não)
APELIDOS = {
    "nicolas ferreira": "Nikolas Ferreira",
    "nikolas": "Nikolas Ferreira",
    "lulinha": "Fábio Luís Lula da Silva",
    "lula": "Luiz Inácio Lula da Silva",
    "flavio": "Flávio Bolsonaro",
    "flavio bolsonaro": "Flávio Bolsonaro",
    "pavanato": "Lucas Pavanato",
    "janones": "André Janones",
    "kim": "Kim Kataguiri",
    "mamaefalei": "Arthur do Val",
}
# nomes que a gente sempre quer no banco, mesmo sem aparecer nas tags ainda
FIXOS = ["Renan Santos", "Kim Kataguiri", "Arthur do Val", "Guto Zacarias", "Amanda Vettorazzo"]


def _get(url: str, params: dict) -> dict:
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _baixar_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def slug(nome: str) -> str:
    return re.sub(r"\s+", "_", col.normalizar(nome))


# ── licença ─────────────────────────────────────────────────────────────────

def licenca_ok(curta: str, aceitar_sa: bool = False) -> bool:
    """CC0, domínio público e CC BY sim; CC BY-SA só com aceitar_sa; o resto (NC, ND, fair use,
    sem licença) nunca."""
    l = (curta or "").strip().lower()
    if not l or "nc" in l.split("-") or "-nd" in l or "fair" in l or "copyright" in l:
        return False
    if l.startswith("cc0") or l.startswith("public domain") or l == "pd" or l.startswith("pd-"):
        return True
    if l == "attribution":       # {{Attribution}} do Commons (ex.: Agência Senado): livre, só pede crédito
        return True
    if l.startswith("cc by-sa") or l.startswith("cc-by-sa"):
        return aceitar_sa
    return bool(re.match(r"cc[ -]by(?![- ]?(nc|nd|sa))", l))


def _texto(meta: dict, chave: str) -> str:
    v = meta.get(chave, {}).get("value", "")
    return html.unescape(re.sub(r"<[^>]+>", "", v)).strip()


def info_arquivo(titulo: str) -> dict | None:
    """imageinfo de um File: do Commons, com licença, autor, crédito e url (LARGURA_FOTO px)."""
    r = _get(COMMONS, {"action": "query", "titles": titulo, "prop": "imageinfo", "format": "json",
                       "iiprop": "url|extmetadata|size|mime", "iiurlwidth": LARGURA_FOTO})
    paginas = list(r.get("query", {}).get("pages", {}).values())
    if not paginas or "imageinfo" not in paginas[0]:
        return None
    return _info(paginas[0]["title"], paginas[0]["imageinfo"][0])


def _info(titulo: str, ii: dict) -> dict:
    meta = ii.get("extmetadata", {})
    return {"titulo": titulo, "url": ii.get("thumburl") or ii.get("url"),
            "pagina": ii.get("descriptionurl"), "mime": ii.get("mime", ""),
            "largura": ii.get("width", 0), "licenca": _texto(meta, "LicenseShortName"),
            "licenca_url": _texto(meta, "LicenseUrl"), "autor": _texto(meta, "Artist"),
            "credito": _texto(meta, "Credit")}


def arquivos_da_categoria(categoria: str) -> list[dict]:
    r = _get(COMMONS, {"action": "query", "generator": "categorymembers", "format": "json",
                       "gcmtitle": f"Category:{categoria}", "gcmtype": "file", "gcmlimit": MAX_CATEGORIA,
                       "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
                       "iiurlwidth": LARGURA_FOTO})
    return [_info(p["title"], p["imageinfo"][0])
            for p in r.get("query", {}).get("pages", {}).values() if "imageinfo" in p]


# ── wikidata ────────────────────────────────────────────────────────────────

def item_da_pessoa(nome: str) -> dict | None:
    """{qid, nome, imagem (P18), categoria (P373)} do 1º resultado que é ser humano."""
    busca = _get(WIKIDATA, {"action": "wbsearchentities", "search": nome, "language": "pt",
                            "uselang": "pt", "type": "item", "limit": 5, "format": "json"})
    ids = [s["id"] for s in busca.get("search", [])]
    if not ids:
        return None
    ents = _get(WIKIDATA, {"action": "wbgetentities", "ids": "|".join(ids), "format": "json",
                           "props": "claims|labels", "languages": "pt|en"})["entities"]
    for qid in ids:
        e = ents.get(qid, {})
        claims = e.get("claims", {})
        tipos = [c["mainsnak"].get("datavalue", {}).get("value", {}).get("id") for c in claims.get("P31", [])]
        if HUMANO not in tipos:
            continue
        valor = lambda p: next((c["mainsnak"]["datavalue"]["value"] for c in claims.get(p, [])  # noqa: E731
                                if "datavalue" in c["mainsnak"]), None)
        rotulo = (e.get("labels", {}).get("pt") or e.get("labels", {}).get("en") or {}).get("value", nome)
        return {"qid": qid, "nome": rotulo, "imagem": valor("P18"), "categoria": valor("P373")}
    return None


# ── lista ───────────────────────────────────────────────────────────────────

def contar_nomes(outputs: Path = OUTPUTS) -> Counter:
    """Tags dos blocos já processados (normalizadas, apelido resolvido), com contagem."""
    cont = Counter()
    for bj in outputs.glob("*/blocos.json"):
        try:
            blocos = json.loads(bj.read_text(encoding="utf-8"))["blocos"]
        except (OSError, ValueError, KeyError):
            continue
        for b in blocos:
            for t in {col.normalizar(t) for t in b.get("tags", [])}:
                cont[col.normalizar(APELIDOS.get(t, t))] += 1
    return cont


def candidatos(cont: Counter, minimo: int = 1) -> list[str]:
    """Tags que parecem nome de gente (2+ palavras ou apelido conhecido) + os FIXOS."""
    nomes = [n for n, c in cont.most_common() if c >= minimo and (len(n.split()) >= 2 or n in APELIDOS)]
    for f in FIXOS:
        if col.normalizar(f) not in nomes:
            nomes.append(col.normalizar(f))
    return nomes


# ── baixar ──────────────────────────────────────────────────────────────────

def um_rosto(img) -> tuple | None:
    """O rosto dominante: o maior, se for pelo menos DOMINANTE x a área do 2º (foto de grupo
    não serve; um falso positivo pequeno do Haar não derruba a foto oficial)."""
    import cv2
    import numpy as np
    cinza = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    # o Haar falha ora reduzido (André Fernandes), ora em resolução cheia (Lula): tenta os dois
    for esc in dict.fromkeys((min(1.0, tr.LARGURA_DETECCAO / img.width), 1.0)):
        pequeno = cv2.resize(cinza, None, fx=esc, fy=esc) if esc < 1 else cinza
        achados = sorted(det.detectMultiScale(pequeno, scaleFactor=1.1, minNeighbors=6,
                                              minSize=(max(24, pequeno.shape[1] // 12),) * 2),
                         key=lambda r: -r[2] * r[3])
        if len(achados) == 0:
            continue
        if len(achados) > 1 and achados[0][2] * achados[0][3] < DOMINANTE * achados[1][2] * achados[1][3]:
            return None
        return tuple(int(v / esc) for v in achados[0])
    return None


def opcoes(item: dict, arquivo: str | None) -> list[dict]:
    """Fotos a tentar: a escolhida à mão (--arquivo) ou a oficial do item (P18). A categoria
    NÃO entra sozinha: tem diagrama, foto de grupo e gente errada (o "Lula" virou o PowerPoint
    da Lava Jato no 1º teste). Ela só vira sugestão pra escolher à mão."""
    titulo = arquivo if arquivo else (f"File:{item['imagem']}" if item.get("imagem") else None)
    if not titulo:
        return []
    info = info_arquivo(titulo if titulo.startswith("File:") else f"File:{titulo}")
    if not info:
        print(f"    - {titulo}: não existe no Commons")
        return []
    if info["mime"] not in ("image/jpeg", "image/png") or info["largura"] < LARGURA_MIN:
        print(f"    - {titulo}: {info['largura']} px / {info['mime']} (precisa de foto >= {LARGURA_MIN} px)")
        return []
    return [info]


def sugerir(item: dict, aceitar_sa: bool, n: int = 8) -> list[str]:
    """Fotos da categoria do Commons com licença que serve, pra escolher à mão com --arquivo."""
    if not item.get("categoria"):
        return []
    return [f"{i['titulo']} ({i['licenca']})" for i in arquivos_da_categoria(item["categoria"])
            if licenca_ok(i["licenca"], aceitar_sa) and i["mime"] in ("image/jpeg", "image/png")][:n]


def baixar(nome: str, arquivo: str | None = None, aceitar_sa: bool = False) -> dict | None:
    """Acha, confere a licença, recorta e registra. Devolve a entrada do licencas.json."""
    from PIL import Image
    alvo = APELIDOS.get(col.normalizar(nome), nome)
    item = item_da_pessoa(alvo)
    if not item:
        print(f"  [!] {nome}: nenhuma pessoa com esse nome no Wikidata")
        return None
    print(f"  {nome} → {item['nome']} ({item['qid']})")
    for info in opcoes(item, arquivo):
        if not licenca_ok(info["licenca"], aceitar_sa):
            print(f"    - {info['titulo']}: licença '{info['licenca'] or 'sem licença'}' não serve")
            continue
        img = Image.open(BytesIO(_baixar_bytes(info["url"]))).convert("RGB")
        rosto = um_rosto(img)
        if not rosto:
            print(f"    - {info['titulo']}: não tem exatamente um rosto")
            continue
        r = col.recortar(img, rosto)
        if not r:
            print(f"    - {info['titulo']}: rembg não separou a pessoa")
            continue
        recorte, rosto_rel = r
        if recorte.height > ALTURA_MAX:            # painel da thumb tem 720 px: mais é peso no repo
            esc = ALTURA_MAX / recorte.height
            recorte = recorte.resize((round(recorte.width * esc), ALTURA_MAX), Image.LANCZOS)
            rosto_rel = tuple(int(v * esc) for v in rosto_rel)
        PERSONAGENS = col.PERSONAGENS
        PERSONAGENS.mkdir(parents=True, exist_ok=True)
        nome_arq = f"{slug(item['nome'])}.webp"
        recorte.save(PERSONAGENS / nome_arq, quality=90, method=6)   # webp com alfa: ~10x menor que png
        entrada = {
            "slug": slug(item["nome"]), "nome": item["nome"],
            "apelidos": apelidos_de(nome, alvo, item["nome"]), "wikidata": item["qid"],
            "arquivo": nome_arq, "rosto": list(rosto_rel), "fonte": info["pagina"],
            "arquivo_commons": info["titulo"], "licenca": info["licenca"],
            "licenca_url": info["licenca_url"], "autor": info["autor"], "credito_fonte": info["credito"],
            "credito": f"Foto de {item['nome']}: {info['autor'] or 'autor no Commons'} / Wikimedia "
                       f"Commons, {info['licenca']} (fundo removido)",
            "baixado_em": date.today().isoformat(),
        }
        registrar(entrada)
        print(f"    ✓ {nome_arq} · {info['licenca']} · {info['autor'][:60]}")
        return entrada
    print(f"  [!] {nome}: a foto oficial do Wikidata não serve (ou não há). Escolha uma do Commons, "
          f"confira que é a pessoa e rode de novo com --arquivo=\"File:...\":")
    for s in sugerir(item, aceitar_sa):
        print(f"      {s}")
    return None


def apelidos_de(nome: str, alvo: str, rotulo: str) -> list[str]:
    """Nome pedido + nome buscado + chaves do APELIDOS que apontam pra essa pessoa, menos o
    rótulo do Wikidata (que já é o `nome` da entrada)."""
    extras = {k for k, v in APELIDOS.items() if col.normalizar(v) in (col.normalizar(alvo), col.normalizar(rotulo))}
    return sorted({col.normalizar(n) for n in (nome, alvo, *extras)} - {col.normalizar(rotulo)})


def registrar(entrada: dict) -> None:
    """Grava/atualiza a entrada (por slug) no licencas.json, juntando apelidos."""
    dados = {"_comment": "Banco de personagens da thumb colagem: só licença aberta do Wikimedia "
                         "Commons, conferida pela API (scripts/personagens.py). credito = linha "
                         "que vai na descrição do vídeo quando a foto entra na thumb.",
             "personagens": col.ler_licencas()}
    antigo = next((p for p in dados["personagens"] if p["slug"] == entrada["slug"]), None)
    if antigo:
        entrada["apelidos"] = sorted(set(antigo.get("apelidos", [])) | set(entrada["apelidos"]))
    dados["personagens"] = sorted([p for p in dados["personagens"] if p["slug"] != entrada["slug"]]
                                  + [entrada], key=lambda p: p["slug"])
    col.LICENCAS.parent.mkdir(parents=True, exist_ok=True)
    col.LICENCAS.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    pos = [a for a in argv if not a.startswith("--")]
    flags = dict(a[2:].split("=", 1) if "=" in a else (a[2:], True) for a in argv if a.startswith("--"))
    if not pos or pos[0] not in ("lista", "baixar"):
        print(__doc__)
        return 1
    cont = contar_nomes(Path(flags["outputs"]) if "outputs" in flags else OUTPUTS)
    if pos[0] == "lista":
        no_banco = {col.normalizar(n) for p in col.ler_licencas() for n in [p["nome"], *p.get("apelidos", [])]}
        for n in candidatos(cont):
            print(f"  {cont.get(n, 0):>3}x  {n}{'  (no banco)' if n in no_banco else ''}")
        return 0
    nomes = pos[1:] or candidatos(cont)[:int(flags.get("top", 12))]
    if flags.get("arquivo") and len(nomes) != 1:
        sys.exit("[!] --arquivo vale pra um nome só")
    ok = 0
    for n in nomes:
        try:
            ok += baixar(n, flags.get("arquivo"), bool(flags.get("aceitar-sa"))) is not None
        except OSError as e:
            print(f"  [!] {n}: falha de rede ({e})")
    print(f"\n{ok}/{len(nomes)} personagem(ns) no banco · {col.LICENCAS}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
