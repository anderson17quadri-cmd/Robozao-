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


def _read_compact_u16(data: bytes, offset: int) -> tuple[int, int]:
    """
    Lê um compact-u16 (codificação shortvec da Solana, usada p/ contar
    assinaturas/contas/etc no formato wire da transação). Devolve (valor, novo_offset).
    """
    valor = 0
    comprimento = 0
    while True:
        elem = data[offset + comprimento]
        valor |= (elem & 0x7F) << (comprimento * 7)
        comprimento += 1
        if elem & 0x80 == 0:
            break
    return valor, offset + comprimento


def _assinar_transacao_bruta(raw_tx: bytes, signing_key) -> bytes:
    """
    Assina uma VersionedTransaction serializada da Jupiter (bytes crus, ainda
    sem assinatura) usando ed25519_pure (Python puro) — sem depender do
    solders/Rust nem do pynacl/libsodium.

    Formato wire da Solana: [compact-u16 nº assinaturas][N * 64 bytes de
    assinatura (vazias)][mensagem]. Assume UM único signatário (a nossa
    wallet como fee payer) — o mesmo pressuposto que o código anterior
    (solders) já fazia.
    """
    num_sigs, inicio_assinaturas = _read_compact_u16(raw_tx, 0)
    fim_assinaturas = inicio_assinaturas + num_sigs * 64
    mensagem = raw_tx[fim_assinaturas:]

    assinatura = signing_key.sign(mensagem)  # 64 bytes ed25519

    tx_assinada = bytearray(raw_tx)
    tx_assinada[inicio_assinaturas:inicio_assinaturas + 64] = assinatura
    return bytes(tx_assinada)


def _sign_and_send(swap_tx_b64: str, skip_preflight: bool = False) -> tuple[str | None, str]:
    """
    Assina a tx (ed25519_pure) e envia via RPC. Devolve (signature|None, detalhe).
    `detalhe` traz o erro real do RPC quando falha (antes era engolido).
    """
    import base64

    from wallet import get_signing_key

    try:
        sk = get_signing_key()
        raw = base64.b64decode(swap_tx_b64)
        tx_assinada = _assinar_transacao_bruta(raw, sk)
        signed_b64 = base64.b64encode(tx_assinada).decode("utf-8")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                signed_b64,
                {"encoding": "base64", "skipPreflight": skip_preflight, "maxRetries": 3},
            ],
        }
        rpc_limiter.acquire()
        resp = requests.post(CFG.solana_rpc_url, json=payload, timeout=_TIMEOUT)
        data = resp.json()
        if "error" in data:
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            return None, str(msg)[:200]
        sig = data.get("result")
        return (sig, "") if sig else (None, "RPC não devolveu assinatura")
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


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

    sig, detalhe = _sign_and_send(swap_tx, skip_preflight=False)
    if not sig:
        # 2ª tentativa: salta a simulação (preflight). Às vezes a simulação
        # falha por estado momentâneo/slippage mas a tx passaria na mesma.
        sig, detalhe2 = _sign_and_send(swap_tx, skip_preflight=True)
        if not sig:
            return {"ok": False, "signature": None, "out_amount": None,
                    "motivo": f"falha a enviar tx: {detalhe or detalhe2}"}

    # ESPERA a confirmação on-chain — a assinatura é devolvida ao submeter,
    # não quando executa. Só depois disto é seguro dizer que o swap resultou.
    from solana_rpc import confirmar_transacao
    estado = confirmar_transacao(sig)
    if estado == "falhou":
        return {"ok": False, "signature": sig, "out_amount": None,
                "motivo": "tx falhou on-chain (rejeitada/sem execução)"}
    if estado == "timeout":
        return {"ok": False, "signature": sig, "out_amount": None,
                "motivo": "tx não confirmou a tempo — verifica na wallet antes de repetir"}

    out_amount = None
    try:
        out_amount = int(quote.get("outAmount"))
    except (TypeError, ValueError):
        pass
    return {"ok": True, "signature": sig, "out_amount": out_amount, "motivo": "ok"}
