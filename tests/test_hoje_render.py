"""hoje.aba_hoje / _placar / _custo: render dos cartões com st mockado (sem AppTest, sem state/ real)."""
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import streamlit as st

import hoje

AGORA = pd.Timestamp("2026-10-22 12:00:00")
CUSTO_OK = {"gasto": 1.0, "orcamento": 10.0, "pct": 10.0, "projecao": 3.0,
            "por_agente": pd.Series({"curador": 1.0})}
EST_OK = {"dias": 5.0, "minimo": 3, "coberto_ate": date(2026, 10, 27)}
VAZIO = pd.DataFrame()


def _renderiza(monkeypatch, tmp_path, blocos, tarefas, est, custo, upload=None):
    """Roda hoje.aba_hoje capturando tudo que vai pro st; devolve o texto concatenado."""
    capturado = []
    monkeypatch.setattr(st, "markdown", lambda t, **kw: capturado.append(t))
    monkeypatch.setattr(st, "columns", lambda *a, **k: [MagicMock(), MagicMock()])
    monkeypatch.setattr(st, "container", lambda **k: MagicMock())
    monkeypatch.setattr(st, "warning", lambda t, **k: capturado.append(f"WARN:{t}"))
    monkeypatch.setattr(st, "caption", lambda t, **k: capturado.append(f"CAP:{t}"))
    monkeypatch.setattr(hoje.visual, "barras", lambda s, **k: capturado.append(f"BARRAS:{list(s.index)}"))
    up = tmp_path / "upload.json"
    if upload is not None:
        up.write_text(json.dumps(upload))
    monkeypatch.setattr(hoje, "UPLOAD_JSON", up)
    monkeypatch.setattr(hoje, "STATE", tmp_path / "state_falso")
    hoje.aba_hoje(blocos, tarefas, est, custo, AGORA)
    return " ".join(capturado)


def test_sem_estoque_mostra_cartao_de_erro(monkeypatch, tmp_path):
    txt = _renderiza(monkeypatch, tmp_path, VAZIO, VAZIO, None, CUSTO_OK)
    assert "<div class='ct erro'><div class='ct-r'>Canal coberto até" in txt
    assert "não consegui calcular" in txt and "indisponível" in txt
    assert "nada esperando você" in txt and "Decisões pendentes ·" not in txt


def test_decisoes_pendentes_listam_e_escapam(monkeypatch, tmp_path):
    blocos = pd.DataFrame([{"stem": "v", "bloco_id": 2, "status": "quarentena", "titulo": "Em <dúvida>",
                            "motivo": "áudio & cortes"}])
    tarefas = pd.DataFrame([{"id": 7, "titulo": "Painel", "decisao_pendente": "Qual cor?"}])
    txt = _renderiza(monkeypatch, tmp_path, blocos, tarefas, EST_OK, CUSTO_OK)
    assert "Decisões pendentes · 2" in txt
    assert "1 do time de dev · 1 em quarentena" in txt
    assert "Tarefa #7 · Painel" in txt and "Qual cor?" in txt
    assert "Em &lt;dúvida&gt;" in txt and "áudio &amp; cortes" in txt
    assert "<div class='ct alerta'><div class='ct-r'>Decisões pendentes" in txt
    assert "<div class='ct '><div class='ct-r'>Canal coberto até" in txt     # estoque ok = sem tom


def test_auditoria_aprovada_tom_ok(monkeypatch, tmp_path):
    txt = _renderiza(monkeypatch, tmp_path, VAZIO, VAZIO, EST_OK, CUSTO_OK,
                     upload={"auditoria_aprovada": True})
    assert "<div class='ct ok'><div class='ct-r'>Auditoria YouTube" in txt
    assert "upload e Shorts liberados" in txt
    txt = _renderiza(monkeypatch, tmp_path, VAZIO, VAZIO, EST_OK, CUSTO_OK,
                     upload={"auditoria_aprovada": "true"})   # só o booleano True conta
    assert "upload e Shorts travados" in txt and "ct ok'" not in txt


def test_custo_acima_do_orcamento_tom_alerta(monkeypatch, tmp_path):
    caro = {"gasto": 8.0, "orcamento": 10.0, "pct": 80.0, "projecao": 12.5,
            "por_agente": pd.Series({"revisor": 8.0})}
    txt = _renderiza(monkeypatch, tmp_path, VAZIO, VAZIO, EST_OK, caro)
    assert "<div class='ct alerta'><div class='ct-r'>Custo do mês" in txt
    assert "WARN:No ritmo atual o mês fecha em US$ 12.50" in txt and "BARRAS:['revisor']" in txt
    txt = _renderiza(monkeypatch, tmp_path, VAZIO, VAZIO, EST_OK, CUSTO_OK)
    assert "<div class='ct '><div class='ct-r'>Custo do mês" in txt and "WARN:" not in txt


def test_custo_sem_gasto_nao_desenha_barras(monkeypatch, tmp_path):
    zero = {"gasto": 0.0, "orcamento": 10.0, "pct": 0.0, "projecao": 0.0,
            "por_agente": pd.Series(dtype=float)}
    txt = _renderiza(monkeypatch, tmp_path, VAZIO, VAZIO, EST_OK, zero)
    assert "CAP:Nenhum gasto de API este mês." in txt and "BARRAS" not in txt


def test_placar_html_vazio_e_preenchido():
    vazio = hoje._placar(hoje.placar(Path("nao_existe.json")))
    assert "—" in vazio and "width:0.0%" in vazio and "Aguardando o Analista" in vazio
    cheio = hoje._placar({"inscritos": (500, 1000), "horas_12m": (9000, 4000),
                          "views_shorts_90d": (None, 10_000_000), "atualizado": "2026-11-01T10:00:00-03:00"})
    assert "width:50.0%" in cheio and "width:100.0%" in cheio      # acima da meta é limitado a 100
    assert "Atualizado em 2026-11-01 10:00" in cheio and "9.000" in cheio
