"""
Dispatcher de fontes de deteção.

Só UMA fonte ativa de cada vez (CFG.fonte_deteccao):
    - "gecko"                -> GeckoTerminal /new_pools (default, dados já completos)
    - "pumpfun_nao_oficial"  -> API não-oficial do pump.fun (só descoberta)
    - "bitquery"             -> Bitquery GraphQL (só descoberta)

TODAS devolvem exatamente o MESMO formato, para o resto do bot (trader.py) não
precisar de saber qual fonte está ativa:
    {pool_address, mint, name, price_usd, liquidity_usd, dex, created_at}

Nota de desenho: as fontes alternativas só fazem *descoberta* (que mints
considerar). O preço/liquidez e o pool_address (necessário para a monitorização
de posições) são padronizados via GeckoTerminal — o oráculo de preço gratuito e
uniforme. Assim, trocar de fonte NUNCA altera o pipeline a jusante.
"""

import gecko
from config import CFG
from logjsonl import log_event

# quantos candidatos de fontes alternativas enriquecer por scan (poupa a API do gecko)
_MAX_CANDIDATOS_ENRIQUECER = 20


def get_new_pump_pools() -> list[dict]:
    """Ponto de entrada único usado pelo bot. Formato de saída sempre igual."""
    fonte = CFG.fonte_deteccao

    if fonte == "gecko":
        return gecko.get_new_pump_pools()

    if fonte == "pumpfun_nao_oficial":
        import fonte_pumpfun
        return _padronizar(fonte_pumpfun.get_new_candidates(), fonte)

    if fonte == "bitquery":
        import fonte_bitquery
        return _padronizar(fonte_bitquery.get_new_candidates(), fonte)

    # valor inesperado (não devia acontecer — config já valida) => fail-safe
    return gecko.get_new_pump_pools()


def _padronizar(candidatos: list[dict], fonte: str) -> list[dict]:
    """
    Converte candidatos crus {mint, name, created_at} no formato completo,
    via GeckoTerminal. Garante pool_address (senão a monitorização não funciona)
    — sem pool no oráculo => candidato descartado (fail-safe, não inventa dados).
    """
    pools: list[dict] = []
    for cand in candidatos[:_MAX_CANDIDATOS_ENRIQUECER]:
        mint = cand.get("mint")
        if not mint:
            continue
        info = gecko.find_pool_by_mint(mint)
        if not info or not info.get("pool_address"):
            # ainda sem pool indexado no oráculo de preço => salta (seguro)
            continue
        pools.append({
            "pool_address": info["pool_address"],
            "mint": mint,
            "name": cand.get("name") or info.get("name") or "?",
            "price_usd": info.get("price_usd"),
            "liquidity_usd": info.get("liquidity_usd") or 0.0,
            "dex": info.get("dex") or "pump-fun",
            "created_at": cand.get("created_at") or info.get("created_at", ""),
        })

    if not pools and candidatos:
        # houve candidatos mas nenhum tinha pool no gecko ainda — regista p/ diagnóstico
        log_event(CFG.log_file, "fonte_sem_pool", fonte=fonte,
                  candidatos=len(candidatos))
    return pools
