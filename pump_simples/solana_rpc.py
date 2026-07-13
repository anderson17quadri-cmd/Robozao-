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


def confirmar_transacao(signature: str, timeout_seg: float = 45.0) -> str:
    """
    Espera uma transação confirmar on-chain. O sendTransaction devolve a
    assinatura logo ao SUBMETER — não quando executa. Sem esperar aqui, o
    resto do código podia ler o saldo cedo demais e achar que a compra falhou.

    Devolve:
      "confirmada" | "falhou" (erro on-chain) | "timeout" (não confirmou a tempo).
    """
    import time as _time
    if not signature:
        return "falhou"
    fim = _time.time() + timeout_seg
    while _time.time() < fim:
        data, _motivo = _rpc_call(
            "getSignatureStatuses",
            [[signature], {"searchTransactionHistory": True}],
        )
        try:
            estado = data["result"]["value"][0]
        except (KeyError, TypeError, IndexError):
            estado = None
        if estado is not None:
            if estado.get("err") is not None:
                return "falhou"
            if estado.get("confirmationStatus") in ("confirmed", "finalized"):
                return "confirmada"
        _time.sleep(2)
    return "timeout"


_TOKEN_PROGRAMS = (
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",   # SPL Token clássico
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",   # Token-2022 (os "...pump")
)


def listar_tokens(owner_pubkey: str) -> list[dict]:
    """
    Lista TODOS os tokens (com saldo > 0) que a wallet detém, dos dois programas
    de token da Solana. Cada item: {mint, amount_base, decimals, amount_humano}.
    Devolve [] se não tiver nenhum ou se falhar.
    """
    if not owner_pubkey:
        return []
    por_mint: dict[str, dict] = {}
    for programa in _TOKEN_PROGRAMS:
        data, _motivo = _rpc_call("getTokenAccountsByOwner", [
            owner_pubkey, {"programId": programa}, {"encoding": "jsonParsed"},
        ])
        if not data or "result" not in data:
            continue
        try:
            contas = data["result"]["value"]
        except (KeyError, TypeError):
            continue
        for c in contas:
            try:
                info = c["account"]["data"]["parsed"]["info"]
                mint = info["mint"]
                ta = info["tokenAmount"]
                base = int(ta["amount"])
                dec = int(ta["decimals"])
            except (KeyError, TypeError, ValueError):
                continue
            if base <= 0:
                continue
            item = por_mint.setdefault(
                mint, {"mint": mint, "amount_base": 0, "decimals": dec, "amount_humano": 0.0})
            item["amount_base"] += base
            item["decimals"] = dec
            item["amount_humano"] = item["amount_base"] / (10 ** dec) if dec is not None else 0.0
    return list(por_mint.values())


def get_token_account_info(owner_pubkey: str, mint: str) -> dict | None:
    """
    Saldo REAL na wallet de um token específico, via getTokenAccountsByOwner
    (jsonParsed) — a fonte da verdade para vender: nunca confia em contas locais
    (que podem desviar por causa de decimais, slippage, ou qualquer coisa
    externa à wallet). Soma todas as contas desse mint (normalmente só há uma).

    Devolve:
      - dict {"amount_base": int, "decimals": int|None, "amount_humano": float}
        quando conseguiu LER a wallet. amount_base=0 é um ZERO CONFIRMADO
        (a wallet respondeu e não tem este token) — distinto de "não consegui
        verificar".
      - None SÓ quando a chamada falhou mesmo (RPC em baixo, resposta
        malformada) e portanto o saldo é DESCONHECIDO.
    Esta distinção é importante: quem compra usa-a para separar "a tx falhou,
    recebi 0 tokens" (zero confirmado -> não abre posição) de "não sei, o RPC
    falhou" (desconhecido -> fallback com aviso).
    """
    if not owner_pubkey or not mint:
        return None
    data, _motivo = _rpc_call("getTokenAccountsByOwner", [
        owner_pubkey, {"mint": mint}, {"encoding": "jsonParsed"},
    ])
    if not data or "result" not in data:
        return None
    try:
        contas = data["result"]["value"]
        total_base = 0
        decimals = None
        for c in contas:
            info = c["account"]["data"]["parsed"]["info"]["tokenAmount"]
            total_base += int(info["amount"])
            decimals = int(info["decimals"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    # sem contas => zero CONFIRMADO (decimals fica None, amount_humano 0.0)
    amount_humano = (total_base / (10 ** decimals)) if decimals is not None else 0.0
    return {"amount_base": total_base, "decimals": decimals,
            "amount_humano": amount_humano}


def get_sol_balance(pubkey: str) -> float | None:
    """Saldo em SOL da wallet (getBalance). None se falhar (RPC em baixo,
    pubkey inválida, etc.) — nunca finge um valor."""
    if not pubkey:
        return None
    data, _motivo = _rpc_call("getBalance", [pubkey])
    if not data or "result" not in data:
        return None
    try:
        lamports = data["result"]["value"]
        return lamports / 1_000_000_000
    except (KeyError, TypeError):
        return None
