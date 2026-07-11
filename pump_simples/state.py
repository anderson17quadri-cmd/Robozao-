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
        # valor de cada entrada (editável no dashboard; começa no do .env)
        self.max_trade_usd: float = CFG.max_trade_usd
        self._load()

    # ---------- persistência ----------
    def _load(self):
        try:
            with open(CFG.state_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.saldo_usd = data.get("saldo_usd", self.saldo_usd)
            self.posicoes = data.get("posicoes", [])
            self.historico = data.get("historico", [])
            self.max_trade_usd = data.get("max_trade_usd", self.max_trade_usd)
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
                "max_trade_usd": self.max_trade_usd,
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
                      amount_usd, tokens, meta_lucro_pct=None, liquidez_usd=None) -> dict:
        with self._lock:
            pos = {
                "id": uuid.uuid4().hex[:8],
                "mint": mint,
                "pool_address": pool_address,
                "name": name,
                "entry_price": entry_price,
                "current_price": entry_price,
                "preco_pico": entry_price,   # pico desde a compra (para o trailing stop)
                "amount_usd": amount_usd,
                "tokens": tokens,
                "liquidez_usd": liquidez_usd,   # liquidez à compra (p/ slippage de venda)
                "opened_at": time.time(),
                "pl_pct": 0.0,
                "pl_usd": 0.0,
                # meta de venda custom desta posição (% de lucro). None => usa o global.
                "meta_lucro_pct": meta_lucro_pct,
                "status": "aberta",
            }
            self.saldo_usd -= amount_usd
            self.posicoes.append(pos)
            self._save_locked()
            return pos

    def set_meta_lucro(self, pos_id, pct) -> bool:
        """Define/limpa a meta de lucro custom de uma posição aberta. pct None => limpa."""
        with self._lock:
            for p in self.posicoes:
                if p["id"] == pos_id:
                    p["meta_lucro_pct"] = pct
                    self._save_locked()
                    return True
            return False

    def get_posicao(self, pos_id) -> dict | None:
        with self._lock:
            p = next((x for x in self.posicoes if x["id"] == pos_id), None)
            return dict(p) if p else None

    def atualizar_preco(self, pos_id, preco):
        with self._lock:
            for p in self.posicoes:
                if p["id"] == pos_id:
                    p["current_price"] = preco
                    # o pico só sobe, nunca desce (referência do trailing stop)
                    pico = p.get("preco_pico") or p.get("entry_price") or preco
                    p["preco_pico"] = max(pico, preco)
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
                # acompanhamento pós-venda (só leitura; não afeta saldo)
                "preco_pos_venda": preco_saida,
                "var_pos_venda_pct": 0.0,
                "pos_venda_atualizado_em": time.time(),
            }
            self.historico.insert(0, fechado)
            self._save_locked()
            return fechado

    def atualizar_preco_vendido(self, trade_id, preco):
        """Atualiza o preço atual de um trade JÁ FECHADO (acompanhamento pós-venda).
        Só leitura de mercado — nunca mexe no saldo nem reabre posição."""
        with self._lock:
            for h in self.historico:
                if h.get("id") == trade_id:
                    h["preco_pos_venda"] = preco
                    base = h.get("exit_price")
                    if base:
                        h["var_pos_venda_pct"] = (preco / base - 1.0) * 100.0
                    h["pos_venda_atualizado_em"] = time.time()
                    break
            self._save_locked()

    def trades_para_acompanhar(self, limite) -> list[dict]:
        """Cópia dos últimos `limite` trades fechados (para reavaliar o preço)."""
        with self._lock:
            return [dict(h) for h in self.historico[:limite]]

    def tem_posicao_para_mint(self, mint) -> bool:
        with self._lock:
            return any(p["mint"] == mint for p in self.posicoes)

    def reset(self):
        """Reinicia a simulação: saldo volta ao inicial, limpa posições e histórico.
        Mantém o valor de entrada configurado. Só faz sentido em DRY_RUN."""
        with self._lock:
            self.saldo_usd = CFG.saldo_virtual_inicial
            self.posicoes = []
            self.historico = []
            self._save_locked()

    def set_max_trade(self, valor) -> bool:
        """Define o valor de cada entrada (persiste). Devolve False se inválido."""
        try:
            if isinstance(valor, str):
                valor = valor.strip().replace(",", ".")  # aceita vírgula decimal
            v = float(valor)
        except (TypeError, ValueError):
            return False
        if v <= 0:
            return False
        with self._lock:
            self.max_trade_usd = v
            self._save_locked()
            return True

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
                "max_trade_usd": round(self.max_trade_usd, 4),
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
