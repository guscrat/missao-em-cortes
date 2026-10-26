"""Step 16 (off-pipeline): resultado do "Testar e comparar" das thumbs → state/thumb_ab.json
(agente="analista"). Junta os testes do modo ab (config/thumb.json: a = template, b/c = colagem)
pra decidir o estilo padrão com dado, não no olho.

Uso:
  uv run py scripts/16_thumb_ab.py registrar <stem> <vídeo> <a|b|c|empate> [--a=41.2 --b=35 --c=23.8] [--nota="..."]
  uv run py scripts/16_thumb_ab.py placar

  registrar: o vídeo é o número do bloco (o "VÍDEO 05" do publicacao.txt). A vencedora é a
             letra que o Studio apontou ("Vencedora" / "Teve melhor desempenho"); "empate" quando
             o Studio diz que não houve diferença. --a/--b/--c = % do tempo de exibição de cada
             thumb (opcional, o Studio mostra). O estilo de cada letra é lido das thumbs do bloco
             na hora (thumb_NN_a/b/c vs a colagem aplicada): registre antes de regerar thumbs.
             Registrar de novo o mesmo vídeo substitui.
  placar:    vitórias por estilo, só nos testes com os 2 estilos (bloco sem colagem não conta).

O YouTube não expõe o resultado do "Testar e comparar" na Data API nem na Analytics API
(out/2026): por isso é à mão. Se um dia expuser, o 12 chama registrar() direto.
Custo: US$ 0.
"""
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import datetime
from pathlib import Path

from _eventos import evento, ler_bloco
from _paths import achar_pasta, stem_de

ROOT = Path(__file__).parent.parent
SAIDA = ROOT / "state" / "thumb_ab.json"
MIN_TESTES = 5        # abaixo disso o placar não sugere padrão (ruído)


def ler() -> dict:
    try:
        return json.loads(SAIDA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"testes": {}}


def estilos(pasta: Path, bid: int) -> dict[str, str]:
    """{letra: 'template' | 'colagem'} das thumbs a/b/c do bloco (as que sobem no teste)."""
    from _publicacao import thumbs_do_teste
    return {t.stem[-1]: estilo for t, estilo in thumbs_do_teste(pasta, bid, None)}


def registrar(stem_ou_pasta: str, bid: int, vencedora: str, watch: dict[str, float] | None = None,
              nota: str = "") -> dict:
    vencedora = vencedora.lower()
    if vencedora not in ("a", "b", "c", "empate"):
        raise ValueError(f"vencedora '{vencedora}': use a, b, c ou empate")
    pasta = achar_pasta(stem_ou_pasta)
    stem = stem_de(pasta)
    por_letra = estilos(pasta, bid)
    if not por_letra:
        raise ValueError(f"bloco {bid:02d} de {stem} sem thumbs (thumbs/thumb_{bid:02d}_a/b/c.png)")
    if vencedora != "empate" and vencedora not in por_letra:
        raise ValueError(f"bloco {bid:02d} não tem thumb '{vencedora}' (tem {', '.join(por_letra)})")
    teste = {"stem": stem, "bloco": bid, "vencedora": vencedora,
             "estilo_vencedor": por_letra.get(vencedora, "empate"),
             "estilos": por_letra, "misto": len(set(por_letra.values())) > 1,
             "watch_time_pct": watch or {}, "nota": nota,
             "youtube_id": (ler_bloco(stem, bid) or {}).get("youtube_id"),
             "registrado": datetime.now().astimezone().isoformat(timespec="seconds")}
    dados = ler()
    dados.setdefault("testes", {})[f"{stem}#{bid:02d}"] = teste
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    evento(stem, "16_thumb_ab", "ok", agente="analista", bloco_id=bid,
           mensagem=f"Testar e comparar: venceu {vencedora} ({teste['estilo_vencedor']})")
    return teste


def placar(dados: dict | None = None) -> dict:
    """{template, colagem, empate, testes, fora}: só testes com os 2 estilos contam."""
    testes = list((dados or ler()).get("testes", {}).values())
    mistos = [t for t in testes if t.get("misto")]
    contagem = {"template": 0, "colagem": 0, "empate": 0}
    for t in mistos:
        contagem[t["estilo_vencedor"] if t["estilo_vencedor"] in contagem else "empate"] += 1
    return {**contagem, "testes": len(mistos), "fora": len(testes) - len(mistos)}


def sugestao(p: dict) -> str:
    decididos = p["template"] + p["colagem"]
    if decididos < MIN_TESTES:
        return f"ainda pouco dado: {decididos}/{MIN_TESTES} testes com vencedor pra sugerir um padrão"
    lider = max(("template", "colagem"), key=lambda e: p[e])
    if p[lider] * 3 >= decididos * 2:                 # ≥ 2/3 das vitórias
        return (f"{lider} venceu {p[lider]} de {decididos}: dá pra virar o padrão "
                f"(config/thumb.json → colagem: {'padrao' if lider == 'colagem' else 'desligado'})")
    return f"sem estilo dominante ({p['template']} x {p['colagem']}): seguir no ab"


def main(argv: list[str]) -> int:
    pos = [a for a in argv if not a.startswith("--")]
    flags = dict(a[2:].split("=", 1) if "=" in a else (a[2:], "") for a in argv if a.startswith("--"))
    if pos[:1] == ["registrar"] and len(pos) == 4:
        try:
            watch = {l: float(flags[l].replace(",", ".")) for l in "abc" if flags.get(l)}
            t = registrar(pos[1], int(pos[2]), pos[3], watch, flags.get("nota", ""))
        except ValueError as e:
            print(f"[!] {e}", file=sys.stderr)
            return 1
        print(f"OK {t['stem']} vídeo {t['bloco']:02d}: venceu {t['vencedora']} ({t['estilo_vencedor']})"
              + ("" if t["misto"] else " — teste sem colagem, não conta no placar") + f" → {SAIDA}")
        return 0
    if pos[:1] == ["placar"]:
        p = placar()
        print(f"Testar e comparar (template x colagem), {p['testes']} teste(s): "
              f"template {p['template']} · colagem {p['colagem']} · empate {p['empate']}"
              + (f" · {p['fora']} sem colagem (não contam)" if p["fora"] else ""))
        print(sugestao(p))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
