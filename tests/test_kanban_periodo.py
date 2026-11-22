"""Filtro de período do kanban (painel/app.py): função pura extraída por ast + smoke AppTest."""
import ast
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "painel" / "app.py"
HOJE = "2026-11-22"


def _carregar():
    """Importar app.py roda a UI; pega só as constantes e recorte_kanban."""
    arv = ast.parse(APP.read_text(encoding="utf-8"))
    nos = [n for n in arv.body
           if (isinstance(n, ast.FunctionDef) and n.name == "recorte_kanban")
           or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in ("FINAIS", "PERIODOS", "PERIODO_PADRAO"))]
    ns = {"pd": pd}
    exec(compile(ast.Module(nos, []), str(APP), "exec"), ns)
    return ns


NS = _carregar()
recorte = NS["recorte_kanban"]

VC = ["stem", "pasta", "status"]
BC = ["stem", "bloco_id", "status", "publish_at"]


def _v(stem, pasta, status="baixado"):
    return {"stem": stem, "pasta": pasta, "status": status}


def _b(stem, i, status, publish_at=None):
    return {"stem": stem, "bloco_id": i, "status": status, "publish_at": publish_at}


def _df(linhas, cols):
    return pd.DataFrame(linhas, columns=cols)


def test_constantes():
    assert NS["PERIODOS"] == [7, 30, 90, 0] and NS["PERIODO_PADRAO"] == 30


def test_publicado_usa_publish_at():
    v = _df([_v("a", "2026-01-01_a")], VC)   # live antiga, mas publicou recente
    b = _df([_b("a", 1, "publicado", "2026-11-20T18:00:00-03:00"),
             _b("a", 2, "publicado", "2026-09-01T18:00:00-03:00")], BC)
    _, bo, n = recorte(v, b, 30, HOJE)
    assert list(bo["bloco_id"]) == [1] and n == 1


def test_publicado_sem_publish_at_cai_na_data_da_pasta():
    v = _df([_v("a", "2026-01-01_a")], VC)
    b = _df([_b("a", 1, "publicado", None)], BC)
    _, bo, n = recorte(v, b, 30, HOJE)
    assert bo.empty and n == 1


def test_descartado_usa_data_da_pasta():
    v = _df([_v("velho", "2026-08-01_velho"), _v("novo", "2026-11-15_novo")], VC)
    b = _df([_b("velho", 1, "descartado"), _b("novo", 1, "descartado")], BC)
    _, bo, n = recorte(v, b, 30, HOJE)
    assert list(bo["stem"]) == ["novo"] and n == 1


def test_pendencias_nunca_somem():
    v = _df([_v("a", "2025-01-01_a")], VC)
    sts = ["aprovado", "quarentena", "agendado", "montado", "segmentado"]
    b = _df([_b("a", i, s, "2025-01-01T10:00:00-03:00") for i, s in enumerate(sts, 1)], BC)
    _, bo, n = recorte(v, b, 7, HOJE)
    assert len(bo) == 5 and n == 0


def test_sem_data_fica():
    v = _df([_v("a", None)], VC)
    b = _df([_b("a", 1, "descartado"), _b("a", 2, "publicado", None)], BC)
    vo, bo, n = recorte(v, b, 7, HOJE)
    assert len(bo) == 2 and n == 0 and len(vo) == 1


def test_dias_zero_nao_filtra():
    v = _df([_v("a", "2020-01-01_a")], VC)
    b = _df([_b("a", 1, "publicado", "2020-01-01T00:00:00-03:00")], BC)
    vo, bo, n = recorte(v, b, 0, HOJE)
    assert n == 0 and len(vo) == 1 and len(bo) == 1


def test_video_sem_bloco_antigo_some_mas_descartado_fica():
    v = _df([_v("antigo", "2026-06-01_antigo"), _v("recente", "2026-11-20_recente"),
             _v("desc", "2026-06-01_desc", "descartado")], VC)
    vo, bo, n = recorte(v, _df([], BC), 30, HOJE)
    assert set(vo["stem"]) == {"recente", "desc"} and n == 1


def test_video_com_todos_blocos_escondidos_nao_conta_duas_vezes():
    """Vídeo com bloco só descartado antigo: conta 1 escondido (o bloco); o vídeo não é
    reavaliado como 'sem bloco' (o filtro usa com_blocos pré-filtro)."""
    v = _df([_v("a", "2026-06-01_a")], VC)
    b = _df([_b("a", 1, "descartado")], BC)
    vo, bo, n = recorte(v, b, 30, HOJE)
    assert bo.empty and n == 1 and len(vo) == 1


def test_borda_exatamente_no_limite_fica():
    v = _df([_v("a", "2026-10-23_a")], VC)   # 30 dias antes de 22/11 = 23/10
    b = _df([_b("a", 1, "descartado")], BC)
    _, bo, n = recorte(v, b, 30, HOJE)
    assert len(bo) == 1 and n == 0


def test_dataframes_vazios():
    vo, bo, n = recorte(pd.DataFrame(), pd.DataFrame(), 30, HOJE)
    assert vo.empty and bo.empty and n == 0


def test_smoke_painel_kanban(banco, monkeypatch):
    import _eventos
    from _eventos import upsert_bloco, upsert_video
    upsert_video("velha", pasta="2026-01-01_velha")
    upsert_bloco("velha", 1, status="descartado", forcar_status=True, titulo="Descartado antigo")
    upsert_video("nova", pasta=f"{datetime.now():%Y-%m-%d}_nova")
    upsert_bloco("nova", 1, status="quarentena", forcar_status=True, titulo="Pendente atual")
    amanha = (datetime.now() + pd.Timedelta(days=1)).strftime("%Y-%m-%dT18:00:00")
    upsert_bloco("nova", 2, status="agendado", forcar_status=True, titulo="Agendado", publish_at=amanha)
    import hoje   # estoque() recarrega módulos de scripts/ (polui outros testes): stub
    monkeypatch.setattr(hoje, "estoque", lambda: None)
    monkeypatch.setenv("MISSAO_DB", str(_eventos.DB_PATH))
    st.cache_data.clear()
    at = AppTest.from_file("../painel/app.py", default_timeout=60).run()
    assert not at.exception
    textos = " ".join(m.value for m in at.markdown)
    assert "Pendente atual" in textos and "Descartado antigo" not in textos
    st.cache_data.clear()
