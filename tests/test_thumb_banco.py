"""_thumb_banco: banco de rostos (reserva da thumb). ffmpeg sempre mockado; BANCO em tmp_path."""
import json

import pytest

import _thumb_banco as tb


@pytest.fixture
def banco_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(tb, "BANCO", tmp_path / "rostos")
    chamadas = []

    def fake_frame(video, t, saida, crop=None):
        chamadas.append((video, t, crop))
        saida.write_bytes(b"png")
    monkeypatch.setattr(tb, "extrair_frame", fake_frame)
    return tmp_path / "rostos", chamadas


def _pasta(tmp_path, bid=1, cand=None, nome="2026-11-01_v"):
    pasta = tmp_path / nome
    (pasta / "thumbs").mkdir(parents=True)
    cand = cand or {"video": "corte_01.mp4", "t": 12.5, "nota": 7, "rosto": [1, 2, 3, 4],
                    "fonte": "corte"}
    (pasta / "thumbs" / f"candidatos_{bid:02d}.json").write_text(
        json.dumps({"candidatos": [cand], "variantes": {"a": 0}}), encoding="utf-8")
    return pasta


def test_slug_e_apresentador():
    assert tb.slug("Renan Santos") == "renan_santos"
    assert tb.slug("Guto Zacarías!") == "guto_zacarias"
    assert tb.apresentador({"speakers_principais": ["Kim", "X"]}) == "Kim"
    assert tb.apresentador({"speakers_principais": []}) is None


def test_guardar_grava_png_e_meta(banco_tmp, tmp_path):
    banco, chamadas = banco_tmp
    pasta = _pasta(tmp_path)
    r = tb.guardar(pasta, {"id": 1, "speakers_principais": ["Renan Santos"]})
    assert r == banco / "renan_santos" / "2026-11-01_v_01.png" and r.exists()
    meta = json.loads(r.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["nota"] == 7 and meta["rosto"] == [1, 2, 3, 4]
    assert chamadas[0][0] == pasta / "cortes" / "corte_01.mp4" and chamadas[0][1] == 12.5


@pytest.mark.parametrize("bloco,cand", [
    ({"id": 1, "speakers_principais": []}, None),                       # sem apresentador
    ({"id": 1, "speakers_principais": ["Kim"]}, {"video": "x", "t": 1, "rosto": None}),
    ({"id": 1, "speakers_principais": ["Kim"]},
     {"video": "x", "t": 1, "rosto": [1], "fonte": "banco"}),           # veio do banco
    ({"id": 9, "speakers_principais": ["Kim"]}, None),                  # sem fila do bloco 9
])
def test_guardar_devolve_none_sem_levantar(banco_tmp, tmp_path, bloco, cand):
    pasta = _pasta(tmp_path, cand=cand)
    assert tb.guardar(pasta, bloco) is None


def test_guardar_ffmpeg_falha_devolve_none(banco_tmp, tmp_path, monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "ffmpeg")
    monkeypatch.setattr(tb, "extrair_frame", boom)
    assert tb.guardar(_pasta(tmp_path), {"id": 1, "speakers_principais": ["Kim"]}) is None


def _semear(banco, pessoa, nome, nota, rosto=(1, 2, 3, 4)):
    d = banco / pessoa
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{nome}.png").write_bytes(b"x")
    (d / f"{nome}.json").write_text(json.dumps({"nota": nota, "rosto": list(rosto)}), encoding="utf-8")


def test_candidatos_ordena_por_nota_e_exclui_pasta(banco_tmp):
    banco, _ = banco_tmp
    _semear(banco, "kim", "A_01", 3)
    _semear(banco, "kim", "B_01", 9)
    _semear(banco, "kim", "C_01", 5, rosto=())      # sem rosto: fora
    c = tb.candidatos("Kim")
    assert [x["nota"] for x in c] == [9, 3] and all(x["fonte"] == "banco" for x in c)
    assert [x["nota"] for x in tb.candidatos("Kim", excluir="B")] == [3]
    assert tb.candidatos(None) == [] and tb.candidatos("Ninguem") == []


def test_podar_fica_com_as_melhores(banco_tmp, monkeypatch):
    banco, _ = banco_tmp
    monkeypatch.setattr(tb, "MAX_POR_PESSOA", 2)
    for i, n in enumerate([1, 8, 5, 9]):
        _semear(banco, "kim", f"L{i}_01", n)
    tb.podar("kim")
    assert sorted(x["nota"] for x in tb.candidatos("kim")) == [8, 9]
    assert len(list((banco / "kim").glob("*.json"))) == 2


def test_apresentador_tira_rotulo_speaker():
    assert tb.apresentador({"speakers_principais": ["Speaker (Arthur do Val)"]}) == "Arthur do Val"
    assert tb.apresentador({"speakers_principais": ["Renan Santos"]}) == "Renan Santos"
