"""_google.credenciais: tudo mockado (nada de login, navegador ou rede)."""
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
    g["token"].write_text("{}")
    g["carregadas"] = ok = FakeCreds()
    assert _google.credenciais(ESC, g["token"]) is ok and g["logins"] == 0


def test_token_sem_escopo_pede_login_de_novo(g, capsys):
    g["token"].parent.mkdir(parents=True)
    g["token"].write_text("{}")
    g["carregadas"] = FakeCreds(scopes=False)
    assert _google.credenciais(ESC, g["token"]) is g["flow_cred"]
    assert g["logins"] == 1 and "escopos" in capsys.readouterr().out


def test_expirado_com_refresh_ok_nao_faz_login(g):
    g["token"].parent.mkdir(parents=True)
    g["token"].write_text("{}")
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
    g["token"].write_text("{}")
    g["carregadas"] = FakeCreds(valid=False, expired=True, refresh_erro=True)
    assert _google.credenciais(ESC, g["token"]) is g["flow_cred"]
    assert g["logins"] == 1 and "revogado" in capsys.readouterr().out


def test_sem_client_secret_sai_com_erro(g, tmp_path, monkeypatch):
    monkeypatch.setattr(_google, "CLIENT_SECRET", _google.ROOT / "secrets" / "_inexistente_teste.json")
    with pytest.raises(SystemExit):
        _google.credenciais(ESC, g["token"])
    assert g["logins"] == 0 and not g["token"].exists()
