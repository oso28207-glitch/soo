#!/usr/bin/env python3
"""
fetch_from_telegram.py
- يقرأ قناة تليجرام
- يحوّل file_id ليكون متوافقاً مع Bot API (عبر copyMessage)
- يبني data.json مع video_url (Cloudflare Worker)
"""
import os
import re
import sys
import json
import asyncio
from pathlib import Path

from pyrogram import Client
import aiohttp

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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
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
    print(f"⚠️ STREAM_BASE غير محدّد", flush=True)

if BOT_TOKEN:
    print(f"🤖 Bot API mode: مفعّل", flush=True)
else:
    print(f"⚠️ BOT_TOKEN غير محدّد — file_id من Pyrogram قد لا يعمل", flush=True)

# ═══════════════════════════════════════════════════════════
#  صيغة الـ caption: "<اسم المسلسل> الموسم 3 الحلقة 5"
# ═══════════════════════════════════════════════════════════
CAPTION_RE = re.compile(
    r"^\s*(?P<series>.+?)\s+"
    r"(?:الموسم|season|s)\s*[:\-]?\s*(?P<season>\d+)\s+"
    r"(?:الحلقة|episode|ep|e)\s*[:\-]?\s*(?P<episode>\d+)\s*$",
    re.IGNORECASE | re.UNICODE,
)


# ═══════════════════════════════════════════════════════════
#  جلب file_id متوافق مع Bot API عبر copyMessage
# ═══════════════════════════════════════════════════════════
async def get_bot_compatible_file_id(
    session: aiohttp.ClientSession,
    bot_token: str,
    chat_id: int,
    message_id: int,
    temp_chat_id: int = None,
) -> str:
    """
    ينسخ الرسالة عبر Bot API ويستخرج file_id المتوافق مع البوت.
    البوت يجب أن يكون Admin في chat_id.
    """
    if not bot_token:
        return ""

    if temp_chat_id is None:
        temp_chat_id = chat_id

    base = f"https://api.telegram.org/bot{bot_token}"

    # 1) انسخ الرسالة
    copy_url = f"{base}/copyMessage"
    payload = {
        "chat_id": temp_chat_id,
        "from_chat_id": chat_id,
        "message_id": message_id,
    }
    try:
        async with session.post(copy_url, json=payload, timeout=30) as resp:
            data = await resp.json()
    except Exception as e:
        print(f"      ⚠️ copyMessage exception: {e}", flush=True)
        return ""

    if not data.get("ok"):
        err = data.get("description", "unknown")
        # لا تطبع كل خطأ لتجنب الفوضى
        if "not enough rights" in err.lower():
            print(f"      ⚠️ البوت ليس Admin في القناة!", flush=True)
        return ""

    new_msg = data["result"]
    new_msg_id = new_msg["message_id"]

    # 2) استخرج file_id
    file_id = ""
    try:
        if "video" in new_msg:
            file_id = new_msg["video"]["file_id"]
        elif "document" in new_msg:
            file_id = new_msg["document"]["file_id"]
        elif "animation" in new_msg:
            file_id = new_msg["animation"]["file_id"]
    except Exception:
        file_id = ""

    # 3) احذف الرسالة المنسوخة
    try:
        await session.post(
            f"{base}/deleteMessage",
            json={"chat_id": temp_chat_id, "message_id": new_msg_id},
            timeout=15,
        )
    except Exception:
        pass

    return file_id


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════
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
        await client.stop()
        sys.exit(1)

    cid_str = str(channel_id)
    short_id = cid_str[4:] if cid_str.startswith("-100") else cid_str.lstrip("-")

    # ─── اختبار البوت (getMe) ───
    if BOT_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getMe",
                    timeout=15,
                ) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        bot = data["result"]
                        print(
                            f"🤖 Bot: {bot.get('first_name')} "
                            f"(@{bot.get('username')})",
                            flush=True,
                        )
                    else:
                        print(f"❌ BOT_TOKEN غير صالح: {data}", flush=True)
                        BOT_TOKEN_LOCAL = ""
        except Exception as e:
            print(f"⚠️ فشل اختبار البوت: {e}", flush=True)

    # ─── قراءة الرسائل ───
    series_map = {}
    count = 0
    skipped = 0
    with_file_id = 0
    failed_file_id = 0

    print(f"\n📥 قراءة السجل (limit={HISTORY_LIMIT})...", flush=True)

    # جلسة aiohttp واحدة لإعادة الاستخدام
    async with aiohttp.ClientSession() as http_session:
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

                # ─── file_id متوافق مع البوت ───
                file_id = ""
                if BOT_TOKEN:
                    file_id = await get_bot_compatible_file_id(
                        http_session,
                        BOT_TOKEN,
                        channel_id,
                        msg.id,
                        temp_chat_id=channel_id,
                    )
                    if not file_id:
                        failed_file_id += 1
                else:
                    # fallback: من Pyrogram
                    try:
                        file_id = msg.video.file_id or ""
                    except Exception:
                        file_id = ""

                if file_id:
                    with_file_id += 1

                # ─── video_url عبر Worker ───
                video_url = ""
                if STREAM_BASE and file_id:
                    video_url = f"{STREAM_BASE}/stream?fid={file_id}"

                # ─── روابط تليجرام ───
                if is_public:
                    watch_url = f"https://t.me/{channel_username}/{msg.id}"
                    embed_url = (
                        f"https://t.me/{channel_username}/{msg.id}?embed=1&mode=tme"
                    )
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

                if count % 25 == 0:
                    print(
                        f"   ... {count} حلقة | "
                        f"file_id: {with_file_id} ✅ / {failed_file_id} ❌",
                        flush=True,
                    )

        except Exception as e:
            print(f"❌ خطأ: {type(e).__name__}: {e}", flush=True)
            await client.stop()
            sys.exit(1)

    await client.stop()

    print(f"\n📊 إحصائيات:", flush=True)
    print(f"   حلقات صالحة: {count}", flush=True)
    print(f"   بحقل file_id: {with_file_id}", flush=True)
    if failed_file_id:
        print(f"   فشل جلب file_id: {failed_file_id}", flush=True)
    print(f"   متجاهلة: {skipped}", flush=True)
    print(f"   مسلسلات: {len(series_map)}", flush=True)

    # ─── ترتيب ───
    series_list = []
    for name, s in series_map.items():
        for sk in s["seasons"]:
            s["seasons"][sk].sort(key=lambda e: e["episode"])
        s["seasons"] = dict(
            sorted(s["seasons"].items(), key=lambda kv: int(kv[0]))
        )
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
