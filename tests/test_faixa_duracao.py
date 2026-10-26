"""Faixa de duração: _eventos (coluna + migração), 12_metricas.por_faixa, 04b.proteger,
10_shorts (short x cold_open, limite), pipeline --bloco. Tudo mockado."""
import ast
import importlib.util
import json
import runpy
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import _eventos
import _paths

SCRIPTS = Path(__file__).parent.parent / "scripts"


def _carregar(nome, arq):
    spec = importlib.util.spec_from_file_location(nome, SCRIPTS / arq)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── _eventos ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("minutos,faixa", [(9, "curto"), (15, "medio"), (25, "longo"), (6, "fora")])
def test_upsert_bloco_preenche_faixa(banco, minutos, faixa):
    _eventos.upsert_bloco("v", 1, duracao_min=minutos)
    r = banco("SELECT duracao_min, faixa_duracao FROM blocos")[0]
    assert r["duracao_min"] == minutos and r["faixa_duracao"] == faixa


def test_upsert_bloco_sem_duracao_nao_mexe_na_faixa(banco):
    _eventos.upsert_bloco("v", 1, duracao_min=9)
    _eventos.upsert_bloco("v", 1, titulo="x")
    assert banco("SELECT faixa_duracao FROM blocos")[0]["faixa_duracao"] == "curto"


def test_migracao_banco_antigo_ganha_coluna(tmp_path, monkeypatch):
    db = tmp_path / "state" / "velho.db"
    db.parent.mkdir()
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE blocos (stem TEXT, bloco_id INTEGER, duracao_min REAL)")
    con.commit()
    con.close()
    con = _eventos.conectar(db)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(blocos)")}
    con.close()
    assert "faixa_duracao" in cols


# ── 12_metricas ────────────────────────────────────────────────────────────

mt = _carregar("metricas_fx", "12_metricas.py")


def _v(dur_min, views=100, ret=50.0, assistido=300):
    return {"duracao_s": dur_min * 60, "views": views, "retencao_pct": ret, "assistido_s": assistido}


def test_faixa_do_video_desconta_montagem():
    assert mt.faixa_do_video(8 * 60 + mt.MONTAGEM_S) == "curto"
    assert mt.faixa_do_video(8 * 60 + mt.MONTAGEM_S - 1) == "abaixo_8"
    assert mt.faixa_do_video(12 * 60 + mt.MONTAGEM_S) == "medio"
    assert mt.faixa_do_video(20 * 60 + mt.MONTAGEM_S) == "longo"
    assert mt.faixa_do_video(30 * 60 + mt.MONTAGEM_S) == "longo"
    assert mt.faixa_do_video(30 * 60 + mt.MONTAGEM_S + 5) == "acima_30"
    assert mt.faixa_do_video(7 * 60) == "abaixo_8"


def test_por_faixa_agrupa_e_calcula_horas():
    g = mt.por_faixa([_v(10, views=100, assistido=360), _v(10, views=100, assistido=360),
                      _v(15), _v(25), _v(6), _v(40), _v(2.5)])   # 2.5 min = Short, ignorado
    assert set(g) == {"curto", "medio", "longo", "abaixo_8", "acima_30"}
    assert g["curto"]["n"] == 2 and g["curto"]["views"] == 200
    assert g["curto"]["horas_assistidas"] == 20.0 and g["curto"]["horas_por_video"] == 10.0
    assert g["medio"]["n"] == 1 and g["longo"]["n"] == 1
    assert g["abaixo_8"]["n"] == 1 and g["acima_30"]["n"] == 1


def test_por_faixa_grupo_sem_views_suficientes_e_none():
    g = mt.por_faixa([_v(10, views=mt.MIN_VIEWS - 1)])
    assert g["curto"] is None and g["medio"] is None


def test_resumo_grupo_media_ponderada_por_views():
    r = mt.resumo_grupo([_v(10, views=100, ret=40), _v(10, views=300, ret=60)])
    assert r["retencao_pct"] == 55.0


# ── 04b proteger ───────────────────────────────────────────────────────────

def _proteger():
    fonte = SCRIPTS / "04b_polir.py"
    arv = ast.parse(fonte.read_text(encoding="utf-8"))
    corpo = [n for n in arv.body
             if (isinstance(n, ast.FunctionDef) and n.name == "proteger")
             or (isinstance(n, ast.Assign) and any(
                 isinstance(t, ast.Name) and t.id in
                 {"PROTECAO_INICIO_S", "PROTECAO_FIM_S", "MIN_INTERVALO_S"} for t in n.targets))]
    ns = {}
    exec(compile(ast.Module(body=corpo, type_ignores=[]), str(fonte), "exec"), ns)
    return ns["proteger"]


proteger = _proteger()


def iv(a, b):
    return {"t_inicio": a, "t_fim": b, "motivo": "x"}


def test_proteger_alinha_borda_que_parte_palavra():
    pal = [{"start": 99.0, "end": 101.0, "word": "a"}, {"start": 109.0, "end": 111.0, "word": "b"}]
    r = proteger([iv(100.0, 110.0)], pal, 300)
    assert (r[0]["t_inicio"], r[0]["t_fim"]) == (101.0, 109.0)
    assert r[0]["motivo"] == "x"


def test_proteger_30s_iniciais_e_20s_finais():
    r = proteger([iv(10, 60), iv(200, 295)], [], 300)
    assert (r[0]["t_inicio"], r[0]["t_fim"]) == (30.0, 60)
    assert (r[1]["t_inicio"], r[1]["t_fim"]) == (200, 280.0)


def test_proteger_descarta_o_que_encolhe_demais():
    assert proteger([iv(5, 30.2), iv(281, 290)], [], 300) == []


def test_proteger_nao_altera_intervalo_ja_seguro():
    r = proteger([iv(100.0, 105.0)], [{"start": 90, "end": 99, "word": "a"}], 300)
    assert (r[0]["t_inicio"], r[0]["t_fim"]) == (100.0, 105.0)


# ── 10_shorts: short x cold_open, limite ───────────────────────────────────

sh = _carregar("shorts_fx", "10_shorts.py")


@pytest.fixture
def shorts(projeto, monkeypatch):
    pasta = projeto.video("kim", blocos=[1, 2, 3])
    data = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))
    b1, b2, b3 = data["blocos"]
    b1["short"] = {"timestamp_inicio": "00:01:00", "timestamp_fim": "00:02:00"}
    b1["cold_open"] = {"timestamp_inicio": "00:00:10", "timestamp_fim": "00:00:30"}
    b2["cold_open"] = {"timestamp_inicio": "00:05:00", "timestamp_fim": "00:05:20"}
    b3["short"] = {"timestamp_inicio": "00:10:00", "timestamp_fim": "00:14:00"}   # 240s
    (pasta / "blocos.json").write_text(json.dumps(data), encoding="utf-8")
    (pasta / "words.json").write_text(json.dumps({"words": [
        {"word": "oi", "start": 61.0, "end": 61.3}]}), encoding="utf-8")
    (projeto.inputs / "kim.mp4").touch()
    zoom = projeto.root / "zoom.json"
    zoom.write_text(json.dumps({"kim": "1626:914:147:0"}))
    monkeypatch.setattr(_paths, "OUTPUTS", projeto.outputs)
    monkeypatch.setattr(sh, "INPUTS", projeto.inputs)
    monkeypatch.setattr(sh, "ZOOM_JSON", zoom)
    monkeypatch.setattr(sh, "centro_rosto", lambda *a: (1000.0, 0.9))
    cmds = []

    def fake_run(cmd, cwd=None, **k):
        cmds.append(cmd)
        Path(cmd[-1]).touch()
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(sh.subprocess, "run", fake_run)
    return pasta, cmds


def test_short_tem_prioridade_sobre_cold_open(shorts):
    pasta, cmds = shorts
    assert sh.main([str(pasta), "--bloco=1"]) == 0
    reg = json.loads((pasta / "shorts" / "shorts.json").read_text(encoding="utf-8"))
    assert 60 <= reg["01"]["duracao_s"] <= 62        # 60s do short, não 20s do cold open


def test_sem_short_cai_pro_cold_open(shorts):
    pasta, cmds = shorts
    assert sh.main([str(pasta), "--bloco=2"]) == 0
    reg = json.loads((pasta / "shorts" / "shorts.json").read_text(encoding="utf-8"))
    assert reg["02"]["duracao_s"] == 21.0


def test_short_acima_do_limite_e_pulado_como_falha(shorts, capsys):
    pasta, cmds = shorts
    assert sh.main([str(pasta), "--bloco=3"]) == 1
    assert cmds == [] and "passa do limite" in capsys.readouterr().out
    assert not (pasta / "shorts" / "shorts.json").exists()


def test_main_completo_gera_dois_e_conta_uma_falha(shorts):
    pasta, cmds = shorts
    assert sh.main([str(pasta)]) == 1
    assert len(cmds) == 2


# ── pipeline --bloco ───────────────────────────────────────────────────────

PIPELINE = SCRIPTS / "pipeline.py"


def _rodar(monkeypatch, argv):
    cmds = []

    def fake_run(cmd, *a, **k):
        nome = Path(cmd[1]).name
        if nome != "sincronizar_estado.py":
            cmds.append((nome, list(cmd[2:])))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(_eventos, "evento", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["pipeline.py", "stem_x", *argv])
    try:
        runpy.run_path(str(PIPELINE), run_name="__main__")
    except SystemExit:
        pass
    return cmds


def test_pipeline_bloco_roda_so_steps_dependentes_com_flag(monkeypatch):
    cmds = _rodar(monkeypatch, ["--bloco=2"])
    assert [s for s, _ in cmds] == ["04_cortar.py", "04c_legendas.py", "06_montar.py"]
    assert all("--bloco=2" in a for _, a in cmds)


def test_pipeline_bloco_com_polir_inclui_04b(monkeypatch):
    cmds = _rodar(monkeypatch, ["--bloco=2", "--polir"])
    assert [s for s, _ in cmds] == ["04_cortar.py", "04b_polir.py", "04c_legendas.py", "06_montar.py"]
    assert all("--bloco=2" in a for _, a in cmds)


def test_pipeline_bloco_sem_legendas(monkeypatch):
    cmds = _rodar(monkeypatch, ["--bloco=2", "--sem-legendas"])
    assert [s for s, _ in cmds] == ["04_cortar.py", "06_montar.py"]
