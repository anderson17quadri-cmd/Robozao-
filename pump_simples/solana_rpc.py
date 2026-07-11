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


def _rpc_call(method: str, params: list) -> tuple[dict | None, str]:
    """Devolve (json | None, motivo). motivo descreve a falha quando json é None."""
    if not CFG.solana_rpc_url:
        return None, "SOLANA_RPC_URL não configurada"
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        rpc_limiter.acquire()  # respeita N pedidos/segundo
        resp = requests.post(CFG.solana_rpc_url, json=payload, timeout=_TIMEOUT)
        if resp.status_code == 429:
            return None, "limite Helius atingido (HTTP 429 — vê os créditos/rate no dashboard)"
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code} do RPC"
        return resp.json(), "ok"
    except Exception as exc:
        return None, f"falha de rede/RPC: {type(exc).__name__}"


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

    data, motivo = _rpc_call(
        "getAccountInfo",
        [mint, {"encoding": "jsonParsed", "commitment": "confirmed"}],
    )
    if data is None:
        resultado["motivo"] = f"{motivo} (fail-closed)"
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


def get_top_holder_concentration(mint: str) -> dict:
    """
    Aproximação da concentração de holders — o sinal de rug que faltava.
    Na Solana não há "código" próprio por token (todos usam o programa SPL
    padrão); os riscos reais são: autoridades (já verificado acima), liquidez
    (já filtrada) e CONCENTRAÇÃO — se um wallet detém uma fatia enorme, pode
    despejar em cima de quem comprou.

    Usa getTokenLargestAccounts + getTokenSupply. Assume que a MAIOR conta é o
    pool/bonding-curve (detém a maioria da supply por desenho — normal, não é
    red flag) e mede a concentração das contas #2–#10 como proxy de "baleias"/dev.
    É uma aproximação (sem o endereço exato do pool não dá para excluir com
    certeza absoluta) — mas é o melhor sinal disponível via RPC gratuita.

    Devolve:
        {"confirmado": bool, "maior_holder_pct": float|None,
         "top2_10_pct": float|None, "motivo": str}
    """
    resultado = {"confirmado": False, "maior_holder_pct": None,
                 "top2_10_pct": None, "motivo": ""}
    if not mint:
        resultado["motivo"] = "mint vazio"
        return resultado
    if not CFG.solana_rpc_url:
        resultado["motivo"] = "SOLANA_RPC_URL não configurada"
        return resultado

    largest, motivo1 = _rpc_call("getTokenLargestAccounts", [mint])
    if largest is None:
        resultado["motivo"] = f"falha RPC (largest accounts): {motivo1}"
        return resultado
    if "error" in largest:
        # RPCs públicas costumam BLOQUEAR ou limitar mais este método específico
        # (mais pesado que o normal). Não é o token que é suspeito — é o RPC.
        resultado["motivo"] = (
            f"RPC recusou getTokenLargestAccounts: {largest['error']} "
            "(comum em RPCs públicas gratuitas — usa Helius ou similar p/ isto funcionar)"
        )
        return resultado

    supply, motivo2 = _rpc_call("getTokenSupply", [mint])
    if supply is None:
        resultado["motivo"] = f"falha RPC (supply): {motivo2}"
        return resultado
    if "error" in supply:
        resultado["motivo"] = f"RPC recusou getTokenSupply: {supply['error']}"
        return resultado

    try:
        contas = largest["result"]["value"]
        total = float(supply["result"]["value"]["amount"])
    except (KeyError, TypeError, ValueError):
        resultado["motivo"] = "resposta RPC inesperada (não foi possível parsear)"
        return resultado

    if not contas or total <= 0:
        resultado["motivo"] = "sem contas de holders ou supply zero"
        return resultado

    valores = sorted((float(c.get("amount", 0)) for c in contas), reverse=True)
    maior_pct = (valores[0] / total * 100.0) if valores else 0.0
    resto = valores[1:10]
    top2_10_pct = (sum(resto) / total * 100.0) if resto else 0.0

    resultado.update({
        "confirmado": True,
        "maior_holder_pct": round(maior_pct, 2),
        "top2_10_pct": round(top2_10_pct, 2),
        "motivo": "ok",
    })
    return resultado
