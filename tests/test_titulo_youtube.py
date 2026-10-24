"""titulo_youtube: coluna nova, gravada pelo 14_canal e preferida pelo painel (tudo mockado)."""
import sqlite3
from types import SimpleNamespace as NS

import _eventos
from _eventos import upsert_bloco

import hoje
from test_canal import AGORA, TITULO_1, _v, ca, local  # noqa: F401 (fixture local)


def test_titulo_do_canal_levemente_diferente_vira_titulo_youtube(local):  # noqa: F811
    _, banco, locais = local
    titulo_canal = "LULA LACRA Flávio com o seu pai preso"
    ca.aplicar([_v("L1", titulo_canal, "private", "2026-10-26T21:00:00Z")], locais, AGORA)
    r = banco("SELECT titulo_youtube, youtube_id FROM blocos WHERE bloco_id=1")[0]
    assert r == {"titulo_youtube": titulo_canal, "youtube_id": "L1"}


def test_so_titulo_mudou_conta_como_mudanca(local):  # noqa: F811
    _, banco, locais = local
    v = _v("L1", TITULO_1, "private", "2026-10-26T21:00:00Z")
    assert len(ca.aplicar([v], locais, AGORA)["longos"]) == 1
    assert ca.aplicar([v], locais, AGORA)["longos"] == []
    v2 = dict(v, titulo=TITULO_1.replace("o pai", "o seu pai"))
    assert len(ca.aplicar([v2], locais, AGORA)["longos"]) == 1
    r = banco("SELECT titulo_youtube FROM blocos WHERE bloco_id=1")[0]
    assert r["titulo_youtube"] == TITULO_1.replace("o pai", "o seu pai")


def test_migracao_adiciona_titulo_youtube(tmp_path):
    db = tmp_path / "velho.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE blocos (stem TEXT, bloco_id INTEGER, status TEXT)")
    con.commit()
    con.close()
    novo = _eventos.conectar(db)
    try:
        cols = {r["name"] for r in novo.execute("PRAGMA table_info(blocos)")}
    finally:
        novo.close()
    assert "titulo_youtube" in cols


def test_upsert_aceita_titulo_youtube(banco):
    upsert_bloco("v", 1, titulo_youtube="Título no ar")
    assert banco("SELECT titulo_youtube FROM blocos")[0]["titulo_youtube"] == "Título no ar"


def test_nome_prefere_titulo_youtube_e_cai_pro_titulo():
    assert hoje._nome(NS(titulo_youtube="No ar", titulo="Local", tema="t", bloco_id=1)) == "No ar"
    nan = float("nan")
    assert hoje._nome(NS(titulo_youtube=nan, titulo="Local", tema="t", bloco_id=1)) == "Local"
    assert hoje._nome(NS(titulo_youtube=None, titulo=None, tema="t", bloco_id=1)) == "t"
    assert hoje._nome(NS(titulo_youtube=None, titulo=None, tema=None, bloco_id=4)) == "bloco 4"
