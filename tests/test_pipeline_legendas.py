"""pipeline.py: legenda karaokê (04c) ligada por padrão. subprocess/evento mockados."""
import io
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import _eventos

NL = chr(10)
PIPELINE = Path(__file__).parent.parent / "scripts" / "pipeline.py"


def _rodar(monkeypatch, argv, falha_em=None, desde="--desde=3"):
    """Roda pipeline.py como módulo. Retorna (comandos [(script, args)], SystemExit|None)."""
    cmds = []

    class FakePopen:
        def __init__(self, cmd, *a, **k):
            self.script = Path(cmd[1]).name
            cmds.append((self.script, list(cmd[2:])))
            self.stderr = io.BufferedReader(io.BytesIO(b""))

        def wait(self):
            return 1 if self.script == falha_em else 0

    def fake_run(cmd, *a, **k):   # sincronizar_estado ao fim continua via subprocess.run
        cmds.append((Path(cmd[1]).name, list(cmd[2:])))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(_eventos, "evento", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["pipeline.py", "stem_x", *([desde] if desde else []), *argv])
    saida = None
    try:
        runpy.run_path(str(PIPELINE), run_name="__main__")
    except SystemExit as e:
        saida = e
    return cmds, saida


def _por_script(cmds):
    return {s: a for s, a in cmds}


def test_padrao_inclui_legendas_e_montar_legendado(monkeypatch):
    cmds, _ = _rodar(monkeypatch, [])
    d = _por_script(cmds)
    assert "04c_legendas.py" in d
    assert "--legendado" in d["06_montar.py"]
    scripts = [s for s, _ in cmds]
    assert scripts.index("04_cortar.py") < scripts.index("04c_legendas.py") < scripts.index("05_cards.py")


def test_sem_legendas_remove_04c_e_legendado(monkeypatch):
    cmds, _ = _rodar(monkeypatch, ["--sem-legendas"])
    d = _por_script(cmds)
    assert "04c_legendas.py" not in d
    assert "--legendado" not in d["06_montar.py"]


def test_polir_passa_polido_ao_04c(monkeypatch):
    cmds, _ = _rodar(monkeypatch, ["--polir"])
    d = _por_script(cmds)
    assert "--polido" in d["04c_legendas.py"]
    assert "--polido" in d["06_montar.py"] and "--legendado" in d["06_montar.py"]
    assert "--polido" not in _por_script(_rodar(monkeypatch, [])[0])["04c_legendas.py"]


def test_retomada_inclui_sem_legendas(monkeypatch):
    _, saida = _rodar(monkeypatch, ["--sem-legendas"], falha_em="04_cortar.py")
    assert saida is not None and "--sem-legendas" in str(saida.code)
    assert "--desde=4" in str(saida.code)


def test_retomada_padrao_nao_menciona_sem_legendas(monkeypatch):
    _, saida = _rodar(monkeypatch, [], falha_em="04c_legendas.py")
    assert "--sem-legendas" not in str(saida.code)
    assert "--desde=4c" in str(saida.code)


def test_desde_depois_do_04c_sem_legendados_falha_alto(monkeypatch):
    # stem_x não tem pasta em outputs/: nenhum corte legendado
    cmds, saida = _rodar(monkeypatch, ["--desde=5"])
    assert saida is not None and "--desde=4c" in str(saida.code)
    assert cmds == []                                   # nenhum step rodou


def test_desde_depois_do_04c_com_sem_legendas_segue(monkeypatch):
    cmds, _ = _rodar(monkeypatch, ["--desde=5", "--sem-legendas"])
    assert [s for s, _ in cmds][0] == "05_cards.py"


def test_sem_desde_nao_quebra(monkeypatch):
    # sem --desde: antes dava TypeError (None > 4.7) antes de qualquer step. stem_x não
    # tem transcrição nem vídeo, então agora chega na checagem do step 2 e pede o download
    cmds, saida = _rodar(monkeypatch, ["--polir"], desde=None)
    assert saida is not None and "01_baixar.py" in str(saida.code)
    assert cmds == []


def test_refazer_vai_so_pro_03(monkeypatch):
    cmds, _ = _rodar(monkeypatch, ["--refazer"], desde="--desde=3")
    assert _por_script(cmds)["03_segmentar.py"][-1] == "--refazer"
    assert all("--refazer" not in a for s, a in cmds if s != "03_segmentar.py")


def test_sem_refazer_03_nao_recebe_flag(monkeypatch):
    cmds, _ = _rodar(monkeypatch, [], desde="--desde=3")
    assert "--refazer" not in _por_script(cmds)["03_segmentar.py"]


# ── rodar(): stderr ao vivo + detalhe da falha ──────────────────────────────

def _rodar_fn():
    sys.path.insert(0, str(PIPELINE.parent))
    import _rodar
    return _rodar.rodar


def test_rodar_captura_ultima_linha_com_acento(tmp_path, capsys):
    rodar = _rodar_fn()
    f = tmp_path / "s.py"
    f.write_text(NL.join(["import sys", "print('ruido', file=sys.stderr)", "sys.exit('msg com acento á')"]), encoding="utf-8")
    cod, msg = rodar([sys.executable, str(f)])
    assert (cod, msg) == (1, "msg com acento á")


def test_rodar_ok_sem_stderr(tmp_path):
    rodar = _rodar_fn()
    f = tmp_path / "ok.py"
    f.write_text("print('oi')", encoding="utf-8")
    assert rodar([sys.executable, str(f)]) == (0, "")


def test_rodar_trunca_em_200(tmp_path):
    rodar = _rodar_fn()
    f = tmp_path / "g.py"
    f.write_text(NL.join(["import sys", "sys.exit('x' * 500)"]), encoding="utf-8")
    cod, msg = rodar([sys.executable, str(f)])
    assert cod == 1 and len(msg) == 200


def test_evento_de_falha_inclui_detalhe(monkeypatch):
    eventos = []

    class FakePopen:
        def __init__(self, cmd, *a, **k):
            self.stderr = io.BufferedReader(io.BytesIO("ValueError: inválido".encode() + bytes([10])))

        def wait(self):
            return 2

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(_eventos, "evento", lambda *a, **k: eventos.append((a, k)))
    monkeypatch.setattr(sys, "argv", ["pipeline.py", "stem_x", "--desde=3"])
    with pytest.raises(SystemExit):
        runpy.run_path(str(PIPELINE), run_name="__main__")
    falha = [(a, k) for a, k in eventos if "falha" in a]
    assert falha and falha[0][1]["mensagem"] == "exit 2: ValueError: inválido"


def test_evento_de_falha_sem_stderr_so_exit(monkeypatch):
    eventos = []

    class FakePopen:
        def __init__(self, cmd, *a, **k):
            self.stderr = io.BufferedReader(io.BytesIO(b""))

        def wait(self):
            return 3

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setattr(_eventos, "evento", lambda *a, **k: eventos.append((a, k)))
    monkeypatch.setattr(sys, "argv", ["pipeline.py", "stem_x", "--desde=3"])
    with pytest.raises(SystemExit):
        runpy.run_path(str(PIPELINE), run_name="__main__")
    assert [k["mensagem"] for a, k in eventos if "falha" in a] == ["exit 3"]
