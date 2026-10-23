"""Gera txt com titulo + descricao + tags por bloco pronto pra colar no YouTube.

Le do blocos.json (que ja tem titulo_sugerido, resumo, ganchos, tags) e monta
o arquivo formatado em outputs/<pasta>/descricoes.txt. Sem chamada de API.

"Conteúdo original" = URL da FONTE (inputs/<stem>.url). O link do nosso canal só
entra na linha "Inscreva-se".

Uso: uv run py scripts/08_descricao.py <stem>
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import json
import re
from _canal import CANAL_URL, eh_nosso_canal
from _descricoes import trocar_creditos
from _grafias import carregar as carregar_grafias, corrigir as corrigir_grafia
from _paths import achar_pasta, stem_de

ROOT = Path(__file__).parent.parent
PLACEHOLDER_URL = "[COLAR URL DA LIVE AQUI]"

# Tags fixas do canal — vao em toda descricao
TAGS_BASE = [
    "Missão em Cortes", "Partido Missão", "Missão 14", "MBL",
    "direita liberal", "política brasileira",
]
# Hashtags fixas no fim da descricao (max 3 por boa pratica YouTube)
HASHTAGS_BASE = ["#MissãoEmCortes", "#PartidoMissão14", "#MBL"]

def slugify_hashtag(s):
    """Transforma 'arthur do val' em '#ArthurDoVal'."""
    s = re.sub(r"[^\w\s]", "", s, flags=re.UNICODE)
    palavras = [p.capitalize() for p in s.split()]
    return "#" + "".join(palavras)

def ler_url_fonte(stem, inputs=None):
    """URL da fonte salva pelo 01_baixar.py em inputs/<stem>.url ("" se faltar).

    Link do NOSSO canal não é fonte: descarta com aviso (cai pro placeholder, e o
    09_upload se recusa a subir sem crédito).
    """
    arq = (inputs or ROOT / "inputs") / f"{stem}.url"
    url = arq.read_text(encoding="utf-8").strip() if arq.exists() else ""
    if url and eh_nosso_canal(url):
        print(f"   [!] {arq.name} aponta pro NOSSO canal, não pra fonte — ignorando")
        return ""
    return url

def bloco_para_texto(b, url_fonte=""):
    # grafia oficial em tudo que vai pro YouTube (título, corpo, convidados, tags/hashtags)
    grafias = carregar_grafias()   # lê o config uma vez por bloco, não por campo
    titulo = corrigir_grafia(b.get("titulo_sugerido", b["tema"]), grafias)
    resumo = corrigir_grafia(b.get("resumo", "").strip(), grafias)
    ganchos = [corrigir_grafia(g, grafias) for g in b.get("ganchos", [])]
    tags_bloco = [corrigir_grafia(t, grafias) for t in b.get("tags", [])]
    speakers = [corrigir_grafia(s, grafias) for s in b.get("speakers_principais", [])]

    # Tags combinadas (sem duplicar, mantem ordem)
    tags_final = []
    for t in [*tags_bloco, *TAGS_BASE]:
        if t.lower() not in [x.lower() for x in tags_final]:
            tags_final.append(t)

    # Hashtags (3 do canal + 2 do bloco)
    hashtags = list(HASHTAGS_BASE)
    for t in tags_bloco[:2]:
        h = slugify_hashtag(t)
        if h not in hashtags:
            hashtags.append(h)

    linhas = []
    linhas.append("=" * 70)
    linhas.append(f"VÍDEO {b['id']:02d} — {b['tema']}")
    linhas.append("=" * 70)
    linhas.append("")
    linhas.append(f"TÍTULO ({len(titulo)} chars):")
    linhas.append(titulo)
    linhas.append("")
    linhas.append("-" * 70)
    linhas.append("DESCRIÇÃO:")
    linhas.append("-" * 70)
    linhas.append("")
    linhas.append(resumo)
    linhas.append("")
    if ganchos:
        linhas.append("Principais momentos:")
        for g in ganchos:
            linhas.append(f"• {g}")
        linhas.append("")
    linhas.append("─" * 40)
    linhas.append(f"🎬 Inscreva-se no canal pra acompanhar mais cortes do Partido Missão (14): {CANAL_URL}")
    if speakers:
        linhas.append(f"🎙️ Convidado(s): {', '.join(speakers)}")
    linhas.append(f"📺 Conteúdo original: {url_fonte or PLACEHOLDER_URL}")
    linhas.append("")
    linhas.append(" ".join(hashtags))
    linhas.append("")
    linhas.append("-" * 70)
    linhas.append("TAGS (separadas por vírgula, copiar pro YouTube Studio):")
    linhas.append("-" * 70)
    linhas.append(", ".join(tags_final))
    linhas.append("")
    linhas.append("")
    return "\n".join(linhas)

def repor_creditos(texto, pasta, blocos):
    """Bloco com thumb colagem aplicada (modo padrão) usa foto do banco com licença aberta: o
    crédito dela é obrigatório. Regerar o txt não pode apagar, então volta do colagem.json."""
    from _colagem import colagem_aplicada
    for b in blocos:
        reg = colagem_aplicada(pasta / "thumbs", b["id"])
        if reg and reg.get("creditos"):
            texto = trocar_creditos(texto, b["id"], reg["creditos"])
    return texto

def main(argv):
    pasta = achar_pasta(argv[0] if argv else "live_teste")
    stem = stem_de(pasta)
    blocos_json = pasta / "blocos.json"
    out = pasta / "descricoes.txt"
    url_fonte = ler_url_fonte(stem)

    with blocos_json.open(encoding="utf-8") as f:
        data = json.load(f)

    cabecalho = [
        f"# Descrições — {stem}",
        f"# Fonte: {blocos_json.name}",
        f"# {len(data['blocos'])} blocos · gerado automaticamente",
    ]
    if not url_fonte:
        cabecalho.append("# Lembrete: preencher a URL da live original em cada bloco antes de subir")
    cabecalho += ["", ""]

    partes = ["\n".join(cabecalho)]
    for b in data["blocos"]:
        partes.append(bloco_para_texto(b, url_fonte))

    texto = repor_creditos("\n".join(partes), pasta, data["blocos"])
    out.write_text(texto, encoding="utf-8")
    print(f"OK {len(data['blocos'])} descrições salvas em {out}")
    if url_fonte:
        print(f"   URL da fonte preenchida: {url_fonte}")
    else:
        print(f"   [!] sem URL da fonte válida em inputs/{stem}.url — preencha a URL da live à mão antes de subir")
    print(f"   Total: {len(out.read_text(encoding='utf-8'))} caracteres")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
