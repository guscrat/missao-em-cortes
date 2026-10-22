"""Agente EDITOR: reescreve título + texto da thumb reprovados pelo revisor (step 11).

Regra de produto (quarentena):
  - título exagerado/infiel → o editor reescreve e o revisor reavalia, no máx. MAX_RODADAS;
    se o título reprovar nas MAX_RODADAS reescritas, aí sim vira decisão do Gu
  - problema de conteúdo (tela compartilhada, corte sem sentido) → o revisor descarta,
    não passa pelo editor

Aplicar a reescrita = trocar o título no descricoes.txt (é o que vai pro YouTube) e o
titulo_sugerido/texto_thumb no blocos.json (guarda os originais em *_original), refazer
a thumb escolhida (mesma variante, frame igual, texto novo) e o Short do bloco, se existir.

Custo: ~US$ 0.01 por reescrita (claude-opus-5-5, só texto). Logado com agente="editor".
"""
import json
import subprocess
import sys
from pathlib import Path

from _descricoes import trocar_titulo

MODELO = "claude-opus-5-5"
PRECO_IN, PRECO_OUT = 4.0, 20.0        # US$ por 1M tokens (opus 5.5)
CUSTO_ESTIMADO = 0.01                  # só pro --dry-run
MAX_RODADAS = 2
MAX_TITULO = 70
SCRIPTS = Path(__file__).parent

SCHEMA = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "texto_thumb": {"type": "string"},
        "mudanca": {"type": "string"},
    },
    "required": ["titulo", "texto_thumb", "mudanca"],
    "additionalProperties": False,
}

SISTEMA = f"""Você é o editor do canal "Missão em Cortes", que publica cortes de lives e \
entrevistas do Partido Missão. O revisor reprovou o título deste corte (infiel à fala, ou \
destacando palavrão/termo ofensivo). Reescreva o título do YouTube e o texto da thumb.

Regras:
- Só afirme o que a transcrição sustenta. Nada de atribuir ao speaker frase, alvo ou \
promessa que ele não disse. Corrija exatamente o problema apontado pelo revisor.
- Continue com gancho: título ousado e curioso é bem-vindo, desde que fiel.
- Título e texto da thumb NUNCA destacam palavrão nem termo que possa soar como ofensa a um \
grupo (raça, etnia, gênero, orientação sexual, religião, origem, deficiência etc.), MESMO que \
esteja na fala. Descreva o tom ("desabafo sem filtro", "detona") em vez de citar o termo.
- titulo: no máximo {MAX_TITULO} caracteres, no formato do canal ("Nome: 'gancho'" funciona bem).
- texto_thumb: 2 a 5 palavras de impacto, no máximo 28 caracteres, diferente do título.
- Não repita tentativas que o revisor já reprovou.
- mudanca: uma frase curta em português dizendo o que você corrigiu."""


def montar_pedido(titulo: str, texto_thumb: str, problema: str, transcricao: str,
                  tentativas: list[dict]) -> str:
    linhas = [f"TÍTULO REPROVADO: {titulo}", f"TEXTO DA THUMB: {texto_thumb}",
              f"PROBLEMA APONTADO PELO REVISOR: {problema}"]
    for i, t in enumerate(tentativas, 1):
        linhas.append(f"TENTATIVA {i} (também reprovada): {t['titulo']} | thumb: "
                      f"{t['texto_thumb']} | motivo: {t['problema']}")
    linhas += ["", "TRANSCRIÇÃO DO TRECHO:", transcricao]
    return "\n".join(linhas)


def reescrever(client, pedido: str) -> tuple[dict | None, object]:
    """({titulo, texto_thumb, mudanca} ou None se recusou, resposta)."""
    resp = client.beta.messages.create(
        model=MODELO,
        max_tokens=8000,
        system=SISTEMA,
        messages=[{"role": "user", "content": pedido}],
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
    )
    if resp.stop_reason == "refusal":
        return None, resp
    texto = next((b.text for b in resp.content if b.type == "text"), None)
    if texto is None:
        raise json.JSONDecodeError(f"resposta sem texto (stop_reason={resp.stop_reason})", "", 0)
    novo = json.loads(texto)
    novo["titulo"] = novo["titulo"].strip()[:100]          # limite duro do YouTube
    novo["texto_thumb"] = novo["texto_thumb"].strip()
    return novo, resp


def custo(resp) -> tuple[int, int, float]:
    tin, tout = resp.usage.input_tokens, resp.usage.output_tokens
    return tin, tout, tin / 1e6 * PRECO_IN + tout / 1e6 * PRECO_OUT


def gravar_texto(pasta: Path, bid: int, titulo: str, texto_thumb: str) -> None:
    """descricoes.txt + blocos.json (originais preservados na 1ª reescrita)."""
    blocos_path = pasta / "blocos.json"
    dados = json.loads(blocos_path.read_text(encoding="utf-8"))
    for b in dados["blocos"]:
        if b["id"] == bid:
            b.setdefault("titulo_original", b.get("titulo_sugerido", ""))
            b.setdefault("texto_thumb_original", b.get("texto_thumb", ""))
            b["titulo_sugerido"], b["texto_thumb"] = titulo, texto_thumb
    blocos_path.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    desc = pasta / "descricoes.txt"
    if desc.exists():
        desc.write_text(trocar_titulo(desc.read_text(encoding="utf-8"), bid, titulo),
                        encoding="utf-8")


def refazer_artes(pasta: Path, bid: int, thumb: Path | None) -> list[str]:
    """Refaz a thumb escolhida e o Short com o texto novo. Devolve avisos (não derruba)."""
    nn, avisos = f"{bid:02d}", []
    py = [sys.executable]
    if thumb and thumb.stem.endswith("_manual"):
        avisos.append("thumb manual tem o texto antigo — refaça com 07_thumb.py --bloco="
                      f"{bid} --t=MM:SS")
    elif thumb:
        variante = thumb.stem.rsplit("_", 1)[-1]
        cmd = [*py, str(SCRIPTS / "07_thumb.py"), pasta.name, f"--bloco={bid}"]
        if variante in ("a", "b", "c"):
            cmd.append(f"--variante={variante}")
        if subprocess.run(cmd, capture_output=True).returncode:
            avisos.append("falhou ao refazer a thumb")
    if any((pasta / "shorts").glob(f"short_{nn}_*.mp4")):
        r = subprocess.run([*py, str(SCRIPTS / "10_shorts.py"), pasta.name, f"--bloco={bid}"],
                           capture_output=True)
        if r.returncode:
            avisos.append("falhou ao refazer o Short")
    return avisos
