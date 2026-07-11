"""
Lógica de trading do robozão — regras simples, sem enrolação.

ENTRADA (só 3 critérios, todos obrigatórios):
  1. Token é pump.fun (já vem filtrado do gecko.get_new_pump_pools)
  2. mint_authority e freeze_authority ambos None (fail-closed via RPC)
  3. Liquidez >= LIQUIDEZ_MINIMA_USD

SAÍDA (o que disparar primeiro vence):
  - Take-profit: +TAKE_PROFIT_PCT%
  - Stop-loss:   -STOP_LOSS_PCT%
  - Timeout:     TIMEOUT_MINUTOS sem sair de perto do zero

Sem IA, sem score, sem checklist. No máximo 1 chamada RPC por candidato.
"""

import time

import gecko
from config import CFG, SOL_MINT
from logjsonl import log_event
from solana_rpc import check_mint_authorities
from state import STATE


def avaliar_e_comprar(pool: dict) -> None:
    """Aplica as 3 regras de entrada a um pool candidato."""
    mint = pool.get("mint", "")
    nome = pool.get("name", "?")
    preco = pool.get("price_usd")
    liquidez = pool.get("liquidity_usd", 0.0) or 0.0

    # já temos posição neste token? não duplica
    if STATE.tem_posicao_para_mint(mint):
        return

    # limite de posições abertas em simultâneo
    if len(STATE.posicoes) >= CFG.max_posicoes_abertas:
        return

    # --- Regra 3: liquidez mínima (barata, verifica primeiro) ---
    if liquidez < CFG.liquidez_minima_usd:
        log_event(CFG.log_file, "rejeicao", mint=mint, name=nome,
                  motivo="liquidez_baixa", liquidez_usd=liquidez,
                  minimo=CFG.liquidez_minima_usd)
        return

    if not preco or preco <= 0:
        log_event(CFG.log_file, "rejeicao", mint=mint, name=nome,
                  motivo="sem_preco")
        return

    # --- Regra 2: autoridades revogadas (fail-closed) ---
    seg = check_mint_authorities(mint)
    if not seg["ok"]:
        log_event(CFG.log_file, "rejeicao", mint=mint, name=nome,
                  motivo="seguranca_autoridades", detalhe=seg["motivo"],
                  mint_authority=seg["mint_authority"],
                  freeze_authority=seg["freeze_authority"],
                  confirmado=seg["confirmado"])
        return

    # --- Passou tudo => COMPRA ---
    amount_usd = min(CFG.max_trade_usd, STATE.saldo_usd)
    if amount_usd <= 0:
        log_event(CFG.log_file, "rejeicao", mint=mint, name=nome,
                  motivo="saldo_insuficiente", saldo=STATE.saldo_usd)
        return

    _executar_compra(pool, amount_usd, preco, seg)


def _executar_compra(pool, amount_usd, preco, seg):
    mint = pool["mint"]
    nome = pool.get("name", "?")

    if CFG.envio_real_armado:
        # caminho REAL — converte USD -> lamports de SOL e faz o swap
        import jupiter
        sol_price = gecko.get_sol_price_usd()
        if not sol_price:
            log_event(CFG.log_file, "rejeicao", mint=mint, name=nome,
                      motivo="sem_preco_sol_para_conversao")
            return
        lamports = int((amount_usd / sol_price) * 1_000_000_000)
        res = jupiter.swap(SOL_MINT, mint, lamports)
        if not res["ok"]:
            log_event(CFG.log_file, "compra_falhou", mint=mint, name=nome,
                      motivo=res["motivo"], modo="REAL")
            return
        tokens = (res["out_amount"] or 0)  # unidades base; preço médio abaixo
        # estimativa de tokens em unidades "humanas" via preço de entrada
        tokens_humanos = amount_usd / preco if preco else 0.0
        pos = STATE.abrir_posicao(mint=mint, pool_address=pool["pool_address"],
                                  name=nome, entry_price=preco,
                                  amount_usd=amount_usd, tokens=tokens_humanos)
        log_event(CFG.log_file, "compra", modo="REAL", mint=mint, name=nome,
                  amount_usd=amount_usd, entry_price=preco,
                  signature=res["signature"], pos_id=pos["id"],
                  seguranca=seg["motivo"])
    else:
        # caminho SIMULADO (DRY_RUN)
        tokens = amount_usd / preco if preco else 0.0
        pos = STATE.abrir_posicao(mint=mint, pool_address=pool["pool_address"],
                                  name=nome, entry_price=preco,
                                  amount_usd=amount_usd, tokens=tokens)
        log_event(CFG.log_file, "compra", modo="DRY_RUN", mint=mint, name=nome,
                  amount_usd=amount_usd, entry_price=preco, pos_id=pos["id"],
                  seguranca=seg["motivo"])


def verificar_posicoes() -> None:
    """Aplica as regras de saída a cada posição aberta."""
    for pos in list(STATE.posicoes):
        preco = gecko.get_pool_price(pos["pool_address"])
        if preco is None or preco <= 0:
            # sem preço => não decide nada agora (não vende às cegas)
            continue

        STATE.atualizar_preco(pos["id"], preco)
        pl_pct = (preco / pos["entry_price"] - 1.0) * 100.0 if pos["entry_price"] else 0.0
        idade_min = (time.time() - pos["opened_at"]) / 60.0

        motivo = None
        if pl_pct >= CFG.take_profit_pct:
            motivo = "take_profit"
        elif pl_pct <= -CFG.stop_loss_pct:
            motivo = "stop_loss"
        elif idade_min >= CFG.timeout_minutos:
            motivo = "timeout"

        if motivo:
            _executar_venda(pos, preco, motivo)


def _executar_venda(pos, preco, motivo):
    if CFG.envio_real_armado:
        import jupiter
        # vende os tokens de volta para SOL
        tokens_base = int(pos["tokens"])  # aproximação; ver README
        res = jupiter.swap(pos["mint"], SOL_MINT, max(tokens_base, 1))
        if not res["ok"]:
            log_event(CFG.log_file, "venda_falhou", mint=pos["mint"],
                      name=pos["name"], motivo=res["motivo"], modo="REAL")
            return
        fechado = STATE.fechar_posicao(pos["id"], preco_saida=preco, motivo=motivo)
        log_event(CFG.log_file, "venda", modo="REAL", mint=pos["mint"],
                  name=pos["name"], motivo=motivo, exit_price=preco,
                  pl_usd=fechado["pl_usd"], pl_pct=fechado["pl_pct"],
                  signature=res["signature"], pos_id=pos["id"])
    else:
        fechado = STATE.fechar_posicao(pos["id"], preco_saida=preco, motivo=motivo)
        log_event(CFG.log_file, "venda", modo="DRY_RUN", mint=pos["mint"],
                  name=pos["name"], motivo=motivo, exit_price=preco,
                  pl_usd=fechado["pl_usd"], pl_pct=fechado["pl_pct"],
                  pos_id=pos["id"])
