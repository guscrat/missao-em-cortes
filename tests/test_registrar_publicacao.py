"""registrar_publicacao: upload manual (Studio) → banco/painel e estoque do Curador."""
import json
from datetime import datetime

import pytest

import registrar_publicacao as rp


@pytest.mark.parametrize("valor,esperado", [
    ("Gi38fFUC6ug", "Gi38fFUC6ug"),
    ("https://www.youtube.com/watch?v=Gi38fFUC6ug", "Gi38fFUC6ug"),
    ("https://youtu.be/-afesWFg7jQ?si=abc", "-afesWFg7jQ"),
    ("https://www.youtube.com/shorts/rWS03SGbrxo", "rWS03SGbrxo"),
    ("curto", None),
])
def test_youtube_id(valor, esperado):
    assert rp.youtube_id(valor) == esperado


def test_quando_iso():
    agora = datetime(2026, 10, 22, 15, 30, 12)
    assert rp.quando_iso(None, agora) == datetime(2026, 10, 22, 15, 30)
    assert rp.quando_iso("2026-10-24T18:00") == datetime(2026, 10, 24, 18, 0)
    with pytest.raises(SystemExit):
        rp.quando_iso("amanhã")


def test_video_futuro_agendado_passado_publicado(banco):
    agora = datetime(2026, 10, 22, 12)
    assert rp.registrar_video("renan_x", 1, "Gi38fFUC6ug", datetime(2026, 10, 23, 18), agora) == "agendado"
    assert rp.registrar_video("renan_x", 2, "rWS03SGbrxo", datetime(2026, 10, 21, 18), agora) == "publicado"
    linhas = {r["bloco_id"]: r for r in banco("SELECT * FROM blocos WHERE stem='renan_x'")}
    assert linhas[1]["status"] == "agendado" and linhas[1]["youtube_id"] == "Gi38fFUC6ug"
    assert linhas[1]["publish_at"] == "2026-10-23T18:00:00-03:00"
    assert linhas[2]["status"] == "publicado"
    assert banco("SELECT 1 FROM eventos WHERE agente='publicador' AND etapa='publicacao_manual'")


def test_short_marca_postado_e_preserva_resto(tmp_path, banco):
    pasta = tmp_path / "2026-10-22_renan_x"
    (pasta / "shorts").mkdir(parents=True)
    (pasta / "shorts" / "shorts.json").write_text(
        json.dumps({"04": {"arquivo": "short_04_x.mp4", "taxa_rosto": 0.9}}), encoding="utf-8")
    rp.registrar_short(pasta, "renan_x", 4, datetime(2026, 10, 22, 19))
    dados = json.loads((pasta / "shorts" / "shorts.json").read_text(encoding="utf-8"))
    assert dados["04"] == {"arquivo": "short_04_x.mp4", "taxa_rosto": 0.9, "postado": "2026-10-22"}
    with pytest.raises(SystemExit):
        rp.registrar_short(pasta, "renan_x", 9, datetime(2026, 10, 22))


def test_main_exige_video_ou_short(monkeypatch, capsys):
    assert rp.main(["renan_x", "--bloco=1"]) == 1
    assert rp.main(["renan_x", "--bloco=1", "--short", "--video=abc"]) == 1


def _pasta_falsa(tmp_path, monkeypatch):
    pasta = tmp_path / "2026-10-22_renan_x"
    (pasta / "shorts").mkdir(parents=True)
    (pasta / "shorts" / "shorts.json").write_text(
        json.dumps({"02": {"arquivo": "s.mp4"}}), encoding="utf-8")
    monkeypatch.setattr(rp, "achar_pasta", lambda stem: pasta)
    return pasta


def test_main_video_com_quando_futuro_agenda(tmp_path, monkeypatch, banco, capsys):
    _pasta_falsa(tmp_path, monkeypatch)
    assert rp.main(["renan_x", "--bloco=2", "--video=https://youtu.be/Gi38fFUC6ug",
                    "--quando=2999-01-01T18:00"]) == 0
    b = banco("SELECT status, youtube_id, publish_at FROM blocos WHERE stem='renan_x' AND bloco_id=2")[0]
    assert (b["status"], b["youtube_id"]) == ("agendado", "Gi38fFUC6ug")
    assert b["publish_at"] == "2999-01-01T18:00:00-03:00"


def test_main_video_sem_quando_vira_publicado(tmp_path, monkeypatch, banco):
    _pasta_falsa(tmp_path, monkeypatch)
    assert rp.main(["renan_x", "--bloco=2", "--video=Gi38fFUC6ug"]) == 0
    assert banco("SELECT status FROM blocos WHERE stem='renan_x'")[0]["status"] == "publicado"


def test_main_video_invalido_aborta(tmp_path, monkeypatch, banco):
    _pasta_falsa(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        rp.main(["renan_x", "--bloco=2", "--video=curto"])


def test_main_short_com_quando(tmp_path, monkeypatch, banco):
    pasta = _pasta_falsa(tmp_path, monkeypatch)
    assert rp.main(["renan_x", "--bloco=2", "--short", "--quando=2026-10-20"]) == 0
    dados = json.loads((pasta / "shorts" / "shorts.json").read_text(encoding="utf-8"))
    assert dados["02"]["postado"] == "2026-10-20"
