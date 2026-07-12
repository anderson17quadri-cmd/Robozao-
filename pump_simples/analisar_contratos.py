"""
Analisa os CONTRATOS das moedas do teu histórico via RugCheck.xyz.

Objetivo: responder com DADOS (não achismo) à pergunta "dá para analisar os
contratos para evitar os rugs?". Pega nas moedas que já fechaste, separa as que
DERAM RUG das que SUBIRAM, e corre o RugCheck em cada uma — para vermos se o
RugCheck teria dado sinal diferente nas más vs nas boas. Só assim decidimos se
vale a pena ligar este filtro no bot (senão é só adicionar lentidão à toa).

Uso:
    python analisar_contratos.py           # analisa os últimos de cada grupo
    python analisar_contratos.py 15        # até 15 de cada grupo (mais lento)

⚠️ Nota honesta: para moedas antigas, o RugCheck mostra o estado ATUAL (já
depois do rug) — por isso um `rugged=sim` retroativo é esperado nas más. O que
interessa mais é ver se sinais como INSIDERS e SCORE separam boas de más, e se
as boas ficariam de fora por engano (falsos positivos).
"""

import json
import sys
import time
from pathlib import Path

import rugcheck

BASE = Path(__file__).resolve().parent


def _carregar_historico() -> list[dict]:
    """
    Fonte dos trades fechados. Prefere o LOG (decisions.jsonl): é append-only e
    sobrevive a reinícios da simulação, por isso tem TODOS os trades (incl. os
    vencedores antigos). O state.json é limpo no "Reiniciar" e às vezes só tem
    os últimos — usa-se só como recurso se o log não existir.
    """
    log = BASE / "decisions.jsonl"
    if log.exists():
        trades = []
        vistos = set()
        for linha in log.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha:
                continue
            try:
                ev = json.loads(linha)
            except Exception:
                continue
            if ev.get("tipo") != "venda":
                continue
            # 1 entrada por mint (a mais recente); evita repetir a mesma moeda
            mint = ev.get("mint")
            chave = mint or ev.get("pos_id") or id(ev)
            if chave in vistos:
                continue
            vistos.add(chave)
            trades.append({"name": ev.get("name"), "mint": mint,
                           "pl_pct": ev.get("pl_pct"), "motivo_saida": ev.get("motivo")})
        if trades:
            return trades

    p = BASE / "state.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("historico", [])
    except Exception:
        return []


def _classificar(h: dict) -> str:
    """rug | vencedor | outro (a partir do resultado real do trade)."""
    pl = h.get("pl_pct") or 0.0
    if h.get("motivo_saida") == "liquidez_colapsou" or pl <= -50:
        return "rug"
    if pl >= 40:
        return "vencedor"
    return "outro"


def _linha(h: dict, rep: dict | None):
    nome = (h.get("name") or "?")[:16]
    pl = h.get("pl_pct") or 0.0
    if rep is None:
        print(f"   {nome:16} | {pl:+6.0f}% | RugCheck: — (sem dados / API falhou)")
        return
    score = rep.get("score")
    rugged = rep.get("rugged")
    ins = rep.get("insiders")
    th = rep.get("top_holder_pct")
    perig = rep.get("risks_perigosos") or []
    rugged_s = "SIM" if rugged else ("não" if rugged is False else "?")
    score_s = str(score) if score is not None else "?"
    ins_s = str(ins) if ins is not None else "?"
    th_s = f"{th:.1f}%" if th is not None else "?"
    perig_s = (", ".join(perig))[:26] if perig else "—"
    print(f"   {nome:16} | {pl:+6.0f}% | score {score_s:>3} | rugged {rugged_s:>3} | "
          f"insiders {ins_s:>4} | 2ºholder {th_s:>6} | {perig_s}")


def _stats(reports: list[dict]) -> dict:
    scores = [r["score"] for r in reports if r and r.get("score") is not None]
    rugged = sum(1 for r in reports if r and r.get("rugged") is True)
    com_insiders = sum(1 for r in reports if r and (r.get("insiders") or 0) > 0)
    perigosos = sum(1 for r in reports if r and r.get("risks_perigosos"))
    scores.sort()
    mediana = scores[len(scores) // 2] if scores else None
    return {"n": len(reports), "com_dados": len(scores), "score_mediana": mediana,
            "rugged": rugged, "com_insiders": com_insiders, "perigosos": perigosos}


def main():
    limite = 12
    if len(sys.argv) > 1:
        try:
            limite = max(1, int(sys.argv[1]))
        except ValueError:
            pass

    hist = _carregar_historico()
    print("=" * 66)
    print(" ANÁLISE DE CONTRATOS (RugCheck) — rugs vs vencedores")
    print("=" * 66)
    if not hist:
        print("\n⚠️  Sem histórico ainda (state.json vazio). Corre o bot um bocado")
        print("   em DEMO primeiro, para haver trades fechados para analisar.\n")
        return

    rugs = [h for h in hist if _classificar(h) == "rug"][:limite]
    vencedores = [h for h in hist if _classificar(h) == "vencedor"][:limite]
    print(f"\nhistórico: {len(hist)} trades  |  a analisar: {len(rugs)} rugs, "
          f"{len(vencedores)} vencedores (máx {limite} de cada)")
    print("(cada moeda = 1 pedido ao RugCheck, com rate-limit — pode demorar um pouco)\n")

    def _analisar_grupo(titulo, grupo):
        print("-" * 66)
        print(f"{titulo} ({len(grupo)}):")
        if not grupo:
            print("   (nenhum neste grupo ainda)")
            return []
        reports = []
        for h in grupo:
            rep = rugcheck.get_report(h.get("mint", ""))
            reports.append(rep)
            _linha(h, rep)
        return reports

    rep_rugs = _analisar_grupo("🩸 RUGS (deram puxão de tapete / -50%+)", rugs)
    print()
    rep_venc = _analisar_grupo("💰 VENCEDORES (+40%+)", vencedores)

    # ---- veredicto ----
    sr = _stats(rep_rugs)
    sv = _stats(rep_venc)
    print("\n" + "=" * 66)
    print(" RESUMO")
    print("=" * 66)
    print(f"   {'grupo':12} {'n':>3} {'c/dados':>8} {'score med':>10} "
          f"{'rugged':>7} {'c/insiders':>11} {'c/perigo':>9}")
    for rot, s in (("RUGS", sr), ("VENCEDORES", sv)):
        print(f"   {rot:12} {s['n']:>3} {s['com_dados']:>8} "
              f"{str(s['score_mediana']):>10} {s['rugged']:>7} "
              f"{s['com_insiders']:>11} {s['perigosos']:>9}")

    print("\n   Como ler:")
    print("   - Se os RUGS têm score/insiders MUITO mais altos que os VENCEDORES,")
    print("     um filtro RugCheck ajudaria — e dá para escolher um corte.")
    print("   - Se os VENCEDORES também têm score alto/insiders, um filtro cortaria")
    print("     moedas boas (falsos positivos) — não compensa.")
    print("   - 'rugged=SIM' retroativo nos rugs é esperado (mostra estado atual);")
    print("     o sinal ÚTIL p/ decidir ANTES de comprar é insiders + score + perigo.")
    print("=" * 66)


if __name__ == "__main__":
    main()
