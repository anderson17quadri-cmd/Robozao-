"""
Rate limiter simples (token bucket) para não estourar limites de RPC.

Foi exatamente o problema do bot anterior — aqui limitamos a N pedidos/segundo
de forma centralizada. Thread-safe.
"""

import threading
import time


class RateLimiter:
    def __init__(self, rate_por_segundo: float):
        self.rate = max(0.1, float(rate_por_segundo))
        self.intervalo_min = 1.0 / self.rate
        self._lock = threading.Lock()
        self._proximo_permitido = 0.0

    def acquire(self) -> None:
        """Bloqueia até ser seguro fazer o próximo pedido."""
        with self._lock:
            agora = time.monotonic()
            espera = self._proximo_permitido - agora
            if espera > 0:
                time.sleep(espera)
                agora = time.monotonic()
            self._proximo_permitido = max(agora, self._proximo_permitido) + self.intervalo_min
