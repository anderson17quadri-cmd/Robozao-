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
import solana_rpc
import watchlist
from config import CFG, SOL_MINT
from logjsonl import log_event
from solana_rpc import check_mint_authorities
from state import STATE

# supply padrão de um token pump.fun (1e9). Usado para estimar o market cap.
PUMP_SUPPLY_ESTIMADO = 1_000_000_000


def _penalidade_iliquidez(liquidez_usd) -> float:
    """
    Penalização extra por pool fino (só DRY_RUN). Em liquidez baixa, o preço
    cotado pela GeckoTerminal "salta" (wicks) e NÃO é realizável — na prática não
    consegues vender lá. Isto desconta esses ganhos fictícios, aproximando o P/L
    simulado do que o gráfico real mostraria.
    """
    try:
        liq = float(liquidez_usd or 0)
    except (TypeError, ValueError):
        liq = 0
    if liq < 2000:
        return 0.30
    if liq < 5000:
        return 0.22
    if liq < 10000:
        return 0.12
    if liq < 20000:
        return 0.06
    return 0.0


def _slippage_fracao(valor_usd: float, liquidez_usd) -> float:
    """
    Slippage estimado por lado (só DRY_RUN), em fração (0.03 = 3%).
    = base fixa (fees/spread) + impacto do tamanho + penalização por pool fino
    (preços não realizáveis em liquidez baixa).
    """
    base = CFG.slippage_simulado_pct / 100.0
    impacto = 0.0
    try:
        if liquidez_usd and liquidez_usd > 0:
            impacto = float(valor_usd) / float(liquidez_usd)
    except (TypeError, ValueError, ZeroDivisionError):
        impacto = 0.0
    return min(0.60, base + impacto + _penalidade_iliquidez(liquidez_usd))


def avaliar_e_comprar(pool: dict) -> None:
    """Aplica as regras de entrada a um pool candidato."""
    mint = pool.get("mint", "")
    nome = pool.get("name", "?")
    preco = pool.get("price_usd")
    liquidez = pool.get("liquidity_usd", 0.0) or 0.0

    # já temos posição neste token? não duplica
    if STATE.tem_posicao_para_mint(mint):
        return

    # já rugou antes (prejuízo grande ou colapso de liquidez)? bloqueado —
    # evita repetir a mesma perda na mesma moeda. Nunca deve nem ficar em vigia.
    bloqueio = STATE.mint_bloqueado(mint)
    if bloqueio["bloqueado"]:
        log_event(CFG.log_file, "rejeicao", mint=mint, name=nome,
                  motivo="mint_bloqueado", detalhe=bloqueio["motivo"])
        watchlist.remover(mint)
        return

    # limite de posições abertas (0 = SEM limite; fica limitado só pelo saldo)
    if CFG.max_posicoes_abertas > 0 and len(STATE.posicoes) >= CFG.max_posicoes_abertas:
        return

    # canal HYPE (opcional): token com tração real pode saltar o filtro de mcap.
    # NUNCA salta liquidez nem segurança. Desligado por default (toggle no dashboard).
    buyers = int(pool.get("buyers_h1") or 0)
    volume = float(pool.get("volume_h1") or 0.0)
    qualifica_hype = (
        STATE.hype_ativo
        and (buyers >= CFG.hype_min_compradores or volume >= CFG.hype_min_volume_usd)
    )
    canal = "hype" if qualifica_hype else "normal"

    # --- Regra 3: liquidez mínima (barata, verifica primeiro) --- (editável no dashboard)
    # a liquidez NUNCA é ignorada, nem no hype (pouca liquidez = preço fictício/rug).
    if liquidez < STATE.liquidez_minima_usd:
        log_event(CFG.log_file, "rejeicao", mint=mint, name=nome,
                  motivo="liquidez_baixa", liquidez_usd=liquidez,
                  minimo=STATE.liquidez_minima_usd)
        if STATE.vigia_ativo:
            watchlist.adicionar(pool)   # pode crescer — fica em vigia por um tempo
        return

    if not preco or preco <= 0:
        log_event(CFG.log_file, "rejeicao", mint=mint, name=nome,
                  motivo="sem_preco")
        return

    # --- Regra 4: market cap à entrada (pump.fun tem ~1e9 de supply => mcap ≈ preço * 1e9) ---
    marketcap = preco * PUMP_SUPPLY_ESTIMADO
    # 4a) MÍNIMO (0 = desligado; o hype salta este — moedas pequenas com tração)
    if (STATE.marketcap_minimo_usd > 0 and not qualifica_hype
            and marketcap < STATE.marketcap_minimo_usd):
        log_event(CFG.log_file, "rejeicao", mint=mint, name=nome,
                  motivo="marketcap_baixo", marketcap_usd=marketcap,
                  minimo=STATE.marketcap_minimo_usd, preco=preco)
        if STATE.vigia_ativo:
            watchlist.adicionar(pool)   # pode crescer — fica em vigia por um tempo
        return
    # 4b) TETO/MÁXIMO (0 = desligado; aplica-se SEMPRE, mesmo no hype). É o
    # padrão mais forte dos rugs: mcap alto = comprado perto do topo. NÃO vai
    # para a vigia (é caro demais, não "cresce para baixo").
    if STATE.marketcap_maximo_usd > 0 and marketcap > STATE.marketcap_maximo_usd:
        log_event(CFG.log_file, "rejeicao", mint=mint, name=nome,
                  motivo="marketcap_alto", marketcap_usd=marketcap,
                  maximo=STATE.marketcap_maximo_usd, preco=preco)
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
    # valor de entrada editável no dashboard (STATE.max_trade_usd), limitado ao saldo
    amount_usd = min(STATE.max_trade_usd, STATE.saldo_usd)
    if amount_usd <= 0:
        log_event(CFG.log_file, "rejeicao", mint=mint, name=nome,
                  motivo="saldo_insuficiente", saldo=STATE.saldo_usd)
        return

    origem = pool.get("origem", "scan")
    _executar_compra(pool, amount_usd, preco, seg, canal, origem)
    watchlist.remover(mint)   # comprado — sai da vigia (no-op se não estava lá)


def _executar_compra(pool, amount_usd, preco, seg, canal="normal", origem="scan"):
    mint = pool["mint"]
    nome = pool.get("name", "?")

    if CFG.envio_real_armado:
        # caminho REAL — converte USD -> lamports de SOL e faz o swap
        import jupiter
        from wallet import get_public_key
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

        # CONFIRMA na blockchain que a compra resultou mesmo em tokens. Uma
        # tx pode ser enviada (e devolver assinatura) mas FALHAR on-chain —
        # nesse caso a wallet fica com 0 tokens. Nunca abre uma posição
        # "fantasma" sem token real por trás.
        pubkey = get_public_key()
        info_saldo = solana_rpc.get_token_account_info(pubkey, mint) if pubkey else None

        if info_saldo is not None and info_saldo["amount_humano"] <= 0:
            # zero CONFIRMADO — o swap não resultou em tokens (tx falhou on-chain
            # apesar de submetida). NÃO abre posição, NÃO mexe no saldo.
            log_event(CFG.log_file, "compra_falhou", mint=mint, name=nome, modo="REAL",
                      motivo="swap enviado mas 0 tokens na wallet (tx provavelmente falhou)",
                      signature=res.get("signature"))
            return

        if info_saldo is not None:
            # tokens REAIS recebidos (decimais corretos). Preço médio real pago
            # => mantém a posição consistente: amount_usd == tokens*entry_price.
            tokens_humanos = info_saldo["amount_humano"]
            entry_price_real = amount_usd / tokens_humanos
        else:
            # saldo DESCONHECIDO (RPC falhou depois do swap). A tx pode ter
            # passado — abre com estimativa mas regista aviso para verificares.
            tokens_humanos = amount_usd / preco if preco else 0.0
            entry_price_real = preco
            log_event(CFG.log_file, "aviso", mint=mint, name=nome,
                      motivo="nao_confirmou_saldo_pos_compra_real",
                      detalhe="tokens estimados, não lidos da wallet",
                      signature=res.get("signature"))

        pos = STATE.abrir_posicao(mint=mint, pool_address=pool["pool_address"],
                                  name=nome, entry_price=entry_price_real,
                                  amount_usd=amount_usd, tokens=tokens_humanos,
                                  liquidez_usd=pool.get("liquidity_usd"),
                                  buyers_h1=pool.get("buyers_h1"),
                                  volume_h1=pool.get("volume_h1"),
                                  txns_h1=pool.get("txns_h1"), canal=canal)
        log_event(CFG.log_file, "compra", modo="REAL", mint=mint, name=nome,
                  amount_usd=amount_usd, entry_price=entry_price_real,
                  preco_cotado=preco, canal=canal, origem=origem,
                  liquidez_usd=pool.get("liquidity_usd"), dex=pool.get("dex"),
                  volume_h1=pool.get("volume_h1"), buyers_h1=pool.get("buyers_h1"),
                  txns_h1=pool.get("txns_h1"),
                  signature=res["signature"], pos_id=pos["id"],
                  seguranca=seg["motivo"])
    else:
        # caminho SIMULADO (DRY_RUN) — aplica slippage: enches mais caro que a cotação
        liquidez = pool.get("liquidity_usd")
        slip = _slippage_fracao(amount_usd, liquidez)
        entry_efetivo = preco * (1.0 + slip)
        tokens = amount_usd / entry_efetivo if entry_efetivo else 0.0
        pos = STATE.abrir_posicao(mint=mint, pool_address=pool["pool_address"],
                                  name=nome, entry_price=entry_efetivo,
                                  amount_usd=amount_usd, tokens=tokens,
                                  liquidez_usd=liquidez,
                                  buyers_h1=pool.get("buyers_h1"),
                                  volume_h1=pool.get("volume_h1"),
                                  txns_h1=pool.get("txns_h1"), canal=canal)
        log_event(CFG.log_file, "compra", modo="DRY_RUN", mint=mint, name=nome,
                  amount_usd=amount_usd, entry_price=entry_efetivo, preco_cotado=preco,
                  slippage_pct=round(slip * 100, 2), canal=canal, origem=origem,
                  liquidez_usd=liquidez, dex=pool.get("dex"),
                  volume_h1=pool.get("volume_h1"), buyers_h1=pool.get("buyers_h1"),
                  txns_h1=pool.get("txns_h1"),
                  pos_id=pos["id"], seguranca=seg["motivo"])


def verificar_posicoes() -> None:
    """Aplica as regras de saída a cada posição aberta."""
    for pos in list(STATE.posicoes):
        info = gecko.get_pool_info(pos["pool_address"], pos.get("mint", ""))
        preco = info.get("price_usd") if info else None
        if preco is None or preco <= 0:
            # sem preço => não decide nada agora (não vende às cegas)
            continue
        liquidez_atual = info.get("liquidity_usd") if info else None

        STATE.atualizar_preco(pos["id"], preco, liquidez_atual)  # também atualiza o pico
        pl_pct = (preco / pos["entry_price"] - 1.0) * 100.0 if pos["entry_price"] else 0.0
        idade_min = (time.time() - pos["opened_at"]) / 60.0

        # --- Proteção contra colapso de liquidez (prioridade máxima) ---
        # Se a liquidez sumiu desde a compra, o preço da AMM deixa de ser fiável
        # (pode não haver ninguém do outro lado). Vende já, ignora as outras regras.
        motivo = None
        liq_compra = pos.get("liquidez_usd")
        if (CFG.liquidez_queda_venda_pct > 0 and liquidez_atual is not None
                and liq_compra and liq_compra > 0):
            queda_pct = (1.0 - liquidez_atual / liq_compra) * 100.0
            if queda_pct >= CFG.liquidez_queda_venda_pct:
                motivo = "liquidez_colapsou"

        if motivo is None:
            # meta de lucro (take-profit): OPCIONAL. Usa a custom da posição se definida,
            # senão o global do .env. Se ambos forem 0, NÃO há meta para cima — o pico
            # corre livremente e só o trailing gere a subida.
            meta = pos.get("meta_lucro_pct")
            alvo_tp = meta if (meta is not None and meta > 0) else CFG.take_profit_pct

            # ganho do pico desde a entrada — usado tanto para escolher o trailing
            # (escalonado) como para a isenção do timeout.
            pico = pos.get("preco_pico") or pos["entry_price"]
            pico_pct = ((pico / pos["entry_price"] - 1.0) * 100.0) if pos["entry_price"] else 0.0

            # trailing ESCALONADO: mais apertado depois de um ganho grande no pico.
            # Dar 30% de um pico de +500% dói muito mais em valor absoluto do que
            # 30% de um pico de +20% — por isso aperta acima de TRAILING_APERTO_ACIMA_PCT.
            trailing_pct_ativo = (
                CFG.trailing_stop_apertado_pct
                if pico_pct >= CFG.trailing_aperto_acima_pct
                else CFG.trailing_stop_pct
            )
            gatilho_trailing = pico * (1.0 - trailing_pct_ativo / 100.0) if pico else 0.0

            # timeout só se aplica aos que NÃO se mexeram. Se o pico já passou o limiar
            # de isenção (ex: +50%), a posição vira "runner" e fica só com o trailing.
            timeout_ativo = (
                CFG.timeout_minutos and CFG.timeout_minutos > 0
                and pico_pct < CFG.timeout_isento_acima_pct
            )

            if alvo_tp and alvo_tp > 0 and pl_pct >= alvo_tp:
                motivo = "take_profit"
            elif gatilho_trailing and preco <= gatilho_trailing:
                motivo = "trailing_stop"
            elif timeout_ativo and idade_min >= CFG.timeout_minutos:
                motivo = "timeout"

        if motivo:
            extra = {}
            if motivo == "trailing_stop":
                extra = {"trailing_pct_usado": trailing_pct_ativo, "pico_pct": round(pico_pct, 1)}
            _executar_venda(pos, preco, motivo, **extra)


def vender_manual(pos_id: str) -> dict:
    """
    Venda manual imediata de 100% da posição, pelo MESMO caminho da venda
    automática (Jupiter em real, simulado em DRY_RUN). Devolve {ok, motivo}.
    """
    pos = STATE.get_posicao(pos_id)
    if pos is None:
        return {"ok": False, "motivo": "posição não encontrada"}

    preco = gecko.get_pool_price(pos["pool_address"], pos.get("mint", ""))
    if preco is None or preco <= 0:
        # sem preço fiável: em DRY_RUN caímos no preço de entrada para não falhar;
        # em real, sem preço não arriscamos — a swap decide pela cotação Jupiter.
        preco = pos.get("current_price") or pos.get("entry_price")
    if not preco or preco <= 0:
        return {"ok": False, "motivo": "sem preço para vender"}

    res = _executar_venda(pos, preco, "manual")
    if res and not res.get("ok"):
        return {"ok": False, "motivo": res.get("motivo", "a venda falhou")}
    return {"ok": True, "motivo": "venda manual executada"}


def revisar_lista_vigia() -> None:
    """
    Reavalia os candidatos na lista de vigia (rejeitados só por liquidez/mcap
    baixos) com dados FRESCOS de preço/liquidez/hype. Compra se entretanto
    cresceram o suficiente para passar os filtros. Resolve o caso de um token
    que ainda não tinha tração no minuto 1 (quando saiu do feed new_pools) mas
    já a tem no minuto 15 — sem isto, esse crescimento nunca seria visto.

    Verifica só CFG.vigia_max_por_ciclo por chamada (os há mais tempo sem
    verificar primeiro), para não disparar chamadas de rede a mais de uma vez.

    Se a vigia estiver desligada (STATE.vigia_ativo=False), não faz nada e
    esvazia o que houver — os dados mostraram que a vigia perdia dinheiro.
    """
    if not STATE.vigia_ativo:
        watchlist.limpar_tudo()
        return

    expirados = watchlist.limpar_expirados()
    if expirados:
        log_event(CFG.log_file, "vigia_expirado", quantidade=expirados)

    for pool in watchlist.candidatos_para_verificar(CFG.vigia_max_por_ciclo):
        mint = pool.get("mint")
        pool_address = pool.get("pool_address")
        if not mint or not pool_address:
            watchlist.remover(mint)
            continue
        if STATE.tem_posicao_para_mint(mint):
            watchlist.remover(mint)
            continue

        info = gecko.get_pool_info(pool_address, mint)
        if not info:
            continue   # falha de rede — tenta de novo no próximo ciclo

        pool_fresco = {
            **pool,
            "price_usd": info["price_usd"],
            "liquidity_usd": info["liquidity_usd"],
            "dex": info.get("dex") or pool.get("dex"),
            "volume_h1": info.get("volume_h1"),
            "buyers_h1": info.get("buyers_h1"),
            "txns_h1": info.get("txns_h1"),
            "origem": "vigia",
        }
        watchlist.atualizar(mint, pool_fresco)
        avaliar_e_comprar(pool_fresco)   # compra e remove da vigia se qualificar agora


def acompanhar_vendidos() -> None:
    """
    Acompanhamento pós-venda: reavalia o preço dos últimos N tokens JÁ VENDIDOS,
    só para ver como evoluíram. NÃO compra, NÃO vende, NÃO mexe no saldo.
    Reaproveita o mesmo gecko.get_pool_price das posições abertas.
    """
    for trade in STATE.trades_para_acompanhar(CFG.acompanhar_vendidos_max):
        preco = gecko.get_pool_price(trade.get("pool_address", ""), trade.get("mint", ""))
        if preco is None or preco <= 0:
            continue
        STATE.atualizar_preco_vendido(trade["id"], preco)


def _executar_venda(pos, preco, motivo, **extra_log):
    if CFG.envio_real_armado:
        import jupiter
        from wallet import get_public_key

        # NUNCA vende uma quantidade "adivinhada" a partir do estado local —
        # pergunta à wallet quanto REALMENTE tem deste mint agora (unidades
        # base + decimais corretos) e vende exatamente isso. Isto corrige um
        # bug sério: a venda usava pos["tokens"] (unidades "humanas", vindas
        # da compra) como se já fossem unidades base, o que enviava à Jupiter
        # uma quantidade errada por um fator de 10^decimais — a venda falhava
        # ou vendia uma fração ínfima, deixando a posição real presa.
        pubkey = get_public_key()
        saldo = solana_rpc.get_token_account_info(pubkey, pos["mint"]) if pubkey else None
        if not saldo or saldo["amount_base"] <= 0:
            m = ("sem saldo deste token na wallet — provavelmente já foi vendido, "
                 "ou o RPC não devolve as contas de tokens (a posição fica aberta)")
            log_event(CFG.log_file, "venda_falhou", mint=pos["mint"],
                      name=pos["name"], modo="REAL", motivo=m)
            return {"ok": False, "motivo": m}

        res = jupiter.swap(pos["mint"], SOL_MINT, saldo["amount_base"])
        if not res["ok"]:
            log_event(CFG.log_file, "venda_falhou", mint=pos["mint"],
                      name=pos["name"], motivo=res["motivo"], modo="REAL")
            return {"ok": False, "motivo": res["motivo"]}
        fechado = STATE.fechar_posicao(pos["id"], preco_saida=preco, motivo=motivo)
        log_event(CFG.log_file, "venda", modo="REAL", mint=pos["mint"],
                  name=pos["name"], motivo=motivo, exit_price=preco,
                  pl_usd=fechado["pl_usd"], pl_pct=fechado["pl_pct"],
                  signature=res["signature"], pos_id=pos["id"], **extra_log)
        return {"ok": True, "motivo": "ok"}
    else:
        # DRY_RUN — aplica slippage: enches a venda mais barato que a cotação.
        # Usa a liquidez ATUAL (não a da compra) — se colapsou entretanto, o
        # slippage simulado tem de refletir isso (senão fica otimista demais).
        valor_bruto = (pos.get("tokens") or 0.0) * preco   # tamanho da venda em USD
        liquidez_para_slippage = pos.get("liquidez_atual")
        if liquidez_para_slippage is None:
            liquidez_para_slippage = pos.get("liquidez_usd")
        slip = _slippage_fracao(valor_bruto, liquidez_para_slippage)
        exit_efetivo = preco * (1.0 - slip)
        fechado = STATE.fechar_posicao(pos["id"], preco_saida=exit_efetivo, motivo=motivo)
        log_event(CFG.log_file, "venda", modo="DRY_RUN", mint=pos["mint"],
                  name=pos["name"], motivo=motivo, exit_price=exit_efetivo,
                  preco_cotado=preco, slippage_pct=round(slip * 100, 2),
                  pl_usd=fechado["pl_usd"], pl_pct=fechado["pl_pct"],
                  pos_id=pos["id"], **extra_log)
        return {"ok": True, "motivo": "ok"}
