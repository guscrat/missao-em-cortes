"""_legenda (extraído do 04c) e detecção de rosto do step 10 com cv2 falso."""
import importlib.util
import sys
import types
from pathlib import Path

import _legenda

_spec = importlib.util.spec_from_file_location(
    "shorts2", Path(__file__).parent.parent / "scripts" / "10_shorts.py")
sh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sh)


def test_hhmmss_para_segundos():
    assert _legenda.hhmmss_para_segundos("01:02:03.5") == 3723.5


def test_palavras_na_janela_relativa_e_ignora_vazias():
    todas = [{"word": " a", "start": 9.0, "end": 9.5},
             {"word": " b", "start": 10.5, "end": 11.0},
             {"word": "  ", "start": 11.0, "end": 11.2},
             {"word": " c", "start": 20.0, "end": 20.5}]
    out = _legenda.palavras_na_janela(todas, 10.0, 20.0)
    assert out == [{"word": "b", "start": 0.5, "end": 1.0}]


def test_filtro_ass_relativo_sem_drive(tmp_path):
    filtro, cwd = _legenda.filtro_ass(tmp_path / "x.ass")
    assert filtro.startswith("ass=x.ass:fontsdir=") and ":\\" not in filtro
    assert cwd == tmp_path


class _FakeNp:
    def __getitem__(self, k):
        return self


def _fake_cv2(n_frames_ok, rostos):
    cv2 = types.SimpleNamespace()
    cv2.data = types.SimpleNamespace(haarcascades="")
    cv2.CAP_PROP_POS_MSEC = 0
    cv2.COLOR_BGR2GRAY = 0
    lidos = {"n": 0, "released": False}

    class Det:
        def __init__(self, *_): pass
        def detectMultiScale(self, *a, **k): return rostos

    class Cap:
        def __init__(self, *_): pass
        def set(self, *_): pass
        def read(self):
            lidos["n"] += 1
            return lidos["n"] <= n_frames_ok, _FakeNp()
        def release(self): lidos["released"] = True

    cv2.CascadeClassifier = Det
    cv2.VideoCapture = Cap
    cv2.resize = lambda img, *a, **k: img
    cv2.cvtColor = lambda img, *_: img
    return cv2, lidos


def test_centro_rosto_com_cv2_falso(monkeypatch):
    cv2, lidos = _fake_cv2(10_000, [(100, 50, 40, 40)])
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    regiao = (960, 540, 100, 0)   # escala 1.0
    cx, taxa = sh.centro_rosto(Path("v.mp4"), 0.0, 10.0, regiao)
    assert cx == 100 + 100 + 20 and taxa == 1.0
    assert lidos["released"]


def test_centro_rosto_frames_ilegiveis_sem_rosto(monkeypatch):
    cv2, lidos = _fake_cv2(0, [(1, 1, 40, 40)])
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    cx, taxa = sh.centro_rosto(Path("v.mp4"), 0.0, 5.0, (960, 540, 0, 0))
    assert cx is None and lidos["released"]
