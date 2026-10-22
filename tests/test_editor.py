"""_editor (agente editor) e flags do 07: tudo mockado (sem API, sem ffmpeg)."""
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

import _editor

ROOT = Path(__file__).parent.parent


def _pasta(tmp_path, desc=True):
    p = tmp_path / "2026-06-25_v"
    p.mkdir()
    blocos = {"blocos": [{"id": 1, "titulo_sugerido": "Velho 1", "texto_thumb": "VELHO 1"},
                         {"id": 2, "titulo_sugerido": "Velho 2", "texto_thumb": "VELHO 2"}]}
    (p / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    if desc:
        partes = []
        for i in (1, 2):
            t = f"Velho {i}"
            partes += ["=" * 70, f"VÍDEO {i:02d} — tema", "=" * 70, "", f"TÍTULO ({len(t)} chars):",
                       t, "", "-" * 70, "DESCRIÇÃO:", "-" * 70, "d", ""]
        (p / "descricoes.txt").write_text("\n".join(partes), encoding="utf-8")
    return p


def _blocos(p):
    return {b["id"]: b for b in json.loads((p / "blocos.json").read_text(encoding="utf-8"))["blocos"]}


def test_gravar_texto_preserva_original_so_na_primeira(tmp_path):
    p = _pasta(tmp_path)
    _editor.gravar_texto(p, 1, "Novo A", "NOVO A")
    _editor.gravar_texto(p, 1, "Novo B", "NOVO B")
    b = _blocos(p)
    assert b[1]["titulo_sugerido"] == "Novo B" and b[1]["texto_thumb"] == "NOVO B"
    assert b[1]["titulo_original"] == "Velho 1" and b[1]["texto_thumb_original"] == "VELHO 1"
    assert "titulo_original" not in b[2] and b[2]["titulo_sugerido"] == "Velho 2"
    txt = (p / "descricoes.txt").read_text(encoding="utf-8")
    assert "Novo B" in txt and "Velho 1" not in txt and "Velho 2" in txt


def test_gravar_texto_sem_descricoes_nao_quebra(tmp_path):
    p = _pasta(tmp_path, desc=False)
    _editor.gravar_texto(p, 1, "X", "Y")
    assert not (p / "descricoes.txt").exists() and _blocos(p)[1]["titulo_sugerido"] == "X"


@pytest.fixture
def chamadas(monkeypatch):
    cmds = []

    def fake_run(cmd, **kw):
        cmds.append(cmd)
        return types.SimpleNamespace(returncode=fake_run.rc)
    fake_run.rc = 0
    monkeypatch.setattr(_editor.subprocess, "run", fake_run)
    return cmds


def test_refazer_artes_variante_certa_sem_short(tmp_path, chamadas):
    p = _pasta(tmp_path)
    assert _editor.refazer_artes(p, 1, p / "thumbs" / "thumb_01_b.png") == []
    assert len(chamadas) == 1
    c = chamadas[0]
    assert c[0] == sys.executable and c[1].endswith("07_thumb.py")
    assert c[2:] == [p.name, "--bloco=1", "--variante=b"]


def test_refazer_artes_manual_so_avisa(tmp_path, chamadas):
    p = _pasta(tmp_path)
    av = _editor.refazer_artes(p, 1, p / "thumbs" / "thumb_01_manual.png")
    assert chamadas == [] and len(av) == 1 and "manual" in av[0]


def test_refazer_artes_short_so_se_existir(tmp_path, chamadas):
    p = _pasta(tmp_path)
    (p / "shorts").mkdir()
    (p / "shorts" / "short_02_x.mp4").write_bytes(b"")     # outro bloco não conta
    _editor.refazer_artes(p, 1, None)
    assert chamadas == []
    (p / "shorts" / "short_01_x.mp4").write_bytes(b"")
    _editor.refazer_artes(p, 1, None)
    assert len(chamadas) == 1 and chamadas[0][1].endswith("10_shorts.py")
    assert chamadas[0][-1] == "--bloco=1"


def test_refazer_artes_falha_vira_aviso(tmp_path, monkeypatch):
    monkeypatch.setattr(_editor.subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(returncode=1))
    p = _pasta(tmp_path)
    (p / "shorts").mkdir()
    (p / "shorts" / "short_01_x.mp4").write_bytes(b"")
    av = _editor.refazer_artes(p, 1, p / "thumbs" / "thumb_01_a.png")
    assert len(av) == 2


class _Client:
    def __init__(self, resp):
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: resp))


def _resp(texto=None, stop="end_turn"):
    content = [types.SimpleNamespace(type="text", text=texto)] if texto is not None else []
    return types.SimpleNamespace(stop_reason=stop, content=content,
                                 usage=types.SimpleNamespace(input_tokens=1000, output_tokens=100))


def test_reescrever_corta_titulo_em_100_e_limpa_espacos():
    j = json.dumps({"titulo": "  " + "a" * 150 + "  ", "texto_thumb": "  OI  ", "mudanca": "m"})
    novo, _ = _editor.reescrever(_Client(_resp(j)), "pedido")
    assert len(novo["titulo"]) == 100 and novo["texto_thumb"] == "OI"


def test_reescrever_recusa_devolve_none():
    novo, resp = _editor.reescrever(_Client(_resp(None, stop="refusal")), "p")
    assert novo is None and resp.stop_reason == "refusal"


def test_reescrever_sem_texto_levanta_json_error():
    with pytest.raises(json.JSONDecodeError):
        _editor.reescrever(_Client(_resp(None)), "p")


def test_custo_e_montar_pedido():
    assert _editor.custo(_resp("x"))[2] == pytest.approx(0.004 + 0.002)
    ped = _editor.montar_pedido("T", "TT", "prob", "transc",
                                [{"titulo": "T2", "texto_thumb": "X", "problema": "p2"}])
    assert "TENTATIVA 1" in ped and "T2" in ped and ped.endswith("transc")


@pytest.mark.parametrize("flags", [["--variante=a"], ["--bloco=1", "--variante=z"]])
def test_07_variante_invalida_sai_com_erro(flags):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "07_thumb.py"), "x", *flags],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "--variante" in r.stderr
