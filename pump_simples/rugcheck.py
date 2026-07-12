"""
Análise de contrato via RugCheck.xyz (API pública, gratuita, sem chave).

O que acrescenta ao que já verificamos por RPC (mint/freeze authority):
  - score de risco normalizado (0 = limpo, quanto maior pior)
  - flag `rugged` (a própria avaliação do RugCheck)
  - riscos específicos nomeados (metadata mutável, etc.)
  - % de LP bloqueado
  - histórico do criador (devs que criam moedas em série p/ dar rug)
  - deteção de carteiras insider (compras coordenadas que despejam juntas)

IMPORTANTE — limitação honesta: em tokens acabados de nascer (~1 min, o que o
bot compra) os sinais mais fortes (insiders, histórico do criador) costumam vir
VAZIOS porque o RugCheck ainda não teve tempo de os calcular. É mais útil em
tokens que já negociaram um bocado (ex.: os da lista de vigia, ou para análise
retroativa dos que já rugaram). Por isso: FAIL-OPEN — se a API falhar ou não
tiver dados, NÃO bloqueia (senão rejeitava tudo). É um extra, não a trava
principal de segurança (essa continua a ser o check de autoridades por RPC).
"""

import requests

from ratelimit import RateLimiter

_BASE = "https://api.rugcheck.xyz/v1"
_TIMEOUT = 15
# limite conservador para não irritar a API gratuita
_limiter = RateLimiter(1.5)


def _get(url: str) -> dict | None:
    try:
        _limiter.acquire()
        resp = requests.get(url, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def get_resumo(mint: str) -> dict | None:
    """
    Resumo leve (1 pedido). Devolve dict normalizado ou None (fail-open):
        {"score": int, "rugged": bool|None, "lp_locked_pct": float|None,
         "risks": [str], "risks_perigosos": [str]}
    `risks_perigosos` = só os de nível 'danger' (ignora 'warn' cosméticos).
    """
    if not mint:
        return None
    data = _get(f"{_BASE}/tokens/{mint}/report/summary")
    if not data:
        return None
    risks = data.get("risks") or []
    return {
        "score": data.get("score_normalised"),
        "rugged": data.get("rugged"),
        "lp_locked_pct": data.get("lpLockedPct"),
        "risks": [r.get("name") for r in risks if r.get("name")],
        "risks_perigosos": [r.get("name") for r in risks
                            if (r.get("level") or "").lower() == "danger"],
    }


def get_report(mint: str) -> dict | None:
    """
    Report completo (1 pedido, mais pesado). Devolve dict normalizado com os
    sinais ricos, ou None (fail-open):
        {"score", "rugged", "lp_locked_pct", "total_holders",
         "top_holder_pct", "insiders", "creator_tokens", "risks_perigosos"}
    """
    if not mint:
        return None
    data = _get(f"{_BASE}/tokens/{mint}/report")
    if not data:
        return None

    top = data.get("topHolders") or []
    # ignora a maior conta (curva/bonding do pump.fun detém ~toda a supply antes
    # de graduar — normal, não é red flag); mede a maior das RESTANTES.
    pcts_reais = sorted(
        (h.get("pct") or 0.0) for h in top if not h.get("insider", False))
    top_holder_pct = pcts_reais[-2] if len(pcts_reais) >= 2 else (
        pcts_reais[-1] if pcts_reais else None)

    creator_tokens = data.get("creatorTokens")
    risks = data.get("risks") or []
    return {
        "score": data.get("score_normalised"),
        "rugged": data.get("rugged"),
        "lp_locked_pct": data.get("lpLockedPct"),
        "total_holders": data.get("totalHolders"),
        "top_holder_pct": top_holder_pct,
        "insiders": data.get("graphInsidersDetected"),
        "creator_tokens": len(creator_tokens) if isinstance(creator_tokens, list) else None,
        "risks_perigosos": [r.get("name") for r in risks
                            if (r.get("level") or "").lower() == "danger"],
    }
