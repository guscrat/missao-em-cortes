"""Step 10: Shorts 9:16. Sem OpenCV/ffmpeg de verdade (detecção e subprocess mockados)."""
import importlib.util
import json
from pathlib import Path

import pytest

import _paths

_spec = importlib.util.spec_from_file_location(
    "shorts", Path(__file__).parent.parent / "scripts" / "10_shorts.py")
sh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sh)

REGIAO = (1626, 914, 147, 0)   # kim_decisao


# ── enquadramento ──────────────────────────────────────────────────────────

def test_janela_centra_no_rosto_dentro_da_regiao():
    w, h, x, y = sh.janela_9x16(REGIAO, 1000)
    assert (w, h, y) == (514, 914, 0)
    assert x == 1000 - 257 or x == 1000 - 257 + 1
    assert w % 2 == 0 and h % 2 == 0 and x % 2 == 0


def test_janela_presa_nas_bordas_da_regiao():
    _, _, x, _ = sh.janela_9x16(REGIAO, 0)          # rosto na borda esquerda
    assert x >= 147
    w, _, x, _ = sh.janela_9x16(REGIAO, 5000)       # muito à direita
    assert x + w <= 147 + 1626


def test_janela_sem_rosto_usa_centro_da_regiao():
    w, _, x, _ = sh.janela_9x16(REGIAO, None)
    assert abs((x + w / 2) - (147 + 1626 / 2)) <= 2


def test_janela_regiao_estreita_nao_estoura():
    w, h, x, _ = sh.janela_9x16((400, 1080, 10, 0), 200)
    assert w <= 400 and x >= 10 and x + w <= 410


def _det(frame, cx, w=40, cy=300):
    return {"frame": frame, "cx": cx, "cy": cy, "w": w}


def test_agrupar_rostos_junta_mesmo_rosto_entre_frames():
    dets = [_det(0, 500), _det(0, 1100), _det(1, 510), _det(1, 1095), _det(2, 1500)]
    grupos = sh.agrupar_rostos(dets)
    assert sorted(len(g) for g in grupos) == [1, 2, 2]


def test_escolher_rosto_prefere_frequente_perto_do_centro():
    # telão: rosto grande, sempre lá, longe do centro; palestrante: menor, central
    telao = [_det(i, 300, w=200) for i in range(10)]
    palestrante = [_det(i, 980, w=30) for i in range(0, 10, 2)]
    cx, taxa = sh.escolher_rosto(sh.agrupar_rostos(telao + palestrante), 10, 960)
    assert cx == 980 and taxa == 0.5


def test_escolher_rosto_ignora_rosto_raro_no_centro():
    frequente = [_det(i, 400) for i in range(10)]
    raro = [_det(0, 960)]
    cx, _ = sh.escolher_rosto(sh.agrupar_rostos(frequente + raro), 10, 960)
    assert cx == 400


def test_escolher_rosto_sem_frequente_devolve_o_mais_visto_com_taxa_baixa():
    dets = [_det(0, 400), _det(1, 400), _det(5, 900)]
    cx, taxa = sh.escolher_rosto(sh.agrupar_rostos(dets), 10, 960)
    assert cx == 400 and taxa == 0.2


def test_escolher_rosto_sem_deteccao():
    assert sh.escolher_rosto([], 10, 960) == (None, 0.0)
    assert sh.escolher_rosto([], 0, 960) == (None, 0.0)


# ── texto e ASS ────────────────────────────────────────────────────────────

def test_quebrar_titulo_em_linhas_curtas():
    assert sh.quebrar_titulo("Direita é campo de vagabundos") == r"DIREITA É CAMPO\NDE VAGABUNDOS"


def test_quebrar_titulo_no_maximo_3_linhas():
    assert sh.quebrar_titulo("um dois tres quatro cinco seis sete oito nove dez onze doze treze "
                             "catorze quinze").count(r"\N") == 2


def test_gerar_ass_short_tem_titulo_marca_e_karaoke():
    pal = [{"word": "olá", "start": 0.5, "end": 0.9}, {"word": "gente", "start": 1.0, "end": 1.4}]
    ass = sh.gerar_ass_short(pal, "Título curto", 20.0)
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "Style: Titulo," in ass and "Style: Marca," in ass and "Style: Karaoke," in ass
    assert ",Titulo,,0,0,0,,TÍTULO CURTO" in ass and "MISSÃO EM CORTES" in ass
    assert r"{\k" in ass and "OLÁ" in ass


def test_ler_zoom(tmp_path, monkeypatch):
    cfg = tmp_path / "zoom.json"
    cfg.write_text(json.dumps({"_comment": "x", "a": "1476:830:200:100", "b": "crop=10:20:3:4"}))
    monkeypatch.setattr(sh, "ZOOM_JSON", cfg)
    assert sh.ler_zoom("a") == (1476, 830, 200, 100)
    assert sh.ler_zoom("b") == (10, 20, 3, 4)
    assert sh.ler_zoom("nao_tem") is None
    monkeypatch.setattr(sh, "ZOOM_JSON", tmp_path / "nao_existe.json")
    assert sh.ler_zoom("a") is None


def test_cmd_short_crop_escala_legenda_e_fade(tmp_path):
    ass = tmp_path / "shorts" / "short_01.ass"
    cmd, cwd = sh.cmd_short(tmp_path / "v.mp4", 10.0, 20.0, (514, 914, 846, 0), ass,
                            tmp_path / "s.mp4")
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("crop=514:914:846:0,scale=1080:1920")
    assert vf.index("ass=short_01.ass") < vf.index("fade=t=in")   # texto também faz fade
    assert "fade=t=out:st=19.700" in vf
    assert cmd[cmd.index("-ss") + 1] == "10.000" and cmd[cmd.index("-t") + 1] == "20.000"
    assert cwd == ass.parent and Path(cmd[-1]).is_absolute()


def test_slug():
    assert sh.slug("Kim Kataguiri anuncia Superministério!") == "kim_kataguiri_anuncia_superministerio"


# ── main() com detecção e ffmpeg mockados ──────────────────────────────────

@pytest.fixture
def video(projeto, monkeypatch):
    pasta = projeto.video("kim", blocos=[1, 2, 3])
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))
    blocos["blocos"][0]["cold_open"] = {"timestamp_inicio": "00:00:10", "timestamp_fim": "00:00:30"}
    blocos["blocos"][1]["cold_open"] = {"timestamp_inicio": "00:01:00", "timestamp_fim": "00:01:20"}
    (pasta / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    (pasta / "words.json").write_text(json.dumps({"words": [
        {"word": "oi", "start": 12.0, "end": 12.3}, {"word": "fora", "start": 50.0, "end": 50.3}]}),
        encoding="utf-8")
    (projeto.inputs / "kim.mp4").touch()
    zoom = projeto.root / "zoom.json"
    zoom.write_text(json.dumps({"kim": "1626:914:147:0"}))
    monkeypatch.setattr(_paths, "OUTPUTS", projeto.outputs)
    monkeypatch.setattr(sh, "INPUTS", projeto.inputs)
    monkeypatch.setattr(sh, "ZOOM_JSON", zoom)
    monkeypatch.setattr(sh, "centro_rosto", lambda v, ini, fim, reg: (1000.0, 0.9))
    chamadas = []

    class _R:
        returncode, stderr = 0, ""

    def fake_run(cmd, cwd=None, **k):
        chamadas.append(cmd)
        Path(cmd[-1]).touch()
        return _R()
    monkeypatch.setattr(sh.subprocess, "run", fake_run)
    return pasta, chamadas


def test_main_gera_short_por_cold_open(video):
    pasta, chamadas = video
    assert sh.main([str(pasta)]) == 0
    out = pasta / "shorts"
    assert sorted(p.name for p in out.glob("*.mp4")) == ["short_01_tema_1.mp4", "short_02_tema_2.mp4"]
    reg = json.loads((out / "shorts.json").read_text(encoding="utf-8"))
    assert reg["01"]["revisar"] is False and reg["01"]["crop"].startswith("514:914:")
    assert reg["01"]["duracao_s"] == 21.0                      # 20s + 0.5s de folga em cada ponta
    ass = (out / "short_01.ass").read_text(encoding="utf-8")
    assert "OI" in ass and "FORA" not in ass and "THUMB 1" in ass   # texto_thumb como manchete
    assert len(chamadas) == 2                                   # bloco 3 sem cold_open: pulado


def test_main_pouco_rosto_marca_revisar(video, monkeypatch, capsys):
    pasta, _ = video
    monkeypatch.setattr(sh, "centro_rosto", lambda *a: (None, 0.0))
    assert sh.main([str(pasta), "--bloco=1"]) == 0
    assert "REVISE" in capsys.readouterr().out
    reg = json.loads((pasta / "shorts" / "shorts.json").read_text(encoding="utf-8"))
    assert reg["01"]["revisar"] is True and reg["01"]["taxa_rosto"] == 0.0


def test_main_sem_video_original_falha_alto(video, projeto):
    pasta, _ = video
    (projeto.inputs / "kim.mp4").unlink()
    with pytest.raises(SystemExit):
        sh.main([str(pasta)])


def test_main_sem_zoom_usa_quadro_inteiro(video, monkeypatch, capsys):
    pasta, _ = video
    monkeypatch.setattr(sh, "ZOOM_JSON", Path("nao_existe.json"))
    monkeypatch.setattr(sh, "dimensoes", lambda v: (1920, 1080))
    regioes = []
    monkeypatch.setattr(sh, "centro_rosto", lambda v, i, f, reg: regioes.append(reg) or (None, 0.5))
    sh.main([str(pasta), "--bloco=1"])
    assert regioes == [(1920, 1080, 0, 0)] and "zoom.json" in capsys.readouterr().out


def test_main_ffmpeg_falhou_retorna_1(video, monkeypatch):
    pasta, _ = video

    class _R:
        returncode, stderr = 1, "boom"
    monkeypatch.setattr(sh.subprocess, "run", lambda *a, **k: _R())
    assert sh.main([str(pasta), "--bloco=1"]) == 1
