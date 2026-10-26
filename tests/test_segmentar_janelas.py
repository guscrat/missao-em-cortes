"""03_segmentar: live longa em janelas de 60 min + âncora das frases pelo texto.

O 03 roda no nível do módulo: extraímos do fonte (ast) só constantes e funções e
executamos num namespace isolado, com um Anthropic falso. Sem API.
"""
import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import _custo
import _fronteira as fr

FONTE = Path(__file__).parent.parent / "scripts" / "03_segmentar.py"
NOMES_CONST = {"MODELO", "JANELA_MIN", "FOLGA_JANELA_MIN", "AVANCO_VAZIO_MIN",
               "RABO_JANELA_MIN"}
NOMES_FUNC = {"linhas_com_tempo", "janelas", "pedir_blocos", "chamar_llm", "extrair_json",
              "ts_s", "inicio_s"}


def _ts(s):
    return fr.segundos_para_ts(s)[:8]


def transcricao(minutos):
    return "\n".join(f"[{_ts(m * 60)}] Speaker: fala do minuto {m}." for m in range(minutos))


class FakeMessages:
    def __init__(self, respostas):
        self.respostas, self.pedidos = list(respostas), []

    def create(self, **kwargs):
        self.pedidos.append(kwargs)
        texto = json.dumps(self.respostas.pop(0))
        return SimpleNamespace(content=[SimpleNamespace(text=texto)],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=100))


def carregar(tmp_path, monkeypatch, minutos, respostas, palavras=None):
    arvore = ast.parse(FONTE.read_text(encoding="utf-8"))
    corpo = [no for no in arvore.body
             if (isinstance(no, ast.FunctionDef) and no.name in NOMES_FUNC)
             or (isinstance(no, ast.Assign) and any(
                 isinstance(t, ast.Name) and t.id in NOMES_CONST for t in no.targets))]
    (tmp_path / "transcricao.txt").write_text(transcricao(minutos), encoding="utf-8")
    if palavras is not None:
        (tmp_path / "words.json").write_text(json.dumps({"words": palavras}), encoding="utf-8")
    msgs = FakeMessages(respostas)
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(
        Anthropic=lambda: SimpleNamespace(messages=msgs)))
    eventos = []
    ns = {"json": json, "fr": fr, "_custo": _custo, "PASTA": tmp_path, "stem": "x",
          "INPUT": tmp_path / "transcricao.txt", "BRUTA": tmp_path / "segmentacao_bruta.json",
          "PROMPT": tmp_path / "prompt.md",
          "evento": lambda *a, **k: eventos.append((a, k))}
    (tmp_path / "prompt.md").write_text("PROMPT", encoding="utf-8")
    exec(compile(ast.Module(body=corpo, type_ignores=[]), str(FONTE), "exec"), ns)
    return ns, msgs, eventos


def bloco(ini_min, fim_min, **extra):
    return {"timestamp_inicio": _ts(ini_min * 60), "timestamp_fim": _ts(fim_min * 60),
            "tema": "t", "titulo_sugerido": "t", "score_potencial": 5, **extra}


def test_live_curta_uma_chamada_sem_contexto_de_trecho(tmp_path, monkeypatch):
    ns, msgs, eventos = carregar(tmp_path, monkeypatch, 65, [{"blocos": [bloco(1, 20)]}])
    data = ns["chamar_llm"]()
    assert len(msgs.pedidos) == 1
    assert "TRECHO DA LIVE" not in msgs.pedidos[0]["messages"][0]["content"]
    assert [b["id"] for b in data["blocos"]] == [1]
    assert json.loads((tmp_path / "segmentacao_bruta.json").read_text(encoding="utf-8")) == data
    assert len(eventos) == 1 and eventos[0][1]["custo_usd"] > 0


def test_live_longa_janelas_em_sequencia_a_partir_do_fim_do_ultimo_bloco(tmp_path, monkeypatch):
    # 150 min: janela 1 = 0-60 (blocos até 50) → janela 2 começa em 50 → 50-110 (até 105)
    # → janela 3 começa em 105 e é a última (sobram 44 min ≤ 70)
    respostas = [{"blocos": [bloco(2, 20), bloco(20, 50)], "observacoes": "a"},
                 {"blocos": [bloco(50, 80), bloco(80, 105)]},
                 {"blocos": [bloco(105, 140)], "observacoes": "c"}]
    ns, msgs, _ = carregar(tmp_path, monkeypatch, 150, respostas)
    data = ns["chamar_llm"]()
    assert len(msgs.pedidos) == 3
    conteudos = [p["messages"][0]["content"] for p in msgs.pedidos]
    assert "de 00:00:00 a 01:00:00" in conteudos[0] and "TERMINAM dentro" in conteudos[0]
    assert "de 00:50:00 a 01:50:00" in conteudos[1]
    assert "ÚLTIMO trecho" in conteudos[2] and "fala do minuto 104." not in conteudos[2]
    assert "fala do minuto 149." in conteudos[2]
    assert [b["id"] for b in data["blocos"]] == [1, 2, 3, 4, 5]
    assert "[trecho 1] a" in data["observacoes"] and "[trecho 3] c" in data["observacoes"]
    # prompt de sistema em cache (as janelas saem em sequência)
    assert msgs.pedidos[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_janela_sem_bloco_anda_45_min(tmp_path, monkeypatch):
    ns, msgs, _ = carregar(tmp_path, monkeypatch, 150,
                           [{"blocos": []}, {"blocos": [bloco(46, 70)]}, {"blocos": []},
                            {"blocos": []}])
    ns["chamar_llm"]()
    assert "de 00:45:00 a 01:45:00" in msgs.pedidos[1]["messages"][0]["content"]
    assert "de 01:10:00" in msgs.pedidos[2]["messages"][0]["content"]
    assert "de 01:55:00" in msgs.pedidos[3]["messages"][0]["content"]
    assert len(msgs.pedidos) == 4


def test_cursor_usa_o_fim_real_ancorado_pelo_texto(tmp_path, monkeypatch):
    # o LLM diz que o bloco acaba em 40 min, mas a frase de encerramento está em 49 min
    palavras = [{"word": w, "start": 49 * 60 + i, "end": 49 * 60 + i + 0.5}
                for i, w in enumerate("e vocês falharam miseravelmente nessa eleição.".split())]
    respostas = [{"blocos": [bloco(5, 40, frase_de_encerramento="vocês falharam miseravelmente "
                                                               "nessa eleição.")]},
                 {"blocos": []}, {"blocos": []}, {"blocos": []}]
    ns, msgs, _ = carregar(tmp_path, monkeypatch, 150, respostas, palavras)
    ns["chamar_llm"]()
    assert "de 00:49:05 a 01:49:05" in msgs.pedidos[1]["messages"][0]["content"]


def test_bloco_que_comeca_antes_da_janela_e_descartado(tmp_path, monkeypatch):
    respostas = [{"blocos": [bloco(2, 30)]}, {"blocos": [bloco(10, 25), bloco(31, 60)]},
                 {"blocos": []}, {"blocos": []}]
    ns, _, _ = carregar(tmp_path, monkeypatch, 150, respostas)
    data = ns["chamar_llm"]()
    assert [b["timestamp_inicio"] for b in data["blocos"]] == ["00:02:00", "00:31:00"]


def test_janela_do_meio_falha_registra_custo_e_guarda_parcial(tmp_path, monkeypatch):
    # só 1 resposta: a 2ª chamada estoura (IndexError = falha da API no meio)
    ns, _, eventos = carregar(tmp_path, monkeypatch, 150, [{"blocos": [bloco(2, 40)]}])
    try:
        ns["chamar_llm"]()
        assert False, "devia propagar a falha"
    except IndexError:
        pass
    assert len(eventos) == 1 and "INCOMPLETO" in eventos[0][1]["mensagem"]
    assert eventos[0][1]["custo_usd"] > 0
    parcial = json.loads((tmp_path / "segmentacao_bruta_parcial.json").read_text(encoding="utf-8"))
    assert len(parcial["blocos"]) == 1
    assert not (tmp_path / "segmentacao_bruta.json").exists()


def test_bloco_colado_no_fim_da_janela_vai_pra_proxima(tmp_path, monkeypatch):
    # janela 1 = 0-60: o bloco 40-59 termina a 1 min do fim (assunto provavelmente cortado):
    # sai, e a janela 2 começa no fim do bloco anterior (40), não em 59
    respostas = [{"blocos": [bloco(5, 40), bloco(40, 59)]}, {"blocos": [bloco(40, 75)]},
                 {"blocos": []}, {"blocos": []}]
    ns, msgs, _ = carregar(tmp_path, monkeypatch, 150, respostas)
    data = ns["chamar_llm"]()
    assert "de 00:40:00 a 01:40:00" in msgs.pedidos[1]["messages"][0]["content"]
    assert [(b["timestamp_inicio"], b["timestamp_fim"]) for b in data["blocos"]][:2] == [
        ("00:05:00", "00:40:00"), ("00:40:00", "01:15:00")]


# ── âncora pelo texto (_fronteira.ancorar) ──────────────────────────────────

def _frase(texto, t0, passo=0.4):
    return [{"word": w, "start": t0 + i * passo, "end": t0 + i * passo + 0.3}
            for i, w in enumerate(texto.split())]


def test_ancorar_acha_a_frase_longe_do_tempo_do_llm():
    pal = (_frase("um dois três quatro cinco", 100)
           + _frase("Nós fomos muito prejudicados nessa eleição, gente.", 600))
    assert fr.ancorar(pal, "Nós fomos muito prejudicados nessa eleição.", 300, "inicio") == 600
    fim = fr.ancorar(pal, "Nós fomos muito prejudicados nessa eleição, gente.", 300, "fim")
    assert fim == pal[-1]["end"]


def test_ancorar_ignora_acento_pontuacao_e_caixa():
    pal = _frase("o FLÁVIO não reconhece, o resultado!", 50)
    assert fr.ancorar(pal, "o flavio nao reconhece o resultado", 40, "inicio") == 50


def test_ancorar_frase_repetida_fica_com_a_mais_perta():
    pal = _frase("não comprem esse papo da fraude", 100) + _frase("não comprem esse papo da fraude", 500)
    assert fr.ancorar(pal, "não comprem esse papo da fraude", 480, "inicio") == 500
    assert fr.ancorar(pal, "não comprem esse papo da fraude", 120, "inicio") == 100


def test_ancorar_sem_achado_ou_frase_curta_devolve_none():
    pal = _frase("uma frase qualquer sem nada a ver", 10)
    assert fr.ancorar(pal, "Pablo Marçal camisa dez do Lula", 10, "inicio") is None
    assert fr.ancorar(pal, "uma frase", 10, "inicio") is None
    assert fr.ancorar([], "uma frase qualquer", 10, "fim") is None


def test_ancorar_respeita_a_janela():
    pal = _frase("nós fomos muito prejudicados nessa eleição", 2000)
    assert fr.ancorar(pal, "nós fomos muito prejudicados nessa eleição", 100, "inicio",
                      janela_s=600) is None
