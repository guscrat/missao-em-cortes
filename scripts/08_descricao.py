"""Gera txt com titulo + descricao + tags por bloco pronto pra colar no YouTube.

Le do blocos.json (que ja tem titulo_sugerido, resumo, ganchos, tags) e monta
o arquivo formatado em outputs/<stem>_descricoes.txt. Sem chamada de API.

Uso: uv run py scripts/08_descricao.py outputs/<stem>_blocos.json
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import json
import re

ROOT = Path(__file__).parent.parent

input_arg = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "outputs" / "live_teste_blocos.json")
BLOCOS_JSON = Path(input_arg)
stem = BLOCOS_JSON.stem.replace("_blocos", "")
OUT = ROOT / "outputs" / f"{stem}_descricoes.txt"

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

def bloco_para_texto(b):
    titulo = b.get("titulo_sugerido", b["tema"])
    resumo = b.get("resumo", "").strip()
    ganchos = b.get("ganchos", [])
    tags_bloco = b.get("tags", [])
    speakers = b.get("speakers_principais", [])

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
    linhas.append("🎬 Inscreva-se no canal pra acompanhar mais cortes do Partido Missão (14).")
    if speakers:
        linhas.append(f"🎙️ Convidado(s): {', '.join(speakers)}")
    linhas.append("📺 Conteúdo original: [COLAR URL DA LIVE AQUI]")
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

with BLOCOS_JSON.open(encoding="utf-8") as f:
    data = json.load(f)

cabecalho = [
    f"# Descrições — {stem}",
    f"# Fonte: {BLOCOS_JSON.name}",
    f"# {len(data['blocos'])} blocos · gerado automaticamente",
    "# Lembrete: preencher a URL da live original em cada bloco antes de subir",
    "",
    "",
]

partes = [cabecalho_str := "\n".join(cabecalho)]
for b in data["blocos"]:
    partes.append(bloco_para_texto(b))

OUT.write_text("\n".join(partes), encoding="utf-8")
print(f"OK {len(data['blocos'])} descrições salvas em {OUT}")
print(f"   Total: {len(OUT.read_text(encoding='utf-8'))} caracteres")
