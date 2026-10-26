"""03_segmentar: pós-processamento do nível do módulo, rodado de verdade (subprocess)
em --reaproveitar sobre segmentacao_bruta.json + words.json sintéticos numa pasta tmp.
Sem API, sem rede, banco apontado pra tmp."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import _fronteira as fr

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "03_segmentar.py"
PERIODO = 4.2    # s por frase: 8 palavras x 0.4s + 1.0s de pausa
DUR = 3600.0


def t_frase(i):
    return i * PERIODO


def frase(i):
    return " ".join(f"t{i}k{k}" + ("." if k == 7 else "") for k in range(8))


def words(n=int(DUR / PERIODO)):
    out = []
    for i in range(n):
        for k in range(8):
            s = t_frase(i) + k * 0.4
            out.append({"word": f"t{i}k{k}" + ("." if k == 7 else ""),
                        "start": round(s, 2), "end": round(s + 0.38, 2)})
    return out


def ts(s):
    return fr.segundos_para_ts(s)


def idx(minuto):
    return round(minuto * 60 / PERIODO)


def bloco(bid, ini_min, fim_min, score=5, llm_ini=None, llm_fim=None, **extra):
    """Bloco cujas frases de abertura/encerramento são as REAIS de ini_min/fim_min;
    llm_ini/llm_fim (min) são os tempos (errados) que o LLM disse."""
    i, f = idx(ini_min), idx(fim_min)
    b = {"id": bid, "tema": f"tema {bid}", "titulo_sugerido": f"titulo {bid}",
         "score_potencial": score,
         "timestamp_inicio": ts((llm_ini if llm_ini is not None else ini_min) * 60),
         "timestamp_fim": ts((llm_fim if llm_fim is not None else fim_min) * 60),
         "duracao_minutos": fim_min - ini_min,
         "frase_de_abertura": frase(i), "frase_de_encerramento": frase(f - 1)}
    b.update(extra)
    return b


@pytest.fixture
def pasta(tmp_path):
    p = tmp_path / "outputs" / "2026-10-26_fake"
    p.mkdir(parents=True)
    (p / "words.json").write_text(json.dumps({"duration": DUR, "words": words()}), encoding="utf-8")
    return p


def rodar(pasta, blocos, flags=("--reaproveitar",), bruta=True):
    if bruta:
        (pasta / "segmentacao_bruta.json").write_text(
            json.dumps({"blocos": blocos}), encoding="utf-8")
    env = {**os.environ, "MISSAO_DB": str(pasta.parent / "t.db"), "ANTHROPIC_API_KEY": "x",
           "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(SCRIPT), str(pasta), *flags], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    saida = pasta / "blocos.json"
    return r, (json.loads(saida.read_text(encoding="utf-8")) if saida.exists() else None)


def secs(s):
    h, m, x = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(x)


def test_ancora_corrige_tempo_errado_do_llm(pasta):
    # LLM disse 25-35 min, mas as frases citadas estão em 10-20 min
    r, d = rodar(pasta, [bloco(1, 10, 20, llm_ini=18, llm_fim=28)])
    assert r.returncode == 0, r.stdout + r.stderr
    b = d["blocos"][0]
    assert abs(secs(b["timestamp_inicio"]) - 600) < 5
    assert abs(secs(b["timestamp_fim"]) - 1200) < 6
    assert b["ancora"]["inicio"] and b["ancora"]["fim"]
    assert b["ancora"]["desvio_s"][0] < -400
    assert "ancorado pelo texto" in r.stdout
    assert 9.5 <= b["duracao_minutos"] <= 10.5


def test_bloco_curto_descartado_e_nao_derruba_com_erro_de_cold_open(pasta):
    curto = bloco(1, 5, 11, cold_open={"timestamp_inicio": "bobagem",
                                       "timestamp_fim": "x", "frase": "a b c"})
    bom = bloco(2, 20, 30)
    r, d = rodar(pasta, [curto, bom])
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (pasta / "blocos_invalido.json").exists()
    assert [b["tema"] for b in d["blocos"]] == ["tema 2"]
    assert len(d["descartados"]) == 1
    desc = d["descartados"][0]
    assert desc["tema"] == "tema 1" and "mínimo" in desc["motivo"]
    assert "cold_open com timestamps ilegíveis" not in r.stdout


def test_sobreposicao_grande_fica_o_de_maior_score(pasta):
    r, d = rodar(pasta, [bloco(1, 10, 22, score=6), bloco(2, 12, 24, score=9)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert [x["tema"] for x in d["blocos"]] == ["tema 2"]
    assert d["descartados"][0]["tema"] == "tema 1"
    assert "sobreposição" in d["descartados"][0]["motivo"]


def test_sobreposicao_grande_primeiro_com_maior_score(pasta):
    r, d = rodar(pasta, [bloco(1, 10, 22, score=9), bloco(2, 12, 24, score=6)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert [x["tema"] for x in d["blocos"]] == ["tema 1"]
    assert d["descartados"][0]["tema"] == "tema 2"


def test_sobreposicao_curta_ajusta_fim_do_anterior(pasta):
    # fim do 1 invade ~8s o início do 2 (dentro da janela de 30s)
    a = bloco(1, 10, 20)
    b = bloco(2, 20, 31)
    a["frase_de_encerramento"] = frase(idx(20) + 2)
    a["timestamp_fim"] = ts(t_frase(idx(20) + 3))
    r, d = rodar(pasta, [a, b])
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(d["blocos"]) == 2 and "descartados" not in d
    ini2 = secs(d["blocos"][1]["timestamp_inicio"])
    fim1 = secs(d["blocos"][0]["timestamp_fim"])
    ini1 = secs(d["blocos"][0]["timestamp_inicio"])
    assert fim1 <= ini2
    assert d["blocos"][0]["duracao_minutos"] == round((fim1 - ini1) / 60, 1)


def test_cold_open_fora_do_bloco_cai_pro_gancho_do_short(pasta):
    sh_i = idx(14)
    sh = {"timestamp_inicio": ts(t_frase(sh_i)), "timestamp_fim": ts(t_frase(sh_i + 20)),
          "gancho": frase(sh_i), "frase_final": frase(sh_i + 19)}
    co = {"timestamp_inicio": ts(40 * 60), "timestamp_fim": ts(40 * 60 + 20),   # fora do bloco
          "frase": "nada disso existe nas palavras"}
    r, d = rodar(pasta, [bloco(1, 10, 20, short=sh, cold_open=co)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "usei o gancho do Short" in r.stdout
    c = d["blocos"][0]["cold_open"]
    assert 600 <= secs(c["timestamp_inicio"]) < secs(c["timestamp_fim"]) <= 1200
    assert abs(secs(c["timestamp_inicio"]) - t_frase(sh_i)) < 6
    assert c["frase"].startswith(f"t{sh_i}k0")


def test_ids_renumerados_por_tempo_sem_buraco(pasta):
    r, d = rodar(pasta, [bloco(7, 30, 40), bloco(3, 10, 20), bloco(9, 45, 55)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert [b["id"] for b in d["blocos"]] == [1, 2, 3]
    tempos = [secs(b["timestamp_inicio"]) for b in d["blocos"]]
    assert tempos == sorted(tempos)
    assert d["blocos"][0]["tema"] == "tema 3"


def test_reaproveitar_sem_bruta_sai_com_erro(pasta):
    r, d = rodar(pasta, [], bruta=False)
    assert r.returncode != 0
    assert "segmentacao_bruta.json" in (r.stdout + r.stderr)
    assert d is None


def test_nenhum_bloco_sobra_sai_com_erro_e_dump_com_descartados(pasta):
    r, d = rodar(pasta, [bloco(1, 1, 5), bloco(2, 10, 14)])
    assert r.returncode != 0 and d is None
    dump = json.loads((pasta / "blocos_invalido.json").read_text(encoding="utf-8"))
    assert dump["blocos"] == [] and len(dump["descartados"]) == 2


def test_empate_de_score_fica_o_primeiro_com_motivo_certo(pasta):
    r, d = rodar(pasta, [bloco(1, 1, 20, score=7), bloco(2, 10, 30, score=7)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert [b["tema"] for b in d["blocos"]] == ["tema 1"]
    assert "mesmo score" in d["descartados"][0]["motivo"]
