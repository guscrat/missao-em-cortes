"""Camada de estado do pipeline: SQLite em state/pipeline.db.

Todo script/agente registra o que fez aqui; o painel (painel/app.py) só LÊ.

Regra de ouro: o painel nunca derruba o pipeline. Toda escrita é best-effort —
se o banco falhar (lock, disco, etc.), loga um aviso e segue.

Tabelas:
  videos   — 1 linha por fonte (stem)
  blocos   — 1 linha por corte (stem + bloco_id), com o status no kanban
  eventos  — log append-only: quem (agente), o quê (etapa), status, tokens, custo
  tarefas  — tarefas macro do time de dev (o Gu acompanha no painel, aba "Time de dev")
  metricas_video / trafego_video / termos_busca / termos_canal — foto diária do YouTube
             Analytics (17_analytics, agente analista); o painel mostra na aba "Analytics"
  reach_dia / reach_relatorio — impressões e CTR da miniatura por vídeo e dia, do relatório
             Reach da YouTube Reporting API (17_analytics)
  em_alta  — vídeos antigos (30+ dias) cujas views dispararam na última semana, com o tema
             (17_analytics); painel, resumo semanal e Curador (prioriza lives desses temas)
  sugestoes — vídeos que o Curador (13) achou que valem virar corte; no modo "sugerir" o Gu
             escolhe no painel (botão Processar → status pedida → o 13 processa)

Uso:
    from _eventos import evento, upsert_video, upsert_bloco
    evento("renan_live3", "03_segmentar", "ok", agente="editor",
           tokens_in=40_000, tokens_out=3_000, custo_usd=0.17)
"""
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from _fronteira import faixa

ROOT = Path(__file__).parent.parent
DB_PATH = Path(os.environ.get("MISSAO_DB") or ROOT / "state" / "pipeline.db")
BUSY_TIMEOUT_S = 10   # espera por lock; o hook do Claude Code baixa pra caber em <1s

# Status de bloco, na ordem do fluxo. Os "AUTO" são derivados dos arquivos em
# outputs/ (sincronizar_estado.py pode sobrescrever). Os demais são decisões de
# agente/humano e NUNCA são rebaixados pela sincronização.
STATUS_AUTO = ["segmentado", "cortado", "montado"]
STATUS_DECISAO = ["revisao", "aprovado", "quarentena", "descartado", "agendado", "publicado",
                  "arquivado"]
STATUS_BLOCO = STATUS_AUTO + STATUS_DECISAO
# Ainda não foi pro YouTube nem foi descartado: é o que a regra de conteúdo antigo arquiva.
STATUS_ARQUIVAVEL = ["segmentado", "cortado", "montado", "revisao", "aprovado", "quarentena"]

STATUS_VIDEO = ["curadoria", "baixado", "transcrito", "segmentado", "descartado"]

STATUS_SUGESTAO = ["sugerida", "pedida", "processando", "processada", "falhou", "expirada"]
SUGESTAO_ABERTA = ["sugerida", "pedida", "processando", "falhou"]   # o que o painel mostra

ETAPAS_TAREFA = ["backlog", "fazendo", "testando", "revisando", "pronto", "bloqueado"]
ETAPAS_ATIVAS = ["fazendo", "testando", "revisando"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    stem        TEXT PRIMARY KEY,
    pasta       TEXT,
    fonte_url   TEXT,
    status      TEXT NOT NULL DEFAULT 'curadoria',
    criado_em   TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blocos (
    stem          TEXT NOT NULL REFERENCES videos(stem),
    bloco_id      INTEGER NOT NULL,
    tema          TEXT,
    titulo        TEXT,
    texto_thumb   TEXT,
    score         REAL,
    duracao_min   REAL,               -- duração real do corte (tempos encaixados no 03/11)
    faixa_duracao TEXT,               -- curto 5-10 | medio 10-20 | longo 20-30 | fora
    status        TEXT NOT NULL DEFAULT 'segmentado',
    motivo        TEXT,               -- por que foi pra quarentena/devolvido
    video_path    TEXT,
    thumb_path    TEXT,
    publish_at    TEXT,
    youtube_id    TEXT,
    titulo_youtube TEXT,              -- título real no canal (14_canal); o painel prefere ele
    atualizado_em TEXT NOT NULL,
    PRIMARY KEY (stem, bloco_id)
);

CREATE TABLE IF NOT EXISTS eventos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    stem        TEXT,
    bloco_id    INTEGER,
    agente      TEXT NOT NULL,        -- pipeline | curador | editor | revisor | publicador | analista
    etapa       TEXT NOT NULL,        -- ex: 03_segmentar, revisao_titulo
    status      TEXT NOT NULL,        -- inicio | ok | falha | aviso | aprovado | devolvido
    mensagem    TEXT,
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    custo_usd   REAL DEFAULT 0,
    cache_escrita INTEGER DEFAULT 0,  -- tokens do input escritos no prompt cache (já em tokens_in)
    cache_leitura INTEGER DEFAULT 0,  -- tokens do input lidos do prompt cache (já em tokens_in)
    duracao_s   REAL,
    tarefa_id   INTEGER                -- tarefa de dev em andamento (custo por tarefa no painel)
);

CREATE TABLE IF NOT EXISTS tarefas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo           TEXT NOT NULL,
    etapa            TEXT NOT NULL DEFAULT 'backlog',
    responsavel      TEXT,
    ultimo_resultado TEXT,            -- APROVADO | REPROVADO (+ mensagem curta)
    rodada           INTEGER NOT NULL DEFAULT 0,   -- quantas vezes voltou reprovada
    branch           TEXT,
    decisao_pendente TEXT,            -- pergunta pro Gu (faixa amarela no painel)
    atualizado_em    TEXT NOT NULL
);

-- Foto diária do YouTube Analytics (17_analytics): acumulado de cada vídeo desde a publicação.
CREATE TABLE IF NOT EXISTS metricas_video (
    data          TEXT NOT NULL,      -- dia da coleta (AAAA-MM-DD)
    youtube_id    TEXT NOT NULL,
    titulo        TEXT,
    publicado     TEXT,
    duracao_s     INTEGER,
    views         INTEGER,
    impressoes    INTEGER,            -- impressões da miniatura (None = API não devolveu)
    ctr_pct       REAL,               -- CTR da miniatura, em %
    retencao_pct  REAL,               -- % média assistida (a "retenção" do Studio)
    assistido_s   REAL,               -- duração média assistida
    PRIMARY KEY (data, youtube_id)
);

CREATE TABLE IF NOT EXISTS trafego_video (
    data        TEXT NOT NULL,
    youtube_id  TEXT NOT NULL,
    origem      TEXT NOT NULL,        -- insightTrafficSourceType (YT_SEARCH, SUBSCRIBER...)
    views       INTEGER,
    minutos     REAL,
    PRIMARY KEY (data, youtube_id, origem)
);

CREATE TABLE IF NOT EXISTS termos_busca (
    data        TEXT NOT NULL,
    youtube_id  TEXT NOT NULL,
    termo       TEXT NOT NULL,        -- termo da busca do YouTube que trouxe a view
    views       INTEGER,
    PRIMARY KEY (data, youtube_id, termo)
);

CREATE TABLE IF NOT EXISTS termos_canal (
    data        TEXT NOT NULL,        -- termos de busca do canal inteiro nos 7 dias até `data`
    termo       TEXT NOT NULL,
    views       INTEGER,
    PRIMARY KEY (data, termo)
);

-- Origens de tráfego do canal inteiro nos 7 dias até `data` (% que não vem da busca).
CREATE TABLE IF NOT EXISTS trafego_canal (
    data        TEXT NOT NULL,
    origem      TEXT NOT NULL,
    views       INTEGER,
    PRIMARY KEY (data, origem)
);

-- Views de cada vídeo nos 7 primeiros dias depois de publicado (não muda mais: calculado 1 vez).
CREATE TABLE IF NOT EXISTS views_7d (
    youtube_id    TEXT PRIMARY KEY,
    titulo        TEXT,
    publicado     TEXT,
    duracao_s     INTEGER,
    views         INTEGER,
    calculado_em  TEXT NOT NULL
);

-- Relatório Reach (Reporting API): 1 CSV por dia; backfill do mesmo dia substitui o anterior.
CREATE TABLE IF NOT EXISTS reach_dia (
    dia         TEXT NOT NULL,        -- dia que o relatório cobre (AAAA-MM-DD)
    youtube_id  TEXT NOT NULL,
    impressoes  INTEGER,
    ctr_pct     REAL,
    PRIMARY KEY (dia, youtube_id)
);

CREATE TABLE IF NOT EXISTS reach_relatorio (
    dia          TEXT PRIMARY KEY,
    create_time  TEXT NOT NULL        -- createTime do relatório importado (backfill = mais novo)
);

-- Vídeos antigos voltando a crescer (17_analytics), 1 foto por coleta.
CREATE TABLE IF NOT EXISTS em_alta (
    data          TEXT NOT NULL,      -- dia da coleta (o mesmo de metricas_video)
    youtube_id    TEXT NOT NULL,
    titulo        TEXT,
    tema          TEXT,               -- blocos.tema do corte; Short/sem bloco = None (usa o título)
    publicado     TEXT,
    views_semana  INTEGER,            -- views nos últimos 7 dias
    views_total   INTEGER,
    fator         REAL,               -- views da semana ÷ média semanal de antes
    PRIMARY KEY (data, youtube_id)
);

-- Sugestões do Curador (13). status: sugerida → pedida (Gu clicou Processar) → processando →
-- processada | falhou; expirada (mais velha que 15 dias, a mesma regra da fila).
CREATE TABLE IF NOT EXISTS sugestoes (
    video_id      TEXT PRIMARY KEY,   -- id do YouTube da fonte
    titulo        TEXT,
    canal         TEXT,
    duracao_min   REAL,
    prioridade    INTEGER,
    motivo        TEXT,
    url           TEXT,
    data          TEXT,               -- data do vídeo na fonte (AAAA-MM-DD)
    cortado_por   TEXT,               -- canais de corte grandes que já cortaram ("X (2)"); "" = ninguém
    status        TEXT NOT NULL DEFAULT 'sugerida',
    stem          TEXT,
    mensagem      TEXT,               -- erro da falha / "processado por link direto"
    sugerida_em   TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_eventos_ts ON eventos(ts);
CREATE INDEX IF NOT EXISTS ix_eventos_stem ON eventos(stem);
"""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def conectar(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or DB_PATH   # lido na chamada (não no def) pra os testes trocarem o banco
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_S)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")   # painel lê enquanto o pipeline escreve
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    # migração: bancos criados antes das colunas tarefa_id, titulo_youtube, cache_* e faixa_duracao
    for tabela, coluna in (("eventos", "tarefa_id INTEGER"), ("blocos", "titulo_youtube TEXT"),
                           ("blocos", "faixa_duracao TEXT"), ("sugestoes", "cortado_por TEXT"),
                           ("eventos", "cache_escrita INTEGER DEFAULT 0"),
                           ("eventos", "cache_leitura INTEGER DEFAULT 0")):
        if coluna.split()[0] not in {r["name"] for r in con.execute(f"PRAGMA table_info({tabela})")}:
            try:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna}")
            except sqlite3.OperationalError:   # outro processo migrou no mesmo instante
                pass
    return con


@contextmanager
def _seguro(acao: str):
    """Best-effort: falha de banco vira aviso, nunca exceção pro pipeline.

    Se nem conectar der, o corpo do `with` roda num banco descartável em memória
    (um contextmanager não consegue pular o corpo — sem isso, o `yield` não
    aconteceria e o Python levantaria "generator didn't yield")."""
    try:
        con = conectar()
    except Exception as e:  # noqa: BLE001 — de propósito
        print(f"[aviso] painel: não consegui {acao} ({e}) — pipeline segue", file=sys.stderr)
        con = sqlite3.connect(":memory:")
        con.executescript(SCHEMA)
    try:
        with con:
            yield con
    except Exception as e:  # noqa: BLE001 — de propósito
        print(f"[aviso] painel: não consegui {acao} ({e}) — pipeline segue", file=sys.stderr)
    finally:
        con.close()


def _executar(acao: str, fn, padrao=None):
    """Best-effort pra quem precisa de um RETORNO (id, linha): banco fora do ar devolve
    `padrao` — diferente do _seguro, que roda num banco em memória e "daria certo" falso."""
    try:
        con = conectar()
        try:
            with con:
                return fn(con)
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001 — de propósito
        print(f"[aviso] painel: não consegui {acao} ({e})", file=sys.stderr)
        return padrao


def upsert_video(stem: str, pasta: str | None = None, fonte_url: str | None = None,
                 status: str | None = None) -> None:
    agora = _agora()
    with _seguro(f"gravar vídeo {stem}") as con:
        con.execute(
            """INSERT INTO videos (stem, pasta, fonte_url, status, criado_em, atualizado_em)
               VALUES (?, ?, ?, COALESCE(?, 'curadoria'), ?, ?)
               ON CONFLICT(stem) DO UPDATE SET
                 pasta = COALESCE(excluded.pasta, pasta),
                 fonte_url = COALESCE(excluded.fonte_url, fonte_url),
                 status = COALESCE(?, status),
                 atualizado_em = excluded.atualizado_em""",
            (stem, pasta, fonte_url, status, agora, agora, status),
        )


def upsert_bloco(stem: str, bloco_id: int, *, forcar_status: bool = False, **campos) -> None:
    """Cria/atualiza um bloco. `status` só sobrescreve status AUTO, a não ser que
    forcar_status=True (agentes de decisão usam isso). Quem grava duracao_min leva junto a
    faixa_duracao (o Analista compara retenção por faixa)."""
    permitidos = {"tema", "titulo", "texto_thumb", "score", "duracao_min", "status",
                  "motivo", "video_path", "thumb_path", "publish_at", "youtube_id", "titulo_youtube"}
    invalidos = set(campos) - permitidos
    if invalidos:
        raise ValueError(f"campos inválidos pra bloco: {invalidos}")
    if campos.get("duracao_min") is not None:
        campos["faixa_duracao"] = faixa(campos["duracao_min"])
    status = campos.pop("status", None)
    if status and status not in STATUS_BLOCO:
        raise ValueError(f"status inválido: {status}")

    with _seguro(f"gravar bloco {stem}#{bloco_id}") as con:
        # garante a FK sem depender da ordem de chamada
        con.execute("INSERT OR IGNORE INTO videos (stem, criado_em, atualizado_em) "
                    "VALUES (?, ?, ?)", (stem, _agora(), _agora()))
        con.execute(
            """INSERT INTO blocos (stem, bloco_id, status, atualizado_em)
               VALUES (?, ?, COALESCE(?, 'segmentado'), ?)
               ON CONFLICT(stem, bloco_id) DO NOTHING""",
            (stem, bloco_id, status, _agora()),
        )
        if campos:
            sets = ", ".join(f"{k} = ?" for k in campos)
            con.execute(f"UPDATE blocos SET {sets}, atualizado_em = ? "
                        f"WHERE stem = ? AND bloco_id = ?",
                        (*campos.values(), _agora(), stem, bloco_id))
        if status:
            if forcar_status:
                con.execute("UPDATE blocos SET status = ?, atualizado_em = ? "
                            "WHERE stem = ? AND bloco_id = ?",
                            (status, _agora(), stem, bloco_id))
            else:
                marcadores = ",".join("?" * len(STATUS_AUTO))
                con.execute(f"UPDATE blocos SET status = ?, atualizado_em = ? "
                            f"WHERE stem = ? AND bloco_id = ? AND status IN ({marcadores})",
                            (status, _agora(), stem, bloco_id, *STATUS_AUTO))


def arquivar_blocos(stem: str, motivo: str) -> list[int]:
    """Arquiva os blocos do stem que ainda não foram pro YouTube (STATUS_ARQUIVAVEL).
    Agendado, publicado e descartado ficam como estão. Retorna os ids arquivados."""
    marcadores = ",".join("?" * len(STATUS_ARQUIVAVEL))
    def arquivar(con):
        ids = [r["bloco_id"] for r in con.execute(
            f"SELECT bloco_id FROM blocos WHERE stem = ? AND status IN ({marcadores}) "
            f"ORDER BY bloco_id", (stem, *STATUS_ARQUIVAVEL))]
        con.execute(f"UPDATE blocos SET status = 'arquivado', motivo = ?, atualizado_em = ? "
                    f"WHERE stem = ? AND status IN ({marcadores})",
                    (motivo, _agora(), stem, *STATUS_ARQUIVAVEL))
        return ids
    return _executar(f"arquivar blocos de {stem}", arquivar, padrao=[])


def ler_bloco(stem: str, bloco_id: int) -> dict | None:
    """Lê um bloco do banco. Best-effort: banco fora do ar = None (como se não existisse)."""
    def ler(con):
        r = con.execute("SELECT * FROM blocos WHERE stem = ? AND bloco_id = ?",
                        (stem, bloco_id)).fetchone()
        return dict(r) if r else None
    return _executar(f"ler bloco {stem}#{bloco_id}", ler)


def evento(stem: str | None, etapa: str, status: str, *, agente: str = "pipeline",
           bloco_id: int | None = None, mensagem: str = "", tokens_in: int = 0,
           tokens_out: int = 0, custo_usd: float = 0.0, duracao_s: float | None = None,
           tarefa_id: int | None = None, cache_escrita: int = 0, cache_leitura: int = 0) -> None:
    """tarefa_id: tarefa de dev a que o evento pertence. Sem ele, usa a env MISSAO_TAREFA
    (ex: rodar um script real com API paga dentro de uma tarefa → custo cai nela)."""
    if tarefa_id is None and os.environ.get("MISSAO_TAREFA", "").isdigit():
        tarefa_id = int(os.environ["MISSAO_TAREFA"])
    with _seguro(f"registrar evento {etapa}") as con:
        con.execute(
            """INSERT INTO eventos (ts, stem, bloco_id, agente, etapa, status, mensagem,
                                    tokens_in, tokens_out, custo_usd, duracao_s, tarefa_id,
                                    cache_escrita, cache_leitura)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_agora(), stem, bloco_id, agente, etapa, status, mensagem,
             tokens_in, tokens_out, custo_usd, duracao_s, tarefa_id, cache_escrita, cache_leitura),
        )


# ── YouTube Analytics (17_analytics) ───────────────────────────────────────

def gravar_analytics(data: str, metricas: list[dict], trafego: list[dict],
                     termos: list[dict], termos_canal: list[dict],
                     trafego_canal: list[dict] = ()) -> None:
    """Foto do dia: substitui o que já houver do mesmo `data` (rodar 2x no dia não duplica)."""
    tabelas = (("metricas_video", ("youtube_id", "titulo", "publicado", "duracao_s", "views",
                                   "impressoes", "ctr_pct", "retencao_pct", "assistido_s"), metricas),
               ("trafego_video", ("youtube_id", "origem", "views", "minutos"), trafego),
               ("termos_busca", ("youtube_id", "termo", "views"), termos),
               ("termos_canal", ("termo", "views"), termos_canal),
               ("trafego_canal", ("origem", "views"), trafego_canal))
    with _seguro(f"gravar analytics de {data}") as con:
        for tabela, colunas, linhas in tabelas:
            con.execute(f"DELETE FROM {tabela} WHERE data = ?", (data,))
            con.executemany(
                f"INSERT INTO {tabela} (data, {', '.join(colunas)}) "
                f"VALUES (?, {', '.join('?' * len(colunas))})",
                [(data, *(linha.get(c) for c in colunas)) for linha in linhas])


def gravar_views_7d(linhas: list[dict]) -> None:
    """Views dos 7 primeiros dias de cada vídeo (calculado 1 vez; recalcular substitui)."""
    colunas = ("youtube_id", "titulo", "publicado", "duracao_s", "views")
    with _seguro("gravar views dos 7 primeiros dias") as con:
        con.executemany(f"INSERT OR REPLACE INTO views_7d ({', '.join(colunas)}, calculado_em) "
                        f"VALUES ({', '.join('?' * len(colunas))}, ?)",
                        [(*(x.get(c) for c in colunas), _agora()) for x in linhas])


def views_7d() -> list[dict]:
    """[{youtube_id, titulo, publicado, duracao_s, views}], mais recente primeiro. Sem banco = []."""
    return _executar("ler views dos 7 primeiros dias", lambda con: [dict(r) for r in con.execute(
        "SELECT youtube_id, titulo, publicado, duracao_s, views FROM views_7d "
        "ORDER BY publicado DESC")], padrao=[])


def temas_por_youtube(ids: list[str]) -> dict[str, str]:
    """{youtube_id: tema do bloco} dos cortes já no canal. Best-effort: sem banco = {}."""
    if not ids:
        return {}
    return _executar("ler temas por vídeo", lambda con: {
        r["youtube_id"]: r["tema"] for r in con.execute(
            "SELECT youtube_id, tema FROM blocos WHERE tema IS NOT NULL AND youtube_id IN "
            f"({', '.join('?' * len(ids))})", ids)}, padrao={})


def gravar_em_alta(data: str, linhas: list[dict]) -> None:
    """Foto do dia dos vídeos antigos em alta (substitui o mesmo `data`)."""
    colunas = ("youtube_id", "titulo", "tema", "publicado", "views_semana", "views_total", "fator")
    with _seguro(f"gravar vídeos em alta de {data}") as con:
        con.execute("DELETE FROM em_alta WHERE data = ?", (data,))
        con.executemany(f"INSERT INTO em_alta (data, {', '.join(colunas)}) "
                        f"VALUES (?, {', '.join('?' * len(colunas))})",
                        [(data, *(x.get(c) for c in colunas)) for x in linhas])


def em_alta_atual() -> list[dict]:
    """Vídeos antigos em alta da coleta MAIS RECENTE (coleta sem nenhum = []), maior fator
    primeiro; `tema` cai no título quando o vídeo não tem bloco. Best-effort: sem banco = []."""
    return _executar("ler vídeos em alta", lambda con: [
        {**dict(r), "tema": r["tema"] or r["titulo"]} for r in con.execute(
            "SELECT * FROM em_alta WHERE data = (SELECT MAX(data) FROM metricas_video) "
            "ORDER BY fator DESC, views_semana DESC")], padrao=[])


def reach_importados() -> dict[str, str]:
    """{dia: createTime} dos relatórios Reach já importados. Banco fora do ar = {}."""
    return _executar("ler relatórios reach", lambda con: {
        r["dia"]: r["create_time"] for r in con.execute("SELECT * FROM reach_relatorio")}, padrao={})


def gravar_reach(dia: str, create_time: str, linhas: list[dict]) -> None:
    """Grava o relatório Reach de um dia, substituindo o que houver desse dia."""
    with _seguro(f"gravar reach de {dia}") as con:
        con.execute("DELETE FROM reach_dia WHERE dia = ?", (dia,))
        con.executemany("INSERT INTO reach_dia (dia, youtube_id, impressoes, ctr_pct) "
                        "VALUES (?, ?, ?, ?)",
                        [(dia, x["youtube_id"], x["impressoes"], x["ctr_pct"]) for x in linhas])
        con.execute("INSERT INTO reach_relatorio (dia, create_time) VALUES (?, ?) "
                    "ON CONFLICT(dia) DO UPDATE SET create_time = excluded.create_time",
                    (dia, create_time))


def reach_por_video() -> tuple[str | None, dict[str, dict]]:
    """(primeiro dia com relatório, {youtube_id: {impressoes, ctr_pct}}) somando todos os dias
    importados; CTR ponderado pelas impressões. Sem relatório: (None, {})."""
    def ler(con):
        desde = con.execute("SELECT MIN(dia) FROM reach_dia").fetchone()[0]
        return desde, {r["youtube_id"]: {"impressoes": r["imp"],
                                         "ctr_pct": round(r["cliques"] / r["imp"], 2) if r["imp"] else 0.0}
                       for r in con.execute(
                           "SELECT youtube_id, SUM(impressoes) AS imp, "
                           "SUM(impressoes * ctr_pct) AS cliques FROM reach_dia GROUP BY youtube_id")}
    return _executar("ler reach", ler, padrao=(None, {}))


def termos_semana(limite: int = 10) -> list[dict]:
    """[{termo, views}] da busca do YouTube que mais trouxeram views ao canal nos 7 dias da
    coleta mais recente. Best-effort: banco fora do ar ou sem coleta = []."""
    return _executar("ler termos de busca", lambda con: [dict(r) for r in con.execute(
        "SELECT termo, views FROM termos_canal WHERE data = (SELECT MAX(data) FROM termos_canal) "
        "ORDER BY views DESC, termo LIMIT ?", (limite,))], padrao=[])


def ultima_coleta() -> dict:
    """Coleta mais recente: {data, metricas: [linha de metricas_video], trafego: {origem:
    views somadas}, trafego_semana: {origem: views do canal nos 7 dias}, trafego_semana_antes:
    o mesmo da coleta de 7+ dias antes}. Best-effort: sem banco ou sem coleta, data None e
    tudo vazio."""
    def semana(con, data):
        return {r[0]: r[1] for r in con.execute(
            "SELECT origem, views FROM trafego_canal WHERE data = ?", (data,))}

    def ler(con):
        data = con.execute("SELECT MAX(data) FROM metricas_video").fetchone()[0]
        antes = con.execute("SELECT MAX(data) FROM trafego_canal WHERE data <= date(?, '-7 days')",
                            (data,)).fetchone()[0] if data else None
        return {"data": data,
                "metricas": [dict(r) for r in con.execute(
                    "SELECT * FROM metricas_video WHERE data = ?", (data,))],
                "trafego": {r[0]: r[1] for r in con.execute(
                    "SELECT origem, SUM(views) FROM trafego_video WHERE data = ? GROUP BY origem",
                    (data,))},
                "trafego_semana": semana(con, data), "trafego_semana_antes": semana(con, antes)}
    return _executar("ler analytics", ler, padrao={"data": None, "metricas": [], "trafego": {},
                                                   "trafego_semana": {}, "trafego_semana_antes": {}})


# ── sugestões do Curador (13) ──────────────────────────────────────────────

def gravar_sugestao(video_id: str, *, status: str | None = None, **campos) -> None:
    """Cria/atualiza a sugestão. Sem `status`, uma já existente mantém o dela (o Gu pode ter
    pedido): só os campos passados mudam."""
    permitidos = {"titulo", "canal", "duracao_min", "prioridade", "motivo", "url", "data",
                  "stem", "mensagem", "cortado_por"}
    invalidos = set(campos) - permitidos
    if invalidos:
        raise ValueError(f"campos inválidos pra sugestão: {invalidos}")
    if status and status not in STATUS_SUGESTAO:
        raise ValueError(f"status inválido: {status}")
    agora = _agora()
    with _seguro(f"gravar sugestão {video_id}") as con:
        con.execute("INSERT INTO sugestoes (video_id, status, sugerida_em, atualizado_em) "
                    "VALUES (?, COALESCE(?, 'sugerida'), ?, ?) ON CONFLICT(video_id) DO NOTHING",
                    (video_id, status, agora, agora))
        sets = {**campos, **({"status": status} if status else {})}
        if sets:
            con.execute(f"UPDATE sugestoes SET {', '.join(f'{k} = ?' for k in sets)}, "
                        f"atualizado_em = ? WHERE video_id = ?", (*sets.values(), agora, video_id))


def pedir_sugestao(video_id: str) -> bool:
    """Gu clicou Processar: sugerida/falhou → pedida. False = não existe ou já andou."""
    return bool(_executar(f"pedir sugestão {video_id}", lambda con: con.execute(
        "UPDATE sugestoes SET status = 'pedida', mensagem = NULL, atualizado_em = ? "
        "WHERE video_id = ? AND status IN ('sugerida', 'falhou')",
        (_agora(), video_id)).rowcount, padrao=0))


def listar_sugestoes(status: list[str] | None = None) -> list[dict]:
    """Sugestões (todas ou só dos status pedidos), maior prioridade primeiro; pedidas na
    ordem do clique (atualizado_em). Banco fora do ar = []."""
    filtro = f"WHERE status IN ({', '.join('?' * len(status))})" if status else ""
    return _executar("ler sugestões", lambda con: [dict(r) for r in con.execute(
        f"SELECT * FROM sugestoes {filtro} ORDER BY prioridade DESC, data DESC, atualizado_em",
        status or [])], padrao=[])


# ── tarefas do time de dev ─────────────────────────────────────────────────

def nova_tarefa(titulo: str, branch: str | None = None,
                responsavel: str = "tech-lead") -> int | None:
    """Cria a tarefa no backlog. Retorna o id (None se o banco falhar)."""
    return _executar("criar tarefa", lambda con: con.execute(
        "INSERT INTO tarefas (titulo, branch, responsavel, atualizado_em) VALUES (?, ?, ?, ?)",
        (titulo, branch, responsavel, _agora())).lastrowid)


def atualizar_tarefa(tarefa_id: int, *, reprovou: bool = False, **campos) -> bool | None:
    """Atualiza campos da tarefa. reprovou=True soma 1 na rodada.
    Retorna True/False (achou a tarefa ou não) e None se o banco falhar."""
    permitidos = {"titulo", "etapa", "responsavel", "ultimo_resultado", "branch",
                  "decisao_pendente"}
    invalidos = set(campos) - permitidos
    if invalidos:
        raise ValueError(f"campos inválidos pra tarefa: {invalidos}")
    if "etapa" in campos and campos["etapa"] not in ETAPAS_TAREFA:
        raise ValueError(f"etapa inválida: {campos['etapa']} (use {', '.join(ETAPAS_TAREFA)})")
    sets = [f"{k} = ?" for k in campos] + (["rodada = rodada + 1"] if reprovou else [])
    return _executar(f"atualizar tarefa #{tarefa_id}", lambda con: con.execute(
        f"UPDATE tarefas SET {', '.join(sets + ['atualizado_em = ?'])} WHERE id = ?",
        (*campos.values(), _agora(), tarefa_id)).rowcount > 0)


def ler_tarefa(tarefa_id: int) -> dict | None:
    def ler(con):
        r = con.execute("SELECT * FROM tarefas WHERE id = ?", (tarefa_id,)).fetchone()
        return dict(r) if r else None
    return _executar(f"ler tarefa #{tarefa_id}", ler)


def listar_tarefas(incluir_prontas: bool = False) -> list[dict]:
    filtro = "" if incluir_prontas else "WHERE etapa != 'pronto'"
    return _executar("listar tarefas", lambda con: [
        dict(r) for r in con.execute(f"SELECT * FROM tarefas {filtro} ORDER BY id")], padrao=[])


def tarefa_ativa() -> int | None:
    """A tarefa em andamento mais recente (fazendo/testando/revisando) — é nela que os
    hooks penduram a atividade dos subagents."""
    marcadores = ",".join("?" * len(ETAPAS_ATIVAS))
    def achar(con):
        r = con.execute(f"SELECT id FROM tarefas WHERE etapa IN ({marcadores}) "
                        f"ORDER BY atualizado_em DESC, id DESC LIMIT 1", ETAPAS_ATIVAS).fetchone()
        return r["id"] if r else None
    return _executar("achar tarefa ativa", achar)


if __name__ == "__main__":
    # Smoke test: uv run py scripts/_eventos.py
    conectar().close()
    print(f"OK banco em {DB_PATH}")
