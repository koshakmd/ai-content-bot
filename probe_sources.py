import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from telethon.sync import TelegramClient

load_dotenv()

SOURCES_FILE = Path("sources_telegram_channels.txt")
OUTPUT_FILE = Path("source_probe.json")
POSTS_PER_CHANNEL = 5

PROMO_RE = re.compile(
    r"(реклам|подпис|переход|промокод|скидк|розыгрыш|giveaway|казино|ставк|беттинг|18\+|xxx|порн)",
    re.IGNORECASE,
)


def username_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def classify_media(message) -> str:
    if message.video:
        return "video"
    if message.photo:
        return "photo"
    if message.gif:
        return "gif"
    if message.document:
        return "document"
    return "text"


def main() -> None:
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session = os.getenv("USERBOT_SESSION", "userbot.session")

    if not api_id or not api_hash:
        raise SystemExit("Missing TELEGRAM_API_ID / TELEGRAM_API_HASH in .env")

    if not SOURCES_FILE.exists():
        raise SystemExit(f"Missing {SOURCES_FILE}")

    sources = [
        line.strip()
        for line in SOURCES_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    client = TelegramClient(session, int(api_id), api_hash)
    client.start()

    report = []

    print(f"[*] Probing {len(sources)} source channels, {POSTS_PER_CHANNEL} posts each\n")

    for i, source in enumerate(sources, start=1):
        username = username_from_url(source)
        row = {
            "source": source,
            "username": username,
            "ok": False,
            "title": None,
            "posts": [],
            "summary": {},
            "error": None,
        }

        try:
            entity = client.get_entity(username)
            messages = client.get_messages(entity, limit=POSTS_PER_CHANNEL)

            counts = {"video": 0, "photo": 0, "gif": 0, "document": 0, "text": 0}
            promo_count = 0

            for message in messages:
                media_type = classify_media(message)
                counts[media_type] += 1
                text = (message.text or "").strip()
                promotional = bool(PROMO_RE.search(text))
                promo_count += int(promotional)

                row["posts"].append({
                    "id": message.id,
                    "media_type": media_type,
                    "text": text[:300],
                    "views": message.views,
                    "forwards": message.forwards,
                    "promotional_hint": promotional,
                })

            row["ok"] = True
            row["title"] = getattr(entity, "title", username)
            row["summary"] = {
                "posts_checked": len(messages),
                **counts,
                "promo_hint": promo_count,
            }

            s = row["summary"]
            print(
                f"[{i:02}/{len(sources):02}] @{username:<24} "
                f"video={s['video']} photo={s['photo']} text={s['text']} promo~={s['promo_hint']}"
            )

        except Exception as exc:
            row["error"] = str(exc)
            print(f"[{i:02}/{len(sources):02}] @{username:<24} ERROR: {exc}")

        report.append(row)

    client.disconnect()
    OUTPUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] Report saved to: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
