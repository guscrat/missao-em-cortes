"""Step 4c: legenda karaokê. Sem ffmpeg de verdade (subprocess mockado)."""
import importlib.util
import json
from pathlib import Path

import pytest

import _legenda
import _paths

_spec = importlib.util.spec_from_file_location(
    "legendas", Path(__file__).parent.parent / "scripts" / "04c_legendas.py")
leg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(leg)


def _w(word, start, end):
    return {"word": word, "start": start, "end": end}


def test_palavras_do_bloco_relativas_ao_corte_com_padding():
    todas = [_w("antes", 8.0, 8.5), _w(" oi", 9.5, 10.0), _w("tchau", 20.0, 20.5),
             _w("depois", 23.0, 23.5), _w("  ", 12.0, 12.1)]
    bloco = {"timestamp_inicio": "00:00:10", "timestamp_fim": "00:00:21"}
    pal = leg.palavras_do_bloco(todas, bloco)
    # janela do corte = [9, 23): padding 1s antes e 2s depois, igual ao 04_cortar
    assert [p["word"] for p in pal] == ["oi", "tchau"]
    assert pal[0]["start"] == pytest.approx(0.5)


def test_remapear_polido_tira_palavra_cortada_e_puxa_as_seguintes():
    pal = [_w("a", 1.0, 1.5), _w("b", 5.2, 5.6), _w("c", 10.0, 10.5)]
    out = leg.remapear_polido(pal, [{"t_inicio": 5.0, "t_fim": 8.0}])
    assert [p["word"] for p in out] == ["a", "c"]
    assert out[0]["start"] == 1.0
    assert out[1]["start"] == pytest.approx(7.0)   # 10 - 3s removidos


def test_remapear_polido_sem_intervalos_nao_mexe():
    pal = [_w("a", 1.0, 1.5)]
    assert leg.remapear_polido(pal, []) == pal


def test_agrupar_linhas_respeita_limites():
    pal = [_w(f"p{i}", i * 0.3, i * 0.3 + 0.25) for i in range(9)]
    linhas = leg.agrupar_linhas(pal)
    assert [len(l) for l in linhas] == [4, 4, 1]


def test_agrupar_linhas_quebra_em_pausa_e_fim_de_frase():
    pal = [_w("Oi.", 0.0, 0.3), _w("tudo", 0.4, 0.6), _w("bem", 2.0, 2.3)]
    assert [[p["word"] for p in l] for l in leg.agrupar_linhas(pal)] == [["Oi."], ["tudo"], ["bem"]]


def test_agrupar_linhas_quebra_texto_longo():
    pal = [_w("inconstitucionalissimamente", 0, 1), _w("palavrão", 1, 1.5)]
    assert len(leg.agrupar_linhas(pal)) == 2


def test_gerar_ass_karaoke_tempos_e_cores():
    linhas = [[_w("e", 1.0, 1.2), _w("isso", 1.5, 2.0)], [_w("sono.", 2.1, 2.5)]]
    ass = leg.gerar_ass(linhas)
    assert "Style: Karaoke,Anton," in ass and _legenda.AMARELO_14 in ass
    eventos = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    # 1ª linha termina quando a 2ª começa (nunca duas na tela)
    assert eventos[0].startswith("Dialogue: 0,0:00:01.00,0:00:02.10,")
    # \k da 1ª palavra cobre até o início da próxima (pausa incluída)
    assert eventos[0].endswith(r"{\k50}E {\k50}ISSO")
    assert eventos[1].startswith("Dialogue: 0,0:00:02.10,0:00:02.80,")


def test_gerar_ass_escapa_comandos():
    ass = leg.gerar_ass([[_w(r"{\b1}oi", 0, 1)]])
    assert "B1OI" in ass and r"{\b1}" not in ass


def test_ts_ass_formato():
    assert _legenda.ts_ass(3725.456) == "1:02:05.46"


def test_cmd_queimar_usa_caminhos_relativos_no_filtro(tmp_path):
    ass = tmp_path / "cortes" / "legendados" / "legenda_01.ass"
    cmd, cwd = leg.cmd_queimar(tmp_path / "c.mp4", ass, tmp_path / "s.mp4")
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("ass=legenda_01.ass:fontsdir=") and ":" not in vf.split("fontsdir=")[1]
    assert cwd == ass.parent and Path(cmd[-1]).is_absolute()


# ── main() com ffmpeg mockado ──────────────────────────────────────────────

@pytest.fixture
def video(projeto, monkeypatch):
    pasta = projeto.video("v", blocos=[1, 2], cortes=[1, 2])
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))
    for b in blocos["blocos"]:
        b["timestamp_inicio"], b["timestamp_fim"] = "00:00:10", "00:00:20"
    (pasta / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    (pasta / "words.json").write_text(json.dumps({"words": [
        _w("olá", 10.0, 10.4), _w("pessoal", 10.5, 11.0), _w("cortado", 14.0, 14.5),
        _w("fim.", 15.0, 15.5)]}), encoding="utf-8")
    (pasta / "cortes" / "corte_01_slug_polido.mp4").touch()
    (pasta / "polimento.json").write_text(json.dumps({"blocos": [
        {"id": 1, "intervalos_remover": [{"t_inicio": 4.5, "t_fim": 5.5, "motivo": "x"}]}]}),
        encoding="utf-8")
    monkeypatch.setattr(_paths, "OUTPUTS", projeto.outputs)
    chamadas = []

    class _R:
        returncode, stderr = 0, ""

    def fake_run(cmd, cwd=None, **k):
        chamadas.append((cmd, cwd))
        Path(cmd[-1]).touch()
        return _R()
    monkeypatch.setattr(leg.subprocess, "run", fake_run)
    return pasta, chamadas


def test_main_legenda_todos_na_subpasta(video):
    pasta, chamadas = video
    assert leg.main([str(pasta)]) == 0
    out = pasta / "cortes" / "legendados"
    assert sorted(p.name for p in out.glob("*.mp4")) == ["corte_01_slug.mp4", "corte_02_slug.mp4"]
    assert (out / "legenda_01.ass").exists() and len(chamadas) == 2
    # o corte original não é sobrescrito e o polido não é usado sem --polido
    assert "_polido" not in chamadas[0][0][chamadas[0][0].index("-i") + 1]


def test_main_polido_remapeia(video):
    pasta, _ = video
    assert leg.main([str(pasta), "--polido", "--bloco=1"]) == 0
    ass = (pasta / "cortes" / "legendados" / "legenda_01_polido.ass").read_text(encoding="utf-8")
    assert "CORTADO" not in ass and "FIM." in ass
    assert (pasta / "cortes" / "legendados" / "corte_01_slug_polido.mp4").exists()


def test_main_so_queimar_preserva_ass_editado(video):
    pasta, _ = video
    leg.main([str(pasta), "--bloco=1"])
    ass = pasta / "cortes" / "legendados" / "legenda_01.ass"
    ass.write_text("editado à mão", encoding="utf-8")
    leg.main([str(pasta), "--bloco=1", "--so-queimar"])
    assert ass.read_text(encoding="utf-8") == "editado à mão"


def test_main_sem_words_json_falha_alto(video):
    pasta, _ = video
    (pasta / "words.json").unlink()
    with pytest.raises(SystemExit):
        leg.main([str(pasta)])


def test_main_ffmpeg_falhou_retorna_1(video, monkeypatch):
    pasta, _ = video

    class _R:
        returncode, stderr = 1, "boom"
    monkeypatch.setattr(leg.subprocess, "run", lambda *a, **k: _R())
    assert leg.main([str(pasta), "--bloco=1"]) == 1


def test_escolher_arquivo_prefere_legendado(tmp_path):
    for n in ("video_01_a.mp4", "video_01_a_polido.mp4", "video_01_a_legendado.mp4"):
        (tmp_path / n).touch()
    assert _paths.escolher_arquivo(tmp_path, "video_01_*.mp4").name == "video_01_a_legendado.mp4"
    (tmp_path / "video_01_a_polido_legendado.mp4").touch()
    assert _paths.escolher_arquivo(tmp_path, "video_01_*.mp4").name == "video_01_a_polido_legendado.mp4"
    assert _paths.escolher_arquivo(tmp_path, "video_01_*.mp4", False).name == "video_01_a.mp4"
