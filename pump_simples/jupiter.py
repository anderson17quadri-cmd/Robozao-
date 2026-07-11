"""
Execução de swaps via Jupiter API (quote + swap).

SÓ é usado quando o envio real está armado (DRY_RUN=false E PERMITIR_ENVIO_REAL=true).
Imports de assinatura são preguiçosos. Toda chamada em try/except.

Isto é a camada de execução real — mantida deliberadamente simples. Testa com
valores minúsculos (MAX_TRADE_USD default = $2) antes de confiar.
"""

import requests

from config import CFG, SOL_MINT
from solana_rpc import rpc_limiter

_TIMEOUT = 20


def get_quote(input_mint: str, output_mint: str, amount_lamports: int) -> dict | None:
    """Pede uma cotação à Jupiter. Devolve o quoteResponse (dict) ou None."""
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(int(amount_lamports)),
        "slippageBps": str(CFG.slippage_bps),
    }
    try:
        resp = requests.get(
            f"{CFG.jupiter_api_base}/quote", params=params, timeout=_TIMEOUT
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _build_swap_tx(quote: dict, user_pubkey: str) -> str | None:
    """Pede à Jupiter a transação de swap serializada (base64)."""
    body = {
        "quoteResponse": quote,
        "userPublicKey": user_pubkey,
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
    }
    try:
        resp = requests.post(
            f"{CFG.jupiter_api_base}/swap", json=body, timeout=_TIMEOUT
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("swapTransaction")
    except Exception:
        return None


def _sign_and_send(swap_tx_b64: str) -> str | None:
    """Assina a tx com a wallet e envia via RPC. Devolve a signature ou None."""
    import base64

    from solders.transaction import VersionedTransaction  # type: ignore
    from solders.keypair import Keypair  # noqa: F401  (garante dependência)

    from wallet import get_keypair

    try:
        kp = get_keypair()
        raw = base64.b64decode(swap_tx_b64)
        unsigned = VersionedTransaction.from_bytes(raw)
        signed = VersionedTransaction(unsigned.message, [kp])
        signed_b64 = base64.b64encode(bytes(signed)).decode("utf-8")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                signed_b64,
                {"encoding": "base64", "skipPreflight": False, "maxRetries": 3},
            ],
        }
        rpc_limiter.acquire()
        resp = requests.post(CFG.solana_rpc_url, json=payload, timeout=_TIMEOUT)
        data = resp.json()
        if "error" in data:
            return None
        return data.get("result")
    except Exception:
        return None


def swap(input_mint: str, output_mint: str, amount_lamports: int) -> dict:
    """
    Executa um swap real. Devolve:
        {"ok": bool, "signature": str|None, "out_amount": int|None, "motivo": str}
    """
    from wallet import get_public_key

    pubkey = get_public_key()
    if not pubkey:
        return {"ok": False, "signature": None, "out_amount": None,
                "motivo": "wallet indisponível"}

    quote = get_quote(input_mint, output_mint, amount_lamports)
    if not quote:
        return {"ok": False, "signature": None, "out_amount": None,
                "motivo": "sem cotação Jupiter"}

    swap_tx = _build_swap_tx(quote, pubkey)
    if not swap_tx:
        return {"ok": False, "signature": None, "out_amount": None,
                "motivo": "falha a construir swap tx"}

    sig = _sign_and_send(swap_tx)
    if not sig:
        return {"ok": False, "signature": None, "out_amount": None,
                "motivo": "falha a assinar/enviar tx"}

    out_amount = None
    try:
        out_amount = int(quote.get("outAmount"))
    except (TypeError, ValueError):
        pass
    return {"ok": True, "signature": sig, "out_amount": out_amount, "motivo": "ok"}
