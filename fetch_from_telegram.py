#!/usr/bin/env python3
"""يقرأ قناة تليجرام ويولّد data.json تلقائياً."""
import os
import re
import sys
import json
import asyncio
from pathlib import Path

from pyrogram import Client

# ═══════════════════════════════════════════════════════════
#  قراءة الأسرار — يدعم STRING_SESSION و STRING_SESSION2
# ═══════════════════════════════════════════════════════════
API_ID_RAW = os.environ.get("API_ID", "").strip()
API_HASH = os.environ.get("API_HASH", "").strip()
CHANNEL = os.environ.get("CHANNEL", "").strip()

# يأخذ STRING_SESSION أولاً، وإذا كان فاضياً يأخذ STRING_SESSION2
STRING_SESSION = (
    os.environ.get("STRING_SESSION", "").strip()
    or os.environ.get("STRING_SESSION2", "").strip()
)

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

if not API_HASH:
    errors.append("API_HASH فاضي")
elif len(API_HASH) != 32:
    errors.append(f"API_HASH غير صالح (الطول={len(API_HASH)}، المتوقع 32)")

if not CHANNEL:
    errors.append("CHANNEL فاضي")

if not STRING_SESSION:
    errors.append(
        "STRING_SESSION و STRING_SESSION2 فارغان! "
        "أضف STRING_SESSION في GitHub → Settings → Secrets"
    )
elif len(STRING_SESSION) < 100:
    errors.append(
        f"STRING_SESSION قصير جداً (الطول={len(STRING_SESSION)}). "
        "الجلسة الصحيحة عادةً 300+ حرف."
    )

if errors:
    print("❌ أخطاء في الإعدادات:", flush=True)
    for e in errors:
        print(f"   • {e}", flush=True)
    print("\n💡 تحقق من: GitHub repo → Settings → Secrets and variables → Actions", flush=True)
    sys.exit(1)

print(f"✅ الإعدادات صحيحة", flush=True)
print(f"   API_ID: {API_ID}", flush=True)
print(f"   CHANNEL: {CHANNEL}", flush=True)
print(f"   STRING_SESSION: {len(STRING_SESSION)} حرف", flush=True)

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
    print("\n🔐 Connecting to Telegram...", flush=True)
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
        print(f"\n❌ فشل الاتصال: {type(e).__name__}: {e}", flush=True)
        print("\n💡 الأسباب المحتملة:", flush=True)
        print("   • STRING_SESSION لا يطابق API_ID/API_HASH", flush=True)
        print("   • الجلسة أُنهيت من Telegram → الأجهزة", flush=True)
        print("   • الجلسة قُصّت عند اللصق (تحقق من عدم وجود فراغات)", flush=True)
        print("   • استخدم API_ID/API_HASH نفسه المستخدم لتوليد الجلسة", flush=True)
        sys.exit(1)

    me = await client.get_me()
    print(f"✅ Connected as {me.first_name} (@{me.username or 'N/A'})", flush=True)

    series_map = {}
    count = 0
    skipped = 0

    print(f"\n📥 Reading history (limit={HISTORY_LIMIT})...", flush=True)
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

            # بناء رابط t.me
            chat_id_str = str(msg.chat.id)
            if chat_id_str.startswith("-100"):
                short_id = chat_id_str[4:]
                telegram_url = f"https://t.me/c/{short_id}/{msg.id}"
            else:
                username = getattr(msg.chat, "username", None) or "c"
                telegram_url = f"https://t.me/{username}/{msg.id}"

            ep_obj = {
                "episode": episode,
                "message_id": msg.id,
                "duration": msg.video.duration or 0,
                "thumb_url": "",
                "video_url": "",
                "telegram_url": telegram_url,
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
        print(f"❌ خطأ أثناء قراءة السجل: {type(e).__name__}: {e}", flush=True)
        await client.stop()
        sys.exit(1)

    await client.stop()

    print(f"\n📊 إحصائيات:", flush=True)
    print(f"   حلقات صالحة: {count}", flush=True)
    print(f"   رسائل متجاهلة: {skipped}", flush=True)
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
        json.dumps({"series": series_list}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n✅ Wrote {count} episodes across {len(series_list)} series → {OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
