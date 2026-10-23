"""Parser do descricoes.txt (formato do 08_descricao.py), compartilhado pelo 09 e pelo 11,
e o texto do Short: manchete (10 queima) e título "manchete | quem fala" (09 sobe, 14 reconhece).

Edição manual no txt vale: é o que vai pro YouTube, então é o que o revisor confere.
"""
import json
import re
from pathlib import Path

import _grafias

CANAIS = Path(__file__).parent.parent / "config" / "canais.json"
LIMITE_MANCHETE = 60   # chars: manchete queimada e título do Short no YouTube

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


def _cortar(texto: str, limite: int) -> str:
    """Corta em palavra inteira pra caber em `limite` (palavra única gigante: corte seco)."""
    if len(texto) <= limite:
        return texto
    corte = texto[:limite + 1]
    if " " not in corte:
        return texto[:limite]
    return corte.rsplit(" ", 1)[0].rstrip(" ,;:—-")


def manchete(bloco: dict, limite: int = LIMITE_MANCHETE) -> str:
    """Manchete do Short: texto_thumb (já passou pelo revisor), senão o tema, com as grafias
    oficiais (também em CAIXA ALTA) e cortada em palavra inteira se passar de `limite`. É o
    texto queimado no topo do Short (10)."""
    texto = " ".join((bloco.get("texto_thumb") or bloco.get("tema") or "").split())
    return _cortar(_grafias.corrigir(texto), limite)


def _dono_do_canal(stem: str) -> str:
    """Nome do canal pelo prefixo do stem em config/canais.json (ex.: 'Mamãefalei (Arthur do Val)')."""
    try:
        canais = json.loads(CANAIS.read_text(encoding="utf-8"))["canais"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    prefixo = stem.split("_", 1)[0]
    return next((c.get("nome", "") for c in canais if c.get("prefixo") == prefixo), "")


def quem_fala(bloco: dict, stem: str = "") -> str:
    """Nome oficial (grafias) de quem fala: o 1º de speakers_principais que é personagem
    conhecido; senão o dono do canal (prefixo do stem). '' se não der pra saber."""
    for fonte in [*(bloco.get("speakers_principais") or []), _dono_do_canal(stem)]:
        nomes = _grafias.citados([fonte]) if fonte else []
        if nomes:
            return nomes[0]
    return ""


def titulo_short(bloco: dict, stem: str = "") -> str:
    """Título do Short no YouTube: "MANCHETE | Nome de quem fala", até LIMITE_MANCHETE chars.
    Se não couber, corta a manchete (nunca o nome). '' sem manchete ou sem quem fala."""
    nome = quem_fala(bloco, stem)
    if not nome:
        return ""
    sufixo = f" | {nome}"
    if len(sufixo) >= LIMITE_MANCHETE:       # nome não deixa espaço pra manchete (nunca corta o nome)
        return ""
    m = manchete(bloco, LIMITE_MANCHETE - len(sufixo))
    return f"{m}{sufixo}" if m else ""


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
