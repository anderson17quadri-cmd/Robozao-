"""
Verifica se os tokens em carteira (posições abertas) são REAIS.

Confirma, para cada posição:
  1. O pool_address existe mesmo na GeckoTerminal (não é um endereço inventado
     ou corrompido) e o mint guardado bate certo com o mint do pool.
  2. (se SOLANA_RPC_URL estiver configurada) o mint existe on-chain de facto —
     mesma verificação getAccountInfo usada no check de segurança.
  3. Mostra o link do pump.fun para confirmares visualmente tu mesmo.

Isto NÃO confirma que a trade foi executada a sério (isso é o ponto 0 do
diagnostico.py — trades reais têm assinatura on-chain). Confirma que o TOKEN em
si é genuíno — não um mint fictício ou um pool que já não existe.

Uso:
    python verificar_tokens.py                 # posições abertas do state.json
    python verificar_tokens.py --historico 10  # também os últimos 10 do histórico
"""

import json
import sys
from pathlib import Path

import gecko

BASE = Path(__file__).resolve().parent


def _carregar_estado() -> dict:
    caminho = BASE / "state.json"
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _verificar_uma(pos: dict, rpc_disponivel: bool) -> None:
    mint = pos.get("mint", "")
    nome = pos.get("name", "?")
    pool_address = pos.get("pool_address", "")

    print(f"\n• {nome}  ({mint})")
    print(f"  pool_address: {pool_address}")

    r = gecko.verificar_pool(pool_address, mint)
    if r["existe"]:
        print(f"  ✅ GECKOTERMINAL: pool real — \"{r['name']}\", "
              f"liquidez ${r['liquidity_usd']:,.0f}, dex={r['dex']}")
        if r["mint_confere"] is False:
            print(f"     ⚠️  MINT NÃO BATE CERTO! guardado={mint} | no pool={r['mint_no_gecko']}")
        elif r["mint_confere"] is True:
            print("     ✅ mint confere com o do pool")
    elif r["confirmado"]:
        # confirmou ativamente que NÃO existe (não é falha de rede)
        print(f"  ❌ GECKOTERMINAL: {r['motivo']}")
        print("     -> pool não encontrado. Pode ter sido removido/migrado de dex,")
        print("        ou o endereço guardado estar errado. Confirma com o link abaixo.")
    else:
        # não deu para confirmar nem desmentir — NÃO é prova de nada
        print(f"  ⚠️  GECKOTERMINAL: {r['motivo']}")
        print("     -> INCONCLUSIVO (não prova que o token seja falso). Tenta mais")
        print("        tarde, ou confirma via RPC/link abaixo.")

    if rpc_disponivel:
        import solana_rpc
        seg = solana_rpc.check_mint_authorities(mint)
        if seg["confirmado"]:
            print(f"  ✅ RPC SOLANA: mint existe on-chain de facto "
                  f"(mint_authority={seg['mint_authority']}, freeze={seg['freeze_authority']})")
        else:
            print(f"  ⚠️  RPC SOLANA: não confirmou ({seg['motivo']}) — "
                  "pode ser falha de rede, não necessariamente o token ser falso")

    print(f"  🔗 confirma tu mesmo: https://pump.fun/coin/{mint}")


def main():
    incluir_historico = 0
    if "--historico" in sys.argv:
        try:
            incluir_historico = int(sys.argv[sys.argv.index("--historico") + 1])
        except (IndexError, ValueError):
            incluir_historico = 10

    estado = _carregar_estado()
    if not estado:
        print("Sem state.json — o bot ainda não guardou nenhuma posição.")
        return

    from config import CFG
    rpc_disponivel = bool(CFG.solana_rpc_url)

    posicoes = estado.get("posicoes", [])
    print("=" * 62)
    print(f" VERIFICAÇÃO DE TOKENS — são reais?")
    print(f"   posições abertas: {len(posicoes)}")
    print(f"   RPC Solana configurada: {'sim' if rpc_disponivel else 'não (só GeckoTerminal)'}")
    print("=" * 62)

    if not posicoes:
        print("\nSem posições abertas agora.")
    for pos in posicoes:
        _verificar_uma(pos, rpc_disponivel)

    if incluir_historico:
        hist = estado.get("historico", [])[:incluir_historico]
        print("\n" + "=" * 62)
        print(f" HISTÓRICO (últimos {len(hist)})")
        print("=" * 62)
        for h in hist:
            _verificar_uma(h, rpc_disponivel)

    print("\n" + "=" * 62)
    print(" Resumo:")
    print("   ✅ = token confirmado real e independente (GeckoTerminal/RPC).")
    print("   ⚠️  = INCONCLUSIVO (falha de rede/rate-limit) — NÃO prova nada,")
    print("        tenta correr de novo.")
    print("   ❌ = confirmado que o pool não existe/foi removido — investiga.")
    print(" Isto NÃO significa que a compra foi executada a sério — para isso,")
    print(" vê a secção 0 do diagnostico.py (assinatura on-chain = trade real).")
    print("=" * 62)


if __name__ == "__main__":
    main()
