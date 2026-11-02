"""Abertura sem propaganda (_fronteira), momentos da descricao, revisor (abertura e momentos
fora), grade de horarios da publicacao. Tudo mockado, sem API."""
import importlib.util
import json
import sys
import types
from datetime import date, datetime
from pathlib import Path

import pytest

import _fronteira as fr
import _descricoes as d
import _paths
import _publicacao as pub

_spec = importlib.util.spec_from_file_location(
    "revisor_ab", Path(__file__).parent.parent / "scripts" / "11_revisor.py")
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)


def seq(texto, t0=100.0, passo=0.5):
    """Palavras de `texto` a cada `passo` s a partir de t0."""
    return [{"word": w, "start": t0 + i * passo, "end": t0 + i * passo + 0.4}
            for i, w in enumerate(texto.split())]


def cheio(n, prefixo="x"):
    """n palavras de enchimento, com ponto final a cada 6."""
    return " ".join(f"{prefixo}{i}" + ("." if i % 6 == 5 else "") for i in range(n))


TERMOS = [["valet"], ["like", "na", "live"]]
CONT = [["festival"], ["revista"]]


# ── _fronteira ─────────────────────────────────────────────────────────────

def test_termos_propaganda_le_o_config_normalizado():
    termos, cont = fr.termos_propaganda()
    assert ["valet"] in termos and ["like", "na", "live"] in termos
    assert ["festival"] in cont and ["festival"] not in termos


def test_termos_propaganda_config_ausente(monkeypatch, tmp_path):
    monkeypatch.setattr(fr, "PROPAGANDA_JSON", tmp_path / "nao_existe.json")
    assert fr.termos_propaganda() == ([], [])


def test_caso_real_valetplus_pula_ate_depois_do_festival():
    txt = ("Então, entre no valetplus, valet .org .br. E nós teremos já já o nosso festival, "
           "que vai ser incrível. Vamos que vamos. E eu volto a repetir. Quem fez voto útil "
           + cheio(40))
    p = seq(txt)
    termos, cont = fr.termos_propaganda()
    r = fr.pular_propaganda(p, 100.0, termos, cont)
    assert r is not None
    novo, pulado = r
    palavra = next(w for w in p if w["start"] == novo)["word"]
    assert palavra in ("Vamos", "E", "Quem")
    assert novo > p[txt.split().index("festival,")]["start"]
    assert "valetplus" in pulado and "Quem" not in pulado


def test_sem_propaganda_none():
    assert fr.pular_propaganda(seq("Boa noite a todos. " + cheio(30)), 100.0, TERMOS, CONT) is None


def test_termo_depois_dos_30s_nao_abre():
    p = seq(cheio(70) + " valet agora. Segue. " + cheio(30, "y"))
    assert fr.pular_propaganda(p, 100.0, TERMOS, CONT) is None


def test_continua_sozinho_nao_abre():
    p = seq("Gente o festival e a revista foram otimos. " + cheio(30))
    assert fr.pular_propaganda(p, 100.0, TERMOS, CONT) is None


def test_propaganda_longa_demais_devolve_none():
    partes = ["valet " + cheio(39, f"z{i}_") for i in range(14)]   # termo a cada ~20s
    assert fr.pular_propaganda(seq(" ".join(partes)), 100.0, TERMOS, CONT) is None


def test_termos_vazios_ou_sem_palavras():
    assert fr.pular_propaganda([], 0.0, TERMOS) is None
    assert fr.pular_propaganda(seq("valet. a b c"), 100.0, []) is None


def test_termo_de_varias_palavras_normaliza_acento_e_pontuacao():
    p = seq("Deixa o LIKE, na live! Obrigado. Agora sim. " + cheio(30))
    novo, pulado = fr.pular_propaganda(p, 100.0, TERMOS, CONT)
    assert "LIKE," in pulado
    assert next(w for w in p if w["start"] == novo)["word"] in ("Obrigado.", "Agora")
    assert fr.pular_propaganda(seq("Deixa o like na casa. " + cheio(30)), 100.0, TERMOS) is None


def test_emenda_ate_40s_e_nao_alem():
    perto = "valet aqui. " + cheio(48, "a") + " revista boa. " + cheio(30, "b")
    _, pulado = fr.pular_propaganda(seq(perto), 100.0, TERMOS, CONT)
    assert "revista" in pulado
    longe = "valet aqui. " + cheio(100, "c") + " revista boa. " + cheio(30, "e")
    _, pulado2 = fr.pular_propaganda(seq(longe), 100.0, TERMOS, CONT)
    assert "revista" not in pulado2


# ── _descricoes: momentos / remover_momentos ──────────────────────────────

def _bloco_txt(bid, ganchos):
    linhas = ["=" * 70, f"VÍDEO {bid:02d} — tema", "=" * 70, "", "TÍTULO (3 chars):", "Abc", "",
              "-" * 70, "DESCRIÇÃO:", "-" * 70, "", f"Resumo {bid}.", ""]
    if ganchos:
        linhas.append("Principais momentos:")
        linhas += [f"• {g}" for g in ganchos]
        linhas.append("")
    linhas += ["─" * 40, "🎬 Inscreva-se no canal: https://x", "📺 Conteúdo original: https://y",
               "", "#MissaoEmCortes #Missao14", "-" * 70, "TAGS (x):", "-" * 70, "a, b", ""]
    return "\n".join(linhas)


def test_momentos_lista_itens():
    desc = d.ler_descricoes(_bloco_txt(1, ["Primeiro", "Segundo: x"]))[1]["descricao"]
    assert d.momentos(desc) == ["Primeiro", "Segundo: x"]
    assert d.momentos("sem lista") == []


def test_remover_momentos_so_no_bloco_certo():
    txt = _bloco_txt(1, ["A", "B"]) + _bloco_txt(2, ["A", "C"])
    ds = d.ler_descricoes(d.remover_momentos(txt, 2, ["A"]))
    assert d.momentos(ds[1]["descricao"]) == ["A", "B"]
    assert d.momentos(ds[2]["descricao"]) == ["C"]
    assert "Principais momentos:" in ds[2]["descricao"]


def test_remover_todos_tira_cabecalho_e_preserva_resto():
    txt = _bloco_txt(1, ["A", "B"]) + _bloco_txt(2, ["A"])
    ds = d.ler_descricoes(d.remover_momentos(txt, 1, ["A", "B"]))
    desc = ds[1]["descricao"]
    assert "Principais momentos:" not in desc and "Resumo 1." in desc
    assert "Inscreva-se no canal" in desc and "Conteúdo original" in desc
    assert "#MissaoEmCortes" in desc and "\n\n\n" not in desc
    assert d.momentos(ds[2]["descricao"]) == ["A"]
    assert ds[1]["titulo"] == "Abc"


def test_remover_item_inexistente_ou_bloco_inexistente_nao_muda():
    txt = _bloco_txt(1, ["A"])
    assert d.remover_momentos(txt, 1, ["Z"]) == txt
    assert d.remover_momentos(txt, 9, ["A"]) == txt


# ── revisor: conferir_abertura ─────────────────────────────────────────────

PROP = "valet agora. " + cheio(12, "p") + " "


@pytest.fixture
def cenario(projeto, monkeypatch):
    pasta = projeto.video("v", blocos=[1])
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))
    b = blocos["blocos"][0]
    b["timestamp_inicio"], b["timestamp_fim"] = "00:01:40", "00:11:40"
    b["ganchos"] = ["Fala Dentro", "Fala Fora"]
    (pasta / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    monkeypatch.setattr(_paths, "OUTPUTS", projeto.outputs)
    refeitos = []
    monkeypatch.setattr(rv, "refazer_bloco", lambda p, bid: refeitos.append(bid) or True)
    monkeypatch.setattr(rv._fronteira, "termos_propaganda", lambda: (TERMOS, CONT))
    return pasta, b, refeitos, projeto.banco


def _com_prop():
    return seq(PROP + cheio(1300, "q"))


def _sem_prop():
    return seq("Boa noite a todos. " + cheio(1300, "q"))


def _blocos_json(pasta):
    return json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))["blocos"][0]


def test_abertura_sem_propaganda(cenario):
    pasta, b, refeitos, _ = cenario
    assert rv.conferir_abertura("v", pasta, b, _sem_prop()) == (None, None)
    assert refeitos == [] and _blocos_json(pasta)["timestamp_inicio"] == "00:01:40"


def test_abertura_com_propaganda_grava_e_refaz(cenario):
    pasta, b, refeitos, _ = cenario
    reg, motivo = rv.conferir_abertura("v", pasta, b, _com_prop())
    assert motivo is None and refeitos == [1]
    assert reg["pulado_s"] > 0 and "valet" in reg["trecho"]
    salvo = _blocos_json(pasta)
    assert salvo["timestamp_inicio"] != "00:01:40"
    assert salvo["timestamp_inicio"] == b["timestamp_inicio"]
    assert salvo["timestamp_fim"].startswith("00:11:40") and salvo["duracao_minutos"] <= 10.0


def test_abertura_sobra_menos_de_5min_quarentena_sem_gravar(cenario):
    pasta, b, refeitos, _ = cenario
    b["timestamp_fim"] = "00:06:00"
    reg, motivo = rv.conferir_abertura("v", pasta, b, _com_prop())
    assert motivo and "revisar à mão" in motivo
    assert refeitos == [] and _blocos_json(pasta)["timestamp_inicio"] == "00:01:40"


def test_abertura_refazer_falhou_quarentena(cenario, monkeypatch):
    pasta, b, _, _ = cenario
    monkeypatch.setattr(rv, "refazer_bloco", lambda p, bid: False)
    _, motivo = rv.conferir_abertura("v", pasta, b, _com_prop())
    assert motivo and "falhou ao refazer" in motivo


def test_abertura_dry_run_so_mostra(cenario, capsys):
    pasta, b, refeitos, _ = cenario
    reg, motivo = rv.conferir_abertura("v", pasta, b, _com_prop(), reajustar=False)
    assert reg and motivo and "propaganda" in motivo
    assert refeitos == [] and _blocos_json(pasta)["timestamp_inicio"] == "00:01:40"
    assert "abre com propaganda" in capsys.readouterr().out


# ── revisor: limpar_momentos ───────────────────────────────────────────────

def _desc(pasta, ganchos):
    (pasta / "descricoes.txt").write_text(_bloco_txt(1, ganchos), encoding="utf-8")


def test_limpar_casa_com_pontuacao_e_acento_diferentes(cenario):
    pasta = cenario[0]
    momentos = ["O Brasil não aguenta mais!", "Outra fala"]
    _desc(pasta, momentos)
    assert rv.limpar_momentos(pasta, 1, ["o brasil nao aguenta mais"], momentos) == [
        "O Brasil não aguenta mais!"]
    ds = d.ler_descricoes((pasta / "descricoes.txt").read_text(encoding="utf-8"))
    assert d.momentos(ds[1]["descricao"]) == ["Outra fala"]


def test_limpar_tira_dos_ganchos_do_blocos_json_com_grafias(cenario):
    pasta = cenario[0]
    blocos = json.loads((pasta / "blocos.json").read_text(encoding="utf-8"))
    blocos["blocos"][0]["ganchos"] = ["Kim Kataguri disse x", "Fica"]
    (pasta / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    momentos = ["Kim Kataguiri disse x", "Fica"]      # a descricao ja tem a grafia oficial
    _desc(pasta, momentos)
    assert rv.limpar_momentos(pasta, 1, ["Kim Kataguiri disse x"], momentos) == [
        "Kim Kataguiri disse x"]
    assert _blocos_json(pasta)["ganchos"] == ["Fica"]


def test_limpar_ignora_item_inventado(cenario):
    pasta = cenario[0]
    momentos = ["Fala Dentro", "Fala Fora"]
    _desc(pasta, momentos)
    antes = (pasta / "descricoes.txt").read_text(encoding="utf-8")
    assert rv.limpar_momentos(pasta, 1, ["algo totalmente diferente que o LLM inventou"],
                              momentos) == []
    assert (pasta / "descricoes.txt").read_text(encoding="utf-8") == antes
    assert _blocos_json(pasta)["ganchos"] == ["Fala Dentro", "Fala Fora"]


def test_limpar_sem_descricoes_txt_ainda_limpa_ganchos(cenario):
    pasta = cenario[0]
    assert rv.limpar_momentos(pasta, 1, ["Fala Fora"], ["Fala Dentro", "Fala Fora"]) == ["Fala Fora"]
    assert _blocos_json(pasta)["ganchos"] == ["Fala Dentro"]


# ── revisor: main ──────────────────────────────────────────────────────────

class _NaoChamar:
    def __init__(self):
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._boom))

    def _boom(self, **k):
        raise AssertionError("API não deveria ser chamada")


class _Cli:
    def __init__(self, checagens):
        self.chamadas = []
        fake = self

        class _M:
            def create(self, **kw):
                fake.chamadas.append(kw)
                return types.SimpleNamespace(
                    stop_reason="end_turn", model="claude-opus-5-5",
                    content=[types.SimpleNamespace(type="text", text=json.dumps(checagens))],
                    usage=types.SimpleNamespace(input_tokens=10, output_tokens=10))
        self.beta = types.SimpleNamespace(messages=_M())


OKC = {"titulo_fiel": True, "titulo_problema": "", "thumb_ok": True, "thumb_problema": "",
       "tela_compartilhada": False, "tela_problema": "", "corte_sem_sentido": False,
       "sentido_problema": "", "momentos_fora": []}


def _main_pronto(cenario, monkeypatch, palavras, cli):
    pasta, _, refeitos, banco = cenario
    (pasta / "words.json").write_text(json.dumps({"words": palavras}), encoding="utf-8")
    (pasta / "cortes" / "corte_01_slug.mp4").touch()
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(
        Anthropic=lambda: cli, APIError=RuntimeError))
    monkeypatch.setattr(rv, "frames_b64", lambda v: ["f"])
    monkeypatch.setattr(rv, "ler_imagem_b64", lambda p: "t")
    monkeypatch.setattr(rv, "conferir_fronteira", lambda *a, **k: ({"inicio_ok": True}, None))
    return pasta, refeitos, banco


def test_main_momentos_fora_removidos_vao_pro_revisao_json(cenario, monkeypatch):
    cli = _Cli({**OKC, "momentos_fora": ["Fala Fora"]})
    pasta, _, _ = _main_pronto(cenario, monkeypatch, _sem_prop(), cli)
    _desc(pasta, ["Fala Dentro", "Fala Fora"])
    assert rv.main([str(pasta)]) == 0
    rev = json.loads((pasta / "revisao.json").read_text(encoding="utf-8"))["01"]
    assert rev["momentos_removidos"] == ["Fala Fora"] and rev["abertura"] is None
    assert "• Fala Fora" in cli.chamadas[0]["messages"][0]["content"][-1]["text"]
    ds = d.ler_descricoes((pasta / "descricoes.txt").read_text(encoding="utf-8"))
    assert d.momentos(ds[1]["descricao"]) == ["Fala Dentro"]
    assert _blocos_json(pasta)["ganchos"] == ["Fala Dentro"]


def test_main_abertura_em_quarentena_nao_chama_llm(cenario, monkeypatch):
    pasta0 = cenario[0]
    blocos = json.loads((pasta0 / "blocos.json").read_text(encoding="utf-8"))
    blocos["blocos"][0]["timestamp_fim"] = "00:06:00"
    (pasta0 / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    pasta, refeitos, banco = _main_pronto(cenario, monkeypatch, _com_prop(), _NaoChamar())
    assert rv.main([str(pasta)]) == 0
    rev = json.loads((pasta / "revisao.json").read_text(encoding="utf-8"))["01"]
    assert rev["status"] == "quarentena" and rev["abertura"]["pulado_s"] > 0
    assert rev["custo_usd"] == 0.0 and refeitos == []
    assert banco("SELECT status FROM blocos WHERE bloco_id=1")[0]["status"] == "quarentena"


# ── _publicacao: horas e grade ─────────────────────────────────────────────

def test_horas_sem_grade_e_18h():
    assert pub.horas(None, [date(2026, 10, 26)] * 2) == ["18h", "18h"]
    assert pub.horas([], [date(2026, 10, 26)]) == ["18h"]


def test_horas_com_grade_um_por_horario_e_ja_passou():
    hoje, amanha = date(2026, 10, 26), date(2026, 10, 27)
    r = pub.horas(["12h", "19h"], [hoje, hoje, amanha, amanha], datetime(2026, 10, 26, 14))
    assert r == ["JÁ (12h passou)", "19h", "12h", "19h"]


def test_horas_excedente_repete_ultimo_horario():
    d1 = date(2026, 10, 27)
    assert pub.horas(["12h", "19h"], [d1] * 3, datetime(2026, 10, 26, 9)) == ["12h", "19h", "19h"]


@pytest.fixture
def pasta_pub(tmp_path, monkeypatch, banco):
    import _cobertura
    monkeypatch.setattr(_cobertura, "CANAL_JSON", tmp_path / "canal.json")
    monkeypatch.setattr(pub, "auditoria_aprovada", lambda: False)
    monkeypatch.setattr(pub, "modo_evento", lambda hoje=None, cfg=None: None)
    monkeypatch.setattr(pub, "ultimo_agendado", lambda: None)
    pasta = tmp_path / "2026-10-26_x"
    (pasta / "finalizados").mkdir(parents=True)
    (pasta / "thumbs").mkdir()
    blocos = [{"id": i, "score_potencial": 10 - i, "duracao_minutos": 9.0,
               "titulo_sugerido": f"s{i}"} for i in (1, 2, 3)]
    (pasta / "blocos.json").write_text(json.dumps({"blocos": blocos}), encoding="utf-8")
    (pasta / "revisao.json").write_text(json.dumps(
        {f"{i:02d}": {"status": "aprovado"} for i in (1, 2, 3)}), encoding="utf-8")
    for i in (1, 2, 3):
        (pasta / "finalizados" / f"video_{i:02d}_a.mp4").touch()
    return pasta


def test_gerar_com_grade_um_video_por_horario_a_partir_de_hoje(pasta_pub):
    caminho, _ = pub.gerar(pasta_pub, datetime(2026, 10, 26, 9), grade=["12h", "19h"])
    t = caminho.read_text(encoding="utf-8")
    assert "seg 26/10 12h · VÍDEO 01" in t
    assert "seg 26/10 19h · VÍDEO 02" in t
    assert "ter 27/10 12h · VÍDEO 03" in t


def test_gerar_com_grade_horario_que_passou_vira_ja(pasta_pub):
    caminho, _ = pub.gerar(pasta_pub, datetime(2026, 10, 26, 14), grade=["12h", "19h"])
    t = caminho.read_text(encoding="utf-8")
    assert "seg 26/10 JÁ (12h passou) · VÍDEO 01" in t
    assert "seg 26/10 19h · VÍDEO 02" in t


def test_gerar_com_grade_continua_depois_do_ultimo_agendado(pasta_pub, monkeypatch):
    monkeypatch.setattr(pub, "ultimo_agendado", lambda: date(2026, 10, 28))
    caminho, _ = pub.gerar(pasta_pub, datetime(2026, 10, 26, 9), grade=["12h", "19h"])
    assert "qui 29/10 12h · VÍDEO 01" in caminho.read_text(encoding="utf-8")


def test_gerar_sem_grade_mantem_18h(pasta_pub):
    caminho, _ = pub.gerar(pasta_pub, datetime(2026, 10, 26, 9))
    t = caminho.read_text(encoding="utf-8")
    assert "seg 26/10 18h · VÍDEO 01" in t and "JÁ" not in t
