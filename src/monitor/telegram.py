from __future__ import annotations

import os

import requests

API = "https://api.telegram.org/bot{token}/{method}"


def split_message(text: str, limit: int = 3900) -> list[str]:
    """Parte un texto largo en bloques, cortando entre párrafos."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        cand = f"{cur}\n\n{para}" if cur else para
        if len(cand) > limit and cur:
            chunks.append(cur)
            cur = para
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    return chunks


class TelegramClient:
    """Cliente fino da Bot API — sem lógica de negócio."""

    def __init__(self, token: str | None = None, chat_id: str | None = None) -> None:
        self.token = token or os.environ["TELEGRAM_BOT_TOKEN"]
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

    def send_message(self, text: str, chat_id: str | int | None = None) -> None:
        # Telegram corta en 4096 caracteres: se parte en bloques por párrafo
        for chunk in split_message(text):
            self._send_one(chunk, chat_id)

    def _send_one(self, text: str, chat_id: str | int | None = None) -> None:
        resp = requests.post(
            API.format(token=self.token, method="sendMessage"),
            json={
                "chat_id": chat_id or self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=20,
        )
        resp.raise_for_status()

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> list[dict]:
        params: dict[str, int] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        resp = requests.get(
            API.format(token=self.token, method="getUpdates"),
            params=params,
            timeout=timeout + 20,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])
