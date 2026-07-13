"""
Venda manual de EMERGÊNCIA — vende tokens da tua wallet de volta para SOL,
SEM depender do bot nem do dashboard. Para quando ficaste com um token comprado
em modo real e não consegues vender pela interface.

Usa a MESMA wallet do .env (WALLET_PRIVATE_KEY) e a Jupiter para o swap. Envia
transações REAIS on-chain — corre isto só quando quiseres mesmo vender.

Uso:
    python vender_token.py                 # LISTA os tokens que tens na wallet
    python vender_token.py <MINT>          # vende 100% desse token -> SOL
    python vender_token.py all             # vende TODOS os tokens -> SOL

Slippage alto de propósito (para SAIR mesmo de tokens de baixa liquidez).
"""

import sys

from config import CFG, SOL_MINT
import solana_rpc
import jupiter
from wallet import get_public_key

# tolerância de slippage MUITO alta para GARANTIR a saída (mesmo perdendo no
# preço) — é uma venda de emergência, o objetivo é sair, não otimizar. Tokens
# finos mexem-se depressa; com pouca tolerância a tx é rejeitada on-chain.
SLIPPAGE_SAIDA_BPS = 5000  # 50%


def _tabela(tokens):
    if not tokens:
        print("   (nenhum token com saldo > 0 nesta wallet)")
        return
    for t in tokens:
        print(f"   • {t['mint']}")
        print(f"       {t['amount_humano']}  (base: {t['amount_base']}, decimais: {t['decimals']})")


def listar(pub):
    print(f"\nTokens na wallet {pub}:")
    _tabela(solana_rpc.listar_tokens(pub))
    sol = solana_rpc.get_sol_balance(pub)
    print(f"\nSOL: {sol}")
    print("\nPara vender um: python vender_token.py <MINT>")
    print("Para vender todos: python vender_token.py all")


def vender_um(mint: str, pub: str) -> bool:
    info = solana_rpc.get_token_account_info(pub, mint)
    if not info or info["amount_base"] <= 0:
        print(f"   ⚠️  {mint[:8]}… — 0 tokens na wallet (nada para vender)")
        return False
    print(f"   a vender {info['amount_humano']} de {mint[:8]}… ({info['amount_base']} base)…")
    res = jupiter.swap(mint, SOL_MINT, info["amount_base"])
    if res["ok"]:
        print(f"   ✅ VENDIDO! assinatura: {res['signature']}")
        print(f"      confirma em: https://solscan.io/tx/{res['signature']}")
        return True
    print(f"   ❌ não deu: {res['motivo']}")
    if "cotação" in (res["motivo"] or ""):
        print("      (a Jupiter não achou rota — o token pode ter liquidez ~zero/rugou)")
    return False


def main():
    # slippage alto só neste script (não afeta o bot)
    CFG.slippage_bps = SLIPPAGE_SAIDA_BPS

    pub = get_public_key()
    print("=" * 60)
    print(" VENDA DE EMERGÊNCIA (tokens -> SOL, via Jupiter)")
    print("=" * 60)
    if not pub:
        print("\n❌ wallet não configurada. Confirma WALLET_PRIVATE_KEY no .env")
        print("   e que o base58 está instalado (pip install base58).")
        return
    print(f" wallet: {pub}")
    print(f" RPC...: {CFG.solana_rpc_url[:45]}…")

    arg = sys.argv[1] if len(sys.argv) > 1 else ""

    if not arg:
        listar(pub)
        return

    if arg.lower() == "all":
        tokens = solana_rpc.listar_tokens(pub)
        if not tokens:
            print("\n   (nada para vender)")
            return
        print(f"\n a vender TODOS os {len(tokens)} tokens -> SOL:\n")
        vendidos = sum(1 for t in tokens if vender_um(t["mint"], pub))
        print(f"\n {vendidos}/{len(tokens)} vendidos.")
        return

    # vender um mint específico
    print()
    vender_um(arg, pub)


if __name__ == "__main__":
    main()
