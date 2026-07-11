"""
Loop principal do robozão.

- Procura tokens novos pump.fun (a cada INTERVALO_SCAN_SEGUNDOS)
- Avalia entrada com as 3 regras
- Monitoriza posições abertas (a cada INTERVALO_VERIFICACAO_SEGUNDOS)

Controlável por uma thread (start/stop) — usado pelo dashboard.
Toda chamada de rede já está em try/except nos módulos; aqui há uma rede
de segurança extra para o loop nunca morrer.
"""

import threading
import time

import trader
from config import CFG
from logjsonl import log_event
from state import STATE
from wallet import get_public_key, wallet_status


class BotController:
    """Arranca/pára o loop do bot numa thread de fundo."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.is_running():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        if not self.is_running():
            return False
        self._stop.set()
        STATE.bot_running = False
        STATE.ultima_msg = "a parar..."
        return True

    def _run(self):
        modo = "REAL ⚠️" if CFG.envio_real_armado else "DRY_RUN (simulado)"
        STATE.bot_running = True
        STATE.ultima_msg = f"a correr — {modo}"
        log_event(CFG.log_file, "bot_start", modo=modo,
                  wallet=wallet_status(), pubkey=get_public_key(),
                  dry_run=CFG.dry_run, envio_real=CFG.envio_real_armado)

        ultimo_scan = 0.0
        while not self._stop.is_set():
            agora = time.time()
            try:
                # 1) monitoriza posições abertas (mais frequente)
                trader.verificar_posicoes()

                # 2) procura tokens novos (menos frequente)
                if agora - ultimo_scan >= CFG.intervalo_scan_segundos:
                    ultimo_scan = agora
                    STATE.ultimo_scan = agora
                    import gecko
                    pools = gecko.get_new_pump_pools()
                    STATE.ultima_msg = (
                        f"{modo} — {len(pools)} pools novos, "
                        f"{len(STATE.posicoes)} posições abertas"
                    )
                    for pool in pools:
                        if self._stop.is_set():
                            break
                        trader.avaliar_e_comprar(pool)
            except Exception as exc:
                # rede de segurança final — o loop NUNCA morre
                log_event(CFG.log_file, "erro_loop", erro=str(exc),
                          tipo_erro=type(exc).__name__)
                STATE.ultima_msg = f"{modo} — erro tratado: {exc}"

            # dorme em pequenos passos para responder rápido ao stop
            self._stop.wait(CFG.intervalo_verificacao_segundos)

        STATE.bot_running = False
        STATE.ultima_msg = "parado"
        log_event(CFG.log_file, "bot_stop")


# controlador único partilhado com o dashboard
CONTROLLER = BotController()


def _run_headless():
    """Corre o bot sem dashboard (Ctrl+C para parar)."""
    print("=" * 60)
    print(" robozão — bot pump.fun (headless)")
    print(f"  modo........: {'DRY_RUN (simulado)' if not CFG.envio_real_armado else 'REAL ⚠️'}")
    print(f"  wallet......: {wallet_status()}  ({get_public_key() or 'sem pubkey'})")
    print(f"  saldo.......: ${STATE.saldo_usd:.2f}")
    print(f"  take/stop...: +{CFG.take_profit_pct:.0f}% / -{CFG.stop_loss_pct:.0f}%")
    print(f"  timeout.....: {CFG.timeout_minutos:.0f} min")
    print(f"  liquidez min: ${CFG.liquidez_minima_usd:.0f}")
    print("=" * 60)
    CONTROLLER.start()
    try:
        while CONTROLLER.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\na parar...")
        CONTROLLER.stop()
        time.sleep(1)


if __name__ == "__main__":
    _run_headless()
