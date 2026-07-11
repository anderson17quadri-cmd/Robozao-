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
        "wallet": wallet_status(),
        "pubkey": get_public_key(),
        "take_profit_pct": CFG.take_profit_pct,
        "stop_loss_pct": CFG.stop_loss_pct,
        "timeout_minutos": CFG.timeout_minutos,
        "liquidez_minima_usd": CFG.liquidez_minima_usd,
        "max_trade_usd": CFG.max_trade_usd,
        "intervalo_verificacao": CFG.intervalo_verificacao_segundos,
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
