"""Send-only Telegram bot messages (Bot API, no polling)."""
from __future__ import annotations

import requests

from ..config import settings


def send(text: str, dry_run: bool = False, parse_mode: str = "HTML") -> dict:
    s = settings()
    if dry_run or not s.telegram_token or not s.telegram_chat_id:
        return {"sent": False, "reason": "dry_run" if dry_run else "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset", "text": text}
    out = []
    for chunk in _chunks(text, 3800):
        r = requests.post(f"https://api.telegram.org/bot{s.telegram_token}/sendMessage",
                          json={"chat_id": s.telegram_chat_id, "text": chunk, "parse_mode": parse_mode,
                                "disable_web_page_preview": True}, timeout=20)
        out.append(r.status_code)
    return {"sent": all(c == 200 for c in out), "status": out}


def _chunks(text: str, n: int):
    while text:
        cut = text.rfind("\n", 0, n) if len(text) > n else len(text)
        cut = cut if cut > 0 else n
        yield text[:cut]
        text = text[cut:].lstrip("\n")
