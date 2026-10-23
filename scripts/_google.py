"""Login OAuth do Google (YouTube), compartilhado pelo 09 (upload) e pelo 12 (métricas).

Cada uso tem o PRÓPRIO token com os escopos mínimos: o de upload não ganha permissão de
leitura e vice-versa. 1ª vez (ou escopo novo) abre o navegador; depois reusa o token.
Credencial do app (OAuth desktop) por projeto do Google Cloud, tudo em secrets/ (fora do Git):
  - upload (09):   secrets/youtube_client_secret.json   (projeto missao-em-cortes-publisher)
  - métricas (12): secrets/analytics_client_secret.json (projeto missao-em-cortes-analytics)
Token feito com o client de um projeto não serve pro outro: se o client_id gravado no token
não bate com o do client_secret pedido, refaz o login (nunca mistura os projetos).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CLIENT_SECRET = ROOT / "secrets" / "youtube_client_secret.json"


def escopos_gravados(token: Path) -> set[str]:
    """Escopos autorizados no login, como gravados no arquivo do token."""
    try:
        escopos = json.loads(token.read_text(encoding="utf-8")).get("scopes") or []
    except (OSError, ValueError):
        return set()
    return set(escopos.split() if isinstance(escopos, str) else escopos)


def _client_id(arquivo: Path, *chaves: str) -> str | None:
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for chave in chaves:
        dados = dados.get(chave) if isinstance(dados, dict) else None
    return dados if isinstance(dados, str) else None


def client_id_do_secret(client_secret: Path) -> str | None:
    """client_id do JSON baixado do Google Cloud ({"installed": {"client_id": ...}})."""
    return (_client_id(client_secret, "installed", "client_id")
            or _client_id(client_secret, "web", "client_id"))


class LoginNecessario(RuntimeError):
    """Sem token válido numa rodada sem ninguém olhando (ex.: Agendador do Windows)."""


def credenciais(escopos: list[str], token: Path, client_secret: Path | None = None,
                interativo: bool = True):
    """interativo=False nunca abre o navegador: sem token válido, levanta LoginNecessario."""
    client_secret = client_secret or CLIENT_SECRET   # padrão: o do upload (09)
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = Credentials.from_authorized_user_file(str(token), escopos) if token.exists() else None
    # o from_authorized_user_file troca os escopos do arquivo pelos pedidos (has_scopes
    # sempre daria True): compara com o que foi de fato autorizado e gravado no token
    if creds and not set(escopos) <= escopos_gravados(token):
        print("   [aviso] o token não tem todos os escopos pedidos — vai pedir login de novo")
        creds = None
    esperado = client_id_do_secret(client_secret)
    if creds and esperado and _client_id(token, "client_id") != esperado:
        print(f"   [aviso] o token é de outro projeto do Google (não de {client_secret.name}) "
              f"— vai pedir login de novo")
        creds = None
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            print("   [aviso] token do YouTube expirou/foi revogado — vai pedir login de novo")
            creds = None
    if not creds or not creds.valid:
        if not interativo:
            raise LoginNecessario(f"precisa de login no Google ({token.name}): rode o "
                                  f"script à mão uma vez pra abrir o navegador")
        if not client_secret.exists():
            sys.exit(f"[!] Falta {client_secret.relative_to(ROOT) if client_secret.is_relative_to(ROOT) else client_secret}"
                     f" — baixe a credencial OAuth (app de desktop) no Google Cloud e salve com esse nome.")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), escopos)
        creds = flow.run_local_server(port=0)
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    return creds
