"""Capítulos do YouTube: _capitulos (ancorar, LinhaDoTempo, linhas, no_video), _descricoes
(remover/trocar), 08 ponta a ponta, 03 pós-processamento e fluxo do 11. Tudo mockado."""
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

import _capitulos as cap
import _descricoes as d
import _fronteira as fr
import _paths

desc08 = importlib.import_module("08_descricao")

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("revisor_cap", ROOT / "scripts" / "11_revisor.py")
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

PERIODO = 4.2    # 8 palavras x 0.4s + 1.0s de pausa, ponto no fim da frase


def frase(i):
    return " ".join(f"t{i}k{k}" + ("." if k == 7 else "") for k in range(8))


def t_frase(i):
    return i * PERIODO


def palavras(n=900):
    out = []
    for i in range(n):
        for k in range(8):
            s = t_frase(i) + k * 0.4
            out.append({"word": f"t{i}k{k}" + ("." if k == 7 else ""),
                        "start": round(s, 2), "end": round(s + 0.38, 2)})
    return out


PAL = palavras()


def ts(s):
    return fr.segundos_para_ts(s)


def seg(ts_):
    h, m, s = ts_.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def cap_llm(i, titulo, erro_s=0.0):
    return {"titulo": titulo, "timestamp_inicio": ts(t_frase(i) + erro_s),
            "frase_de_abertura": frase(i)}


# ── ancorar ────────────────────────────────────────────────────────────────

INI, FIM = t_frase(100), t_frase(300)    # ~7 min a ~21 min


def test_ancorar_acha_tempo_real_pela_frase():
    caps = [cap_llm(100, "Abertura"), cap_llm(150, "Meio", erro_s=20), cap_llm(220, "Fim", erro_s=-15)]
    saida, avisos = cap.ancorar(PAL, caps, INI, FIM)
    assert avisos == []
    assert [c["titulo"] for c in saida] == ["Abertura", "Meio", "Fim"]
    assert seg(saida[1]["timestamp_inicio"]) == pytest.approx(t_frase(150), abs=0.1)
    assert seg(saida[2]["timestamp_inicio"]) == pytest.approx(t_frase(220), abs=0.1)


def test_ancorar_primeiro_forcado_no_inicio_do_bloco():
    saida, _ = cap.ancorar(PAL, [cap_llm(110, "A"), cap_llm(150, "B")], INI, FIM)
    assert seg(saida[0]["timestamp_inicio"]) == pytest.approx(INI, abs=0.01)


def test_ancorar_ordena_e_descarta_fora_do_bloco_e_ilegivel():
    caps = [cap_llm(200, "Depois"), cap_llm(120, "Antes"), cap_llm(50, "Fora do bloco"),
            {"titulo": "Quebrado", "timestamp_inicio": "bobagem", "frase_de_abertura": "a b c"},
            {"titulo": "", "timestamp_inicio": ts(INI + 30)}]
    saida, avisos = cap.ancorar(PAL, caps, INI, FIM)
    assert [c["titulo"] for c in saida] == ["Antes", "Depois"]
    assert any("fora do bloco" in a for a in avisos) and any("ilegível" in a for a in avisos)


def test_ancorar_maximo_8_e_titulo_curto():
    caps = [cap_llm(100 + 10 * i, f"Cap {i}") for i in range(10)]
    caps[3]["titulo"] = "x" * 80
    saida, avisos = cap.ancorar(PAL, caps, INI, FIM)
    assert len(saida) == cap.MAX_CAPITULOS
    assert len(saida[3]["titulo"]) <= cap.TITULO_MAX
    assert any("10 capítulos" in a for a in avisos)


def test_ancorar_sem_words_mantem_tempo_do_llm():
    saida, _ = cap.ancorar([], [cap_llm(150, "B"), cap_llm(200, "C")], INI, FIM)
    assert seg(saida[1]["timestamp_inicio"]) == pytest.approx(t_frase(200), abs=0.01)


def test_ancorar_vazio():
    assert cap.ancorar(PAL, [], INI, FIM) == ([], [])
    assert cap.ancorar(PAL, None, INI, FIM) == ([], [])


# ── LinhaDoTempo ───────────────────────────────────────────────────────────

def pasta_bloco(tmp_path, polido=False, cold=False, ivs=()):
    p = tmp_path / "outputs" / "2026-10-26_fake"
    (p / "cortes").mkdir(parents=True)
    (p / "finalizados").mkdir()
    (p / "finalizados" / ("video_01_slug_polido.mp4" if polido else "video_01_slug.mp4")).touch()
    if cold:
        (p / "cortes" / "cold_01_slug.mp4").touch()
    if ivs:
        (p / "polimento.json").write_text(json.dumps({"blocos": [
            {"id": 1, "intervalos_remover": [{"t_inicio": a, "t_fim": z, "motivo": "x"} for a, z in ivs]},
            {"id": 2, "intervalos_remover": [{"t_inicio": 1, "t_fim": 99, "motivo": "outro bloco"}]},
        ]}), encoding="utf-8")
    return p


def bloco(cold=False, **extra):
    b = {"id": 1, "timestamp_inicio": ts(INI), "timestamp_fim": ts(FIM)}
    if cold:
        b["cold_open"] = {"timestamp_inicio": ts(t_frase(500)), "timestamp_fim": ts(t_frase(500) + 20)}
    b.update(extra)
    return b


def test_tempo_simples_sem_cold_sem_polido(tmp_path):
    t = cap.LinhaDoTempo(pasta_bloco(tmp_path), bloco(), PAL)
    assert t.offset == cap.INTRO_S + cap.CARD_S
    assert t.para_video(t.ini) == pytest.approx(6.0)
    assert t.para_video(t.ini + 100) == pytest.approx(106.0)
    assert t.total_s == pytest.approx(6.0 + (t.fim - t.ini) + cap.OUTRO_S)


def test_tempo_com_cold_open(tmp_path):
    t = cap.LinhaDoTempo(pasta_bloco(tmp_path, cold=True), bloco(cold=True), PAL)
    a, z = fr.janela(PAL, t_frase(500), t_frase(500) + 20, fr.COLD_PADDING_S, fr.COLD_PADDING_S)
    assert t.offset == pytest.approx((z - a) + 6.0)
    assert t.offset > 20 + 6.0 - 0.1
    assert t.para_video(t.ini) == pytest.approx(t.offset)


def test_cold_open_sem_mp4_nao_conta(tmp_path):
    t = cap.LinhaDoTempo(pasta_bloco(tmp_path, cold=False), bloco(cold=True), PAL)
    assert t.offset == 6.0


def test_polido_desconta_jump_cuts_so_do_proprio_bloco(tmp_path):
    p = pasta_bloco(tmp_path, polido=True, ivs=[(10, 20), (50, 60)])
    t = cap.LinhaDoTempo(p, bloco(), PAL)
    assert t.corte_s == pytest.approx((t.fim - t.ini) - 20)
    assert t.para_video(t.ini + 5) == pytest.approx(6 + 5)
    assert t.para_video(t.ini + 30) == pytest.approx(6 + 30 - 10)      # depois do 1º corte
    assert t.para_video(t.ini + 100) == pytest.approx(6 + 100 - 20)    # depois dos 2
    assert t.para_video(t.ini + 15) == pytest.approx(6 + 10)           # dentro do removido: cola


def test_nao_polido_ignora_polimento_json(tmp_path):
    p = pasta_bloco(tmp_path, polido=False, ivs=[(10, 20)])
    t = cap.LinhaDoTempo(p, bloco(), PAL)
    assert t.ivs == [] and t.para_video(t.ini + 30) == pytest.approx(36)


@pytest.mark.parametrize("polido,cold", [(False, False), (True, False), (False, True), (True, True)])
def test_ida_e_volta_para_video_para_live(tmp_path, polido, cold):
    p = pasta_bloco(tmp_path, polido=polido, cold=cold, ivs=[(10, 20), (50, 60)] if polido else ())
    t = cap.LinhaDoTempo(p, bloco(cold=cold), PAL)
    for dt in (0, 5, 25, 65, 150, 400):          # fora de qualquer trecho removido
        live = t.ini + dt
        assert t.para_live(t.para_video(live)) == pytest.approx(live, abs=1e-6)


def test_para_video_e_para_live_nos_limites(tmp_path):
    t = cap.LinhaDoTempo(pasta_bloco(tmp_path), bloco(), PAL)
    assert t.para_video(t.ini - 50) == t.offset                      # antes do bloco: clamp
    assert t.para_video(t.fim + 500) == pytest.approx(t.offset + t.fim - t.ini)
    assert t.para_live(0) == t.ini                                   # dentro do cold/intro/card
    assert t.para_live(10**6) == t.fim


# ── linhas (regras do YouTube) ─────────────────────────────────────────────

def tempo_fake(corte_s=900.0, offset=6.0):
    t = types.SimpleNamespace(corte_s=corte_s, total_s=offset + corte_s + cap.OUTRO_S)
    t.para_video = lambda live: offset + live
    return t


def caps_em(*segundos):
    return [{"titulo": f"Assunto {i}", "timestamp_inicio": ts(s)} for i, s in enumerate(segundos)]


def test_linhas_formata_e_primeiro_vira_zero():
    out = cap.linhas(caps_em(500, 600, 800), tempo_fake())
    assert out == ["00:00 Assunto 0", "10:06 Assunto 1", "13:26 Assunto 2"]


def test_linhas_formato_com_hora():
    out = cap.linhas(caps_em(0, 100, 3700), tempo_fake(corte_s=4000))
    assert out[-1] == "1:01:46 Assunto 2"


def test_linhas_corte_menor_que_8min_nao_tem():
    assert cap.linhas(caps_em(0, 100, 200), tempo_fake(corte_s=479)) == []
    assert cap.linhas(caps_em(0, 100, 200), tempo_fake(corte_s=480)) != []


def test_linhas_menos_de_3_nao_tem():
    assert cap.linhas(caps_em(0, 100), tempo_fake()) == []
    assert cap.linhas([], tempo_fake()) == []
    assert cap.linhas(None, tempo_fake()) == []


def test_linhas_capitulo_com_menos_de_10s_sai():
    out = cap.linhas(caps_em(0, 100, 105, 300), tempo_fake())
    assert [l.split(" ", 1)[1] for l in out] == ["Assunto 0", "Assunto 1", "Assunto 3"]


def test_linhas_exatamente_10s_fica():
    assert len(cap.linhas(caps_em(0, 100, 110), tempo_fake())) == 3


def test_linhas_segundo_a_menos_de_10s_do_zero_sai():
    out = cap.linhas(caps_em(0, 2, 100, 200), tempo_fake(offset=0.0))
    assert [l.split(" ", 1)[1] for l in out] == ["Assunto 0", "Assunto 2", "Assunto 3"]


def test_linhas_ultimo_perto_do_fim_sai():
    t = tempo_fake(corte_s=900)     # total 911
    out = cap.linhas(caps_em(0, 100, 200, 900), t)   # último em 906: 5s do fim
    assert len(out) == 3
    assert cap.linhas(caps_em(0, 100, 900), t) == []   # sobraria 2


def test_linhas_maximo_8_e_corrigir_grafia():
    out = cap.linhas(caps_em(*range(0, 1000, 100)), tempo_fake(), corrigir=str.upper)
    assert len(out) == cap.MAX_CAPITULOS and out[0] == "00:00 ASSUNTO 0"


# ── no_video ───────────────────────────────────────────────────────────────

def test_no_video_le_so_a_secao_capitulos():
    texto = ("Resumo com 12:34 no meio.\n\nCapítulos:\n00:00 Abertura\n05:10 Segundo assunto\n"
             "1:02:03 Terceiro\n\nPrincipais momentos:\n• 09:59 Isso não é capítulo\n10:00 Nem isso\n")
    assert cap.no_video(texto) == [(0.0, "Abertura"), (310.0, "Segundo assunto"),
                                   (3723.0, "Terceiro")]


def test_no_video_sem_secao_ou_so_resumo():
    assert cap.no_video("Resumo.\n\n00:00 Solta\n05:00 Solta") == []
    assert cap.no_video("") == []


def test_no_video_aceita_crlf():
    assert cap.no_video("R\r\n\r\nCapítulos:\r\n00:00 A\r\n01:00 B\r\n\r\nx") == [(0.0, "A"), (60.0, "B")]


# ── _descricoes.remover_capitulos / trocar_capitulos ───────────────────────

def txt_bloco(bid, caps=("00:00 Abertura", "05:00 Meio", "10:00 Fim", "12:00 Extra"),
              ganchos=("Fala A", "Fala B")):
    linhas = ["=" * 70, f"VÍDEO {bid:02d} — tema", "=" * 70, "", "TÍTULO (3 chars):", "Abc", "",
              "-" * 70, "DESCRIÇÃO:", "-" * 70, "", f"Resumo {bid}.", ""]
    if caps:
        linhas += ["Capítulos:", *caps, ""]
    if ganchos:
        linhas += ["Principais momentos:", *[f"• {g}" for g in ganchos], ""]
    linhas += ["─" * 40, "🎬 Inscreva-se: https://x", "📺 Conteúdo original: https://y",
               "🖼️ Créditos da imagem: Foto de Fulano (CC BY 2.0)", "",
               "#MissaoEmCortes", "-" * 70, "TAGS (x):", "-" * 70, "a, b", ""]
    return "\n".join(linhas)


def dois_blocos():
    return txt_bloco(1) + "\n" + txt_bloco(2)


def test_remover_um_capitulo_do_meio_preserva_resto():
    out = d.remover_capitulos(dois_blocos(), 1, ["Meio"])
    b1 = d.ler_descricoes(out)[1]["descricao"]
    assert cap.no_video(b1) == [(0.0, "Abertura"), (600.0, "Fim"), (720.0, "Extra")]
    assert d.momentos(b1) == ["Fala A", "Fala B"]
    assert "Créditos da imagem" in b1 and "Conteúdo original" in b1
    assert d.ler_descricoes(out)[2] == d.ler_descricoes(dois_blocos())[2]


def test_remover_o_primeiro_tira_secao_inteira_e_preserva_momentos():
    out = d.remover_capitulos(dois_blocos(), 1, ["Abertura"])
    b1 = d.ler_descricoes(out)[1]["descricao"]
    assert "Capítulos:" not in b1 and "00:00" not in b1 and "05:00" not in b1
    assert d.momentos(b1) == ["Fala A", "Fala B"]
    assert "Créditos da imagem" in b1 and "\n\n\n" not in b1
    assert "Capítulos:" in d.ler_descricoes(out)[2]["descricao"]


def test_remover_ate_sobrar_menos_de_3_tira_secao():
    out = d.remover_capitulos(dois_blocos(), 1, ["Meio", "Extra"])
    assert "Capítulos:" not in d.ler_descricoes(out)[1]["descricao"]
    out2 = d.remover_capitulos(dois_blocos(), 1, ["Meio"], minimo=4)
    assert "Capítulos:" not in d.ler_descricoes(out2)[1]["descricao"]


def test_remover_titulo_inexistente_ou_bloco_inexistente_nao_muda():
    base = dois_blocos()
    assert d.remover_capitulos(base, 1, ["Não existe"]) == base
    assert d.remover_capitulos(base, 9, ["Meio"]) == base
    assert d.remover_capitulos(txt_bloco(1, caps=()), 1, ["Meio"]) == txt_bloco(1, caps=())


def test_remover_sem_momentos_nem_creditos_nao_quebra():
    out = d.remover_capitulos(txt_bloco(1, ganchos=()), 1, ["Abertura"])
    b1 = d.ler_descricoes(out)[1]["descricao"]
    assert "Capítulos:" not in b1 and "Resumo 1." in b1


def test_trocar_capitulos_substitui_secao_e_preserva_o_resto():
    out = d.trocar_capitulos(dois_blocos(), 1, ["00:00 Novo A", "01:00 Novo B", "02:00 Novo C"])
    b1 = d.ler_descricoes(out)[1]["descricao"]
    assert cap.no_video(b1) == [(0.0, "Novo A"), (60.0, "Novo B"), (120.0, "Novo C")]
    assert "Abertura" not in b1 and b1.count("Capítulos:") == 1
    assert d.momentos(b1) == ["Fala A", "Fala B"] and "Créditos da imagem" in b1
    assert d.ler_descricoes(out)[2] == d.ler_descricoes(dois_blocos())[2]


def test_trocar_sem_secao_poe_depois_do_resumo():
    out = d.trocar_capitulos(txt_bloco(1, caps=()), 1, ["00:00 A", "01:00 B", "02:00 C"])
    b1 = d.ler_descricoes(out)[1]["descricao"]
    assert b1.index("Resumo 1.") < b1.index("Capítulos:") < b1.index("Principais momentos:")
    assert len(cap.no_video(b1)) == 3


def test_trocar_por_vazio_tira_secao():
    out = d.trocar_capitulos(dois_blocos(), 1, [])
    b1 = d.ler_descricoes(out)[1]["descricao"]
    assert "Capítulos:" not in b1 and d.momentos(b1) == ["Fala A", "Fala B"]


def test_trocar_e_idempotente():
    novas = ["00:00 A", "01:00 B", "02:00 C"]
    um = d.trocar_capitulos(dois_blocos(), 1, novas)
    assert d.trocar_capitulos(um, 1, novas) == um


# ── 08 ponta a ponta ───────────────────────────────────────────────────────

BLOCO_08 = {"id": 1, "tema": "tema", "titulo_sugerido": "Título", "resumo": "Resumo.",
            "ganchos": ["gancho um"], "tags": ["Renan Santos"],
            "timestamp_inicio": ts(INI), "timestamp_fim": ts(FIM)}


@pytest.fixture
def proj08(tmp_path, monkeypatch):
    pasta = pasta_bloco(tmp_path)
    (tmp_path / "inputs").mkdir()
    (pasta / "words.json").write_text(json.dumps({"words": PAL}), encoding="utf-8")
    monkeypatch.setattr(_paths, "OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(desc08, "ROOT", tmp_path)

    def rodar(b):
        (pasta / "blocos.json").write_text(json.dumps({"blocos": [b]}), encoding="utf-8")
        assert desc08.main(["fake"]) == 0
        return (pasta / "descricoes.txt").read_text(encoding="utf-8")
    return pasta, rodar


def test_08_com_capitulos_depois_do_resumo(proj08):
    _, rodar = proj08
    caps = [{"titulo": "Abertura", "timestamp_inicio": ts(INI)},
            {"titulo": "Meio", "timestamp_inicio": ts(INI + 200)},
            {"titulo": "Fim", "timestamp_inicio": ts(INI + 500)}]
    texto = rodar({**BLOCO_08, "capitulos": caps})
    b = d.ler_descricoes(texto)[1]["descricao"]
    assert b.index("Resumo.") < b.index("Capítulos:") < b.index("Principais momentos:")
    assert cap.no_video(b)[0] == (0.0, "Abertura")
    assert cap.no_video(b)[1][0] == pytest.approx(206.0, abs=1.0)   # +3s intro +3s card
    assert d.momentos(b) == ["gancho um"]


def test_08_sem_campo_capitulos_identico_ao_anterior(proj08):
    _, rodar = proj08
    com_vazio = rodar({**BLOCO_08, "capitulos": []})
    sem_campo = rodar(dict(BLOCO_08))
    assert sem_campo == com_vazio
    assert "Capítulos" not in sem_campo
    assert desc08.bloco_para_texto(BLOCO_08, "") in sem_campo


def test_08_corte_curto_ou_poucos_capitulos_nao_gera_secao(proj08, capsys):
    _, rodar = proj08
    caps = [{"titulo": "A", "timestamp_inicio": ts(INI)}, {"titulo": "B", "timestamp_inicio": ts(INI + 100)}]
    assert "Capítulos:" not in rodar({**BLOCO_08, "capitulos": caps})
    assert "sem capítulos" in capsys.readouterr().out


def test_08_sem_words_json_nao_quebra(proj08):
    pasta, rodar = proj08
    (pasta / "words.json").unlink()
    caps = [{"titulo": t, "timestamp_inicio": ts(INI + s)} for t, s in (("A", 0), ("B", 200), ("C", 400))]
    assert "Capítulos:" in rodar({**BLOCO_08, "capitulos": caps})


def test_08_grafia_oficial_no_titulo_do_capitulo(proj08, monkeypatch):
    _, rodar = proj08
    monkeypatch.setattr(desc08, "corrigir_grafia", lambda t, g=None: t.replace("kim", "KIM"))
    caps = [{"titulo": t, "timestamp_inicio": ts(INI + s)} for t, s in (("kim fala", 0), ("B", 200), ("C", 400))]
    assert "00:00 KIM fala" in rodar({**BLOCO_08, "capitulos": caps})


# ── 03: pós-processamento com capitulos (subprocess, como test_segmentar_posproc) ──

def _rodar_03(pasta, blocos):
    (pasta / "segmentacao_bruta.json").write_text(json.dumps({"blocos": blocos}), encoding="utf-8")
    env = {**os.environ, "MISSAO_DB": str(pasta.parent / "t.db"), "ANTHROPIC_API_KEY": "x",
           "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "03_segmentar.py"), str(pasta),
                        "--reaproveitar"], cwd=ROOT, env=env, capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    f = pasta / "blocos.json"
    return r, (json.loads(f.read_text(encoding="utf-8")) if f.exists() else None)


def _bloco_03(caps, **extra):
    i, f = round(600 / PERIODO), round(1200 / PERIODO)
    b = {"id": 1, "tema": "tema", "titulo_sugerido": "t", "score_potencial": 5,
         "timestamp_inicio": ts(600), "timestamp_fim": ts(1200), "duracao_minutos": 10,
         "frase_de_abertura": frase(i), "frase_de_encerramento": frase(f - 1)}
    if caps is not None:
        b["capitulos"] = caps
    b.update(extra)
    return b


@pytest.fixture
def pasta03(tmp_path):
    p = tmp_path / "outputs" / "2026-10-26_fake"
    p.mkdir(parents=True)
    n = int(3600 / PERIODO)
    (p / "words.json").write_text(json.dumps({"duration": 3600.0, "words": palavras(n)}), encoding="utf-8")
    return p


def test_03_ancora_capitulos_e_forca_primeiro(pasta03):
    i0 = round(600 / PERIODO)
    caps = [cap_llm(i0 + 30, "Meio", erro_s=25), cap_llm(i0 + 10, "Segundo", erro_s=-20),
            cap_llm(i0 + 90, "Terceiro")]
    r, data = _rodar_03(pasta03, [_bloco_03(caps)])
    assert r.returncode == 0, r.stdout + r.stderr
    out = data["blocos"][0]["capitulos"]
    assert [c["titulo"] for c in out] == ["Segundo", "Meio", "Terceiro"]
    assert seg(out[0]["timestamp_inicio"]) == pytest.approx(seg(data["blocos"][0]["timestamp_inicio"]), abs=0.01)
    assert seg(out[1]["timestamp_inicio"]) == pytest.approx(t_frase(i0 + 30), abs=0.1)
    assert seg(out[2]["timestamp_inicio"]) == pytest.approx(t_frase(i0 + 90), abs=0.1)


def test_03_capitulo_fora_do_bloco_vira_aviso_nao_erro(pasta03):
    i0 = round(600 / PERIODO)
    caps = [cap_llm(i0, "A"), cap_llm(i0 + 20, "B"), cap_llm(i0 + 40, "C"), cap_llm(10, "Longe")]
    r, data = _rodar_03(pasta03, [_bloco_03(caps)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert [c["titulo"] for c in data["blocos"][0]["capitulos"]] == ["A", "B", "C"]
    assert "fora do bloco" in r.stdout


def test_03_bloco_sem_capitulos_continua_sem_campo(pasta03):
    r, data = _rodar_03(pasta03, [_bloco_03(None)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert not data["blocos"][0].get("capitulos")


def test_prompt_de_segmentacao_pede_capitulos():
    prompt = (ROOT / "prompts" / "segmentacao.md").read_text(encoding="utf-8")
    assert "capitulos" in prompt and "frase_de_abertura" in prompt


# ── 11: schema, marcas na transcrição, limpar, recalcular ──────────────────

def test_schema_do_revisor_exige_capitulos_errados():
    assert "capitulos_errados" in rv.SCHEMA["properties"]
    assert "capitulos_errados" in rv.SCHEMA["required"]


@pytest.fixture
def rev(projeto, monkeypatch):
    pasta = projeto.video("v", blocos=[1])
    (pasta / "words.json").write_text(json.dumps({"words": PAL}), encoding="utf-8")
    b = {"id": 1, "tema": "tema 1", "titulo_sugerido": "T", "texto_thumb": "X",
         "score_potencial": 8, "timestamp_inicio": ts(INI), "timestamp_fim": ts(FIM),
         "capitulos": [{"titulo": "Abertura", "timestamp_inicio": ts(INI)},
                       {"titulo": "Meio do papo", "timestamp_inicio": ts(INI + 200)},
                       {"titulo": "Final da conversa", "timestamp_inicio": ts(INI + 500)},
                       {"titulo": "Extra", "timestamp_inicio": ts(INI + 600)}]}
    (pasta / "blocos.json").write_text(json.dumps({"blocos": [b]}), encoding="utf-8")
    (pasta / "finalizados" / "video_01_slug.mp4").touch()
    (pasta / "cortes" / "corte_01_slug.mp4").touch()
    monkeypatch.setattr(_paths, "OUTPUTS", projeto.outputs)
    return pasta, b


def _escreve_txt(pasta, caps):
    (pasta / "descricoes.txt").write_text(txt_bloco(1, caps=caps), encoding="utf-8")


CAPS_TXT = ("00:00 Abertura", "03:26 Meio do papo", "08:26 Final da conversa", "10:06 Extra")
TITULOS = ["Abertura", "Meio do papo", "Final da conversa", "Extra"]


def _desc_de(pasta):
    return d.ler_descricoes((pasta / "descricoes.txt").read_text(encoding="utf-8"))[1]["descricao"]


def test_transcricao_com_marcas_nos_lugares_certos(rev):
    pasta, b = rev
    _escreve_txt(pasta, CAPS_TXT)
    texto, titulos = rv.transcricao_com_capitulos(pasta, b, PAL, _desc_de(pasta), [])
    assert titulos == TITULOS
    assert texto.index("[CAPÍTULO 00:00: Abertura]") < texto.index("[CAPÍTULO 03:26: Meio do papo]")
    pos = texto.index("[CAPÍTULO 03:26: Meio do papo]")
    proxima = texto[pos:].split("]", 1)[1].split()[0]
    i = int(proxima[1:].split("k")[0])
    assert abs(t_frase(i) - (INI + 200)) <= PERIODO


def test_transcricao_sem_capitulos_e_pura(rev):
    pasta, b = rev
    texto, titulos = rv.transcricao_com_capitulos(pasta, b, PAL, "Resumo.\n\nPrincipais momentos:\n• a", [])
    assert titulos == [] and "[CAPÍTULO" not in texto and texto.startswith("t")


def test_transcricao_respeita_trechos_removidos(rev):
    pasta, b = rev
    _escreve_txt(pasta, CAPS_TXT)
    ini = seg(b["timestamp_inicio"])
    texto, _ = rv.transcricao_com_capitulos(pasta, b, PAL, _desc_de(pasta), [(ini + 100, ini + 110)])
    j = round((ini + 105) / PERIODO)
    assert f"t{j}k3" not in texto.split()


def test_limpar_capitulo_errado_tira_do_txt_e_do_json(rev):
    pasta, _ = rev
    _escreve_txt(pasta, CAPS_TXT)
    assert rv.limpar_capitulos(pasta, 1, ["meio do papo"], TITULOS) == ["Meio do papo"]
    txt = _desc_de(pasta)
    assert [t for _, t in cap.no_video(txt)] == ["Abertura", "Final da conversa", "Extra"]
    assert d.momentos(txt) == ["Fala A", "Fala B"]
    caps = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"][0]["capitulos"]
    assert [c["titulo"] for c in caps] == ["Abertura", "Final da conversa", "Extra"]


def test_limpar_primeiro_zera_secao_e_capitulos_do_bloco(rev):
    pasta, _ = rev
    _escreve_txt(pasta, CAPS_TXT)
    rv.limpar_capitulos(pasta, 1, ["Abertura"], TITULOS)
    txt = (pasta / "descricoes.txt").read_text(encoding="utf-8")
    assert "Capítulos:" not in txt and "Principais momentos:" in txt
    assert json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"][0]["capitulos"] == []


def test_limpar_deixando_menos_de_3_tira_secao(rev):
    pasta, _ = rev
    _escreve_txt(pasta, CAPS_TXT)
    rv.limpar_capitulos(pasta, 1, ["Meio do papo", "Extra"], TITULOS)
    assert "Capítulos:" not in (pasta / "descricoes.txt").read_text(encoding="utf-8")


def test_limpar_titulo_inventado_nao_mexe(rev):
    pasta, _ = rev
    _escreve_txt(pasta, CAPS_TXT)
    antes = (pasta / "descricoes.txt").read_text(encoding="utf-8")
    assert rv.limpar_capitulos(pasta, 1, ["coisa que o modelo inventou"], TITULOS) == []
    assert (pasta / "descricoes.txt").read_text(encoding="utf-8") == antes
    assert rv.limpar_capitulos(pasta, 1, [], TITULOS) == []


def test_recalcular_refaz_secao_com_tempos_novos(rev):
    pasta, _ = rev
    _escreve_txt(pasta, ("00:00 Velho", "01:00 Velho 2", "02:00 Velho 3"))
    rv.recalcular_capitulos(pasta, 1)
    txt = _desc_de(pasta)
    assert cap.no_video(txt)[0] == (0.0, "Abertura")
    assert cap.no_video(txt)[1][0] == pytest.approx(206.0, abs=1.0)
    assert "Velho" not in txt and d.momentos(txt) == ["Fala A", "Fala B"]


def test_recalcular_bloco_sem_capitulos_nao_mexe(projeto):
    pasta = projeto.video("w", blocos=[1])
    _escreve_txt(pasta, CAPS_TXT)
    antes = (pasta / "descricoes.txt").read_text(encoding="utf-8")
    rv.recalcular_capitulos(pasta, 1)
    assert (pasta / "descricoes.txt").read_text(encoding="utf-8") == antes


def test_recalcular_sem_txt_nao_quebra(rev):
    rv.recalcular_capitulos(rev[0], 1)


def test_refazer_bloco_recalcula_so_se_deu_certo(rev, monkeypatch):
    pasta, _ = rev
    chamados = []
    monkeypatch.setattr(rv, "recalcular_capitulos", lambda p, bid: chamados.append(bid))
    monkeypatch.setattr(rv, "flags_refazer", lambda p, nn: [])
    monkeypatch.setattr(rv.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0))
    assert rv.refazer_bloco(pasta, 1) is True and chamados == [1]
    monkeypatch.setattr(rv.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1))
    assert rv.refazer_bloco(pasta, 1) is False and chamados == [1]


# main() ponta a ponta: o revisor aponta capítulo errado e ele sai

class _Cli:
    def __init__(self, checagens):
        self.chamadas = []
        outer = self

        class _M:
            def create(self, **kw):
                outer.chamadas.append(kw)
                return types.SimpleNamespace(
                    stop_reason="end_turn", model="claude-opus-5-5",
                    content=[types.SimpleNamespace(type="text", text=json.dumps(checagens))],
                    usage=types.SimpleNamespace(input_tokens=5000, output_tokens=1000))
        self.beta = types.SimpleNamespace(messages=_M())


OK = {"titulo_fiel": True, "titulo_problema": "", "thumb_ok": True, "thumb_problema": "",
      "tela_compartilhada": False, "tela_problema": "", "corte_sem_sentido": False,
      "sentido_problema": "", "momentos_fora": [], "capitulos_errados": []}


def _prepara_main(rev, monkeypatch, checagens):
    pasta, _ = rev
    _escreve_txt(pasta, CAPS_TXT)
    (pasta / "thumbs" / "thumb_01_a.png").touch()
    cli = _Cli(checagens)
    monkeypatch.setitem(sys.modules, "anthropic",
                        types.SimpleNamespace(Anthropic=lambda: cli, APIError=RuntimeError))
    monkeypatch.setattr(rv, "frames_b64", lambda v: ["f"] * 6)
    monkeypatch.setattr(rv, "ler_imagem_b64", lambda p: "thumb")
    monkeypatch.setattr(rv, "proximo_frame", lambda pasta, bid: False)
    monkeypatch.setattr(rv._fronteira, "termos_propaganda", lambda: ([], 0))
    return pasta, cli


def test_main_manda_marcas_e_remove_capitulo_errado(rev, monkeypatch):
    pasta, cli = _prepara_main(rev, monkeypatch, {**OK, "capitulos_errados": ["Meio do papo"]})
    assert rv.main([str(pasta), "--bloco=1"]) == 0
    prompt = cli.chamadas[0]["messages"][0]["content"][-1]["text"]
    assert "[CAPÍTULO 03:26: Meio do papo]" in prompt
    txt = (pasta / "descricoes.txt").read_text(encoding="utf-8")
    assert "Meio do papo" not in txt and "00:00 Abertura" in txt and "Principais momentos:" in txt
    caps = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"][0]["capitulos"]
    assert "Meio do papo" not in [c["titulo"] for c in caps]
    rev_json = json.loads((pasta / "revisao.json").read_text(encoding="utf-8"))
    assert rev_json["01"]["capitulos_removidos"] == ["Meio do papo"]


def test_main_sem_capitulo_errado_nao_mexe(rev, monkeypatch):
    pasta, cli = _prepara_main(rev, monkeypatch, OK)
    antes = (pasta / "descricoes.txt").read_text(encoding="utf-8")
    assert rv.main([str(pasta), "--bloco=1"]) == 0
    assert (pasta / "descricoes.txt").read_text(encoding="utf-8") == antes
    assert json.loads((pasta / "revisao.json").read_text(encoding="utf-8"))["01"]["capitulos_removidos"] == []
