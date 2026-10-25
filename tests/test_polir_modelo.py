"""04b_polir: chamada ao Sonnet 5.5 (effort low, system em cache, bloco thinking).

O 04b roda no nível do módulo, então extraímos do fonte (ast) só as constantes e as
funções puras necessárias e executamos num namespace isolado. Sem API, sem ffmpeg.
"""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import _custo

FONTE = Path(__file__).parent.parent / "scripts" / "04b_polir.py"
NOMES_CONST = {"MODELO", "EFFORT", "PROMPT_SISTEMA", "PALAVRAS_FILTRO"}
NOMES_FUNC = {"palavras_para_texto", "chamar_claude"}


class FakeMessages:
    def __init__(self, content):
        self.content, self.kwargs = content, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(content=self.content, usage=SimpleNamespace())


def carregar(tmp_path, content):
    arvore = ast.parse(FONTE.read_text(encoding="utf-8"))
    corpo = []
    for no in arvore.body:
        if isinstance(no, ast.FunctionDef) and no.name in NOMES_FUNC:
            corpo.append(no)
        elif isinstance(no, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in NOMES_CONST for t in no.targets):
            corpo.append(no)
    msgs = FakeMessages(content)
    ns = {"json": json, "DEBUG_DIR": tmp_path / "debug", "stem": "x",
          "get_client": lambda: SimpleNamespace(messages=msgs)}
    exec(compile(ast.Module(body=corpo, type_ignores=[]), str(FONTE), "exec"), ns)
    return ns, msgs


PALAVRAS = [{"start": 0.0, "end": 0.5, "word": "oi"}]


def test_chamada_sonnet_effort_low_system_com_cache(tmp_path):
    texto = SimpleNamespace(type="text", text='{"intervalos_remover": [{"t_inicio": 1, "t_fim": 2, "motivo": "câmera"}]}')
    ns, msgs = carregar(tmp_path, [texto])
    intervalos, _ = ns["chamar_claude"](PALAVRAS, 10.0, 1)
    k = msgs.kwargs
    assert k["model"] == "claude-sonnet-5-5"
    assert k["output_config"] == {"effort": "low"}
    assert k["max_tokens"] == 16000
    assert k["system"] == [{"type": "text", "text": ns["PROMPT_SISTEMA"],
                            "cache_control": {"type": "ephemeral"}}]
    assert len(intervalos) == 1


def test_resposta_com_thinking_antes_do_texto(tmp_path):
    thinking = SimpleNamespace(type="thinking", thinking="hmm")   # sem .text
    texto = SimpleNamespace(type="text", text='```json\n{"intervalos_remover": []}\n```')
    ns, _ = carregar(tmp_path, [thinking, texto])
    intervalos, _ = ns["chamar_claude"](PALAVRAS, 10.0, 1)
    assert intervalos == []


def test_filtra_motivo_ignorar(tmp_path):
    texto = SimpleNamespace(type="text", text=json.dumps({"intervalos_remover": [
        {"t_inicio": 1, "t_fim": 2, "motivo": "manter"},
        {"t_inicio": 5, "t_fim": 9, "motivo": "internet caiu"}]}))
    ns, _ = carregar(tmp_path, [texto])
    intervalos, _ = ns["chamar_claude"](PALAVRAS, 10.0, 1)
    assert [i["t_inicio"] for i in intervalos] == [5]


def test_custo_tem_o_sonnet_5_5():
    assert "claude-sonnet-5-5" in _custo.PRECOS
