"""reconciliar_falhas (13) e hoje.marcar_novas (painel). Banco temporário, sem rede."""
import pandas as pd

from test_curador import cu, raiz  # noqa: F401

import _eventos as ev
import hoje


def _falha(vid, stem):
    ev.gravar_sugestao(vid, status="falhou", mensagem="erro", stem=stem)


def test_falha_com_bloco_agendado_vira_processada(raiz):
    _falha("a", "live1")
    ev.upsert_bloco("live1", 1, status="segmentado")
    ev.upsert_bloco("live1", 2, forcar_status=True, status="agendado")
    assert cu.reconciliar_falhas() == ["a"]
    s, = ev.listar_sugestoes()
    assert s["status"] == "processada" and s["mensagem"] == "terminado na mão: 1 corte(s) pronto(s)"


def test_falha_so_com_segmentado_ou_quarentena_continua(raiz):
    _falha("a", "live1")
    ev.upsert_bloco("live1", 1, status="segmentado")
    ev.upsert_bloco("live1", 2, forcar_status=True, status="quarentena")
    assert cu.reconciliar_falhas() == []
    assert ev.listar_sugestoes()[0]["status"] == "falhou"


def test_falha_sem_stem_ignorada(raiz):
    ev.gravar_sugestao("a", status="falhou", mensagem="erro")
    assert cu.reconciliar_falhas() == []
    assert ev.listar_sugestoes()[0]["status"] == "falhou"


def _df(*linhas):
    return pd.DataFrame([{"video_id": v, "sugerida_em": e, "prioridade": p, "data": d}
                         for v, e, p, d in linhas])


def test_marcar_novas_ordem():
    sug = _df(("velha_alta", "2026-10-29T17:00", 9, "2026-10-01"),
              ("nova_baixa", "2026-10-31T17:00", 3, "2026-10-02"),
              ("nova_alta", "2026-10-31T17:00", 8, "2026-10-03"))
    r = hoje.marcar_novas(sug)
    assert list(r["video_id"]) == ["nova_alta", "nova_baixa", "velha_alta"]
    assert list(r["nova"]) == [True, True, False]


def test_marcar_novas_todas_do_mesmo_dia():
    sug = _df(("a", "2026-10-31T10:00", 1, "2026-10-01"), ("b", "2026-10-31T17:00", 5, "2026-10-02"))
    assert not hoje.marcar_novas(sug)["nova"].any()


def test_marcar_novas_sem_coluna_ou_toda_nula():
    sug = pd.DataFrame([{"video_id": "a", "prioridade": 1, "data": "2026-10-01"}])
    assert hoje.marcar_novas(sug)["nova"].tolist() == [False]
    sug["sugerida_em"] = None
    assert hoje.marcar_novas(sug)["nova"].tolist() == [False]
