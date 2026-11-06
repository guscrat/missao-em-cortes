import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import _atualidade as at  # noqa: E402


@pytest.fixture
def pasta(tmp_path):
    p = tmp_path / "2026-10-26_renan_x"
    p.mkdir()
    blocos = {"blocos": [
        {"id": 1, "resumo": "r1", "short": {"timestamp_inicio": "00:00:01.0",
                                            "timestamp_fim": "00:00:03.0"}},
        {"id": 2, "resumo": "r2", "cold_open": {"frase": "frase do cold open"}},
    ]}
    (p / "blocos.json").write_text(json.dumps(blocos), encoding="utf-8")
    palavras = [{"word": " antes", "start": 0.5}, {"word": " Lula", "start": 1.2},
                {"word": " ganhou.", "start": 2.0}, {"word": " depois", "start": 3.5}]
    (p / "words.json").write_text(json.dumps(palavras), encoding="utf-8")
    return p


class FakeClient:
    def __init__(self, texto, stop="end_turn"):
        self.pedidos = []
        self.texto, self.stop = texto, stop
        self.messages = self

    def create(self, **kw):
        self.pedidos.append(kw)
        return SimpleNamespace(
            stop_reason=self.stop, model=at.MODELO,
            content=[SimpleNamespace(type="text", text=self.texto)],
            usage=SimpleNamespace(input_tokens=800, output_tokens=40,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0))


@pytest.fixture
def eventos(monkeypatch):
    regs = []
    monkeypatch.setattr(at, "evento", lambda *a, **k: regs.append((a, k)))
    monkeypatch.setattr(at._custo, "checar_orcamento", lambda stem, etapa: None)
    return regs


def test_data_da_live_pelo_nome_da_pasta(pasta, tmp_path):
    assert at.data_da_live(pasta) == date(2026, 10, 26)
    assert at.data_da_live(tmp_path / "sem_data") is None


def test_texto_do_short_pelo_trecho_short(pasta):
    assert at.texto_do_short(pasta, 1) == "Lula ganhou."


def test_texto_do_short_antigo_usa_cold_open(pasta):
    assert at.texto_do_short(pasta, 2) == "frase do cold open"


def test_checar_short_datado_registra_custo(pasta, eventos, monkeypatch):
    cli = FakeClient('{"datado": true, "motivo": "apuração ao vivo"}')
    monkeypatch.setattr(at, "_client", cli)
    assert at.checar_short("renan_x", pasta, 1, date(2026, 11, 7), "LULA GANHOU?") == \
        (True, "apuração ao vivo")
    pedido = cli.pedidos[0]["messages"][0]["content"]
    assert "DATA DA LIVE (aprox.): 26/10/2026" in pedido
    assert "DATA DE PUBLICAÇÃO DO SHORT: 07/11/2026" in pedido and "Lula ganhou." in pedido
    (args, kw), = eventos
    assert args[:3] == ("renan_x", "09_atualidade", "llm") and kw["agente"] == "revisor"
    assert kw["custo_usd"] > 0 and kw["mensagem"].startswith(at.MODELO)


def test_checar_short_nao_datado(pasta, eventos, monkeypatch):
    monkeypatch.setattr(at, "_client", FakeClient('{"datado": false, "motivo": ""}'))
    assert at.checar_short("renan_x", pasta, 1, date(2026, 11, 7)) == (False, "")


def test_recusa_vira_falha_e_o_short_nao_sobe(pasta, eventos, monkeypatch):
    monkeypatch.setattr(at, "_client", FakeClient("", stop="refusal"))
    with pytest.raises(RuntimeError, match="recusou"):
        at.checar_short("renan_x", pasta, 1, date(2026, 11, 7))


def test_orcamento_estourado_para_antes_da_chamada(pasta, monkeypatch):
    cli = FakeClient('{"datado": false, "motivo": ""}')
    monkeypatch.setattr(at, "_client", cli)

    def estoura(stem, etapa):
        raise at._custo.OrcamentoEstourado("teto")
    monkeypatch.setattr(at._custo, "checar_orcamento", estoura)
    with pytest.raises(at._custo.OrcamentoEstourado):
        at.checar_short("renan_x", pasta, 1, date(2026, 11, 7))
    assert cli.pedidos == []
