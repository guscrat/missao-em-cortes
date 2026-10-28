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

import _custo
import _grafias
from _descricoes import trocar_creditos, trocar_titulo

MODELO = "claude-opus-5-5"
CUSTO_ESTIMADO = 0.01                  # só pro --dry-run
MAX_RODADAS = 2
MAX_TITULO = 70
SCRIPTS = Path(__file__).parent
GRAFIAS_PEDIDO = ("GRAFIAS OFICIAIS (nome de pessoa sempre assim, mesmo que a transcrição ou as "
                  "tags escrevam diferente):")

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
- Toda fala citada (no título, na thumb ou entre aspas) tem que estar DENTRO da transcrição \
deste trecho: nada de frase dita em outro momento da live.
- Continue com gancho: título ousado e curioso é bem-vindo, desde que fiel.
- Título e texto da thumb NUNCA destacam palavrão nem termo que possa soar como ofensa a um \
grupo (raça, etnia, gênero, orientação sexual, religião, origem, deficiência etc.), MESMO que \
esteja na fala. Descreva o tom ("desabafo sem filtro", "detona") em vez de citar o termo.
- titulo: no máximo {MAX_TITULO} caracteres, no formato do canal ("Nome: 'gancho'" funciona bem).
- texto_thumb: 2 a 5 palavras de impacto, no máximo 28 caracteres, diferente do título.
- Números, datas, fatos e nomes batem EXATAMENTE com a transcrição; nome de pessoa sempre na \
grafia oficial da lista do pedido.
- Não repita tentativas que o revisor já reprovou.
- Se o pedido trouxer TERMOS QUE O PÚBLICO BUSCA, prefira usar um deles no título (é \
o que traz view pela busca do YouTube), mas SÓ se o trecho for sobre aquilo. Nunca force um \
termo que a transcrição não sustenta.
- mudanca: uma frase curta em português dizendo o que você corrigiu."""


def montar_pedido(titulo: str, texto_thumb: str, problema: str, transcricao: str,
                  tentativas: list[dict], termos: list[str] | None = None) -> str:
    """termos: os da busca do YouTube que mais trouxeram views na semana (17_analytics)."""
    linhas = [f"TÍTULO REPROVADO: {titulo}", f"TEXTO DA THUMB: {texto_thumb}",
              f"PROBLEMA APONTADO PELO REVISOR: {problema}"]
    for i, t in enumerate(tentativas, 1):
        linhas.append(f"TENTATIVA {i} (também reprovada): {t['titulo']} | thumb: "
                      f"{t['texto_thumb']} | motivo: {t['problema']}")
    if termos:
        linhas += ["", "TERMOS QUE O PÚBLICO BUSCA (busca do YouTube, mais views na semana): "
                   + "; ".join(termos)]
    linhas += ["", GRAFIAS_PEDIDO, _grafias.para_prompt(), "", "TRANSCRIÇÃO DO TRECHO:", transcricao]
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
    novo["titulo"] = _grafias.corrigir(novo["titulo"].strip())[:100]   # limite duro do YouTube
    novo["texto_thumb"] = _grafias.corrigir(novo["texto_thumb"].strip())
    return novo, resp


MAX_LINHA_COLAGEM = 16

SCHEMA_COLAGEM = {
    "type": "object",
    "properties": {
        "opcoes": {"type": "array", "items": {
            "type": "object",
            "properties": {"linha1": {"type": "string"}, "linha2": {"type": "string"}},
            "required": ["linha1", "linha2"], "additionalProperties": False}},
    },
    "required": ["opcoes"],
    "additionalProperties": False,
}

SISTEMA_COLAGEM = f"""Você é o editor do canal "Missão em Cortes", que publica cortes de lives \
e entrevistas do Partido Missão. Escreva 3 opções DIFERENTES de texto para a thumbnail estilo \
canal de react: 2 linhas curtas e grandes, em MAIÚSCULAS.

Regras:
- De preferência em forma de pergunta (gera curiosidade), mas só se a transcrição sustentar. \
Só afirme o que a fala sustenta: nada de atribuir ao speaker frase, alvo ou promessa que ele \
não disse. Números, datas, fatos e nomes têm que bater EXATAMENTE com a transcrição (o \
revisor reprova "3 INQUÉRITOS" se a fala diz 2).
- Nome de pessoa sempre na grafia oficial da lista do pedido.
- Cada linha com no máximo {MAX_LINHA_COLAGEM} caracteres (contando espaços e pontuação).
- Marque com *asteriscos* 1 ou 2 palavras de impacto (vão em amarelo). Se citar o nome da \
pessoa comentada, marque com [colchetes] (vai em vermelho), ex.: "[LULA] VAI *CAIR*?". \
No máximo um nome por opção.
- O nome em [colchetes] fica ao lado da CENA DESTACADA (a que leva círculo/seta vermelha). \
Só use [nome] se a descrição dessa cena diz que é essa pessoa; se não diz quem é, escreva \
sem nome em vermelho. Nunca ponha o nome de uma pessoa ao lado da foto de outra.
- NUNCA destaque palavrão nem termo que possa soar como ofensa a um grupo (raça, etnia, \
gênero, orientação sexual, religião, origem, deficiência etc.), MESMO que esteja na fala.
- Diferente do título do YouTube (não repita a frase)."""


def montar_pedido_colagem(titulo: str, texto_thumb: str, destacada: str, outra: str,
                          transcricao: str) -> str:
    linhas = [f"TÍTULO DO YOUTUBE: {titulo}", f"TEXTO DA THUMB ATUAL: {texto_thumb}",
              f"CENA DESTACADA (círculo/seta): {destacada or 'sem descrição (não use nome)'}",
              f"OUTRA CENA: {outra or 'sem descrição'}",
              "", GRAFIAS_PEDIDO, _grafias.para_prompt(),
              "", "TRANSCRIÇÃO DO TRECHO:", transcricao]
    return "\n".join(linhas)


def opcao_valida(linhas: list[str]) -> bool:
    """2 linhas, cada uma cabendo em MAX_LINHA_COLAGEM sem as marcas, 1-2 amarelas, até 1 nome."""
    import _colagem as col
    if len(linhas) != 2 or not all(l.strip() for l in linhas):
        return False
    junto = " ".join(linhas)
    amarelas = sum(1 for _, c in (p for l in linhas for p in col.pedacos(l)) if c == col.AMARELO)
    nomes = junto.count("[")
    return (all(len(col.sem_marcas(l)) <= MAX_LINHA_COLAGEM + 2 for l in linhas)
            and 1 <= amarelas <= 2 and nomes <= 1 and junto.count("*") % 2 == 0)


def texto_colagem(client, pedido: str) -> tuple[list[list[str]] | None, object]:
    """([[linha1, linha2], ...] só as opções válidas, ou None se recusou, resposta)."""
    resp = client.beta.messages.create(
        model=MODELO,
        max_tokens=8000,
        system=SISTEMA_COLAGEM,
        messages=[{"role": "user", "content": pedido}],
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": SCHEMA_COLAGEM}},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
    )
    if resp.stop_reason == "refusal":
        return None, resp
    # Resposta paga mas ilegível volta [] (não exceção) pra o custo ainda ser logado
    texto = next((b.text for b in resp.content if b.type == "text"), None)
    try:
        opcoes = [[_grafias.corrigir(o["linha1"].strip().upper()),
                   _grafias.corrigir(o["linha2"].strip().upper())]
                  for o in json.loads(texto)["opcoes"]]
    except (TypeError, ValueError, KeyError, AttributeError):
        return [], resp
    return [o for o in opcoes if opcao_valida(o)][:3], resp


MAX_TEXTO_THUMB = 28

SCHEMA_THUMB_AB = {
    "type": "object",
    "properties": {"opcoes": {"type": "array", "items": {"type": "string"}}},
    "required": ["opcoes"],
    "additionalProperties": False,
}

SISTEMA_THUMB_AB = f"""Você é o editor do canal "Missão em Cortes", que publica cortes de lives \
e entrevistas do Partido Missão. A thumb deste corte vai pro "Testar e comparar" do YouTube \
com 3 textos. O primeiro já existe (TEXTO DA THUMB ATUAL). Escreva mais 2 opções \
DIFERENTES dele e entre si, com outro ângulo (ex.: uma em pergunta, outra afirmando o \
gancho mais forte), pra o teste dizer qual tipo de texto funciona.

Regras:
- 2 a 5 palavras de impacto, no máximo {MAX_TEXTO_THUMB} caracteres, em MAIÚSCULAS.
- Só afirme o que o resumo e os ganchos sustentam. Nada de atribuir ao speaker frase, alvo \
ou promessa que ele não disse. Números, datas, fatos e nomes batem EXATAMENTE com o pedido; \
nome de pessoa sempre na grafia oficial da lista.
- NUNCA destaque palavrão nem termo que possa soar como ofensa a um grupo (raça, etnia, \
gênero, orientação sexual, religião, origem, deficiência etc.), MESMO que esteja na fala.
- Diferente do título do YouTube (não repita a frase)."""


def montar_pedido_thumb_ab(titulo: str, texto_thumb: str, bloco: dict) -> str:
    """Sem a transcrição (barato): resumo + ganchos (frases do trecho). O revisor confere as
    3 contra a transcrição depois."""
    linhas = [f"TÍTULO DO YOUTUBE: {titulo}", f"TEXTO DA THUMB ATUAL: {texto_thumb}",
              f"RESUMO DO TRECHO: {bloco.get('resumo', '')}",
              "GANCHOS (frases ditas no trecho):", *[f"- {g}" for g in bloco.get("ganchos") or []],
              "", GRAFIAS_PEDIDO, _grafias.para_prompt()]
    return "\n".join(linhas)


def textos_thumb_ab(client, pedido: str, atual: str) -> tuple[list[str] | None, object]:
    """([até 2 textos válidos e diferentes do atual] ou None se recusou, resposta)."""
    resp = client.beta.messages.create(
        model=MODELO,
        max_tokens=4000,
        system=SISTEMA_THUMB_AB,
        messages=[{"role": "user", "content": pedido}],
        output_config={"effort": "low",
                       "format": {"type": "json_schema", "schema": SCHEMA_THUMB_AB}},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
    )
    if resp.stop_reason == "refusal":
        return None, resp
    # Resposta paga mas ilegível volta [] (não exceção) pra o custo ainda ser logado
    texto = next((b.text for b in resp.content if b.type == "text"), None)
    try:
        opcoes = [_grafias.corrigir(o.strip().upper()) for o in json.loads(texto)["opcoes"]]
    except (TypeError, ValueError, KeyError, AttributeError):
        return [], resp
    vistos, validas = {atual.strip().upper()}, []
    for o in opcoes:
        if o and len(o) <= MAX_TEXTO_THUMB and o not in vistos:
            vistos.add(o)
            validas.append(o)
    return validas[:2], resp


def custo(resp) -> tuple[int, int, float]:
    u = _custo.uso(resp, MODELO)
    return u["tokens_in"], u["tokens_out"], u["custo_usd"]


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


def _colagem_aplicada(thumb: Path) -> dict | None:
    import _colagem
    return _colagem.variante_aplicada(thumb)


def voltar_template(pasta: Path, bid: int, letras: tuple[str, ...] = ()) -> bool:
    """Tira a colagem do bloco: refaz no template atual (07) as variantes `letras` (vazio = a/b/c;
    modo ab = b/c) e tira da descrição o crédito da foto do banco (a foto saiu da thumb).
    True se o 07 rodou."""
    base = [sys.executable, str(SCRIPTS / "07_thumb.py"), pasta.name, f"--bloco={bid}"]
    for cmd in [[*base, f"--variante={l}"] for l in letras] or [base]:
        if subprocess.run(cmd, capture_output=True).returncode:
            return False
    desc = pasta / "descricoes.txt"
    if desc.exists():
        desc.write_text(trocar_creditos(desc.read_text(encoding="utf-8"), bid, []), encoding="utf-8")
    return True


def refazer_colagem_ab(pasta: Path, bid: int) -> list[str]:
    """Modo ab: a 'a' (template) já foi refeita; as colagens b/c ainda têm o texto antigo.
    Refaz com o texto_thumb novo (--sem-editor); não saiu → b/c voltam pro template."""
    import _colagem
    if not _colagem.colagem_ab(pasta / "thumbs", bid):
        return []
    r = subprocess.run([sys.executable, str(SCRIPTS / "07b_colagem.py"), pasta.name,
                        f"--bloco={bid}", "--ab", "--sem-editor"], capture_output=True)
    if not r.returncode:
        return []
    if voltar_template(pasta, bid, ("b", "c")):
        return ["colagem (b/c) não saiu com o texto novo: voltou pro template atual"]
    return ["colagem (b/c) não saiu com o texto novo e falhou ao voltar pro template"]


def refazer_classica_ab(pasta: Path, bid: int, feita: str) -> list[str]:
    """Modo ab da clássica: as outras variantes (b/c) ainda têm os textos alternativos do
    texto_thumb antigo. Refaz cada uma no mesmo frame; o 07 cai pro texto_thumb novo (as
    alternativas valem só pro texto de que saíram), sem chamar o editor de novo."""
    from _paths import modo_thumb
    if modo_thumb() != "ab":
        return []
    for letra in "abc":
        if letra == feita or not (pasta / "thumbs" / f"thumb_{bid:02d}_{letra}.png").exists():
            continue
        r = subprocess.run([sys.executable, str(SCRIPTS / "07_thumb.py"), pasta.name,
                            f"--bloco={bid}", f"--variante={letra}"], capture_output=True)
        if r.returncode:
            return [f"falhou ao refazer a thumb {letra} com o texto novo"]
    return []


def refazer_artes(pasta: Path, bid: int, thumb: Path | None) -> list[str]:
    """Refaz a thumb escolhida e o Short com o texto novo. Devolve avisos (não derruba)."""
    nn, avisos = f"{bid:02d}", []
    py = [sys.executable]
    if thumb and thumb.stem.endswith("_manual"):
        avisos.append("thumb manual tem o texto antigo — refaça com 07_thumb.py --bloco="
                      f"{bid} --t=MM:SS")
    elif thumb and _colagem_aplicada(thumb):
        # thumb colagem (modo padrão): refaz a colagem com o texto_thumb novo, sem o editor da
        # colagem escrever outro texto por cima do que o revisor vai reavaliar. Não saiu →
        # template atual nas 3 variantes, pra nenhuma ficar com o texto reprovado.
        r = subprocess.run([*py, str(SCRIPTS / "07b_colagem.py"), pasta.name, f"--bloco={bid}",
                            "--aplicar", "--sem-editor"], capture_output=True)
        if r.returncode:
            avisos.append("colagem não saiu com o texto novo: voltou pro template atual")
            if not voltar_template(pasta, bid):
                avisos.append("falhou ao refazer a thumb")
    elif thumb:
        variante = thumb.stem.rsplit("_", 1)[-1]
        cmd = [*py, str(SCRIPTS / "07_thumb.py"), pasta.name, f"--bloco={bid}"]
        if variante in ("a", "b", "c"):
            cmd.append(f"--variante={variante}")
        if subprocess.run(cmd, capture_output=True).returncode:
            avisos.append("falhou ao refazer a thumb")
        avisos += refazer_classica_ab(pasta, bid, variante)
        avisos += refazer_colagem_ab(pasta, bid)
    if any((pasta / "shorts").glob(f"short_{nn}_*.mp4")):
        r = subprocess.run([*py, str(SCRIPTS / "10_shorts.py"), pasta.name, f"--bloco={bid}"],
                           capture_output=True)
        if r.returncode:
            avisos.append("falhou ao refazer o Short")
    return avisos
