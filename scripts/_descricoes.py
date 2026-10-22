"""Parser do descricoes.txt (formato do 08_descricao.py), compartilhado pelo 09 e pelo 11.

Edição manual no txt vale: é o que vai pro YouTube, então é o que o revisor confere.
"""
import re

_CABECALHO_BLOCO = re.compile(r"^=+\nVÍDEO (\d+) — [^\n]*\n=+\n", re.M)
_TITULO = re.compile(r"^TÍTULO \(\d+ chars\):\n(.+)$", re.M)
_CORPO = re.compile(r"^-+\nDESCRIÇÃO:\n-+\n(.*?)\n-+\nTAGS[^\n]*\n-+\n([^\n]*)", re.M | re.S)


def ler_descricoes(texto: str) -> dict[int, dict]:
    """{bloco_id: {"titulo", "descricao", "tags"}} a partir do descricoes.txt."""
    partes = _CABECALHO_BLOCO.split(texto.replace("\r\n", "\n"))
    saida = {}
    for bid, corpo in zip(partes[1::2], partes[2::2]):
        titulo, miolo = _TITULO.search(corpo), _CORPO.search(corpo)
        if not (titulo and miolo):
            continue
        saida[int(bid)] = {
            "titulo": titulo.group(1).strip(),
            "descricao": miolo.group(1).strip(),
            "tags": [t.strip() for t in miolo.group(2).split(",") if t.strip()],
        }
    return saida


def trocar_titulo(texto: str, bloco_id: int, novo: str) -> str:
    """Troca o título (e a contagem de chars) de UM bloco, sem mexer no resto do txt."""
    texto = texto.replace("\r\n", "\n")
    cabecalhos = list(_CABECALHO_BLOCO.finditer(texto))
    for i, cab in enumerate(cabecalhos):
        if int(cab.group(1)) != bloco_id:
            continue
        fim = cabecalhos[i + 1].start() if i + 1 < len(cabecalhos) else len(texto)
        trecho = _TITULO.sub(lambda m: f"TÍTULO ({len(novo)} chars):\n{novo}",
                             texto[cab.end():fim], count=1)
        return texto[:cab.end()] + trecho + texto[fim:]
    return texto
