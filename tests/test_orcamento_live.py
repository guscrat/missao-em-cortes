"""Orçamento por live (_custo), trava nos scripts pagos, alerta do painel. Tudo mockado."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

import _custo
import _eventos
import hoje

ROOT = Path(__file__).parent.parent


def _resp(i=0, o=0, esc=0, e1h=0, lei=0, modelo="claude-opus-5-5"):
    return SimpleNamespace(model=modelo, usage=SimpleNamespace(
        input_tokens=i, output_tokens=o, cache_creation_input_tokens=esc,
        cache_read_input_tokens=lei,
        cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=e1h)))


def _gasta(stem, usd):
    _eventos.evento(stem, "03_segmentar", "llm", custo_usd=usd)


def _config(tmp_path, **cfg):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "painel.json").write_text(json.dumps(cfg), encoding="utf-8")


def _libera_arquivo(dados):
    _custo.LIBERADAS.parent.mkdir(parents=True, exist_ok=True)
    _custo.LIBERADAS.write_text(json.dumps(dados), encoding="utf-8")


# ── custo com escrita de 1h ────────────────────────────────────────────────

def test_escrita_1h_custa_2x_o_input():
    # Opus: input 4.00 -> 1h = 8.00/M; 5min = 5.00/M
    assert _custo.uso(_resp(esc=1_000_000, e1h=1_000_000), "claude-opus-5-5")["custo_usd"] == pytest.approx(8.0)
    assert _custo.uso(_resp(esc=1_000_000), "claude-opus-5-5")["custo_usd"] == pytest.approx(5.0)


def test_escrita_mista_5min_e_1h():
    u = _custo.uso(_resp(esc=1_000_000, e1h=400_000), "claude-opus-5-5")
    assert u["custo_usd"] == pytest.approx(600_000 * 5 / 1e6 + 400_000 * 8 / 1e6)
    assert u["cache_escrita"] == 1_000_000


def test_escrita_1h_maior_que_escrita_total_e_limitada():
    assert _custo.uso(_resp(esc=100, e1h=500), "claude-opus-5-5")["custo_usd"] == pytest.approx(100 * 8 / 1e6)


def test_sem_campo_cache_creation_segue_como_5min():
    resp = SimpleNamespace(model="claude-opus-5-5", usage=SimpleNamespace(
        input_tokens=0, output_tokens=0, cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=None))
    assert _custo.uso(resp, "claude-opus-5-5")["custo_usd"] == pytest.approx(5.0)


# ── gasto_live ─────────────────────────────────────────────────────────────

def test_gasto_live_soma_so_da_live(banco):
    _gasta("a", 0.5)
    _gasta("a", 0.25)
    _gasta("b", 9.0)
    assert _custo.gasto_live("a") == pytest.approx(0.75)
    assert _custo.gasto_live("nada") == 0.0


def test_gasto_live_sem_banco_e_zero(banco):
    assert _custo.gasto_live("a") == 0.0


def test_gasto_live_banco_quebrado_e_none(banco, capsys):
    _eventos.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _eventos.DB_PATH.write_text("isso não é sqlite", encoding="utf-8")
    assert _custo.gasto_live("a") is None
    assert "sem a trava" in capsys.readouterr().err


# ── limites / checar_orcamento ─────────────────────────────────────────────

def test_limites_padrao_e_config(tmp_path):
    assert _custo.limites_live() == (1.0, 2.0)
    _config(tmp_path, alerta_live_usd=0.5, trava_live_usd=3)
    assert _custo.limites_live() == (0.5, 3.0)


def test_abaixo_da_trava_passa(banco):
    _gasta("a", 1.99)
    _custo.checar_orcamento("a", "x")


def test_na_trava_para_e_grava_aviso(banco):
    _gasta("a", 2.0)
    with pytest.raises(_custo.OrcamentoEstourado) as e:
        _custo.checar_orcamento("a", "03_segmentar")
    assert isinstance(e.value, SystemExit)
    assert "_custo.py liberar a" in str(e.value)
    av = banco("SELECT etapa, status, mensagem FROM eventos WHERE status = 'aviso'")
    assert av and av[0]["etapa"] == "03_segmentar" and "orçamento" in av[0]["mensagem"]


def test_trava_vem_do_config(banco, tmp_path):
    _config(tmp_path, trava_live_usd=5)
    _gasta("a", 4.0)
    _custo.checar_orcamento("a", "x")
    _gasta("a", 1.0)
    with pytest.raises(_custo.OrcamentoEstourado):
        _custo.checar_orcamento("a", "x")


def test_liberada_acima_do_gasto_passa_so_pra_aquela_live(banco):
    _gasta("a", 2.5)
    _gasta("b", 2.5)
    _libera_arquivo({"a": 4.0})
    _custo.checar_orcamento("a", "x")
    with pytest.raises(_custo.OrcamentoEstourado):
        _custo.checar_orcamento("b", "x")


def test_liberada_mas_gasto_alcanca_o_novo_teto_trava(banco):
    _gasta("a", 4.0)
    _libera_arquivo({"a": 4.0})
    with pytest.raises(_custo.OrcamentoEstourado):
        _custo.checar_orcamento("a", "x")


def test_banco_quebrado_nao_trava(banco):
    _eventos.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _eventos.DB_PATH.write_text("lixo", encoding="utf-8")
    _custo.checar_orcamento("a", "x")


# ── liberar + CLI ──────────────────────────────────────────────────────────

def test_liberar_padrao_e_gasto_mais_trava(banco):
    _gasta("a", 2.3)
    assert _custo.liberar("a") == pytest.approx(4.3)
    assert _custo.liberadas() == {"a": 4.3}
    _custo.checar_orcamento("a", "x")


def test_liberar_ate_e_preserva_outras(banco):
    _custo.liberar("a", ate=7)
    _custo.liberar("b", ate=3.456)
    assert _custo.liberadas() == {"a": 7.0, "b": 3.46}


def _cli(monkeypatch, *argv):
    spec = importlib.util.spec_from_file_location("__main__", ROOT / "scripts" / "_custo.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "argv", ["_custo.py", *argv])
    spec.loader.exec_module(mod)


def test_cli_liberar_com_ate(banco, tmp_path, monkeypatch, capsys):
    # o __main__ é um módulo novo: aponta o state dele pra tmp via ROOT do arquivo real
    # não dá pra trocar; então roda em subprocesso com cwd/ROOT falso copiando o script
    scripts = tmp_path / "fake" / "scripts"
    scripts.mkdir(parents=True)
    for nome in [p.name for p in (ROOT / "scripts").glob("_*.py")]:
        (scripts / nome).write_text((ROOT / "scripts" / nome).read_text(encoding="utf-8"),
                                    encoding="utf-8")
    env = {**os.environ, "MISSAO_DB": str(tmp_path / "t.db"), "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(scripts / "_custo.py"), "liberar", "live_x", "--ate=6.5"],
                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0 and "6.50" in r.stdout, r.stdout + r.stderr
    salvo = json.loads((tmp_path / "fake" / "state" / "orcamento_lives.json").read_text(encoding="utf-8"))
    assert salvo == {"live_x": 6.5}


def test_cli_liberar_sem_ate_usa_gasto_mais_trava(tmp_path):
    scripts = tmp_path / "fake" / "scripts"
    scripts.mkdir(parents=True)
    for nome in [p.name for p in (ROOT / "scripts").glob("_*.py")]:
        (scripts / nome).write_text((ROOT / "scripts" / nome).read_text(encoding="utf-8"),
                                    encoding="utf-8")
    env = {**os.environ, "MISSAO_DB": str(tmp_path / "t.db"), "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(scripts / "_custo.py"), "liberar", "live_x"],
                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    salvo = json.loads((tmp_path / "fake" / "state" / "orcamento_lives.json").read_text(encoding="utf-8"))
    assert salvo == {"live_x": 2.0}   # gasto 0 + trava padrão (config ausente no ROOT falso)


def test_cli_liberar_sem_stem_sai_com_uso(monkeypatch):
    with pytest.raises(SystemExit) as e:
        _cli(monkeypatch, "liberar")
    assert "liberar <stem>" in str(e.value)


# ── trava num script de loop (11_revisor) ──────────────────────────────────

def test_revisor_para_antes_de_chamar_o_client(banco):
    spec = importlib.util.spec_from_file_location("revisor_orc", ROOT / "scripts" / "11_revisor.py")
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)
    _gasta("live", 3.0)
    client = MagicMock()
    with pytest.raises(_custo.OrcamentoEstourado):
        rv.editar(client, MagicMock(), "live", Path("."), {"id": 1}, "t", "T", "p", "", [])
    with pytest.raises(_custo.OrcamentoEstourado):
        rv.revisar_bloco(client, MagicMock(), "live", Path("."), {"id": 1}, "01", None, "t", "T", "")
    assert not client.messages.create.called


# ── alertas_custo_live ─────────────────────────────────────────────────────

AGORA = pd.Timestamp("2026-10-26 12:00")


def _custos(*linhas):
    return pd.DataFrame(linhas, columns=["stem", "custo_usd", "ultimo"])


def test_alerta_vazio_e_abaixo_do_alerta(tmp_path):
    assert hoje.alertas_custo_live(_custos(), AGORA, 1, 2) == []
    assert hoje.alertas_custo_live(_custos(("a", 0.99, "2026-10-26 10:00")), AGORA, 1, 2,
                                   tmp_path / "n.json") == []


def test_alerta_aviso_a_partir_de_1(tmp_path):
    r = hoje.alertas_custo_live(_custos(("a", 1.0, "2026-10-26 10:00")), AGORA, 1, 2, tmp_path / "n.json")
    assert [x[0] for x in r] == ["aviso"] and "a" in r[0][1]


def test_alerta_erro_a_partir_de_2(tmp_path):
    r = hoje.alertas_custo_live(_custos(("a", 2.0, "2026-10-26 10:00")), AGORA, 1, 2, tmp_path / "n.json")
    assert [x[0] for x in r] == ["erro"] and "liberar a" in r[0][2]


def test_alerta_liberada_vira_aviso_e_depois_erro(tmp_path):
    lib = tmp_path / "lib.json"
    lib.write_text(json.dumps({"a": 4.0}), encoding="utf-8")
    r = hoje.alertas_custo_live(_custos(("a", 2.5, "2026-10-26 10:00")), AGORA, 1, 2, lib)
    assert [x[0] for x in r] == ["aviso"] and "liberada até US$ 4.00" in r[0][2]
    r = hoje.alertas_custo_live(_custos(("a", 4.0, "2026-10-26 10:00")), AGORA, 1, 2, lib)
    assert [x[0] for x in r] == ["erro"]


def test_alerta_janela_de_7_dias(tmp_path):
    c = _custos(("velha", 5.0, "2026-10-18 10:00"), ("nova", 5.0, "2026-10-20 10:00"))
    r = hoje.alertas_custo_live(c, AGORA, 1, 2, tmp_path / "n.json")
    assert [x[1] for x in r] == ["Live travada por custo: nova"]


def test_alerta_ordena_pelo_maior_gasto(tmp_path):
    c = _custos(("a", 2.5, "2026-10-26 10:00"), ("b", 9.0, "2026-10-26 10:00"))
    r = hoje.alertas_custo_live(c, AGORA, 1, 2, tmp_path / "n.json")
    assert [x[1].split(": ")[1] for x in r] == ["b", "a"]


def test_padrao_do_painel_tem_limites():
    assert hoje.PADRAO["alerta_live_usd"] == 1.0 and hoje.PADRAO["trava_live_usd"] == 2.0
