"""shorts_oculto: lançador sem janela do upload de Shorts. subprocess falso, paths em tmp_path."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import shorts_oculto as so

INICIO = datetime(2026, 11, 7, 17, 50, 0)


@pytest.fixture
def amb(tmp_path, monkeypatch, banco):
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(so, "LOG", tmp_path / "state" / "shorts.log")
    monkeypatch.setattr(so, "FILA", tmp_path / "state" / "shorts_fila.json")
    monkeypatch.setattr(so, "ROOT", tmp_path)
    return SimpleNamespace(banco=banco, fila=so.FILA, log=so.LOG)


def _falhas(amb):
    try:
        return [r["mensagem"] for r in
                amb.banco("SELECT mensagem FROM eventos WHERE etapa='09_shorts_rodada' AND status='falha'")]
    except Exception:   # noqa: BLE001 — banco nem foi criado
        return []


def _resumo(amb, quando):
    amb.fila.write_text(json.dumps({"atualizado": quando.isoformat(timespec="seconds") + "-03:00"}))


def test_comando_sobe_a_fila_toda():
    assert so.comando()[1:] == ["run", "py", "scripts/09_upload.py", "todos", "--shorts"]


def test_ok_nao_registra(amb):
    assert so.conferir(0, INICIO) is None and _falhas(amb) == []


def test_saiu_com_erro_mas_09_ja_registrou_a_rodada(amb):
    _resumo(amb, INICIO + timedelta(minutes=3))       # 09 gravou: falha de upload já está no banco
    assert so.conferir(1, INICIO) is None and _falhas(amb) == []


def test_quebrou_antes_do_resumo_registra_com_a_ultima_linha(amb):
    _resumo(amb, INICIO - timedelta(days=1))          # resumo de ontem
    msg = so.conferir(1, INICIO, detalhe="google.auth.exceptions.RefreshError: invalid_grant")
    assert "exit 1" in msg and "invalid_grant" in msg
    assert len(_falhas(amb)) == 1


def test_nem_iniciou(amb):
    msg = so.conferir(None, INICIO, erro="não consegui iniciar o upload de Shorts (x)")
    assert "não consegui iniciar" in msg and len(_falhas(amb)) == 1


def test_ultima_linha_so_desta_rodada(amb):
    amb.log.write_text("velho\n=== rodada ===\n", encoding="utf-8")
    desde = amb.log.stat().st_size
    with open(amb.log, "a", encoding="utf-8") as f:
        f.write("subindo\nTraceback\nValueError: x\n\n")
    assert so.ultima_linha(amb.log, desde) == "ValueError: x"
    assert so.ultima_linha(amb.log, amb.log.stat().st_size) == ""


def test_main_roda_o_09_e_loga(amb, monkeypatch):
    chamadas = []
    monkeypatch.setattr(so.subprocess, "run",
                        lambda cmd, **kw: chamadas.append(cmd) or SimpleNamespace(returncode=0))
    assert so.main() == 0
    assert chamadas and chamadas[0][-2:] == ["todos", "--shorts"]
    assert "shorts_oculto (sem janela)" in amb.log.read_text(encoding="utf-8")


def test_resumo_em_utc_compara_na_hora_local(amb):
    """O 09 grava em UTC: resumo de 1h antes do início (em UTC 'parece' depois) não conta."""
    from datetime import timezone
    antes = (INICIO - timedelta(hours=1)).astimezone(timezone.utc)
    amb.fila.write_text(json.dumps({"atualizado": antes.isoformat(timespec="seconds")}))
    assert so.resumo_gravado(INICIO) is False
    depois = (INICIO + timedelta(minutes=2)).astimezone(timezone.utc)
    amb.fila.write_text(json.dumps({"atualizado": depois.isoformat(timespec="seconds")}))
    assert so.resumo_gravado(INICIO) is True
