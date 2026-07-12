"""
Padrões dos RUGS — o que os tokens que nos deram puxão de tapete têm em comum,
e (o mais importante) se há algo QUE DÊ PARA SABER ANTES DE COMPRAR.

Junta compra<->venda (pos_id) do decisions.jsonl, separa RUGS (saída por
liquidez_colapsou ou P/L <= -50%) do resto, e compara as duas populações em
cada característica: liquidez, market cap, hype (compradores/volume), canal,
origem, tipo de dex, e a velocidade a que morrem.

Regra de leitura: uma característica só é ÚTIL para filtrar se o valor dos RUGS
for claramente diferente do dos NÃO-RUGS. Se forem parecidos, filtrar por ela
cortaria moedas boas na mesma proporção — não compensa (já vimos isso com o
RugCheck).

Uso:
    python padroes_rugs.py
"""

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
PUMP_SUPPLY = 1_000_000_000  # supply típica pump.fun (mcap ≈ preço * supply)


def _carregar_trades() -> list[dict]:
    """Junta cada compra à sua venda pelo pos_id. Devolve trades com as
    features da compra + o resultado/tempo da venda."""
    log = BASE / "decisions.jsonl"
    if not log.exists():
        return []
    compras, vendas = {}, {}
    for linha in log.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            ev = json.loads(linha)
        except Exception:
            continue
        pid = ev.get("pos_id")
        if not pid:
            continue
        if ev.get("tipo") == "compra":
            compras[pid] = ev
        elif ev.get("tipo") == "venda":
            vendas[pid] = ev

    trades = []
    for pid, v in vendas.items():
        c = compras.get(pid)
        if not c:
            continue
        entry = c.get("entry_price") or 0.0
        tempo_min = None
        if v.get("epoch") and c.get("epoch"):
            tempo_min = max(0.0, (v["epoch"] - c["epoch"]) / 60.0)
        trades.append({
            "name": v.get("name"),
            "pl_pct": v.get("pl_pct") or 0.0,
            "motivo": v.get("motivo"),
            "liquidez": c.get("liquidez_usd"),
            "entry_price": entry,
            "mcap": (entry * PUMP_SUPPLY) if entry else None,
            "buyers": c.get("buyers_h1"),
            "volume": c.get("volume_h1"),
            "canal": c.get("canal") or "normal",
            "origem": c.get("origem") or "scan",
            "dex": c.get("dex"),
            "tempo_min": tempo_min,
        })
    return trades


def _e_rug(t: dict) -> bool:
    return t["motivo"] == "liquidez_colapsou" or t["pl_pct"] <= -50


def _med(vals):
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def _fmt(v, tipo=""):
    if v is None:
        return "—"
    if tipo == "$":
        return f"${v:,.0f}"
    if tipo == "price":
        return f"${v:.8f}"
    if tipo == "min":
        return f"{v:.1f} min"
    return f"{v:.0f}"


def _cmp_num(rot, rugs, naos, chave, tipo=""):
    mr, mn = _med([t[chave] for t in rugs]), _med([t[chave] for t in naos])
    # gap relativo para assinalar se separa
    marca = ""
    if mr is not None and mn is not None and mn != 0:
        ratio = mr / mn if mn else 0
        if ratio >= 1.5 or ratio <= 0.66:
            marca = "  <<< SEPARA"
    print(f"   {rot:26} rugs {_fmt(mr, tipo):>14}   |  não-rugs {_fmt(mn, tipo):>14}{marca}")


def _cmp_cat(rot, rugs, naos, chave):
    """Distribuição de uma categoria (canal/origem/dex) em rugs vs não-rugs."""
    def dist(grupo):
        c = Counter(str(t.get(chave)) for t in grupo)
        tot = sum(c.values()) or 1
        return {k: v / tot * 100 for k, v in c.items()}
    dr, dn = dist(rugs), dist(naos)
    chaves = sorted(set(dr) | set(dn))
    print(f"   {rot}:")
    for k in chaves:
        r, n = dr.get(k, 0), dn.get(k, 0)
        marca = "  <<< mais nos rugs" if r >= n + 15 else ""
        print(f"      {k:16} rugs {r:4.0f}%  |  não-rugs {n:4.0f}%{marca}")


def main():
    trades = _carregar_trades()
    print("=" * 68)
    print(" PADRÕES DOS RUGS — o que têm em comum, e o que dá p/ saber antes")
    print("=" * 68)
    if not trades:
        print("\n⚠️  Sem trades emparelháveis no decisions.jsonl ainda.\n")
        return

    rugs = [t for t in trades if _e_rug(t)]
    naos = [t for t in trades if not _e_rug(t)]
    print(f"\ntrades: {len(trades)}  |  rugs: {len(rugs)}  |  não-rugs: {len(naos)}")
    if not rugs or not naos:
        print("   (preciso de rugs E não-rugs para comparar — corre mais um período)")
        return

    print("\n" + "-" * 68)
    print("A) QUÃO DEPRESSA MORREM? (tempo da compra até à saída)")
    _cmp_num("tempo até sair (mediana)", rugs, naos, "tempo_min", "min")
    # distribuição do tempo dos rugs
    tempos = sorted(t["tempo_min"] for t in rugs if t["tempo_min"] is not None)
    if tempos:
        faixas = [(0, 2, "< 2 min"), (2, 5, "2–5 min"), (5, 10, "5–10 min"),
                  (10, 20, "10–20 min"), (20, 1e9, "> 20 min")]
        print("   distribuição do tempo-até-rugar:")
        for lo, hi, rot in faixas:
            q = sum(1 for x in tempos if lo <= x < hi)
            if q:
                print(f"      {rot:12} {q:3}  {'█' * round(q/len(tempos)*28)}")

    print("\n" + "-" * 68)
    print("B) O QUE DÁ PARA SABER ANTES DE COMPRAR? (features à compra)")
    print("   (só serve para filtrar se 'rugs' e 'não-rugs' forem MUITO diferentes)")
    _cmp_num("liquidez à compra", rugs, naos, "liquidez", "$")
    _cmp_num("market cap à compra", rugs, naos, "mcap", "$")
    _cmp_num("preço de entrada", rugs, naos, "entry_price", "price")
    _cmp_num("compradores (1h)", rugs, naos, "buyers")
    _cmp_num("volume (1h)", rugs, naos, "volume", "$")
    print()
    _cmp_cat("por CANAL", rugs, naos, "canal")
    _cmp_cat("por ORIGEM", rugs, naos, "origem")
    if any(t.get("dex") for t in trades):
        _cmp_cat("por DEX (curva pump-fun vs graduado)", rugs, naos, "dex")

    print("\n" + "=" * 68)
    print(" COMO DECIDIR")
    print("=" * 68)
    print("   - Linhas com '<<< SEPARA' ou '<<< mais nos rugs' = padrão que dá")
    print("     para usar como filtro à entrada (rugs claramente diferentes).")
    print("   - Se nada separar, os rugs são indistinguíveis à compra — a defesa")
    print("     é a SAÍDA (secção A: se morrem muito depressa, saída mais rápida")
    print("     nos primeiros minutos ajuda) e cortar canais/origens que perdem.")
    print("=" * 68)


if __name__ == "__main__":
    main()
