# -*- coding: utf-8 -*-
"""Export recent Telegram channel posts and media into a local reference dataset.

Usage:
    python export_references.py

Reads Telegram credentials from .env and reuses USERBOT_SESSION / userbot.session.
Outputs:
    references/<message_id>/media.*
    references/index.json
"""

import asyncio
import json
import os
from pathlib import Path
from datetime import timezone

from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

CHANNEL = os.getenv("REFERENCE_CHANNEL", "normalno_zhe")
LIMIT = int(os.getenv("REFERENCE_LIMIT", "30"))
OUTPUT_DIR = Path(os.getenv("REFERENCE_OUTPUT_DIR", "references"))
SESSION = os.getenv("USERBOT_SESSION", "userbot.session")

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")


def fail(message: str) -> None:
    print(f"[ERROR] {message}")
    raise SystemExit(1)


async def main() -> None:
    if not API_ID:
        fail("TELEGRAM_API_ID is missing in .env")
    if not API_HASH:
        fail("TELEGRAM_API_HASH is missing in .env")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(SESSION, int(API_ID), API_HASH)
    await client.start()

    try:
        channel = await client.get_entity(CHANNEL)
        messages = await client.get_messages(channel, limit=LIMIT)

        print(f"[OK] Channel: {getattr(channel, 'title', CHANNEL)}")
        print(f"[*] Exporting {len(messages)} posts to: {OUTPUT_DIR.resolve()}")

        records = []

        for position, message in enumerate(messages, start=1):
            post_dir = OUTPUT_DIR / str(message.id)
            post_dir.mkdir(parents=True, exist_ok=True)

            media_path = None
            if message.media:
                try:
                    downloaded = await client.download_media(
                        message,
                        file=str(post_dir / "media"),
                    )
                    if downloaded:
                        media_path = str(Path(downloaded).resolve())
                except Exception as exc:
                    print(f"[WARN] {message.id}: media download failed: {exc}")

            media_type = None
            if message.video:
                media_type = "video"
            elif message.photo:
                media_type = "photo"
            elif message.document:
                media_type = "document"
            elif message.media:
                media_type = type(message.media).__name__

            date = message.date
            if date and date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)

            record = {
                "id": message.id,
                "position": position,
                "date": date.isoformat() if date else None,
                "text": message.text or "",
                "views": message.views,
                "forwards": message.forwards,
                "media_type": media_type,
                "media_path": media_path,
                "post_url": f"https://t.me/{CHANNEL}/{message.id}",
            }
            records.append(record)

            with open(post_dir / "metadata.json", "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2)

            status = media_type or "text"
            print(f"[{position:02d}/{len(messages):02d}] {message.id}  {status}")

        index = {
            "channel": CHANNEL,
            "count": len(records),
            "posts": records,
        }

        with open(OUTPUT_DIR / "index.json", "w", encoding="utf-8") as fh:
            json.dump(index, fh, ensure_ascii=False, indent=2)

        print("\n[OK] Export complete.")
        print(f"     Index: {(OUTPUT_DIR / 'index.json').resolve()}")
        print(f"     Media: {OUTPUT_DIR.resolve()}")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
