"""Parser do descricoes.txt (formato do 08_descricao.py), compartilhado pelo 09 e pelo 11,
e a manchete do Short (10 queima, 09 usa de título, 14 reconhece).

Edição manual no txt vale: é o que vai pro YouTube, então é o que o revisor confere.
"""
import re

LIMITE_MANCHETE = 60   # chars: título do Short no YouTube

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


def manchete(bloco: dict) -> str:
    """Manchete do Short: texto_thumb (já passou pelo revisor), senão o tema; espaços
    normalizados e, se passar de LIMITE_MANCHETE, cortada em palavra inteira. É o texto
    queimado no topo (10), o título no YouTube (09) e uma chave de casamento do 14."""
    texto = " ".join((bloco.get("texto_thumb") or bloco.get("tema") or "").split())
    if len(texto) <= LIMITE_MANCHETE:
        return texto
    return texto[:LIMITE_MANCHETE + 1].rsplit(" ", 1)[0].rstrip(" ,;:—-")


def adicionar_credito(texto: str, bloco_id: int, linha: str) -> str:
    """Põe `linha` (crédito de foto com licença aberta) no fim da DESCRIÇÃO de UM bloco.
    Idempotente: se a linha já está lá, não repete."""
    texto = texto.replace("\r\n", "\n")
    cabecalhos = list(_CABECALHO_BLOCO.finditer(texto))
    for i, cab in enumerate(cabecalhos):
        if int(cab.group(1)) != bloco_id:
            continue
        fim = cabecalhos[i + 1].start() if i + 1 < len(cabecalhos) else len(texto)
        trecho = texto[cab.end():fim]
        miolo = _CORPO.search(trecho)
        if not miolo or linha in miolo.group(1):
            return texto
        pos = cab.end() + miolo.end(1)
        return texto[:pos] + f"\n{linha}" + texto[pos:]
    return texto


_LINHA_CREDITO = re.compile(r"\n?^Foto de [^\n]*\(fundo removido\)$", re.M)


def trocar_creditos(texto: str, bloco_id: int, linhas: list[str]) -> str:
    """Tira os créditos de foto antigos (linhas 'Foto de ... (fundo removido)') da DESCRIÇÃO de
    UM bloco e põe `linhas` no lugar. Lista vazia só tira."""
    texto = texto.replace("\r\n", "\n")
    cabecalhos = list(_CABECALHO_BLOCO.finditer(texto))
    for i, cab in enumerate(cabecalhos):
        if int(cab.group(1)) != bloco_id:
            continue
        fim = cabecalhos[i + 1].start() if i + 1 < len(cabecalhos) else len(texto)
        trecho = texto[cab.end():fim]
        miolo = _CORPO.search(trecho)
        if not miolo:
            return texto
        limpo = _LINHA_CREDITO.sub("", miolo.group(1))
        trecho = trecho[:miolo.start(1)] + limpo + trecho[miolo.end(1):]
        texto = texto[:cab.end()] + trecho + texto[fim:]
        for linha in linhas:
            texto = adicionar_credito(texto, bloco_id, linha)
        return texto
    return texto


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
