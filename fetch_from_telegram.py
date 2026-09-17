#!/usr/bin/env python3
"""يقرأ قناة تليجرام ويولّد data.json تلقائياً مع روابط embed."""
import os
import re
import sys
import json
import asyncio
from pathlib import Path

from pyrogram import Client

# ═══════════════ الإعدادات ═══════════════
API_ID_RAW = os.environ.get("API_ID", "").strip()
API_HASH = os.environ.get("API_HASH", "").strip()
CHANNEL = os.environ.get("CHANNEL", "").strip()
STRING_SESSION = (
    os.environ.get("STRING_SESSION", "").strip()
    or os.environ.get("STRING_SESSION2", "").strip()
)
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "2000"))
OUT = Path("data.json")

# ═══════════════ تحقق ═══════════════
errors = []
API_ID = 0
if not API_ID_RAW:
    errors.append("API_ID فاضي")
else:
    try:
        API_ID = int(API_ID_RAW)
    except ValueError:
        errors.append(f"API_ID ليس رقماً: {API_ID_RAW!r}")

if not API_HASH or len(API_HASH) != 32:
    errors.append(f"API_HASH غير صالح (الطول={len(API_HASH)})")
if not CHANNEL:
    errors.append("CHANNEL فاضي")
if not STRING_SESSION:
    errors.append("STRING_SESSION فارغ!")
elif len(STRING_SESSION) < 100:
    errors.append(f"STRING_SESSION قصير ({len(STRING_SESSION)})")

if errors:
    print("❌ أخطاء:", flush=True)
    for e in errors:
        print(f"   • {e}", flush=True)
    sys.exit(1)

print(f"✅ الإعدادات صحيحة (session len={len(STRING_SESSION)})", flush=True)

# ═══════════════ صيغة caption ═══════════════
CAPTION_RE = re.compile(
    r"^\s*(?P<series>.+?)\s+"
    r"(?:الموسم|season|s)\s*[:\-]?\s*(?P<season>\d+)\s+"
    r"(?:الحلقة|episode|ep|e)\s*[:\-]?\s*(?P<episode>\d+)\s*$",
    re.IGNORECASE | re.UNICODE,
)


async def main():
    print("🔐 Connecting...", flush=True)
    client = Client(
        "fetch_web",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=STRING_SESSION,
        in_memory=True,
    )
    try:
        await client.start()
    except Exception as e:
        print(f"❌ فشل الاتصال: {type(e).__name__}: {e}", flush=True)
        sys.exit(1)

    me = await client.get_me()
    print(f"✅ Connected as {me.first_name}", flush=True)

    # ═══════════════ احصل على معلومات القناة ═══════════════
    print(f"\n📡 جلب معلومات القناة: {CHANNEL}", flush=True)
    try:
        chat = await client.get_chat(CHANNEL)
        channel_id = chat.id
        channel_username = getattr(chat, "username", None) or ""
        channel_title = chat.title or "القناة"
        is_public = bool(channel_username)
        print(f"   الاسم: {channel_title}", flush=True)
        print(f"   ID: {channel_id}", flush=True)
        print(f"   Username: {channel_username or '(لا يوجد — قناة خاصة)'}", flush=True)
        print(f"   النوع: {'عامة ✅' if is_public else 'خاصة ❌'}", flush=True)
    except Exception as e:
        print(f"❌ فشل جلب القناة: {e}", flush=True)
        sys.exit(1)

    # استخرج الجزء الرقمي من -100... لبناء رابط t.me/c/...
    cid_str = str(channel_id)
    short_id = cid_str[4:] if cid_str.startswith("-100") else cid_str.lstrip("-")

    # ═══════════════ قراءة الرسائل ═══════════════
    series_map = {}
    count = 0
    skipped = 0

    print(f"\n📥 قراءة السجل (limit={HISTORY_LIMIT})...", flush=True)
    try:
        async for msg in client.get_chat_history(CHANNEL, limit=HISTORY_LIMIT):
            if not msg.video:
                continue

            caption = (msg.caption or "").strip()
            m = CAPTION_RE.match(caption)
            if not m:
                skipped += 1
                continue

            s_name = m.group("series").strip()
            season = int(m.group("season"))
            episode = int(m.group("episode"))

            # روابط متعددة
            if is_public:
                # رابط عام (يفتح في متصفح)
                watch_url = f"https://t.me/{channel_username}/{msg.id}"
                # رابط embed (يشغّل الفيديو داخل iframe)
                embed_url = f"https://t.me/{channel_username}/{msg.id}?embed=1&mode=tme"
            else:
                # رابط القناة الخاصة (يفتح في تطبيق تليجرام)
                watch_url = f"https://t.me/c/{short_id}/{msg.id}"
                embed_url = ""  # لا يمكن embedding قناة خاصة

            ep_obj = {
                "episode": episode,
                "message_id": msg.id,
                "duration": msg.video.duration or 0,
                "thumb_url": "",
                "video_url": "",         # لا يوجد رابط مباشر (يتطلب سيرفر)
                "embed_url": embed_url,   # للـ iframe
                "telegram_url": watch_url,
            }

            if s_name not in series_map:
                series_map[s_name] = {"name": s_name, "poster_url": "", "seasons": {}}

            sk = str(season)
            if sk not in series_map[s_name]["seasons"]:
                series_map[s_name]["seasons"][sk] = []

            series_map[s_name]["seasons"][sk].append(ep_obj)
            count += 1

            if count % 50 == 0:
                print(f"   ... {count} حلقة", flush=True)
    except Exception as e:
        print(f"❌ خطأ: {type(e).__name__}: {e}", flush=True)
        await client.stop()
        sys.exit(1)

    await client.stop()

    print(f"\n📊 إحصائيات:", flush=True)
    print(f"   حلقات صالحة: {count}", flush=True)
    print(f"   متجاهلة: {skipped}", flush=True)
    print(f"   مسلسلات: {len(series_map)}", flush=True)

    # ترتيب
    series_list = []
    for name, s in series_map.items():
        for sk in s["seasons"]:
            s["seasons"][sk].sort(key=lambda e: e["episode"])
        s["seasons"] = dict(sorted(s["seasons"].items(), key=lambda kv: int(kv[0])))
        series_list.append(s)
    series_list.sort(key=lambda s: s["name"])

    OUT.write_text(
        json.dumps(
            {
                "channel": {
                    "id": channel_id,
                    "username": channel_username,
                    "title": channel_title,
                    "is_public": is_public,
                },
                "series": series_list,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n✅ Wrote {count} episodes across {len(series_list)} series → {OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
