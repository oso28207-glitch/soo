#!/usr/bin/env python3
"""يقرأ قناة تليجرام ويولّد data.json تلقائياً."""
import os
import re
import json
import asyncio
from pathlib import Path

from pyrogram import Client

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
CHANNEL = os.environ.get("CHANNEL", "")
STRING_SESSION = os.environ.get("STRING_SESSION", "")
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "2000"))
OUT = Path("data.json")

# صيغة الـ caption:  "<اسم المسلسل> الموسم 3 الحلقة 5"
CAPTION_RE = re.compile(
    r"^\s*(?P<series>.+?)\s+"
    r"(?:الموسم|season|s)\s*[:\-]?\s*(?P<season>\d+)\s+"
    r"(?:الحلقة|episode|ep|e)\s*[:\-]?\s*(?P<episode>\d+)\s*$",
    re.IGNORECASE | re.UNICODE,
)


async def main():
    print("🔐 Connecting to Telegram...", flush=True)
    client = Client(
        "fetch_web",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=STRING_SESSION.strip(),
        in_memory=True,
    )
    await client.start()
    me = await client.get_me()
    print(f"✅ Connected as {me.first_name}", flush=True)

    series_map = {}
    count = 0

    print(f"📥 Reading history (limit={HISTORY_LIMIT})...", flush=True)
    async for msg in client.get_chat_history(CHANNEL, limit=HISTORY_LIMIT):
        if not msg.video:
            continue
        m = CAPTION_RE.match((msg.caption or "").strip())
        if not m:
            continue

        s_name = m.group("series").strip()
        season = int(m.group("season"))
        episode = int(m.group("episode"))

        # بناء رابط t.me للقناة الخاصة
        chat_id_str = str(msg.chat.id)
        if chat_id_str.startswith("-100"):
            short_id = chat_id_str[4:]
            telegram_url = f"https://t.me/c/{short_id}/{msg.id}"
        else:
            telegram_url = f"https://t.me/{msg.chat.username}/{msg.id}"

        ep_obj = {
            "episode": episode,
            "message_id": msg.id,
            "duration": msg.video.duration or 0,
            "thumb_url": "",
            "video_url": "",
            "telegram_url": telegram_url,
        }

        if s_name not in series_map:
            series_map[s_name] = {"name": s_name, "poster_url": "", "seasons": {}}
        sk = str(season)
        if sk not in series_map[s_name]["seasons"]:
            series_map[s_name]["seasons"][sk] = []
        series_map[s_name]["seasons"][sk].append(ep_obj)
        count += 1

    await client.stop()

    # ترتيب
    series_list = []
    for name, s in series_map.items():
        for sk in s["seasons"]:
            s["seasons"][sk].sort(key=lambda e: e["episode"])
        s["seasons"] = dict(sorted(s["seasons"].items(), key=lambda kv: int(kv[0])))
        series_list.append(s)
    series_list.sort(key=lambda s: s["name"])

    OUT.write_text(
        json.dumps({"series": series_list}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"✅ Wrote {count} episodes across {len(series_list)} series → {OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
