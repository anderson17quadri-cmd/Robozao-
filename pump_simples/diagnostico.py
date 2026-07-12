"""
Diagnóstico do robozão — o que ele fez na prática desde que arrancou.

Lê o log de decisões (decisions.jsonl) e o estado (state.json) e imprime:
  1. Quantos tokens foram avaliados no total.
  2. Comprados vs rejeitados (e o motivo de cada rejeição).
  3. Posições fechadas por motivo (take_profit / stop_loss / timeout / manual) + P/L.
  4. Win rate e P/L médio.
  5. Fonte(s) de deteção usadas e a sua eficácia.
  6-10. Padrões (liquidez, hype, canal hype vs normal, origem scan vs vigia).

Uso:
    python diagnostico.py                # usa decisions.jsonl e state.json locais
    python diagnostico.py outro.jsonl    # aponta a outro log
"""

import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent


def _carregar_jsonl(caminho: Path) -> list[dict]:
    eventos = []
    if not caminho.exists():
        return eventos
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            eventos.append(json.loads(linha))
        except Exception:
            continue  # ignora linha malformada
    return eventos


def _carregar_json(caminho: Path) -> dict:
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fmt_ts(epoch) -> str:
    try:
        return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return "?"


def _eur(v) -> str:
    try:
        return ("+" if v >= 0 else "-") + "€" + f"{abs(v):.4f}"
    except Exception:
        return "?"


def _classificar_seguranca(ev: dict) -> str:
    """Sub-motivo de uma rejeição por segurança das autoridades."""
    detalhe = (ev.get("detalhe") or "").lower()
    if "limite helius" in detalhe or "429" in detalhe:
        return "RPC 429 (limite Helius)"
    if "não configurada" in detalhe or "nao configurada" in detalhe:
        return "RPC não configurada"
    if "rede" in detalhe or "falha" in detalhe or "parsear" in detalhe:
        return "RPC falhou / não confirmou (fail-closed)"
    if ev.get("mint_authority") or ev.get("freeze_authority"):
        return "autoridade ainda ativa (não revogada)"
    return "outro (fail-closed)"


def main():
    log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "decisions.jsonl"
    state_path = BASE / "state.json"

    eventos = _carregar_jsonl(log_path)
    estado = _carregar_json(state_path)

    print("=" * 62)
    print(" DIAGNÓSTICO robozão")
    print(f"   log....: {log_path}")
    print(f"   estado.: {state_path}")
    print("=" * 62)

    if not eventos:
        print("\n⚠️  Sem eventos no log ainda. O bot já correu e comprou/rejeitou algo?")
        print("   (o log só cresce quando o bot está LIGADO e avalia tokens)\n")
        # mesmo sem log, mostra o que houver no estado
        _resumo_estado(estado)
        return

    por_tipo = Counter(e.get("tipo") for e in eventos)
    t0 = min((e.get("epoch", 0) for e in eventos), default=0)
    t1 = max((e.get("epoch", 0) for e in eventos), default=0)
    print(f"\nperíodo: {_fmt_ts(t0)}  ->  {_fmt_ts(t1)}")
    print(f"eventos no log: {len(eventos)}  {dict(por_tipo)}")

    # arranques + modo + fontes
    arranques = [e for e in eventos if e.get("tipo") == "bot_start"]
    fontes_uso = Counter(e.get("fonte_deteccao", "?") for e in arranques)
    modos = Counter(("REAL" if e.get("envio_real") else "DRY_RUN") for e in arranques)
    print(f"arranques do bot: {len(arranques)}  | modo: {dict(modos)}")

    # ---------- 0) MODO: as trades foram REAIS ou simuladas? ----------
    trades = [e for e in eventos if e.get("tipo") in ("compra", "venda")]
    modos_trade = Counter(e.get("modo", "?") for e in trades)
    reais = [e for e in trades if e.get("signature")]  # só trades reais têm assinatura
    print("\n" + "-" * 62)
    print("0) MODO DAS TRADES (reais vs simuladas)")
    print(f"   por modo: {dict(modos_trade)}")
    if reais:
        print(f"   ⚠️  {len(reais)} trade(s) REAIS on-chain (com assinatura):")
        for e in reais[:5]:
            print(f"        {(e.get('name') or '?')[:20]} | sig {str(e.get('signature'))[:24]}…")
    else:
        print("   ✅ NENHUMA transação real. Tudo DRY_RUN (simulado) — 0 SOL gasto,")
        print("      0 assinaturas on-chain. Nada foi comprado/vendido a sério.")

    # ---------- 1) DETEÇÃO / ANÁLISE ----------
    compras = [e for e in eventos if e.get("tipo") == "compra"]
    rejeicoes = [e for e in eventos if e.get("tipo") == "rejeicao"]
    avaliados = compras + rejeicoes
    mints_unicos = {e.get("mint") for e in avaliados if e.get("mint")}
    print("\n" + "-" * 62)
    print("1) DETEÇÃO / ANÁLISE")
    print(f"   tokens avaliados (compra + rejeição): {len(avaliados)}")
    print(f"   tokens únicos avaliados..............: {len(mints_unicos)}")
    print("   (nota: tokens já em carteira ou acima do limite de posições")
    print("    saem cedo e não entram nesta contagem)")

    # ---------- 2) ENTRADAS vs REJEIÇÕES ----------
    print("\n" + "-" * 62)
    print("2) ENTRADAS vs REJEIÇÕES")
    print(f"   ✅ comprados : {len(compras)}")
    print(f"   ❌ rejeitados: {len(rejeicoes)}")
    motivos = Counter(e.get("motivo", "?") for e in rejeicoes)
    for motivo, n in motivos.most_common():
        print(f"        - {motivo}: {n}")
        if motivo == "seguranca_autoridades":
            sub = Counter(_classificar_seguranca(e) for e in rejeicoes
                          if e.get("motivo") == "seguranca_autoridades")
            for s, sn in sub.most_common():
                print(f"            · {s}: {sn}")
    falhas_compra = por_tipo.get("compra_falhou", 0)
    if falhas_compra:
        print(f"   ⚠️  compras que falharam na execução (real): {falhas_compra}")

    # ---------- 3) POSIÇÕES FECHADAS ----------
    vendas = [e for e in eventos if e.get("tipo") == "venda"]
    print("\n" + "-" * 62)
    print("3) POSIÇÕES FECHADAS")
    print(f"   fechadas: {len(vendas)}")
    por_motivo_saida = Counter(e.get("motivo", "?") for e in vendas)
    pl_por_motivo = defaultdict(float)
    for e in vendas:
        pl_por_motivo[e.get("motivo", "?")] += e.get("pl_usd", 0.0) or 0.0
    for motivo, n in por_motivo_saida.most_common():
        print(f"        - {motivo}: {n}  (P/L soma {_eur(pl_por_motivo[motivo])})")
    if vendas:
        recentes = list(reversed(vendas))[:30]   # os MAIS RECENTES primeiro
        print(f"   detalhe (últimos {len(recentes)}, mais recente no topo):")
        for e in recentes:
            nome = (e.get("name") or "?")[:22]
            print(f"        {nome:22} | {e.get('motivo','?'):13} | "
                  f"{(e.get('pl_pct') or 0):+6.1f}% | {_eur(e.get('pl_usd', 0))}")
    abertas = estado.get("posicoes", [])
    print(f"   posições ainda ABERTAS agora: {len(abertas)}")
    if abertas:
        print("   detalhe das abertas:")
        for p in abertas:
            entrada = p.get("entry_price") or 0
            pico = p.get("preco_pico") or entrada
            pico_pct = ((pico / entrada - 1.0) * 100.0) if entrada else 0.0
            nome = (p.get("name") or "?")[:20]
            canal = p.get("canal", "normal")
            idade_min = (time.time() - p.get("opened_at", time.time())) / 60.0
            print(f"        {nome:20} | pl {p.get('pl_pct', 0):+6.1f}% | "
                  f"pico +{pico_pct:5.1f}% | liq.compra ${p.get('liquidez_usd') or 0:,.0f} "
                  f"-> liq.atual ${p.get('liquidez_atual') or 0:,.0f} | "
                  f"canal={canal} | há {idade_min:.0f}min")

    # ---------- 4) WIN RATE / P/L ----------
    print("\n" + "-" * 62)
    print("4) WIN RATE / P/L")
    if not vendas:
        print("   ainda sem trades fechados — nada para calcular.")
    else:
        pls = [e.get("pl_usd", 0.0) or 0.0 for e in vendas]
        vencedores = [p for p in pls if p > 0]
        total = sum(pls)
        win_rate = len(vencedores) / len(pls) * 100.0
        print(f"   trades fechados....: {len(pls)}")
        print(f"   vencedores (P/L>0).: {len(vencedores)}  ->  win rate {win_rate:.0f}%")
        print(f"   P/L total..........: {_eur(total)}")
        print(f"   P/L médio/trade....: {_eur(total/len(pls))}")
        print(f"   melhor / pior......: {_eur(max(pls))} / {_eur(min(pls))}")
        if len(pls) < 10:
            print("   ⚠️  amostra pequena (<10) — win rate ainda pouco fiável.")

    # ---------- 5) FONTE DE DETEÇÃO ----------
    print("\n" + "-" * 62)
    print("5) FONTE DE DETEÇÃO")
    if fontes_uso:
        print("   arranques por fonte:")
        for f, n in fontes_uso.most_common():
            print(f"        - {f}: {n} arranque(s)")
    sem_pool = [e for e in eventos if e.get("tipo") == "fonte_sem_pool"]
    if sem_pool:
        tot_cand = sum(e.get("candidatos", 0) for e in sem_pool)
        print(f"   ⚠️  fonte alternativa devolveu candidatos mas SEM pool no Gecko: "
              f"{len(sem_pool)} vez(es) ({tot_cand} candidatos ignorados)")
        print("       -> a fonte está a detetar, mas os tokens ainda não estão")
        print("          indexados no oráculo de preço (normal em tokens muito novos).")
    if len(fontes_uso) <= 1 and not sem_pool:
        f = next(iter(fontes_uso), "gecko")
        print(f"   só a fonte '{f}' foi usada. Para comparar, muda FONTE_DETECCAO")
        print("   no .env e corre um período com cada uma.")

    # ---------- 6) PADRÃO: ganhadores vs perdedores ----------
    _analise_padroes(compras, vendas)

    # ---------- 7) ARREPENDIMENTO: subiu depois de vender? ----------
    _analise_arrependimento(estado)

    # ---------- 8) DESEMPENHO POR LIQUIDEZ À COMPRA ----------
    _analise_por_liquidez(compras, vendas)

    # ---------- 9) DESEMPENHO POR HYPE (compradores/volume à compra) ----------
    _analise_por_hype(compras, vendas)

    # ---------- 10) DESEMPENHO POR CANAL (hype vs normal) e ORIGEM (scan vs vigia) ----------
    _analise_por_canal(compras, vendas)

    print("\n" + "=" * 62)


def _faixas_desempenho(trades, chave, faixas, unidade=""):
    """Imprime win-rate/P&L por faixa de uma métrica (ex: buyers_h1, volume_h1)."""
    print(f"   {'faixa':12} {'n':>4} {'win%':>6} {'P/L soma':>12} {'P/L med %':>10}")
    algum = False
    for lo, hi, rot in faixas:
        grupo = [t for t in trades if t[chave] is not None and lo <= t[chave] < hi]
        if not grupo:
            continue
        algum = True
        n = len(grupo)
        wins = sum(1 for t in grupo if t["pl_usd"] > 0)
        soma = sum(t["pl_usd"] for t in grupo)
        medpct = _mediana([t["pl_pct"] for t in grupo]) or 0.0
        print(f"   {rot:12} {n:>4} {wins/n*100:>5.0f}% {_eur(soma):>12} {medpct:>+9.1f}%")
    if not algum:
        print("   (sem dados nesta métrica ainda — corre um novo período)")


def _analise_por_hype(compras: list[dict], vendas: list[dict]):
    """Os mais 'hypados' (mais compradores/volume à compra) ganham mais?"""
    print("\n" + "-" * 62)
    print("9) DESEMPENHO POR HYPE À COMPRA (compradores e volume na 1ª hora)")

    compra_por_id = {c.get("pos_id"): c for c in compras if c.get("pos_id")}
    trades = []
    for v in vendas:
        c = compra_por_id.get(v.get("pos_id"))
        if not c:
            continue
        trades.append({
            "buyers_h1": c.get("buyers_h1"),
            "volume_h1": c.get("volume_h1"),
            "pl_usd": v.get("pl_usd") or 0.0,
            "pl_pct": v.get("pl_pct") or 0.0,
        })
    if not trades or all(t["buyers_h1"] is None and t["volume_h1"] is None for t in trades):
        print("   sem métricas de hype registadas ainda (começam a partir de agora).")
        print("   Corre um novo período para ver se os hypados compensam.")
        return

    print("   » por Nº DE COMPRADORES (1h):")
    _faixas_desempenho(trades, "buyers_h1", [
        (0, 5, "< 5"), (5, 15, "5–15"), (15, 40, "15–40"),
        (40, 100, "40–100"), (100, float("inf"), "100+")])

    print("   » por VOLUME (1h):")
    _faixas_desempenho(trades, "volume_h1", [
        (0, 1000, "< $1k"), (1000, 5000, "$1k–5k"), (5000, 20000, "$5k–20k"),
        (20000, 100000, "$20k–100k"), (100000, float("inf"), "$100k+")])


def _grupo_stats(grupo):
    """(n, win%, soma P/L, mediana P/L%) de uma lista de trades {pl_usd, pl_pct}."""
    n = len(grupo)
    wins = sum(1 for t in grupo if t["pl_usd"] > 0)
    soma = sum(t["pl_usd"] for t in grupo)
    medpct = _mediana([t["pl_pct"] for t in grupo]) or 0.0
    return n, (wins / n * 100 if n else 0.0), soma, medpct


def _analise_por_canal(compras: list[dict], vendas: list[dict]):
    """
    O canal HYPE compensa? E as compras da lista de vigia (origem=vigia) vs as
    do scan normal? Responde direto a 'vale a pena manter o HYPE ligado?'.

    Junta compra<->venda pelo pos_id (o canal/origem só existem na compra).
    """
    print("\n" + "-" * 62)
    print("10) DESEMPENHO POR CANAL (hype vs normal) e ORIGEM (scan vs vigia)")

    compra_por_id = {c.get("pos_id"): c for c in compras if c.get("pos_id")}
    trades = []
    for v in vendas:
        c = compra_por_id.get(v.get("pos_id"))
        if not c:
            continue
        trades.append({
            "canal": c.get("canal") or "normal",
            "origem": c.get("origem") or "scan",
            "pl_usd": v.get("pl_usd") or 0.0,
            "pl_pct": v.get("pl_pct") or 0.0,
        })

    if not trades:
        print("   sem trades emparelháveis com canal/origem ainda — corre um novo período.")
        return

    def _tabela(titulo, chave):
        print(f"   » por {titulo}:")
        print(f"   {'grupo':12} {'n':>4} {'win%':>6} {'P/L soma':>12} {'P/L med %':>10}")
        grupos = defaultdict(list)
        for t in trades:
            grupos[t[chave]].append(t)
        for nome in sorted(grupos, key=lambda k: -sum(x["pl_usd"] for x in grupos[k])):
            n, wr, soma, medpct = _grupo_stats(grupos[nome])
            print(f"   {nome:12} {n:>4} {wr:>5.0f}% {_eur(soma):>12} {medpct:>+9.1f}%")

    _tabela("CANAL", "canal")
    _tabela("ORIGEM", "origem")

    # veredicto direto sobre o HYPE
    hype = [t for t in trades if t["canal"] == "hype"]
    normal = [t for t in trades if t["canal"] != "hype"]
    print("   -----")
    if not hype:
        print("   👉 nenhum trade pelo canal HYPE neste período (ou estava desligado).")
    else:
        hn, hwr, hsoma, _ = _grupo_stats(hype)
        nn, nwr, nsoma, _ = _grupo_stats(normal)
        print(f"   👉 HYPE: {hn} trades, win {hwr:.0f}%, P/L {_eur(hsoma)}  |  "
              f"NORMAL: {nn} trades, win {nwr:.0f}%, P/L {_eur(nsoma)}")
        if hsoma < 0 and nsoma > 0:
            print("      O canal HYPE está a PERDER enquanto o normal ganha — considera")
            print("      desligá-lo (botão 🔥 HYPE) ou apertar os limites de hype.")
        elif hsoma > 0 and hwr >= nwr:
            print("      O canal HYPE está a compensar — manter ligado faz sentido.")
        else:
            print("      Resultado do HYPE ainda misto — deixa correr mais para decidir.")


def _analise_por_liquidez(compras: list[dict], vendas: list[dict]):
    """Junta compra(liquidez) + venda(resultado) e mostra win-rate/P&L por faixa de
    liquidez — responde direto a 'a partir de que liquidez os tokens são bons?'."""
    print("\n" + "-" * 62)
    print("8) DESEMPENHO POR LIQUIDEZ À COMPRA")

    compra_por_id = {c.get("pos_id"): c for c in compras if c.get("pos_id")}
    trades = []
    for v in vendas:
        c = compra_por_id.get(v.get("pos_id"))
        if not c:
            continue
        liq = c.get("liquidez_usd")
        if liq is None:
            continue
        trades.append({"liq": float(liq), "pl_usd": v.get("pl_usd") or 0.0,
                       "pl_pct": v.get("pl_pct") or 0.0})

    if not trades:
        print("   sem liquidez registada nas compras ainda (só a partir da versão")
        print("   que a começou a gravar). Corre um novo período.")
        return

    faixas = [(0, 2000, "< $2k"), (2000, 5000, "$2k–5k"), (5000, 10000, "$5k–10k"),
              (10000, 20000, "$10k–20k"), (20000, 50000, "$20k–50k"),
              (50000, float("inf"), "> $50k")]
    print(f"   {'faixa':10} {'n':>4} {'win%':>6} {'P/L soma':>12} {'P/L med %':>10}")
    for lo, hi, rot in faixas:
        grupo = [t for t in trades if lo <= t["liq"] < hi]
        if not grupo:
            continue
        n = len(grupo)
        wins = sum(1 for t in grupo if t["pl_usd"] > 0)
        soma = sum(t["pl_usd"] for t in grupo)
        medpct = _mediana([t["pl_pct"] for t in grupo]) or 0.0
        print(f"   {rot:10} {n:>4} {wins/n*100:>5.0f}% {_eur(soma):>12} {medpct:>+9.1f}%")

    # corte sugerido: primeira faixa (>=) com P/L soma positivo e win-rate decente
    print("   -----")
    acima = {}
    for corte in (5000, 10000, 20000, 50000):
        g = [t for t in trades if t["liq"] >= corte]
        if g:
            acima[corte] = (len(g), sum(1 for t in g if t["pl_usd"] > 0) / len(g) * 100,
                            sum(t["pl_usd"] for t in g))
    for corte, (n, wr, soma) in acima.items():
        print(f"   se só comprasses liquidez ≥ ${corte:,}: {n} trades | "
              f"win {wr:.0f}% | P/L {_eur(soma)}")


def _mediana(valores):
    vals = [v for v in valores if v is not None]
    return statistics.median(vals) if vals else None


def _analise_arrependimento(estado: dict):
    """
    Usa o acompanhamento pós-venda (var_pos_venda_pct no histórico) para responder:
    dos tokens que vendemos, quantos SUBIRAM depois? Foco nos stop-losses — é o
    sinal que diz se o stop está apertado demais (a vender no fundo).
    """
    print("\n" + "-" * 62)
    print("7) ARREPENDIMENTO — subiu depois de vender? (acompanhamento pós-venda)")

    hist = estado.get("historico", [])
    seguidos = [h for h in hist if h.get("var_pos_venda_pct") is not None]
    if not seguidos:
        print("   sem dados de acompanhamento pós-venda ainda.")
        print("   (só os últimos ACOMPANHAR_VENDIDOS_MAX trades são seguidos, e só")
        print("    enquanto o bot está ligado — corre-o mais um pouco.)")
        return

    def _bloco(rotulo, grupo):
        if not grupo:
            print(f"   {rotulo}: (nenhum seguido)")
            return
        vars_ = [h.get("var_pos_venda_pct") or 0.0 for h in grupo]
        subiram = [v for v in vars_ if v > 0]
        forte = [v for v in vars_ if v > 30]     # recuperou bem depois de vender
        med = _mediana(vars_)
        print(f"   {rotulo} (seguidos: {len(grupo)}):")
        print(f"        subiram após a venda....: {len(subiram)}/{len(grupo)} "
              f"({len(subiram)/len(grupo)*100:.0f}%)")
        print(f"        recuperaram >+30%.......: {len(forte)}  "
              f"(estes são os que doem — vendidos no fundo)")
        print(f"        variação pós-venda média: {(_mediana(vars_) or 0):+.1f}% (mediana)")

    trailing = [h for h in seguidos if h.get("motivo_saida") == "trailing_stop"]
    stops = [h for h in seguidos if h.get("motivo_saida") == "stop_loss"]
    timeouts = [h for h in seguidos if h.get("motivo_saida") == "timeout"]
    tps = [h for h in seguidos if h.get("motivo_saida") == "take_profit"]

    _bloco("TRAILING-STOP", trailing)
    _bloco("STOP-LOSS (legado)", stops)
    _bloco("TIMEOUT", timeouts)
    _bloco("TAKE-PROFIT", tps)

    # veredicto sobre a saída de descida (trailing; ou o stop antigo se ainda houver)
    saidas_descida = trailing or stops
    rotulo = "trailing-stops" if trailing else "stop-losses"
    if saidas_descida:
        subiram = sum(1 for h in saidas_descida if (h.get("var_pos_venda_pct") or 0) > 0)
        pct = subiram / len(saidas_descida) * 100
        print("   -----")
        if pct >= 60:
            print(f"   👉 {pct:.0f}% dos {rotulo} SUBIRAM depois de vender: saída apertada")
            print("      — considera alargar TRAILING_STOP_PCT.")
        elif pct <= 35:
            print(f"   👉 só {pct:.0f}% recuperaram: a saída está a proteger bem de rugs.")
            print("      Alargar iria só aumentar as perdas — não recomendado.")
        else:
            print(f"   👉 {pct:.0f}% recuperaram: zona cinzenta. Ajusta o TRAILING_STOP_PCT")
            print("      aos poucos e volta a medir.")


def _analise_padroes(compras: list[dict], vendas: list[dict]):
    print("\n" + "-" * 62)
    print("6) PADRÃO — quem subiu vs quem caiu")

    # junta compra<->venda pelo pos_id (features da compra + resultado da venda)
    compra_por_id = {c.get("pos_id"): c for c in compras if c.get("pos_id")}
    trades = []
    for v in vendas:
        c = compra_por_id.get(v.get("pos_id"))
        if not c:
            continue
        hold = None
        if v.get("epoch") and c.get("epoch"):
            hold = max(0.0, v["epoch"] - c["epoch"])
        trades.append({
            "pl_pct": v.get("pl_pct") or 0.0,
            "entry_price": c.get("entry_price"),
            "liquidez": c.get("liquidez_usd"),   # só existe em compras recentes
            "hold_min": (hold / 60.0) if hold is not None else None,
        })

    if not trades:
        print("   sem trades emparelháveis (compra+venda) no log ainda.")
        return

    # distribuição de resultados (a "forma" do que acontece)
    faixas = {"rug forte (< -50%)": 0, "perda (-50% a -10%)": 0,
              "neutro (-10% a +10%)": 0, "ganho (+10% a +50%)": 0, "moon (> +50%)": 0}
    for t in trades:
        p = t["pl_pct"]
        if p < -50: faixas["rug forte (< -50%)"] += 1
        elif p < -10: faixas["perda (-50% a -10%)"] += 1
        elif p <= 10: faixas["neutro (-10% a +10%)"] += 1
        elif p <= 50: faixas["ganho (+10% a +50%)"] += 1
        else: faixas["moon (> +50%)"] += 1
    n = len(trades)
    print(f"   distribuição de {n} trades:")
    for faixa, q in faixas.items():
        barra = "█" * round(q / n * 30)
        print(f"      {faixa:22} {q:4}  {barra}")

    # compara features: quem CAIU muito vs quem SUBIU muito
    cairam = [t for t in trades if t["pl_pct"] <= -40]
    subiram = [t for t in trades if t["pl_pct"] >= 40]

    def _linha(rotulo, grupo):
        if not grupo:
            print(f"   {rotulo}: (nenhum)")
            return
        ep = _mediana([t["entry_price"] for t in grupo])
        lq = _mediana([t["liquidez"] for t in grupo])
        hd = _mediana([t["hold_min"] for t in grupo])
        ep_s = f"${ep:.8f}" if ep else "—"
        lq_s = f"${lq:,.0f}" if lq else "s/ dados"
        hd_s = f"{hd:.1f} min" if hd is not None else "—"
        print(f"   {rotulo} ({len(grupo)}): preço entrada med {ep_s} | "
              f"liquidez med {lq_s} | tempo até sair med {hd_s}")

    print("   comparação (mediana de cada grupo):")
    _linha("↓ caíram >40%", cairam)
    _linha("↑ subiram >40%", subiram)

    com_liq = sum(1 for t in trades if t["liquidez"] is not None)
    if com_liq == 0:
        print("   ⚠️  liquidez à COMPRA ainda não está no log (ativada agora).")
        print("       Corre um novo período para poder comparar liquidez de quem sobe/cai.")
    else:
        print(f"   (liquidez à compra disponível em {com_liq}/{n} trades)")


def _resumo_estado(estado: dict):
    if not estado:
        print("   (state.json também não existe ainda)\n")
        return
    print("   estado atual:")
    print(f"     saldo........: €{estado.get('saldo_usd', 0):.2f}")
    print(f"     posições.....: {len(estado.get('posicoes', []))}")
    print(f"     histórico....: {len(estado.get('historico', []))}\n")


if __name__ == "__main__":
    main()
