"""
Estado partilhado da app (saldo, posições abertas, histórico, flag do bot).

Thread-safe (o bot corre numa thread, o dashboard noutra). Persistido em JSON
para sobreviver a reinícios. A chave privada NUNCA entra aqui.
"""

import json
import threading
import time
import uuid

from config import CFG


class AppState:
    def __init__(self):
        self._lock = threading.RLock()
        self.saldo_usd: float = CFG.saldo_virtual_inicial
        self.posicoes: list[dict] = []      # posições abertas
        self.historico: list[dict] = []     # trades fechados
        self.bot_running: bool = False
        self.ultimo_scan: float = 0.0
        self.ultima_msg: str = "parado"
        self._load()

    # ---------- persistência ----------
    def _load(self):
        try:
            with open(CFG.state_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.saldo_usd = data.get("saldo_usd", self.saldo_usd)
            self.posicoes = data.get("posicoes", [])
            self.historico = data.get("historico", [])
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"[state] falha a carregar estado: {exc}")

    def _save_locked(self):
        try:
            data = {
                "saldo_usd": self.saldo_usd,
                "posicoes": self.posicoes,
                "historico": self.historico,
                "atualizado_em": time.time(),
            }
            tmp = CFG.state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            import os
            os.replace(tmp, CFG.state_file)
        except Exception as exc:
            print(f"[state] falha a guardar estado: {exc}")

    # ---------- operações ----------
    def abrir_posicao(self, *, mint, pool_address, name, entry_price,
                      amount_usd, tokens) -> dict:
        with self._lock:
            pos = {
                "id": uuid.uuid4().hex[:8],
                "mint": mint,
                "pool_address": pool_address,
                "name": name,
                "entry_price": entry_price,
                "current_price": entry_price,
                "amount_usd": amount_usd,
                "tokens": tokens,
                "opened_at": time.time(),
                "pl_pct": 0.0,
                "pl_usd": 0.0,
                "status": "aberta",
            }
            self.saldo_usd -= amount_usd
            self.posicoes.append(pos)
            self._save_locked()
            return pos

    def atualizar_preco(self, pos_id, preco):
        with self._lock:
            for p in self.posicoes:
                if p["id"] == pos_id:
                    p["current_price"] = preco
                    if p["entry_price"]:
                        p["pl_pct"] = (preco / p["entry_price"] - 1.0) * 100.0
                        p["pl_usd"] = p["amount_usd"] * (p["pl_pct"] / 100.0)
                    break
            self._save_locked()

    def fechar_posicao(self, pos_id, *, preco_saida, motivo) -> dict | None:
        with self._lock:
            pos = next((p for p in self.posicoes if p["id"] == pos_id), None)
            if pos is None:
                return None
            self.posicoes = [p for p in self.posicoes if p["id"] != pos_id]

            valor_saida = pos["amount_usd"]
            if pos["entry_price"] and preco_saida:
                valor_saida = pos["tokens"] * preco_saida
            pl_usd = valor_saida - pos["amount_usd"]
            pl_pct = (pl_usd / pos["amount_usd"] * 100.0) if pos["amount_usd"] else 0.0

            self.saldo_usd += valor_saida

            fechado = {
                **pos,
                "current_price": preco_saida,
                "exit_price": preco_saida,
                "closed_at": time.time(),
                "pl_usd": pl_usd,
                "pl_pct": pl_pct,
                "motivo_saida": motivo,
                "status": "fechada",
            }
            self.historico.insert(0, fechado)
            self._save_locked()
            return fechado

    def tem_posicao_para_mint(self, mint) -> bool:
        with self._lock:
            return any(p["mint"] == mint for p in self.posicoes)

    def snapshot(self) -> dict:
        """Cópia segura para o dashboard (sem segredos)."""
        with self._lock:
            pl_aberto = sum(p.get("pl_usd", 0.0) for p in self.posicoes)
            investido = sum(p.get("amount_usd", 0.0) for p in self.posicoes)
            realizado = sum(h.get("pl_usd", 0.0) for h in self.historico)
            return {
                "saldo_usd": round(self.saldo_usd, 4),
                "investido_usd": round(investido, 4),
                "valor_total_usd": round(self.saldo_usd + investido + pl_aberto, 4),
                "pl_aberto_usd": round(pl_aberto, 4),
                "pl_realizado_usd": round(realizado, 4),
                "posicoes": [dict(p) for p in self.posicoes],
                "historico": [dict(h) for h in self.historico[:50]],
                "bot_running": self.bot_running,
                "ultimo_scan": self.ultimo_scan,
                "ultima_msg": self.ultima_msg,
            }


# instância única
STATE = AppState()
