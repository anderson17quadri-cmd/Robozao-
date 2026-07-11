"""
Fonte de dados: GeckoTerminal (API pública, gratuita, sem chave).

- Deteção de tokens novos pump.fun: /networks/solana/new_pools (filtrando dex=pump-fun)
- Preço atual de um pool: /networks/solana/pools/{address}
- Preço do SOL em USD: /simple/networks/solana/token_price/{mint}

Toda chamada em try/except: uma falha devolve valores seguros (None / lista vazia)
e nunca derruba o loop.
"""

import requests

from config import CFG, SOL_MINT

_HEADERS = {"Accept": "application/json", "User-Agent": "robozao/1.0"}
_TIMEOUT = 12

# ids de dex pump.fun na GeckoTerminal (bonding curve + pool graduado)
_PUMP_DEXES = {"pump-fun", "pumpfun", "pumpswap", "pump-swap"}


def _get_json(url: str, params: dict | None = None) -> dict | None:
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _f(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def get_new_pump_pools() -> list[dict]:
    """
    Devolve pools pump.fun recém-criados, normalizados:
        {pool_address, mint, name, price_usd, liquidity_usd, dex, created_at}
    """
    data = _get_json(f"{CFG.gecko_api_base}/networks/solana/new_pools")
    if not data or "data" not in data:
        return []

    pools: list[dict] = []
    for item in data.get("data", []):
        try:
            attrs = item.get("attributes", {}) or {}
            rel = item.get("relationships", {}) or {}

            dex_id = (
                (rel.get("dex", {}) or {}).get("data", {}) or {}
            ).get("id", "")
            if dex_id not in _PUMP_DEXES:
                continue

            base = (rel.get("base_token", {}) or {}).get("data", {}) or {}
            # id vem como "solana_<mint>"
            base_id = base.get("id", "")
            mint = base_id.split("_", 1)[1] if "_" in base_id else base_id
            if not mint:
                continue

            pools.append(
                {
                    "pool_address": attrs.get("address", ""),
                    "mint": mint,
                    "name": attrs.get("name", "?"),
                    "price_usd": _f(attrs.get("base_token_price_usd")),
                    "liquidity_usd": _f(attrs.get("reserve_in_usd")) or 0.0,
                    "dex": dex_id,
                    "created_at": attrs.get("pool_created_at", ""),
                }
            )
        except Exception:
            # um item malformado nunca estraga a lista inteira
            continue
    return pools


def get_pool_price(pool_address: str) -> float | None:
    """Preço atual (USD) do base token de um pool. None em caso de falha."""
    if not pool_address:
        return None
    data = _get_json(f"{CFG.gecko_api_base}/networks/solana/pools/{pool_address}")
    if not data or "data" not in data:
        return None
    attrs = (data.get("data", {}) or {}).get("attributes", {}) or {}
    return _f(attrs.get("base_token_price_usd"))


def get_sol_price_usd() -> float | None:
    """Preço do SOL em USD (usado só no modo real para converter USD->SOL)."""
    data = _get_json(
        f"{CFG.gecko_api_base}/simple/networks/solana/token_price/{SOL_MINT}"
    )
    if not data:
        return None
    try:
        prices = data["data"]["attributes"]["token_prices"]
        return _f(prices.get(SOL_MINT))
    except Exception:
        return None
