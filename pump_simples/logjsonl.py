"""
Log de decisões em formato JSONL (uma linha JSON por evento).

Regista TODAS as decisões — compra, rejeição e venda — para análise posterior.
Thread-safe. Nunca falha o loop principal por causa de um erro de escrita.
"""

import json
import threading
import time
from datetime import datetime, timezone

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(log_file: str, tipo: str, **campos) -> dict:
    """
    Escreve um evento no ficheiro JSONL e devolve o dict registado
    (para quem quiser reaproveitar, ex: mostrar no dashboard).
    """
    evento = {"ts": _now_iso(), "epoch": time.time(), "tipo": tipo}
    evento.update(campos)
    linha = json.dumps(evento, ensure_ascii=False)
    try:
        with _lock:
            with open(log_file, "a", encoding="utf-8") as fh:
                fh.write(linha + "\n")
    except Exception as exc:  # nunca derruba o loop por causa do log
        print(f"[log] falha a escrever log: {exc}")
    return evento
