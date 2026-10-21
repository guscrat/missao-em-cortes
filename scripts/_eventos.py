"""Camada de estado do pipeline: SQLite em state/pipeline.db.

Todo script/agente registra o que fez aqui; o painel (painel/app.py) só LÊ.

Regra de ouro: o painel nunca derruba o pipeline. Toda escrita é best-effort —
se o banco falhar (lock, disco, etc.), loga um aviso e segue.

Tabelas:
  videos   — 1 linha por fonte (stem)
  blocos   — 1 linha por corte (stem + bloco_id), com o status no kanban
  eventos  — log append-only: quem (agente), o quê (etapa), status, tokens, custo

Uso:
    from _eventos import evento, upsert_video, upsert_bloco
    evento("renan_live3", "03_segmentar", "ok", agente="editor",
           tokens_in=40_000, tokens_out=3_000, custo_usd=0.17)
"""
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "state" / "pipeline.db"

# Status de bloco, na ordem do fluxo. Os "AUTO" são derivados dos arquivos em
# outputs/ (sincronizar_estado.py pode sobrescrever). Os demais são decisões de
# agente/humano e NUNCA são rebaixados pela sincronização.
STATUS_AUTO = ["segmentado", "cortado", "montado"]
STATUS_DECISAO = ["revisao", "aprovado", "quarentena", "agendado", "publicado"]
STATUS_BLOCO = STATUS_AUTO + STATUS_DECISAO

STATUS_VIDEO = ["curadoria", "baixado", "transcrito", "segmentado", "descartado"]

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
    duracao_s   REAL
);

CREATE INDEX IF NOT EXISTS ix_eventos_ts ON eventos(ts);
CREATE INDEX IF NOT EXISTS ix_eventos_stem ON eventos(stem);
"""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def conectar(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")   # painel lê enquanto o pipeline escreve
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
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


def evento(stem: str | None, etapa: str, status: str, *, agente: str = "pipeline",
           bloco_id: int | None = None, mensagem: str = "", tokens_in: int = 0,
           tokens_out: int = 0, custo_usd: float = 0.0, duracao_s: float | None = None) -> None:
    with _seguro(f"registrar evento {etapa}") as con:
        con.execute(
            """INSERT INTO eventos (ts, stem, bloco_id, agente, etapa, status, mensagem,
                                    tokens_in, tokens_out, custo_usd, duracao_s)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_agora(), stem, bloco_id, agente, etapa, status, mensagem,
             tokens_in, tokens_out, custo_usd, duracao_s),
        )


if __name__ == "__main__":
    # Smoke test: uv run py scripts/_eventos.py
    conectar().close()
    print(f"OK banco em {DB_PATH}")
