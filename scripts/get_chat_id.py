"""Averigua tu TELEGRAM_CHAT_ID.

1. Creá un bot con @BotFather y copiá el token.
2. Mandale cualquier mensaje a tu bot (por ejemplo "hola").
3. Corré:  TELEGRAM_BOT_TOKEN=xxx python scripts/get_chat_id.py
   (o el workflow "obtener-chat-id" en GitHub Actions).
"""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()
token = os.environ.get("TELEGRAM_BOT_TOKEN") or sys.exit("Falta TELEGRAM_BOT_TOKEN (cargalo como secret en GitHub).")

r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20)
if r.status_code == 401:
    sys.exit("El token del bot es inválido. Revisá el secret TELEGRAM_BOT_TOKEN.")
r.raise_for_status()
updates = r.json().get("result", [])
if not updates:
    sys.exit("No hay mensajes. Mandale 'hola' a tu bot en Telegram y volvé a correr esto.")

seen = set()
for u in updates:
    msg = u.get("message") or u.get("edited_message") or {}
    chat = msg.get("chat", {})
    if chat and chat["id"] not in seen:
        seen.add(chat["id"])
        print(f"chat_id={chat['id']}  ({chat.get('first_name') or chat.get('title')})")

# Mensaje de prueba opcional (input "mensaje" del workflow)
texto = os.environ.get("MENSAJE", "").strip()
if texto:
    for chat_id in seen:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": texto},
            timeout=20,
        )
        print(f"mensaje a {chat_id}: {'enviado' if resp.ok else resp.text}")
