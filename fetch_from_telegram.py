#!/usr/bin/env python3
"""
fetch_from_telegram.py
- يقرأ قناة تليجرام
- يبني data.json مع file_id و video_url (Cloudflare Worker)
"""
import os
import re
import sys
import json
import asyncio
from pathlib import Path

from pyrogram import Client

# ═══════════════════════════════════════════════════════════
#  الإعدادات
# ═══════════════════════════════════════════════════════════
API_ID_RAW = os.environ.get("API_ID", "").strip()
API_HASH = os.environ.get("API_HASH", "").strip()
CHANNEL = os.environ.get("CHANNEL", "").strip()
STRING_SESSION = (
    os.environ.get("STRING_SESSION", "").strip()
    or os.environ.get("STRING_SESSION2", "").strip()
)
STREAM_BASE = os.environ.get("STREAM_BASE", "").strip().rstrip("/")
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "2000"))
OUT = Path("data.json")

# ═══════════════════════════════════════════════════════════
#  التحقق من الإعدادات
# ═══════════════════════════════════════════════════════════
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
if STREAM_BASE:
    print(f"🎬 Stream proxy: {STREAM_BASE}", flush=True)
else:
    print(f"⚠️ STREAM_BASE غير محدّد — سيتم استخدام روابط تليجرام فقط", flush=True)

# ═══════════════════════════════════════════════════════════
#  صيغة الـ caption: "<اسم المسلسل> الموسم 3 الحلقة 5"
# ═══════════════════════════════════════════════════════════
CAPTION_RE = re.compile(
    r"^\s*(?P<series>.+?)\s+"
    r"(?:الموسم|season|s)\s*[:\-]?\s*(?P<season>\d+)\s+"
    r"(?:الحلقة|episode|ep|e)\s*[:\-]?\s*(?P<episode>\d+)\s*$",
    re.IGNORECASE | re.UNICODE,
)


async def main():
    print("\n🔐 Connecting...", flush=True)
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

    # ─── معلومات القناة ───
    print(f"\n📡 جلب معلومات القناة: {CHANNEL}", flush=True)
    try:
        chat = await client.get_chat(CHANNEL)
        channel_id = chat.id
        channel_username = getattr(chat, "username", None) or ""
        channel_title = chat.title or "القناة"
        is_public = bool(channel_username)
        print(f"   الاسم: {channel_title}", flush=True)
        print(f"   ID: {channel_id}", flush=True)
        print(f"   Username: {channel_username or '(لا يوجد)'}", flush=True)
        print(f"   النوع: {'عامة ✅' if is_public else 'خاصة'}", flush=True)
    except Exception as e:
        print(f"❌ فشل جلب القناة: {e}", flush=True)
        sys.exit(1)

    cid_str = str(channel_id)
    short_id = cid_str[4:] if cid_str.startswith("-100") else cid_str.lstrip("-")

    # ─── قراءة الرسائل ───
    series_map = {}
    count = 0
    skipped = 0
    with_file_id = 0

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

            # file_id للبثّ عبر Cloudflare Worker
            file_id = ""
            try:
                file_id = msg.video.file_id or ""
            except Exception:
                file_id = ""
            if file_id:
                with_file_id += 1

            # رابط البثّ عبر Cloudflare Worker
            video_url = ""
            if STREAM_BASE and file_id:
                video_url = f"{STREAM_BASE}/stream?fid={file_id}"

            # روابط تليجرام (احتياطية)
            if is_public:
                watch_url = f"https://t.me/{channel_username}/{msg.id}"
                embed_url = f"https://t.me/{channel_username}/{msg.id}?embed=1&mode=tme"
            else:
                watch_url = f"https://t.me/c/{short_id}/{msg.id}"
                embed_url = ""

            ep_obj = {
                "episode": episode,
                "message_id": msg.id,
                "duration": msg.video.duration or 0,
                "thumb_url": "",
                "video_url": video_url,
                "embed_url": embed_url,
                "telegram_url": watch_url,
                "file_id": file_id,
            }

            if s_name not in series_map:
                series_map[s_name] = {
                    "name": s_name,
                    "poster_url": "",
                    "seasons": {},
                }

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
    print(f"   بحقل file_id: {with_file_id}", flush=True)
    print(f"   متجاهلة: {skipped}", flush=True)
    print(f"   مسلسلات: {len(series_map)}", flush=True)

    # ─── ترتيب ───
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
                "stream_base": STREAM_BASE,
                "series": series_list,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n✅ Wrote {count} episodes → {OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
