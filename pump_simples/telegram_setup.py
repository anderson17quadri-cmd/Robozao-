"""
Ajuda a obter o teu chat_id do Telegram — passo único de configuração.

1. No Telegram, procura @BotFather, manda /newbot e segue os passos.
   No fim ele dá-te um TOKEN (algo como 123456789:ABCdefGhIJKlmNoPQRstuVwxYZ).
2. Procura o TEU bot novo (pelo nome que deste) e manda-lhe QUALQUER mensagem
   (ex: "oi"). Sem isto, o Telegram não sabe para onde te responder.
3. Corre:
       python telegram_setup.py <TOKEN>
   (ou cola o token em TELEGRAM_BOT_TOKEN no .env e corre sem argumentos)
4. Copia o chat_id que aparecer para TELEGRAM_CHAT_ID no .env.
"""

import sys

import requests

from config import CFG


def main():
    token = sys.argv[1] if len(sys.argv) > 1 else CFG.telegram_bot_token
    if not token:
        print("Preciso do token do bot. Uso: python telegram_setup.py <TOKEN>")
        print("(ou cola-o em TELEGRAM_BOT_TOKEN no .env e corre sem argumentos)")
        return

    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates", timeout=10
        )
        data = resp.json()
    except Exception as exc:
        print(f"Falha a contactar o Telegram: {exc}")
        return

    if not data.get("ok"):
        print(f"Telegram recusou o token: {data}")
        print("Confirma que copiaste o token certo do @BotFather.")
        return

    resultados = data.get("result", [])
    if not resultados:
        print("Nenhuma mensagem encontrada ainda.")
        print("Manda uma mensagem qualquer ao teu bot no Telegram e tenta outra vez.")
        return

    chat_id = resultados[-1]["message"]["chat"]["id"]
    print(f"✅ chat_id encontrado: {chat_id}")
    print()
    print("Cola isto no .env:")
    print(f"TELEGRAM_BOT_TOKEN={token}")
    print(f"TELEGRAM_CHAT_ID={chat_id}")


if __name__ == "__main__":
    main()
