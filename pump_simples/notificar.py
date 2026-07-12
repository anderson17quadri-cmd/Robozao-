"""
Notificações Telegram — usado pelo resumo periódico (e podes reaproveitar para
outros alertas). Sempre em try/except: uma falha aqui NUNCA derruba o bot.

Se TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID não estiverem configurados, os envios
são no-op silencioso (devolvem False) — não é um erro, é "não configurado".

Configuração (ver README ou telegram_setup.py):
1. Cria um bot com o @BotFather no Telegram, copia o token.
2. Manda uma mensagem qualquer ao teu bot novo.
3. Corre `python telegram_setup.py` para obteres o teu chat_id.
4. Cola os dois no .env: TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.
"""

import requests

from config import CFG

_TIMEOUT = 10


def telegram_configurado() -> bool:
    return bool(CFG.telegram_bot_token and CFG.telegram_chat_id)


def enviar_telegram(texto: str) -> bool:
    """Envia uma mensagem de texto pelo bot Telegram. Devolve True se enviou."""
    if not telegram_configurado():
        return False
    try:
        url = f"https://api.telegram.org/bot{CFG.telegram_bot_token}/sendMessage"
        resp = requests.post(
            url, json={"chat_id": CFG.telegram_chat_id, "text": texto}, timeout=_TIMEOUT
        )
        return resp.status_code == 200
    except Exception:
        return False
