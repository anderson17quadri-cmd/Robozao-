"""
Checklist de prontidão para o MODO REAL — corre isto ANTES de mudar DRY_RUN=false.

Só VERIFICA se as peças estão a funcionar (wallet, RPC, Jupiter). NÃO ativa
nada sozinho — continuas a ser tu quem escreve DRY_RUN=false e
PERMITIR_ENVIO_REAL=true no .env, deliberadamente, quando estiveres pronto.

Uso:
    python verificar_pronto_real.py
"""

import requests

import gecko
from config import CFG, SOL_MINT
from wallet import get_public_key, wallet_status

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _titulo(n, texto):
    print(f"\n{n}) {texto}")


def main():
    print("=" * 62)
    print(" CHECKLIST — pronto para o MODO REAL?")
    print(" (isto só verifica — não ativa nada sozinho)")
    print("=" * 62)
    tudo_ok = True

    # 1) Wallet
    _titulo(1, "Wallet")
    pk = get_public_key()
    if pk:
        print(f"   ✅ chave privada válida — endereço: {pk}")
    else:
        tudo_ok = False
        print(f"   ❌ wallet: {wallet_status()} — não consegui obter o endereço público.")
        print("      Verifica WALLET_PRIVATE_KEY no .env e se o 'solders' está instalado:")
        print("      pkg install rust binutils   (Termux, demora)")
        print("      pip install solders")

    # 2) RPC Solana
    _titulo(2, "RPC Solana")
    if not CFG.solana_rpc_url:
        tudo_ok = False
        print("   ❌ SOLANA_RPC_URL não configurada no .env.")
    else:
        try:
            r = requests.post(
                CFG.solana_rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": "getHealth"},
                timeout=10,
            )
            if r.status_code == 200 and r.json().get("result") == "ok":
                print(f"   ✅ RPC responde: {CFG.solana_rpc_url[:45]}...")
            else:
                tudo_ok = False
                print(f"   ⚠️  RPC respondeu de forma inesperada (HTTP {r.status_code}) "
                      "— confirma manualmente antes de avançar.")
        except Exception as exc:
            tudo_ok = False
            print(f"   ❌ RPC não respondeu: {exc}")

    # 3) Jupiter (cotação de teste — não assina nem envia nada)
    _titulo(3, "Jupiter (execução de swaps)")
    try:
        import jupiter
        quote = jupiter.get_quote(SOL_MINT, USDC_MINT, 1_000_000)  # 0.001 SOL, só teste
        if quote and quote.get("outAmount"):
            print(f"   ✅ Jupiter responde (cotação de teste OK: "
                  f"{quote.get('outAmount')} unidades USDC por 0.001 SOL)")
        else:
            tudo_ok = False
            print("   ⚠️  Jupiter não devolveu uma cotação válida — tenta de novo mais tarde.")
    except Exception as exc:
        tudo_ok = False
        print(f"   ❌ falha ao testar a Jupiter: {exc}")

    # 4) Preço SOL (usado para converter USD -> lamports nas compras reais)
    _titulo(4, "Preço do SOL (conversão USD -> SOL)")
    sol_price = gecko.get_sol_price_usd()
    if sol_price:
        print(f"   ✅ preço do SOL disponível: ${sol_price:.2f}")
    else:
        tudo_ok = False
        print("   ⚠️  não consegui obter o preço do SOL agora — tenta de novo.")

    # 5) Config atual (resumo do que o modo real vai usar)
    _titulo(5, "Configuração atual")
    print(f"   DRY_RUN................: {CFG.dry_run}")
    print(f"   PERMITIR_ENVIO_REAL....: {CFG.permitir_envio_real}")
    print(f"   envio_real_armado (já?): {CFG.envio_real_armado}")
    print(f"   MAX_TRADE_USD..........: ${CFG.max_trade_usd:.2f}  (mantém baixo para começar)")
    print(f"   LIQUIDEZ_MINIMA_USD....: ${CFG.liquidez_minima_usd:,.0f}")
    print(f"   MARKETCAP_MINIMO_USD...: ${CFG.marketcap_minimo_usd:,.0f}")
    print(f"   SLIPPAGE_BPS (real)....: {CFG.slippage_bps} ({CFG.slippage_bps/100:.1f}%)")

    # veredicto
    print("\n" + "=" * 62)
    if tudo_ok:
        print(" ✅ TECNICAMENTE PRONTO. Quando decidires avançar, tu mesmo mudas")
        print("    no .env (com calma, deliberadamente):")
        print("        DRY_RUN=false")
        print("        PERMITIR_ENVIO_REAL=true")
        print("    Reinicia o bot depois de editar. O dashboard ainda vai pedir")
        print("    confirmação extra antes de ligar em modo real.")
    else:
        print(" ❌ AINDA FALTA RESOLVER O(S) PONTO(S) MARCADO(S) ACIMA.")
        print("    Corrige e corre este script outra vez antes de avançar.")
    print("\n ⚠️  Lembretes de segurança (não técnicos, mas importantes):")
    print("    - Usa uma wallet cuja chave NUNCA tenha sido partilhada/colada")
    print("      nalgum chat, print ou ficheiro fora do teu controlo.")
    print("    - Não corras dois bots em modo real ao mesmo tempo na mesma wallet.")
    print("    - Começa com MAX_TRADE_USD baixo — a estratégia ainda está em teste.")
    print("=" * 62)


if __name__ == "__main__":
    main()
