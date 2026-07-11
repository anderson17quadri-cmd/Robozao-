"""
Fonte de deteção ALTERNATIVA: Bitquery (GraphQL, oficial).

Plano grátis (100k pontos/mês, sem streaming). Precisa de BITQUERY_API_KEY
(cadastro grátis em bitquery.io). Consulta os tokens criados no programa
pump.fun mais recentes.

Devolve apenas CANDIDATOS crus: {mint, name, created_at}. O dispatcher (fontes.py)
padroniza-os depois via GeckoTerminal para o formato completo que o trader espera.

Toda chamada em try/except: uma falha devolve lista vazia e nunca derruba o loop.
"""

import requests

from config import CFG

_TIMEOUT = 20

# Programa da bonding curve do pump.fun na Solana.
_PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

# Novos tokens = instrução "create" do programa pump.fun, mais recentes primeiro.
_QUERY = """
query NovosTokensPumpFun($program: String!, $limite: Int!) {
  Solana {
    Instructions(
      where: {
        Instruction: { Program: { Address: { is: $program }, Method: { is: "create" } } }
        Transaction: { Result: { Success: true } }
      }
      orderBy: { descending: Block_Time }
      limit: { count: $limite }
    ) {
      Block { Time }
      Instruction {
        Accounts { Address }
      }
    }
  }
}
"""


def get_new_candidates() -> list[dict]:
    """
    Tokens pump.fun recém-criados via Bitquery. Devolve [{mint, name, created_at}].
    Fail-closed de facto: sem chave ou sem resposta => lista vazia => não entra nada.
    """
    if not CFG.bitquery_api_key:
        return []

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CFG.bitquery_api_key}",
    }
    payload = {"query": _QUERY, "variables": {"program": _PUMPFUN_PROGRAM, "limite": 40}}

    try:
        resp = requests.post(
            CFG.bitquery_api_url, json=payload, headers=headers, timeout=_TIMEOUT
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []

    try:
        instrucoes = data["data"]["Solana"]["Instructions"]
    except (KeyError, TypeError):
        return []

    candidatos: list[dict] = []
    for ins in instrucoes or []:
        try:
            contas = (ins.get("Instruction", {}) or {}).get("Accounts", []) or []
            # no "create" do pump.fun, a conta do mint é a 1ª conta da instrução
            mint = contas[0].get("Address") if contas else None
            if not mint:
                continue
            created = (ins.get("Block", {}) or {}).get("Time", "")
            candidatos.append({"mint": mint, "name": "?", "created_at": created})
        except Exception:
            continue
    return candidatos
