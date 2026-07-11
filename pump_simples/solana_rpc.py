"""
RPC Solana (via Helius) — único critério de segurança do robozão.

Confirma que mint_authority E freeze_authority estão AMBOS revogados (None).
Filosofia FAIL-CLOSED: qualquer erro / dados em falta => NÃO é seguro => não compra.

Usa getAccountInfo com encoding jsonParsed. Rate-limited de forma central.
"""

import requests

from config import CFG
from ratelimit import RateLimiter

# limitador partilhado por todas as chamadas RPC do processo
rpc_limiter = RateLimiter(CFG.rpc_max_req_por_segundo)

_TIMEOUT = 12


def _rpc_call(method: str, params: list) -> dict | None:
    if not CFG.solana_rpc_url:
        return None
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        rpc_limiter.acquire()  # respeita N pedidos/segundo
        resp = requests.post(CFG.solana_rpc_url, json=payload, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def check_mint_authorities(mint: str) -> dict:
    """
    Devolve:
        {
          "ok": bool,               # True SÓ se ambos None e confirmado via RPC
          "mint_authority": str|None,
          "freeze_authority": str|None,
          "confirmado": bool,       # conseguimos ler on-chain?
          "motivo": str,
        }
    Fail-closed: se não confirmar, ok=False.
    """
    resultado = {
        "ok": False,
        "mint_authority": None,
        "freeze_authority": None,
        "confirmado": False,
        "motivo": "",
    }

    if not mint:
        resultado["motivo"] = "mint vazio"
        return resultado
    if not CFG.solana_rpc_url:
        resultado["motivo"] = "SOLANA_RPC_URL não configurada (fail-closed)"
        return resultado

    data = _rpc_call(
        "getAccountInfo",
        [mint, {"encoding": "jsonParsed", "commitment": "confirmed"}],
    )
    if data is None:
        resultado["motivo"] = "falha de rede/RPC (fail-closed)"
        return resultado
    if "error" in data:
        resultado["motivo"] = f"erro RPC: {data['error']}"
        return resultado

    try:
        info = data["result"]["value"]["data"]["parsed"]["info"]
    except (KeyError, TypeError):
        resultado["motivo"] = "não foi possível parsear a conta do mint (fail-closed)"
        return resultado

    mint_auth = info.get("mintAuthority")      # None => revogada
    freeze_auth = info.get("freezeAuthority")  # None => revogada

    resultado["mint_authority"] = mint_auth
    resultado["freeze_authority"] = freeze_auth
    resultado["confirmado"] = True

    if mint_auth is None and freeze_auth is None:
        resultado["ok"] = True
        resultado["motivo"] = "autoridades revogadas (mint + freeze = None)"
    else:
        resultado["motivo"] = "autoridade ainda ativa (mint ou freeze != None)"

    return resultado
