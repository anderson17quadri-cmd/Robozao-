"""
Carteira Solana.

- Lê a WALLET_PRIVATE_KEY (base58) do .env — a MESMA wallet do bot anterior.
- A chave privada NUNCA é impressa, logada ou devolvida em texto.
- Imports de assinatura (solders/base58) são preguiçosos: o modo DRY_RUN
  funciona sem essas bibliotecas instaladas.
"""

from config import CFG

_keypair_cache = None  # nunca serializado, nunca logado


def wallet_status() -> str:
    """Estado redigido — nunca revela a chave."""
    return "configurada" if CFG.wallet_private_key else "NÃO configurada"


def _load_keypair():
    """Carrega o Keypair a partir da chave base58. Lança se libs em falta."""
    global _keypair_cache
    if _keypair_cache is not None:
        return _keypair_cache
    if not CFG.wallet_private_key:
        raise RuntimeError("WALLET_PRIVATE_KEY não definida no .env")

    # import preguiçoso — só necessário em modo real
    from solders.keypair import Keypair  # type: ignore

    key = CFG.wallet_private_key.strip()
    try:
        # base58 (formato Phantom / bot anterior)
        _keypair_cache = Keypair.from_base58_string(key)
    except Exception as exc:
        raise RuntimeError(f"chave privada inválida: {type(exc).__name__}") from exc
    return _keypair_cache


def get_public_key() -> str | None:
    """Devolve o endereço público (seguro de mostrar) ou None se não der."""
    try:
        return str(_load_keypair().pubkey())
    except Exception:
        return None


def get_keypair():
    """Só chamado no caminho de execução REAL."""
    return _load_keypair()
