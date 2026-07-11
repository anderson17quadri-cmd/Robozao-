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
from ratelimit import RateLimiter

_HEADERS = {"Accept": "application/json", "User-Agent": "robozao/1.0"}
_TIMEOUT = 12

# ids de dex pump.fun na GeckoTerminal (bonding curve + pool graduado)
_PUMP_DEXES = {"pump-fun", "pumpfun", "pumpswap", "pump-swap"}

# limita as chamadas ao Gecko (free-tier ~30/min) — evita 429 com muitas posições
gecko_limiter = RateLimiter(CFG.gecko_max_req_por_segundo)


def _get_json(url: str, params: dict | None = None) -> dict | None:
    try:
        gecko_limiter.acquire()
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


def _metricas_hype(attrs: dict) -> dict:
    """Extrai sinais de 'hype' dos atributos de um pool GeckoTerminal:
    volume e nº de compradores na última hora + últimos 5 min."""
    vol = attrs.get("volume_usd", {}) or {}
    tx = attrs.get("transactions", {}) or {}
    tx_h1 = tx.get("h1", {}) or {}
    tx_m5 = tx.get("m5", {}) or {}
    return {
        "volume_h1": _f(vol.get("h1")) or 0.0,
        "volume_m5": _f(vol.get("m5")) or 0.0,
        "buyers_h1": int(tx_h1.get("buyers") or 0),
        "buyers_m5": int(tx_m5.get("buyers") or 0),
        "txns_h1": int(tx_h1.get("buys") or 0) + int(tx_h1.get("sells") or 0),
    }


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
                    **_metricas_hype(attrs),
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


def verificar_pool(pool_address: str, mint_esperado: str = "") -> dict:
    """
    Confirma que um pool_address é REAL na GeckoTerminal (não inventado/corrompido)
    e, se `mint_esperado` for dado, que o mint do pool bate certo com o que temos
    guardado. Usado para auditar se as posições do bot são tokens genuínos.

    Devolve:
        {"existe": bool, "motivo": str, "name": str, "price_usd": float|None,
         "liquidity_usd": float, "dex": str, "mint_no_gecko": str,
         "mint_confere": bool|None}
    """
    resultado = {"existe": False, "motivo": "", "name": "?", "price_usd": None,
                 "liquidity_usd": 0.0, "dex": "", "mint_no_gecko": "", "mint_confere": None}
    if not pool_address:
        resultado["motivo"] = "pool_address vazio"
        return resultado

    data = _get_json(f"{CFG.gecko_api_base}/networks/solana/pools/{pool_address}")
    if not data or "data" not in data:
        resultado["motivo"] = "pool NÃO encontrado na GeckoTerminal (endereço inválido/inexistente?)"
        return resultado

    attrs = (data.get("data", {}) or {}).get("attributes", {}) or {}
    rel = (data.get("data", {}) or {}).get("relationships", {}) or {}
    base = (rel.get("base_token", {}) or {}).get("data", {}) or {}
    base_id = base.get("id", "")
    mint_gecko = base_id.split("_", 1)[1] if "_" in base_id else base_id

    resultado.update({
        "existe": True,
        "motivo": "pool confirmado na GeckoTerminal",
        "name": attrs.get("name", "?"),
        "price_usd": _f(attrs.get("base_token_price_usd")),
        "liquidity_usd": _f(attrs.get("reserve_in_usd")) or 0.0,
        "dex": ((rel.get("dex", {}) or {}).get("data", {}) or {}).get("id", ""),
        "mint_no_gecko": mint_gecko,
    })
    if mint_esperado:
        resultado["mint_confere"] = (mint_gecko == mint_esperado)
    return resultado


def get_pool_info(pool_address: str) -> dict | None:
    """
    Info atual e completa de um pool (preço, liquidez, hype) numa só chamada.
    Usado pela lista de vigia para reavaliar um candidato sem depender de ele
    ainda aparecer no feed new_pools (que só mostra os mais recentes).
    """
    if not pool_address:
        return None
    data = _get_json(f"{CFG.gecko_api_base}/networks/solana/pools/{pool_address}")
    if not data or "data" not in data:
        return None
    attrs = (data.get("data", {}) or {}).get("attributes", {}) or {}
    rel = (data.get("data", {}) or {}).get("relationships", {}) or {}
    dex_id = ((rel.get("dex", {}) or {}).get("data", {}) or {}).get("id", "")
    return {
        "price_usd": _f(attrs.get("base_token_price_usd")),
        "liquidity_usd": _f(attrs.get("reserve_in_usd")) or 0.0,
        "dex": dex_id,
        **_metricas_hype(attrs),
    }


def find_pool_by_mint(mint: str) -> dict | None:
    """
    Dado um mint, encontra o melhor pool (maior liquidez) na GeckoTerminal e
    devolve o formato normalizado usado pelo resto do bot:
        {pool_address, mint, name, price_usd, liquidity_usd, dex, created_at}
    None se o token ainda não tiver pool indexado.

    Serve para PADRONIZAR candidatos vindos de fontes que não são a GeckoTerminal
    (pumpfun_nao_oficial / bitquery), garantindo um pool_address para a
    monitorização de preço funcionar igual, independentemente da fonte.
    """
    if not mint:
        return None
    data = _get_json(f"{CFG.gecko_api_base}/networks/solana/tokens/{mint}/pools")
    if not data or "data" not in data:
        return None

    melhor = None
    for item in data.get("data", []):
        try:
            attrs = item.get("attributes", {}) or {}
            rel = item.get("relationships", {}) or {}
            dex_id = ((rel.get("dex", {}) or {}).get("data", {}) or {}).get("id", "")
            liq = _f(attrs.get("reserve_in_usd")) or 0.0
            cand = {
                "pool_address": attrs.get("address", ""),
                "mint": mint,
                "name": attrs.get("name", "?"),
                "price_usd": _f(attrs.get("base_token_price_usd")),
                "liquidity_usd": liq,
                "dex": dex_id,
                "created_at": attrs.get("pool_created_at", ""),
                **_metricas_hype(attrs),
            }
            if cand["pool_address"] and (melhor is None or liq > melhor["liquidity_usd"]):
                melhor = cand
        except Exception:
            continue
    return melhor


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
