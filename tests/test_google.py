"""_google.credenciais: tudo mockado (nada de login, navegador ou rede)."""
import json

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import _google

ESC = ["https://www.googleapis.com/auth/youtube.upload"]


class FakeCreds:
    def __init__(self, valid=True, expired=False, refresh_token="rt", scopes=True, refresh_erro=False):
        self.valid, self.expired, self.refresh_token = valid, expired, refresh_token
        self._scopes, self._erro, self.refreshed = scopes, refresh_erro, 0

    def has_scopes(self, escopos):
        return self._scopes

    def refresh(self, request):
        self.refreshed += 1
        if self._erro:
            raise RefreshError("revogado")
        self.valid = True

    def to_json(self):
        return '{"fake": true}'


@pytest.fixture
def g(tmp_path, monkeypatch):
    """Token e client_secret falsos; conta os logins e devolve o cred que o flow geraria."""
    st = {"logins": 0, "carregadas": None, "flow_cred": FakeCreds()}
    token = tmp_path / "sub" / "token.json"
    secret = tmp_path / "client_secret.json"
    secret.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(_google, "CLIENT_SECRET", secret)

    class FakeFlow:
        def run_local_server(self, port=0):
            st["logins"] += 1
            return st["flow_cred"]

    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file",
                        classmethod(lambda cls, *a, **k: FakeFlow()))
    monkeypatch.setattr(Credentials, "from_authorized_user_file",
                        classmethod(lambda cls, *a, **k: st["carregadas"]))
    st["token"] = token
    return st


def test_sem_token_faz_login_e_grava(g):
    c = _google.credenciais(ESC, g["token"])
    assert c is g["flow_cred"] and g["logins"] == 1
    assert g["token"].read_text(encoding="utf-8") == '{"fake": true}'  # cria a pasta pai


def test_token_valido_reusa_sem_login(g):
    g["token"].parent.mkdir(parents=True)
    g["token"].write_text(json.dumps({"scopes": ESC}))
    g["carregadas"] = ok = FakeCreds()
    assert _google.credenciais(ESC, g["token"]) is ok and g["logins"] == 0


def test_token_sem_escopo_pede_login_de_novo(g, capsys):
    g["token"].parent.mkdir(parents=True)
    g["token"].write_text(json.dumps({"scopes": ESC}))
    g["token"].write_text(json.dumps({"scopes": ["https://www.googleapis.com/auth/outro"]}))
    g["carregadas"] = FakeCreds()
    assert _google.credenciais(ESC, g["token"]) is g["flow_cred"]
    assert g["logins"] == 1 and "escopos" in capsys.readouterr().out


def test_expirado_com_refresh_ok_nao_faz_login(g):
    g["token"].parent.mkdir(parents=True)
    g["token"].write_text(json.dumps({"scopes": ESC}))
    g["carregadas"] = exp = FakeCreds(valid=False, expired=True)
    monkey_req = pytest.MonkeyPatch()
    monkey_req.setattr("google.auth.transport.requests.Request", lambda: object())
    try:
        assert _google.credenciais(ESC, g["token"]) is exp
    finally:
        monkey_req.undo()
    assert exp.refreshed == 1 and g["logins"] == 0
    assert g["token"].read_text(encoding="utf-8") == '{"fake": true}'


def test_refresh_error_cai_pro_login(g, capsys):
    g["token"].parent.mkdir(parents=True)
    g["token"].write_text(json.dumps({"scopes": ESC}))
    g["carregadas"] = FakeCreds(valid=False, expired=True, refresh_erro=True)
    assert _google.credenciais(ESC, g["token"]) is g["flow_cred"]
    assert g["logins"] == 1 and "revogado" in capsys.readouterr().out


def test_sem_client_secret_sai_com_erro(g, tmp_path, monkeypatch):
    monkeypatch.setattr(_google, "CLIENT_SECRET", _google.ROOT / "secrets" / "_inexistente_teste.json")
    with pytest.raises(SystemExit):
        _google.credenciais(ESC, g["token"])
    assert g["logins"] == 0 and not g["token"].exists()


def test_escopos_gravados(tmp_path):
    t = tmp_path / "t.json"
    assert _google.escopos_gravados(t) == set()                       # não existe
    t.write_text("lixo")
    assert _google.escopos_gravados(t) == set()                       # corrompido
    t.write_text(json.dumps({"scopes": "a b"}))
    assert _google.escopos_gravados(t) == {"a", "b"}                  # string com espaço
    t.write_text(json.dumps({"scopes": ["a", "b"]}))
    assert _google.escopos_gravados(t) == {"a", "b"}


def test_escopo_a_mais_no_token_nao_pede_login(g):
    g["token"].parent.mkdir(parents=True)
    g["token"].write_text(json.dumps({"scopes": ESC + ["https://x/extra"]}))
    g["carregadas"] = ok = FakeCreds()
    assert _google.credenciais(ESC, g["token"]) is ok and g["logins"] == 0


# ── projeto certo: token de um client não serve pra outro ──────────────────

def _secret(path, cid):
    path.write_text(json.dumps({"installed": {"client_id": cid}}), encoding="utf-8")
    return path


def _token(g, cid):
    g["token"].parent.mkdir(parents=True, exist_ok=True)
    g["token"].write_text(json.dumps({"client_id": cid, "scopes": ESC}), encoding="utf-8")


def test_token_de_outro_projeto_refaz_login(g, tmp_path, capsys):
    secret = _secret(tmp_path / "analytics_client_secret.json", "analytics-id")
    _token(g, "publisher-id")
    g["carregadas"] = FakeCreds()
    assert _google.credenciais(ESC, g["token"], secret) is g["flow_cred"] and g["logins"] == 1
    assert "outro projeto" in capsys.readouterr().out


def test_token_do_mesmo_projeto_reusa(g, tmp_path):
    secret = _secret(tmp_path / "analytics_client_secret.json", "analytics-id")
    _token(g, "analytics-id")
    g["carregadas"] = FakeCreds()
    assert _google.credenciais(ESC, g["token"], secret) is g["carregadas"] and g["logins"] == 0


def test_login_usa_o_client_secret_pedido(g, tmp_path, monkeypatch):
    secret = _secret(tmp_path / "analytics_client_secret.json", "analytics-id")
    usados = []
    original = InstalledAppFlow.from_client_secrets_file
    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file",
                        classmethod(lambda cls, arq, esc: usados.append(arq) or original(arq, esc)))
    _google.credenciais(ESC, g["token"], secret)
    assert usados == [str(secret)]


def test_falta_client_secret_do_projeto_sai_com_nome(g, tmp_path):
    with pytest.raises(SystemExit, match="analytics_client_secret.json"):
        _google.credenciais(ESC, g["token"], tmp_path / "analytics_client_secret.json")
