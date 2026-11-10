"""Ritmo dos Shorts: correções da revisão (só adianta, login sem terminal, 403 de permissão)."""
import importlib
from datetime import date, datetime

import pytest

import _google

up = importlib.import_module("09_upload")
from zoneinfo import ZoneInfo  # noqa: E402

SP = ZoneInfo("America/Sao_Paulo")
CFG = {**up.DEFAULTS, "shorts_grades": {"3": ["12:00", "16:00", "20:00"]}}


class _Resp:
    def __init__(self, status):
        self.status, self.reason = status, "x"


def _movel(dia, hora, bid, minimo=None, data_live=26):
    return {"stem": "velho", "bid": bid, "nn": f"{bid:02d}", "data_live": date(2026, 10, data_live),
            "score": 0, "minimo": minimo, "atual": datetime(2026, 11, dia, hora, 0, tzinfo=SP),
            "youtube_id": f"S{bid}"}


def test_movel_nunca_vai_pra_depois_fica_parado_no_horario_dele():
    """Ritmo 2/dia e um novo de prioridade pegando 11/11 12h: o velho que está em 11/11 12h
    iria pra depois. Fica parado lá e o novo pega o próximo horário livre."""
    agora_ = datetime(2026, 11, 11, 8, 0, tzinfo=SP)
    velhos = [_movel(11, 12, 1)]
    novo = [{"stem": "novo", "bid": 1, "data_live": date(2026, 11, 10), "score": 0, "minimo": None}]
    s_novos, s_moveis, _ = up.planejar_ritmo(novo, velhos, set(), up.DEFAULTS, None, agora_)
    assert s_moveis == [velhos[0]["atual"]]
    assert s_novos[0] != velhos[0]["atual"]


def test_plano_com_atrasados_e_estavel_e_sem_horario_repetido():
    agora_ = datetime(2026, 11, 11, 8, 0, tzinfo=SP)
    velhos = [_movel(11, 12, 1), _movel(11, 20, 2), _movel(12, 12, 3)]
    novos = [{"stem": "novo", "bid": b, "data_live": date(2026, 11, 10), "score": 0,
              "minimo": datetime(2026, 11, 11, 18, 0, tzinfo=SP)} for b in (1, 2)]
    fim = datetime(2026, 11, 12, 18, 0, tzinfo=SP)
    s_novos, s_moveis, _ = up.planejar_ritmo(novos, velhos, set(), CFG, fim, agora_)
    assert all(s <= m["atual"] for s, m in zip(s_moveis, velhos))
    assert len(set(s_novos + s_moveis)) == 5


def test_autenticar_sem_terminal_nao_abre_navegador(monkeypatch):
    pedidos = []
    monkeypatch.setattr(up, "credenciais", lambda escopos, token, interativo=True:
                        pedidos.append(interativo) or (_ for _ in ()).throw(
                            _google.LoginNecessario("precisa de login")))
    monkeypatch.setattr(up, "tem_terminal", lambda: False)
    with pytest.raises(_google.LoginNecessario):
        up.autenticar()
    assert pedidos == [False]


def test_tem_terminal_sem_stdin(monkeypatch):
    monkeypatch.setattr(up.sys, "stdin", None)
    assert up.tem_terminal() is False


def test_sem_permissao_reconhece_403_de_escopo():
    e = up.HttpError(_Resp(403), b'{"reason": "insufficientPermissions"}')
    assert up._sem_permissao(e) and not up._cota_estourada(e)
    assert not up._sem_permissao(up.HttpError(_Resp(500), b"insufficientPermissions"))
