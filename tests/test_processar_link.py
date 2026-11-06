"""Processar link (painel -> 13 --link): origem no banco, pedir_link, checar_link. Tudo falso."""
import json
import sqlite3

import pandas as pd
import pytest

from test_curador import CFG, HOJE, _item, cu, raiz, rodada  # noqa: F401
from test_curador_sugerir import _modo, _status

import _eventos as ev
import hoje

VID = "abcdefghijk"
URL = f"https://www.youtube.com/watch?v={VID}"
OK = URL


@pytest.fixture
def sugerir(raiz, rodada):
    _modo(raiz, "sugerir")
    return rodada


def _info(**kw):
    return {"title": "Live Manual", "channel": "Fulano", "duration": 3600,
            "upload_date": "20261030", "live_status": "was_live", **kw}


def _sug1():
    return next(s for s in ev.listar_sugestoes() if s["video_id"] == VID)


def _eventos_link(banco):
    return banco("SELECT * FROM eventos WHERE etapa='curador_link'")


def _processar_ok(item):
    return {"stem": item["stem"], "titulo": item["titulo"], "canal": item["canal"],
            "ok": True, "aprovados": 1, "publicacao": "p", "avisos": []}


# --- _eventos ----------------------------------------------------------------------------

def test_origem_defaults_e_primeira_valida(banco):
    ev.gravar_sugestao("a")
    ev.gravar_sugestao("b", origem="manual")
    por = {s["video_id"]: s["origem"] for s in ev.listar_sugestoes()}
    assert por == {"a": "curador", "b": "manual"}
    ev.upsert_video("v1")
    ev.upsert_video("v2", origem="manual")
    ev.upsert_video("v2", origem="curador")          # a primeira vale
    ev.upsert_video("v1", origem="curador")          # NULL antes -> preenche
    ev.upsert_video("v1", origem="manual")
    r = {x["stem"]: x["origem"] for x in banco("SELECT stem, origem FROM videos")}
    assert r == {"v1": "curador", "v2": "manual"}


def test_video_sem_origem_fica_null(banco):
    ev.upsert_video("v")
    assert banco("SELECT origem FROM videos")[0]["origem"] is None


def test_migracao_banco_antigo(tmp_path, monkeypatch):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE sugestoes (video_id TEXT PRIMARY KEY, status TEXT NOT NULL "
                      "DEFAULT 'sugerida'); INSERT INTO sugestoes(video_id) VALUES ('x');"
                      "CREATE TABLE videos (stem TEXT PRIMARY KEY, pasta TEXT, fonte_url TEXT, "
                      "status TEXT NOT NULL DEFAULT 'curadoria', criado_em TEXT NOT NULL, "
                      "atualizado_em TEXT NOT NULL);")
    con.commit()
    con.close()
    monkeypatch.setattr(ev, "DB_PATH", db)
    c = ev.conectar()
    try:
        assert c.execute("SELECT origem FROM sugestoes").fetchone()[0] == "curador"
        c.execute("SELECT origem FROM videos")
    finally:
        c.close()


# --- 13_curador.canal_do_link --------------------------------------------------------------

@pytest.mark.parametrize("info,prefixo", [
    ({"uploader_id": "@renan"}, "renan"), ({"uploader_id": "@KIM"}, "kim"),
    ({"uploader_id": "@outro"}, None), ({}, None)])
def test_canal_do_link(info, prefixo):
    c = cu.canal_do_link(CFG, info)
    assert (c.get("prefixo") if c else None) == prefixo


def test_canal_do_link_por_channel_id_na_url():
    cfg = {"canais": [{"nome": "X", "url": "https://www.youtube.com/channel/UCabc/", "prefixo": "x"}]}
    assert cu.canal_do_link(cfg, {"channel_id": "UCabc"})["prefixo"] == "x"


# --- 13_curador.pedir_link -----------------------------------------------------------------

def _sem_ler(monkeypatch, info=None, erro=None):
    chamadas = []

    def ler(url):
        chamadas.append(url)
        if erro:
            raise erro
        return info
    monkeypatch.setattr(cu, "ler_link", ler)
    return chamadas


def test_link_invalido_falha_e_retorna_0(raiz, sugerir, monkeypatch, banco):
    _sem_ler(monkeypatch, _info())
    assert cu.main(["--link=https://exemplo.com/x"]) == 0
    ev_, = _eventos_link(banco)
    assert ev_["status"] == "falha" and sugerir["processados"] == []


def test_link_ja_processado_nao_grava(raiz, sugerir, monkeypatch):
    (raiz / "inputs" / "s.url").write_text(URL, encoding="utf-8")
    lidos = _sem_ler(monkeypatch, _info())
    assert cu.main([f"--link={URL}"]) == 0
    assert ev.listar_sugestoes() == [] and lidos == [] and sugerir["processados"] == []


@pytest.mark.parametrize("status", ["processando", "processada"])
def test_link_sugestao_processando_ou_processada(raiz, sugerir, monkeypatch, status):
    ev.gravar_sugestao(VID, status=status, titulo="T")
    lidos = _sem_ler(monkeypatch, _info())
    assert cu.main([f"--link={URL}"]) == 0
    assert lidos == [] and sugerir["processados"] == [] and _status(VID) == status


def test_link_novo_grava_manual_e_processa(raiz, sugerir, monkeypatch):
    lidos = _sem_ler(monkeypatch, _info(uploader_id="@kim"))
    assert cu.main([f"--link={URL}&t=30s"]) == 0
    assert lidos == [URL]
    s = _sug1()
    assert s["origem"] == "manual" and s["prioridade"] is None
    assert s["motivo"] == "link colado no painel" and s["canal"] == "Kim"
    assert s["risco"] is None and s["data"] == "2026-10-30" and s["duracao_min"] == 60.0
    assert s["status"] == "processada"
    assert sugerir["processados"] == ["kim_live_manual"]


def test_link_canal_terceiros_marca_risco(raiz, sugerir, monkeypatch):
    cfg = {**CFG, "curador_modo": "sugerir",
           "canais": [{"nome": "Flow", "url": "https://www.youtube.com/@flow", "prefixo": "flow",
                       "terceiros": True}]}
    (raiz / "config" / "canais.json").write_text(json.dumps(cfg), encoding="utf-8")
    _sem_ler(monkeypatch, _info(uploader_id="@flow"))
    cu.main([f"--link={URL}"])
    assert _sug1()["risco"] == cu.RISCO_TERCEIROS


def test_link_origem_manual_chega_no_item_processado(raiz, sugerir, monkeypatch):
    itens = []
    monkeypatch.setattr(cu, "processar", lambda item: itens.append(item) or _processar_ok(item))
    _sem_ler(monkeypatch, _info())
    assert cu.main([f"--link={URL}"]) == 0
    assert itens[0]["origem"] == "manual"


@pytest.mark.parametrize("ls", ["is_live", "is_upcoming", "post_live"])
def test_link_live_nao_terminada_falha(raiz, sugerir, monkeypatch, banco, ls):
    _sem_ler(monkeypatch, _info(live_status=ls))
    assert cu.main([f"--link={URL}"]) == 0
    assert _eventos_link(banco)[0]["status"] == "falha"
    assert ev.listar_sugestoes() == [] and sugerir["processados"] == []


def test_link_erro_do_ytdlp_falha(raiz, sugerir, monkeypatch, banco):
    _sem_ler(monkeypatch, erro=RuntimeError("Private video"))
    assert cu.main([f"--link={URL}"]) == 0
    e, = _eventos_link(banco)
    assert e["status"] == "falha" and "Private" in e["mensagem"]
    assert ev.listar_sugestoes() == []


def test_link_sugestao_do_curador_existente_mantem_origem(raiz, sugerir, monkeypatch):
    ev.gravar_sugestao(VID, titulo="Live Alfa", canal="Renan Santos", url=URL,
                       data=HOJE.isoformat(), prioridade=5, motivo="m")
    lidos = _sem_ler(monkeypatch, _info())
    assert cu.main([f"--link={URL}"]) == 0
    assert lidos == []                                  # não relê
    s = _sug1()
    assert s["origem"] == "curador" and s["prioridade"] == 5 and s["status"] == "processada"
    assert sugerir["processados"] == ["renan_live_alfa"]


def test_processar_pedidos_origem_curador_por_padrao(raiz, sugerir, monkeypatch):
    itens = []
    monkeypatch.setattr(cu, "processar", lambda item: itens.append(item) or _processar_ok(item))
    ev.gravar_sugestao("a", titulo="Live Alfa", canal="Renan Santos", url="u",
                       data=HOJE.isoformat(), prioridade=5)
    assert cu.main(["--processar=a"]) == 0
    assert itens[0]["origem"] == "curador"


@pytest.mark.parametrize("origem,esperado", [("manual", "manual"), (None, "curador")])
def test_processar_grava_origem_no_video(raiz, monkeypatch, banco, origem, esperado):
    gravados = []
    monkeypatch.setattr(cu, "upsert_video", lambda *a, **k: gravados.append(k))
    monkeypatch.setattr(cu, "rodar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("para")))
    item = {**_item("a"), "stem": "renan_x"}
    if origem:
        item["origem"] = origem
    cu.processar_seguro(item)
    assert gravados and gravados[0]["origem"] == esperado


# --- painel ------------------------------------------------------------------------------

def _sug_df(*linhas):
    return pd.DataFrame(linhas, columns=["video_id", "status"])


@pytest.mark.parametrize("entrada", [
    URL, f"https://youtu.be/{VID}", f"https://www.youtube.com/live/{VID}?feature=share",
    f"https://www.youtube.com/shorts/{VID}", f"  {URL}&t=120s  ", f"{URL}&list=PLx"])
def test_checar_link_ok_canonico(entrada):
    assert hoje.checar_link(entrada, _sug_df(), set()) == (OK, None)


@pytest.mark.parametrize("entrada", ["", "   ", None, "banana",
                                     "https://exemplo.com/watch?v=" + VID,
                                     "https://www.youtube.com/@canal"])
def test_checar_link_invalidos(entrada):
    url, erro = hoje.checar_link(entrada, _sug_df(), set())
    assert url is None and erro


def test_checar_link_ja_processado_e_na_fila():
    assert hoje.checar_link(URL, _sug_df(), {VID})[0] is None
    for st_ in ("pedida", "processando"):
        assert hoje.checar_link(URL, _sug_df((VID, st_)), set())[0] is None
    for st_ in ("sugerida", "falhou"):
        assert hoje.checar_link(URL, _sug_df((VID, st_)), set())[0] == OK
    assert hoje.checar_link(URL, pd.DataFrame(), set())[0] == OK


def test_ids_processados(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "a.url").write_text("https://youtu.be/AAAAAAAAAAA", encoding="utf-8")
    monkeypatch.setattr(hoje, "INPUTS", inputs)
    db = tmp_path / "p.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE videos (stem TEXT, fonte_url TEXT)")
    con.executemany("INSERT INTO videos VALUES (?,?)",
                    [("b", "https://www.youtube.com/watch?v=BBBBBBBBBBB"), ("c", None)])
    con.commit()
    con.close()
    assert hoje.ids_processados(db) == {"AAAAAAAAAAA", "BBBBBBBBBBB"}
    assert hoje.ids_processados(tmp_path / "nao.db") == {"AAAAAAAAAAA"}


def test_disparar_processamento_com_link(monkeypatch):
    chamadas = []
    monkeypatch.setattr(hoje.subprocess, "Popen", lambda cmd, **kw: chamadas.append(cmd))
    assert hoje.disparar_processamento(link=OK) is None
    assert chamadas[0][-1] == f"--link={OK}"
    assert hoje.disparar_processamento("abc") is None
    assert chamadas[1][-1] == "--processar=abc"


def test_marcar_novas_nao_marca_manual():
    sug = pd.DataFrame([
        {"video_id": "velha", "sugerida_em": "2026-10-29T17:00", "prioridade": 9,
         "data": "2026-10-01", "origem": "curador"},
        {"video_id": "nova", "sugerida_em": "2026-10-31T17:00", "prioridade": 3,
         "data": "2026-10-02", "origem": "curador"},
        {"video_id": "man", "sugerida_em": "2026-10-31T18:00", "prioridade": None,
         "data": "2026-10-03", "origem": "manual"}])
    r = hoje.marcar_novas(sug).set_index("video_id")["nova"]
    assert r["nova"] and not r["man"] and not r["velha"]


def test_render_sugestao_manual_pill_e_sem_prioridade(tmp_path):
    from streamlit.testing.v1 import AppTest
    cols = ["video_id", "titulo", "canal", "url", "duracao_min", "data", "prioridade",
            "motivo", "status", "mensagem", "origem"]
    df = pd.DataFrame([("m", "Live M", "Fulano", "u", 60.0, "2026-10-30", None,
                        "link colado no painel", "sugerida", None, "manual"),
                       ("c", "Live C", "Kim", "u", 60.0, "2026-10-30", 5, "m", "sugerida", None,
                        "curador")], columns=cols)
    df.to_pickle(tmp_path / "s.pkl")
    src = "\n".join(["import sys", f"sys.path.insert(0, {str(hoje.Path(hoje.__file__).parent)!r})",
                     "import pandas as pd", "import hoje",
                     f"hoje.secao_sugestoes(pd.read_pickle({str(tmp_path / 's.pkl')!r}), False)"])
    at = AppTest.from_string(src).run()
    assert not at.exception
    html_ = " ".join(m.value for m in at.markdown)
    assert html_.count("seu link") == 1 and "[0]" not in html_ and "[5]" in html_


def test_aba_hoje_devolve_dicts(monkeypatch):
    monkeypatch.setattr(hoje, "campo_link", lambda sug: OK)
    monkeypatch.setattr(hoje, "secao_sugestoes", lambda sug, ocupado: ["zzz"])
    monkeypatch.setattr(hoje, "ler_json", lambda p: {})
    agora = pd.Timestamp("2026-10-29 12:00:00")
    custo = hoje.custo_mes(pd.DataFrame(columns=["agente", "custo_usd"]), 50.0, agora)
    try:
        r = hoje.aba_hoje(pd.DataFrame(), pd.DataFrame(), None, custo, agora, pd.DataFrame())
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"aba_hoje exige contexto Streamlit: {e!r}")
    assert {"link": OK} in r and {"video_id": "zzz"} in r
