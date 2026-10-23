"""Grafias oficiais dos personagens (config/grafias.json), usadas pelo editor, pelo revisor e
pela colagem. Ex.: "Nikolas Ferreira", nunca "Nicolas".

- corrigir(texto): troca as grafias erradas conhecidas pela oficial (mantém CAIXA ALTA),
  sem tocar nas frases de "nao_trocar" (ex.: Nicolas Maduro), em qualquer caixa
- para_prompt(): a lista em texto, pro editor e o revisor
- citados(textos): nomes oficiais citados em tags/tema/título (casa nome, curto e erradas)
- variantes(nome): todas as formas de um personagem (pra casar com o banco de fotos)
"""
import json
import re
from pathlib import Path

ARQUIVO = Path(__file__).parent.parent / "config" / "grafias.json"


def carregar(arquivo: Path | None = None) -> list[dict]:
    try:
        dados = json.loads((arquivo or ARQUIVO).read_text(encoding="utf-8"))
        return [p for p in dados["personagens"] if p.get("nome")]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _trocas(lista: list[dict]) -> list[tuple[str, str]]:
    """(errada, oficial), as mais longas primeiro ('Nicolas Ferreira' antes de 'Nicolas').
    Errada com sobrenome vira o nome completo; palavra solta vira a forma curta."""
    pares = [(e, p["nome"] if " " in e else p.get("curto") or p["nome"])
             for p in lista for e in p.get("erradas", [])]
    return sorted(pares, key=lambda x: -len(x[0]))


def _nao_trocar(lista: list[dict]) -> list[str]:
    """Frases de outras pessoas com a grafia de um personagem ('Nicolas Maduro'), mais longas primeiro."""
    return sorted({f for p in lista for f in p.get("nao_trocar", []) if f}, key=len, reverse=True)


def corrigir(texto: str, lista: list[dict] | None = None) -> str:
    """Troca grafia errada pela oficial. Nunca toca nas frases de "nao_trocar" (ex.: 'Nicolas
    Maduro'), em qualquer caixa — é o que protege o texto da thumb/Short, todo em maiúsculas.
    Em texto misto, palavra solta seguida de outro nome próprio também fica como está."""
    if not texto:
        return texto
    lista = carregar() if lista is None else lista
    caixa_alta = texto.upper() == texto
    guardados: list[str] = []

    def guardar(m):
        guardados.append(m.group(0))
        return f"\x00{len(guardados) - 1}\x00"

    for frase in _nao_trocar(lista):
        texto = re.sub(rf"(?<!\w){re.escape(frase)}(?!\w)", guardar, texto, flags=re.I)
    for errada, oficial in _trocas(lista):
        padrao = re.compile(rf"(?<!\w){re.escape(errada)}(?!\w)", re.I)

        def trocar(m, oficial=oficial, errada=errada):
            if " " not in errada and not caixa_alta:
                seguinte = re.match(r"\s+(\w)", texto[m.end():])
                if seguinte and seguinte.group(1).isupper():
                    return m.group(0)
            return oficial.upper() if m.group(0).isupper() else oficial

        texto = padrao.sub(trocar, texto)
    return re.sub(r"\x00(\d+)\x00", lambda m: guardados[int(m.group(1))], texto)


def para_prompt(lista: list[dict] | None = None) -> str:
    """'- Nikolas Ferreira (curto: Nikolas; nunca: Nicolas, ...)' por linha."""
    lista = carregar() if lista is None else lista
    linhas = []
    for p in lista:
        extra = f"curto: {p['curto']}" if p.get("curto") and p["curto"] != p["nome"] else ""
        if p.get("erradas"):
            extra += ("; " if extra else "") + "nunca: " + ", ".join(p["erradas"])
        if p.get("nao_trocar"):
            extra += ("; " if extra else "") + "outra pessoa, não trocar: " + ", ".join(p["nao_trocar"])
        linhas.append(f"- {p['nome']}" + (f" ({extra})" if extra else ""))
    return "\n".join(linhas)


def _norm(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", t.lower())
    return " " + re.sub(r"[^a-z0-9 ]+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip() + " "


def variantes(nome: str, lista: list[dict] | None = None) -> list[str]:
    lista = carregar() if lista is None else lista
    p = next((p for p in lista if _norm(p["nome"]) == _norm(nome)), None)
    return [p["nome"], p.get("curto") or p["nome"], *p.get("erradas", [])] if p else [nome]


def citados(textos: list[str], excluir: str = "", lista: list[dict] | None = None) -> list[str]:
    """Nomes oficiais citados nos textos (na ordem da lista). `excluir` = o apresentador.
    Formas mais longas casam primeiro e saem do texto: 'Flávio Bolsonaro' não conta como
    'Bolsonaro' (Jair), nem 'Fábio Luís Lula da Silva' como 'Lula'."""
    lista = carregar() if lista is None else lista
    juntos = " ".join(_norm(t) for t in textos if t)
    fora = _norm(excluir) if excluir else ""
    formas = sorted(((_norm(f), p["nome"]) for p in lista for f in variantes(p["nome"], lista)),
                    key=lambda x: -len(x[0]))
    achados = set()
    for forma, nome in formas:
        if forma in juntos:
            achados.add(nome)
            juntos = juntos.replace(forma, " | ")
    excluidos = {nome for forma, nome in formas if fora and forma in fora}
    return [p["nome"] for p in lista if p["nome"] in achados - excluidos]
