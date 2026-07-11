"""
Fonte de deteção ALTERNATIVA: API não-oficial do pump.fun.

Baseada no tráfego real da app pump.fun (mesma ideia de github.com/BankkRoll/pumpfun-apis)
via frontend-api.pump.fun. Grátis, sem chave. É engenharia reversa — pode partir
sem aviso se o pump.fun mudar a API.

Devolve apenas CANDIDATOS crus: {mint, name, created_at}. O dispatcher (fontes.py)
padroniza-os depois via GeckoTerminal para o formato completo que o trader espera.

Ranking usado: TRENDING (atividade de trading recente), para ficar próximo do que
a app do pump.fun mostra em destaque — em vez de simplesmente "os mais recentes".
A API não-oficial não expõe um ranking de volume limpo numa só chamada, por isso
usamos `last_trade_timestamp` (tokens a ser negociados agora) como proxy de trending.

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

# Campo de ordenação = proxy de "trending" (atividade recente).
# Alternativas fáceis de trocar: "market_cap" (maiores) ou "created_timestamp" (novos).
_SORT = "last_trade_timestamp"


def get_new_candidates() -> list[dict]:
    """
    Tokens pump.fun em DESTAQUE por atividade recente (trending), mais ativos
    primeiro. Devolve [{mint, name, created_at}]. Só descoberta — sem preço aqui.
    """
    params = {
        "offset": 0,
        "limit": 50,
        "sort": _SORT,
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
