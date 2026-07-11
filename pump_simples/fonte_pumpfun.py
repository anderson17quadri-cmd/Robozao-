"""
Fonte de deteção ALTERNATIVA: API não-oficial do pump.fun.

Baseada no tráfego real da app pump.fun (mesma ideia de github.com/BankkRoll/pumpfun-apis)
via frontend-api.pump.fun. Grátis, sem chave. É engenharia reversa — pode partir
sem aviso se o pump.fun mudar a API.

Devolve apenas CANDIDATOS crus: {mint, name, created_at}. O dispatcher (fontes.py)
padroniza-os depois via GeckoTerminal para o formato completo que o trader espera.

Toda chamada em try/except: uma falha devolve lista vazia e nunca derruba o loop.
"""

import requests

from config import CFG

_TIMEOUT = 12
# headers "de browser" — o frontend-api costuma exigir Origin/Referer
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (robozao)",
    "Origin": "https://pump.fun",
    "Referer": "https://pump.fun/",
}


def get_new_candidates() -> list[dict]:
    """
    Tokens pump.fun recentes, ordenados por criação (mais novos primeiro).
    Devolve [{mint, name, created_at}]. Só descoberta — sem preço/liquidez aqui.
    """
    params = {
        "offset": 0,
        "limit": 50,
        "sort": "created_timestamp",
        "order": "DESC",
        "includeNsfw": "false",
    }
    try:
        resp = requests.get(
            f"{CFG.pumpfun_api_base}/coins",
            params=params, headers=_HEADERS, timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    candidatos: list[dict] = []
    for coin in data:
        try:
            mint = coin.get("mint")
            if not mint:
                continue
            candidatos.append({
                "mint": mint,
                "name": coin.get("name") or coin.get("symbol") or "?",
                "created_at": coin.get("created_timestamp", ""),
            })
        except Exception:
            continue
    return candidatos
