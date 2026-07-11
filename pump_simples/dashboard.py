"""
Dashboard web do robozão (Flask).

- Estética inspirada no pump.fun: tema escuro, cards, verde/vermelho vivos.
- Mostra saldo, posições abertas (P/L em tempo real), histórico e um toggle
  para ligar/desligar o bot.
- Em modo REAL exige confirmação explícita antes de arrancar o bot.

Corre o bot na MESMA processo, numa thread de fundo (BotController).
"""

from pathlib import Path

from flask import Flask, jsonify, render_template, request

from bot import CONTROLLER
from config import CFG
from state import STATE
from wallet import get_public_key, wallet_status

BASE = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(BASE / "web" / "templates"),
    static_folder=str(BASE / "web" / "static"),
)


def _modo_info() -> dict:
    return {
        "dry_run": CFG.dry_run,
        "envio_real_armado": CFG.envio_real_armado,
        "modo_label": "REAL" if CFG.envio_real_armado else "DRY_RUN",
        "fonte_deteccao": CFG.fonte_deteccao,
        "moeda_simbolo": CFG.moeda_simbolo,
        "saldo_inicial": CFG.saldo_virtual_inicial,
        "max_posicoes": CFG.max_posicoes_abertas,
        "wallet": wallet_status(),
        "pubkey": get_public_key(),
        "take_profit_pct": CFG.take_profit_pct,
        "trailing_stop_pct": CFG.trailing_stop_pct,
        "stop_loss_pct": CFG.stop_loss_pct,
        "timeout_minutos": CFG.timeout_minutos,
        "timeout_isento_acima_pct": CFG.timeout_isento_acima_pct,
        "liquidez_minima_usd": CFG.liquidez_minima_usd,
        "marketcap_minimo_usd": CFG.marketcap_minimo_usd,
        "max_trade_usd": CFG.max_trade_usd,
        "slippage_simulado_pct": (0 if CFG.envio_real_armado else CFG.slippage_simulado_pct),
        "intervalo_verificacao": CFG.intervalo_verificacao_segundos,
        "hype_min_compradores": CFG.hype_min_compradores,
        "hype_min_volume_usd": CFG.hype_min_volume_usd,
    }


@app.route("/")
def index():
    return render_template("index.html", modo=_modo_info())


@app.route("/api/state")
def api_state():
    snap = STATE.snapshot()
    snap["bot_running"] = CONTROLLER.is_running()
    snap["modo"] = _modo_info()
    return jsonify(snap)


@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    body = request.get_json(silent=True) or {}
    acao = body.get("acao", "toggle")
    confirmado = bool(body.get("confirmar_real", False))

    quer_ligar = acao == "start" or (acao == "toggle" and not CONTROLLER.is_running())

    if quer_ligar:
        # trava de segurança: modo REAL precisa de confirmação explícita
        if CFG.envio_real_armado and not confirmado:
            return jsonify({
                "ok": False,
                "precisa_confirmacao": True,
                "aviso": "MODO REAL ARMADO — vais gastar SOL da wallet a sério. "
                         "Confirma para continuar.",
            }), 409
        ok = CONTROLLER.start()
        return jsonify({"ok": ok, "bot_running": CONTROLLER.is_running()})
    else:
        CONTROLLER.stop()
        return jsonify({"ok": True, "bot_running": CONTROLLER.is_running()})


@app.route("/api/posicao/<pos_id>/vender", methods=["POST"])
def api_vender(pos_id):
    """Venda manual imediata (100%) de uma posição — mesmo caminho da venda auto."""
    body = request.get_json(silent=True) or {}
    confirmado = bool(body.get("confirmar_real", False))

    # trava de segurança: em modo REAL exige confirmação explícita
    if CFG.envio_real_armado and not confirmado:
        return jsonify({
            "ok": False,
            "precisa_confirmacao": True,
            "aviso": "MODO REAL — esta venda envia uma transação a sério. Confirma.",
        }), 409

    import trader
    res = trader.vender_manual(pos_id)
    status = 200 if res["ok"] else 400
    return jsonify(res), status


@app.route("/api/config", methods=["POST"])
def api_config():
    """Ajusta parâmetros editáveis em runtime (persistem): valor de entrada,
    liquidez mínima e market cap mínimo."""
    body = request.get_json(silent=True) or {}
    campos = {
        "max_trade_usd": STATE.set_max_trade,
        "liquidez_minima_usd": STATE.set_liquidez_minima,
        "marketcap_minimo_usd": STATE.set_marketcap_minimo,
    }
    atualizados = {}
    for campo, setter in campos.items():
        if campo in body:
            if not setter(body.get(campo)):
                return jsonify({"ok": False, "motivo": f"valor inválido para {campo}"}), 400
            atualizados[campo] = getattr(STATE, campo)
    if not atualizados:
        return jsonify({"ok": False, "motivo": "nada para atualizar"}), 400
    return jsonify({"ok": True, **atualizados})


@app.route("/api/hype", methods=["POST"])
def api_hype():
    """Liga/desliga o canal de entrada por hype (persiste)."""
    body = request.get_json(silent=True) or {}
    if "ativo" in body:
        STATE.set_hype_ativo(bool(body.get("ativo")))
    else:
        STATE.set_hype_ativo(not STATE.hype_ativo)   # toggle
    return jsonify({"ok": True, "hype_ativo": STATE.hype_ativo})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Reinicia a simulação (saldo inicial, sem posições/histórico). Só DRY_RUN."""
    if CFG.envio_real_armado:
        return jsonify({"ok": False, "motivo": "reset indisponível em MODO REAL"}), 400
    if CONTROLLER.is_running():
        return jsonify({"ok": False, "motivo": "para o bot antes de reiniciar"}), 409
    STATE.reset()
    return jsonify({"ok": True, "saldo_usd": STATE.saldo_usd})


@app.route("/api/posicao/<pos_id>/meta", methods=["POST"])
def api_meta(pos_id):
    """Define/limpa a meta de lucro custom (%) de uma posição aberta."""
    body = request.get_json(silent=True) or {}
    valor = body.get("meta_lucro_pct", None)

    meta = None
    if valor not in (None, "", "null"):
        try:
            meta = float(valor)
            if meta <= 0:
                meta = None  # <=0 => limpa (volta ao global)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "motivo": "valor inválido"}), 400

    ok = STATE.set_meta_lucro(pos_id, meta)
    return jsonify({"ok": ok, "meta_lucro_pct": meta}), (200 if ok else 404)


def main():
    modo = "REAL ⚠️" if CFG.envio_real_armado else "DRY_RUN (simulado)"
    print("=" * 60)
    print(" robozão — dashboard pump.fun")
    print(f"  modo...: {modo}")
    print(f"  wallet.: {wallet_status()}")
    print(f"  http://{CFG.dashboard_host}:{CFG.dashboard_port}")
    print("=" * 60)
    # use_reloader=False: senão o Flask arranca 2 processos e duplica o bot
    app.run(host=CFG.dashboard_host, port=CFG.dashboard_port,
            debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
