"""Login OAuth do Google (YouTube), compartilhado pelo 09 (upload) e pelo 12 (métricas).

Cada uso tem o PRÓPRIO token com os escopos mínimos: o de upload não ganha permissão de
leitura e vice-versa. 1ª vez (ou escopo novo) abre o navegador; depois reusa o token.
Credencial do app (OAuth desktop) em secrets/youtube_client_secret.json — fora do Git.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CLIENT_SECRET = ROOT / "secrets" / "youtube_client_secret.json"


def credenciais(escopos: list[str], token: Path):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = Credentials.from_authorized_user_file(str(token), escopos) if token.exists() else None
    if creds and not creds.has_scopes(escopos):
        print("   [aviso] o token não tem todos os escopos pedidos — vai pedir login de novo")
        creds = None
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            print("   [aviso] token do YouTube expirou/foi revogado — vai pedir login de novo")
            creds = None
    if not creds or not creds.valid:
        if not CLIENT_SECRET.exists():
            sys.exit(f"[!] Falta {CLIENT_SECRET.relative_to(ROOT)} — baixe a credencial OAuth "
                     f"(app de desktop) no Google Cloud e salve com esse nome.")
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), escopos)
        creds = flow.run_local_server(port=0)
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    return creds
