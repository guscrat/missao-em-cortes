"""Camada de estado do pipeline: SQLite em state/pipeline.db.

Todo script/agente registra o que fez aqui; o painel (painel/app.py) só LÊ.

Regra de ouro: o painel nunca derruba o pipeline. Toda escrita é best-effort —
se o banco falhar (lock, disco, etc.), loga um aviso e segue.

Tabelas:
  videos   — 1 linha por fonte (stem)
  blocos   — 1 linha por corte (stem + bloco_id), com o status no kanban
  eventos  — log append-only: quem (agente), o quê (etapa), status, tokens, custo
  tarefas  — tarefas macro do time de dev (o Gu acompanha no painel, aba "Time de dev")

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
    duracao_min   REAL,
    status        TEXT NOT NULL DEFAULT 'segmentado',
    motivo        TEXT,               -- por que foi pra quarentena/devolvido
    video_path    TEXT,
    thumb_path    TEXT,
    publish_at    TEXT,
    youtube_id    TEXT,
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
    # migração: bancos criados antes da coluna tarefa_id
    if "tarefa_id" not in {r["name"] for r in con.execute("PRAGMA table_info(eventos)")}:
        try:
            con.execute("ALTER TABLE eventos ADD COLUMN tarefa_id INTEGER")
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
    forcar_status=True (agentes de decisão usam isso)."""
    permitidos = {"tema", "titulo", "texto_thumb", "score", "duracao_min", "status",
                  "motivo", "video_path", "thumb_path", "publish_at", "youtube_id"}
    invalidos = set(campos) - permitidos
    if invalidos:
        raise ValueError(f"campos inválidos pra bloco: {invalidos}")
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
           tarefa_id: int | None = None) -> None:
    """tarefa_id: tarefa de dev a que o evento pertence. Sem ele, usa a env MISSAO_TAREFA
    (ex: rodar um script real com API paga dentro de uma tarefa → custo cai nela)."""
    if tarefa_id is None and os.environ.get("MISSAO_TAREFA", "").isdigit():
        tarefa_id = int(os.environ["MISSAO_TAREFA"])
    with _seguro(f"registrar evento {etapa}") as con:
        con.execute(
            """INSERT INTO eventos (ts, stem, bloco_id, agente, etapa, status, mensagem,
                                    tokens_in, tokens_out, custo_usd, duracao_s, tarefa_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_agora(), stem, bloco_id, agente, etapa, status, mensagem,
             tokens_in, tokens_out, custo_usd, duracao_s, tarefa_id),
        )


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
