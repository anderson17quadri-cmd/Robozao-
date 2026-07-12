"""
Carteira Solana.

- Lê a WALLET_PRIVATE_KEY (base58) do .env — a MESMA wallet do bot anterior.
- A chave privada NUNCA é impressa, logada ou devolvida em texto.
- Assinatura via PyNaCl (ed25519), NÃO via solders — de propósito: o solders
  precisa de compilar Rust/PyO3, o que falha facilmente no Termux (sobretudo
  em Python muito recente, onde o PyO3 ainda não tem suporte). O PyNaCl é
  puro C leve, instala em segundos em qualquer telemóvel.
- Imports de assinatura são preguiçosos: o modo DRY_RUN funciona sem
  `pynacl`/`base58` instalados.
"""

from config import CFG

_signing_key_cache = None  # nunca serializado, nunca logado

# tamanho da seed ed25519 dentro da chave secreta Solana de 64 bytes
# (formato Phantom/solana-keygen: [seed(32)][pubkey(32)], tudo em base58)
_SEED_BYTES = 32


def wallet_status() -> str:
    """Estado redigido — nunca revela a chave."""
    return "configurada" if CFG.wallet_private_key else "NÃO configurada"


def _load_signing_key():
    """Carrega a SigningKey (PyNaCl) a partir da chave base58. Lança se libs em falta."""
    global _signing_key_cache
    if _signing_key_cache is not None:
        return _signing_key_cache
    if not CFG.wallet_private_key:
        raise RuntimeError("WALLET_PRIVATE_KEY não definida no .env")

    # imports preguiçosos — só necessários em modo real
    import base58
    from nacl.signing import SigningKey

    key = CFG.wallet_private_key.strip()
    try:
        raw = base58.b58decode(key)
        seed = raw[:_SEED_BYTES]
        if len(seed) != _SEED_BYTES:
            raise ValueError("chave demasiado curta para conter uma seed ed25519")
        _signing_key_cache = SigningKey(seed)
    except Exception as exc:
        raise RuntimeError(f"chave privada inválida: {type(exc).__name__}") from exc
    return _signing_key_cache


def get_public_key() -> str | None:
    """Devolve o endereço público (seguro de mostrar) ou None se não der."""
    try:
        import base58
        sk = _load_signing_key()
        return base58.b58encode(bytes(sk.verify_key)).decode("ascii")
    except Exception:
        return None


def get_signing_key():
    """Só chamado no caminho de execução REAL."""
    return _load_signing_key()
