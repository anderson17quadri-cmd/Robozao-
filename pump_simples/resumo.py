"""
Resumo curto do estado do robozão — pensado para chegar por Telegram sem
teres de abrir o dashboard ou ler o diagnostico.py completo (esse continua a
ser a ferramenta para análise profunda; este é só o essencial em segundos).

Uso:
    python resumo.py     # imprime e tenta enviar por Telegram (se configurado)

Também é chamado automaticamente pelo bot a cada RESUMO_INTERVALO_MINUTOS
(default 60min, 0 = desligado) enquanto está ligado.
"""

import json
from pathlib import Path

import notificar
from config import CFG

BASE = Path(__file__).resolve().parent


def _carregar_estado() -> dict:
    caminho = BASE / "state.json"
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _carregar_eventos() -> list[dict]:
    caminho = Path(CFG.log_file)
    if not caminho.exists():
        return []
    eventos = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            eventos.append(json.loads(linha))
        except Exception:
            continue
    return eventos


def montar_resumo() -> str:
    """Constrói o texto do resumo (usado tanto pelo CLI como pelo envio automático)."""
    estado = _carregar_estado()
    eventos = _carregar_eventos()
    sim = CFG.moeda_simbolo

    saldo = estado.get("saldo_usd", 0.0)
    posicoes = estado.get("posicoes", [])

    vendas = [e for e in eventos if e.get("tipo") == "venda"]
    pl_total = sum(e.get("pl_usd", 0.0) or 0.0 for e in vendas)
    vencedores = sum(1 for e in vendas if (e.get("pl_usd") or 0) > 0)
    win_rate = (vencedores / len(vendas) * 100.0) if vendas else 0.0
    bloqueados = sum(1 for e in eventos if e.get("motivo") == "mint_bloqueado")
    colapsos = sum(1 for e in vendas if e.get("motivo") == "liquidez_colapsou")

    linhas = [
        "🤖 robozão — resumo",
        f"saldo: {sim}{saldo:.2f}",
        f"trades fechados: {len(vendas)} | win rate: {win_rate:.0f}%",
        f"P/L acumulado (log atual): {'+' if pl_total >= 0 else ''}{sim}{pl_total:.2f}",
        f"posições abertas: {len(posicoes)}",
    ]
    for p in posicoes[:6]:
        nome = p.get("name", "?")
        linhas.append(f"  • {nome}: {p.get('pl_pct', 0.0):+.0f}%")
    if bloqueados:
        linhas.append(f"rugs repetidos bloqueados: {bloqueados}")
    if colapsos:
        linhas.append(f"colapsos de liquidez detetados: {colapsos}")
    return "\n".join(linhas)


def enviar_resumo() -> bool:
    """Constrói e tenta enviar o resumo por Telegram. Devolve True se enviou."""
    return notificar.enviar_telegram(montar_resumo())


def main():
    texto = montar_resumo()
    print(texto)
    if notificar.telegram_configurado():
        ok = notificar.enviar_telegram(texto)
        print("\n(enviado por Telegram)" if ok else "\n(falha a enviar por Telegram)")
    else:
        print("\n(Telegram não configurado — ver README ou telegram_setup.py)")


if __name__ == "__main__":
    main()
