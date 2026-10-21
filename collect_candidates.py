"""Collect recent video candidates from selected Telegram donor channels.

Downloads up to 20 recent video posts per channel into candidates/<channel>/
and writes candidates/index.json with basic metadata.

Uses the existing Telethon user session and Telegram API credentials from .env.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from telethon.sync import TelegramClient


load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION = os.getenv("USERBOT_SESSION", "userbot.session")

DONORS = [
    "memsheroes",
    "Ugarnye_video_prikoly",
    "lifeyt",
]

POSTS_PER_CHANNEL = 20
OUT_DIR = Path("candidates")
INDEX_PATH = OUT_DIR / "index.json"

PROMO_RE = re.compile(
    r"(реклама|промокод|подписывай|переходи|переходите|скидк|розыгрыш|"
    r"конкурс|наш канал|подробнее|заказать|купить|18\+|казино|ставк)",
    re.IGNORECASE,
)


def clean_channel_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name)


def main() -> None:
    if not API_ID or not API_HASH:
        raise SystemExit("[ERROR] TELEGRAM_API_ID / TELEGRAM_API_HASH missing in .env")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []

    with TelegramClient(SESSION, API_ID, API_HASH) as client:
        print(f"[*] Collecting video candidates from {len(DONORS)} channels")
        print(f"[*] Up to {POSTS_PER_CHANNEL} recent posts per channel\n")

        for channel_no, username in enumerate(DONORS, start=1):
            entity = client.get_entity(username)
            messages = client.get_messages(entity, limit=POSTS_PER_CHANNEL)
            channel_dir = OUT_DIR / clean_channel_name(username)
            channel_dir.mkdir(parents=True, exist_ok=True)

            saved = 0
            skipped_nonvideo = 0
            flagged_promo = 0

            for msg in messages:
                if not msg.video:
                    skipped_nonvideo += 1
                    continue

                text = (msg.message or "").strip()
                promotional = bool(PROMO_RE.search(text))
                if promotional:
                    flagged_promo += 1

                base = channel_dir / str(msg.id)
                media_path = client.download_media(msg, file=str(base))
                if not media_path:
                    continue

                media_path = Path(media_path)
                saved += 1

                item = {
                    "source_channel": f"@{username}",
                    "message_id": msg.id,
                    "date": msg.date.isoformat() if msg.date else None,
                    "text": text,
                    "promotional_hint": promotional,
                    "media_type": "video",
                    "media_path": str(media_path),
                    "telegram_url": f"https://t.me/{username}/{msg.id}",
                }
                index.append(item)

            print(
                f"[{channel_no:02d}/{len(DONORS):02d}] @{username:<24} "
                f"saved={saved:02d} nonvideo={skipped_nonvideo:02d} promo~={flagged_promo:02d}"
            )

    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n[OK] Candidate collection complete.")
    print(f"     Videos: {len(index)}")
    print(f"     Index:  {INDEX_PATH.resolve()}")
    print(f"     Media:  {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
