"""
Lista de vigia — resolve o "não tem compras".

Tokens pump.fun nascem com liquidez/mcap quase zero e só crescem depois. O feed
new_pools da GeckoTerminal só mostra os muito recentes (~minutos). Sem esta
lista, um token rejeitado por liquidez/mcap baixos no minuto 1 NUNCA mais seria
reavaliado — mesmo que chegasse a $10k de mcap no minuto 15, já teria saído do
feed e o bot nunca o veria crescer.

Aqui guardamos esses candidatos por um tempo (TTL) e reavaliamo-los com dados
frescos (gecko.get_pool_info) a cada ciclo, comprando se entretanto qualificarem.
Mantém os filtros de liquidez/mcap tal como estão — só dá tempo ao token de
crescer até eles, em vez de o descartar para sempre ao fim de 1 minuto.
"""

import time

from config import CFG

_watchlist: dict[str, dict] = {}   # mint -> {pool, added_at, last_checked}
_MAX_ENTRADAS = 300


def adicionar(pool: dict) -> None:
    """Regista um candidato rejeitado (só por liquidez/mcap) para reavaliar depois."""
    mint = pool.get("mint")
    if not mint or mint in _watchlist:
        return
    if len(_watchlist) >= _MAX_ENTRADAS:
        mais_antigo = min(_watchlist, key=lambda m: _watchlist[m]["added_at"])
        del _watchlist[mais_antigo]
    _watchlist[mint] = {"pool": dict(pool), "added_at": time.time(), "last_checked": 0.0}


def remover(mint: str) -> None:
    _watchlist.pop(mint, None)


def atualizar(mint: str, pool: dict) -> None:
    """Atualiza os dados guardados (preço/liquidez frescos) e marca como verificado agora."""
    if mint in _watchlist:
        _watchlist[mint]["pool"] = dict(pool)
        _watchlist[mint]["last_checked"] = time.time()


def limpar_expirados() -> int:
    """Remove entradas mais velhas que VIGIA_TTL_MINUTOS. Devolve quantas saíram."""
    agora = time.time()
    ttl_seg = CFG.vigia_ttl_minutos * 60
    expirados = [m for m, e in _watchlist.items() if agora - e["added_at"] > ttl_seg]
    for m in expirados:
        del _watchlist[m]
    return len(expirados)


def candidatos_para_verificar(limite: int) -> list[dict]:
    """
    Os `limite` candidatos há mais tempo sem verificar (para distribuir as
    chamadas de rede ao longo dos ciclos, em vez de rebentar com o rate limit).
    """
    itens = sorted(_watchlist.values(), key=lambda e: e["last_checked"])
    return [dict(e["pool"]) for e in itens[:limite]]


def limpar_tudo() -> None:
    """Esvazia a lista de vigia (usado quando a vigia é desligada)."""
    _watchlist.clear()


def tamanho() -> int:
    return len(_watchlist)
