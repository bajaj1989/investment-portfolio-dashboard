import logging

import requests

from core.db import get_setting
from core.vault import get_secret

log = logging.getLogger(__name__)


def configured() -> bool:
    return bool(get_secret("telegram_token") and get_setting("telegram_chat_id"))


def send(text: str) -> bool:
    token, chat_id = get_secret("telegram_token"), get_setting("telegram_chat_id")
    if not token or not chat_id:
        log.info("Telegram not configured; message not sent:\n%s", text)
        return False
    for chunk in [text[i : i + 4000] for i in range(0, len(text), 4000)]:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=30,
        )
        if not r.ok:
            log.warning("Telegram send failed: %s %s", r.status_code, r.text[:200])
            return False
    return True


def find_chat_id(token: str) -> str | None:
    """After the user messages the bot, the chat id appears in getUpdates."""
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
    r.raise_for_status()
    for upd in reversed(r.json().get("result", [])):
        msg = upd.get("message") or upd.get("channel_post")
        if msg:
            return str(msg["chat"]["id"])
    return None
