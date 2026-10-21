"""Identidade do NOSSO canal no YouTube (compartilhado pelos steps 8 e 9).

O link do canal só entra na linha "Inscreva-se" da descrição. "Conteúdo original"
é sempre a URL da FONTE (inputs/<stem>.url) — crédito obrigatório pro YPP.
"""
CANAL_ID = "UCRJDgbBEndOdbNaiwzFju2g"
CANAL_HANDLE = "@missaoemcortes-14"      # @missaoemcortes (sem -14) NÃO é nosso
CANAL_URL = f"https://www.youtube.com/channel/{CANAL_ID}"


def eh_nosso_canal(url: str) -> bool:
    """True se a URL aponta pro nosso canal (não serve como crédito da fonte)."""
    u = url.lower()
    return CANAL_ID.lower() in u or CANAL_HANDLE in u
