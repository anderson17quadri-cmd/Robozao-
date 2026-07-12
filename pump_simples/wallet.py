"""
Carteira Solana.

- Lê a WALLET_PRIVATE_KEY (base58) do .env — a MESMA wallet do bot anterior.
- A chave privada NUNCA é impressa, logada ou devolvida em texto.
- Assinatura via `ed25519_pure` (Python puro, stdlib only) — NÃO via solders
  nem pynacl, de propósito: ambos precisam de compilar código nativo
  (Rust/PyO3 e C/libsodium respetivamente), o que falhou repetidamente no
  Termux do utilizador (Python 3.14 sem suporte PyO3; depois libsodium
  bundled incompatível com o Clang/NDK do Android). Python puro nunca
  precisa de compilar nada — funciona em qualquer telemóvel, sempre.
- O import de `base58` é preguiçoso: o modo DRY_RUN funciona sem ele instalado.
"""

from config import CFG
import ed25519_pure

_signing_key_cache = None  # nunca serializado, nunca logado

# tamanho da seed ed25519 dentro da chave secreta Solana de 64 bytes
# (formato Phantom/solana-keygen: [seed(32)][pubkey(32)], tudo em base58)
_SEED_BYTES = 32


class _SigningKey:
    """Par de chaves ed25519 (seed + pública), assinatura via ed25519_pure."""

    def __init__(self, seed: bytes):
        self.seed = seed
        self.public_bytes = ed25519_pure.publickey(seed)

    def sign(self, mensagem: bytes) -> bytes:
        return ed25519_pure.signature(mensagem, self.seed, self.public_bytes)


def wallet_status() -> str:
    """Estado redigido — nunca revela a chave."""
    return "configurada" if CFG.wallet_private_key else "NÃO configurada"


def _load_signing_key() -> _SigningKey:
    """Carrega o par de chaves a partir da chave base58. Lança se inválida."""
    global _signing_key_cache
    if _signing_key_cache is not None:
        return _signing_key_cache
    if not CFG.wallet_private_key:
        raise RuntimeError("WALLET_PRIVATE_KEY não definida no .env")

    import base58  # preguiçoso — só necessário em modo real

    key = CFG.wallet_private_key.strip()
    try:
        raw = base58.b58decode(key)
        seed = raw[:_SEED_BYTES]
        if len(seed) != _SEED_BYTES:
            raise ValueError("chave demasiado curta para conter uma seed ed25519")
        _signing_key_cache = _SigningKey(seed)
    except Exception as exc:
        raise RuntimeError(f"chave privada inválida: {type(exc).__name__}") from exc
    return _signing_key_cache


def get_public_key() -> str | None:
    """Devolve o endereço público (seguro de mostrar) ou None se não der."""
    try:
        import base58
        sk = _load_signing_key()
        return base58.b58encode(sk.public_bytes).decode("ascii")
    except Exception:
        return None


def get_signing_key() -> _SigningKey:
    """Só chamado no caminho de execução REAL."""
    return _load_signing_key()
