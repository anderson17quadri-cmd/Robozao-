"""
Diagnóstico do robozão — o que ele fez na prática desde que arrancou.

Lê o log de decisões (decisions.jsonl) e o estado (state.json) e imprime:
  1. Quantos tokens foram avaliados no total.
  2. Comprados vs rejeitados (e o motivo de cada rejeição).
  3. Posições fechadas por motivo (take_profit / stop_loss / timeout / manual) + P/L.
  4. Win rate e P/L médio.
  5. Fonte(s) de deteção usadas e a sua eficácia.

Uso:
    python diagnostico.py                # usa decisions.jsonl e state.json locais
    python diagnostico.py outro.jsonl    # aponta a outro log
"""

import json
import sys
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
        print("   detalhe:")
        for e in vendas[:30]:
            nome = (e.get("name") or "?")[:22]
            print(f"        {nome:22} | {e.get('motivo','?'):11} | "
                  f"{(e.get('pl_pct') or 0):+6.1f}% | {_eur(e.get('pl_usd', 0))}")
    abertas = estado.get("posicoes", [])
    print(f"   posições ainda ABERTAS agora: {len(abertas)}")

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

    print("\n" + "=" * 62)


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
