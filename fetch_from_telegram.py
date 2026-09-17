#!/usr/bin/env python3
"""
fetch_from_telegram.py
- يقرأ القناة عبر Pyrogram (user session)
- يحوّل file_id إلى Bot-compatible عبر forwarding إلى قناة تخزين
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
STORAGE_CHANNEL = os.environ.get("STORAGE_CHANNEL", "").strip()
HISTORY_LIMIT = int(os.environ.get("HISTORY_LIMIT", "2000"))
OUT = Path("data.json")

# ═══════════════════════════════════════════════════════════
#  التحقق
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

if errors:
    print("❌ أخطاء:", flush=True)
    for e in errors:
        print(f"   • {e}", flush=True)
    sys.exit(1)

print(f"✅ الإعدادات صحيحة (session len={len(STRING_SESSION)})", flush=True)
if STREAM_BASE:
    print(f"🎬 Stream proxy: {STREAM_BASE}", flush=True)
if BOT_TOKEN:
    print(f"🤖 Bot API: مفعّل", flush=True)
    if not STORAGE_CHANNEL:
        print(f"❌ STORAGE_CHANNEL غير محدّد! البوت يحتاج قناة تخزين.", flush=True)
        print(f"   أنشئ قناة خاصة وأضفها كسر STORAGE_CHANNEL", flush=True)
        sys.exit(1)
    print(f"📦 Storage channel: {STORAGE_CHANNEL}", flush=True)

# ═══════════════════════════════════════════════════════════
#  Caption regex
# ═══════════════════════════════════════════════════════════
CAPTION_RE = re.compile(
    r"^\s*(?P<series>.+?)\s+"
    r"(?:الموسم|season|s)\s*[:\-]?\s*(?P<season>\d+)\s+"
    r"(?:الحلقة|episode|ep|e)\s*[:\-]?\s*(?P<episode>\d+)\s*$",
    re.IGNORECASE | re.UNICODE,
)


# ═══════════════════════════════════════════════════════════
#  forwardMessage → storage → file_id
# ═══════════════════════════════════════════════════════════
async def get_bot_file_id_via_forward(
    session: aiohttp.ClientSession,
    bot_token: str,
    source_chat_id: int,
    message_id: int,
    storage_chat_id: str,
) -> str:
    """
    ينسخ (forward) الرسالة إلى قناة التخزين، يستخرج file_id، ثم يحذفها.
    """
    base = f"https://api.telegram.org/bot{bot_token}"

    # 1) forwardMessage
    payload = {
        "chat_id": storage_chat_id,
        "from_chat_id": source_chat_id,
        "message_id": message_id,
    }
    try:
        async with session.post(
            f"{base}/forwardMessage",
            json=payload,
            timeout=30,
        ) as resp:
            data = await resp.json()
    except Exception as e:
        print(f"      ⚠️ forward exception: {e}", flush=True)
        return ""

    if not data.get("ok"):
        err = data.get("description", "unknown")
        print(f"      ⚠️ forwardMessage failed: {err}", flush=True)
        return ""

    new_msg = data["result"]
    new_msg_id = new_msg["message_id"]

    # 2) استخرج file_id
    file_id = ""
    if "video" in new_msg:
        file_id = new_msg["video"]["file_id"]
    elif "document" in new_msg:
        file_id = new_msg["document"]["file_id"]
    elif "animation" in new_msg:
        file_id = new_msg["animation"]["file_id"]

    # 3) احذف الرسالة من قناة التخزين
    try:
        await session.post(
            f"{base}/deleteMessage",
            json={"chat_id": storage_chat_id, "message_id": new_msg_id},
            timeout=15,
        )
    except Exception:
        pass

    return file_id


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════
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
    print(f"\n📡 القناة المصدر: {CHANNEL}", flush=True)
    try:
        chat = await client.get_chat(CHANNEL)
        channel_id = chat.id
        channel_username = getattr(chat, "username", None) or ""
        channel_title = chat.title or "القناة"
        is_public = bool(channel_username)
        print(f"   {channel_title} | ID={channel_id}", flush=True)
    except Exception as e:
        print(f"❌ فشل جلب القناة: {e}", flush=True)
        await client.stop()
        sys.exit(1)

    cid_str = str(channel_id)
    short_id = cid_str[4:] if cid_str.startswith("-100") else cid_str.lstrip("-")

    # ─── اختبار البوت ───
    if BOT_TOKEN:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/getMe",
                    timeout=15,
                ) as r:
                    d = await r.json()
                    if d.get("ok"):
                        b = d["result"]
                        print(
                            f"🤖 Bot: {b.get('first_name')} "
                            f"(@{b.get('username')})",
                            flush=True,
                        )
                    else:
                        print(f"❌ BOT_TOKEN غير صالح", flush=True)
                        sys.exit(1)
        except Exception as e:
            print(f"⚠️ {e}", flush=True)

    # ─── قراءة الرسائل ───
    series_map = {}
    count = 0
    skipped = 0
    with_file_id = 0
    failed_file_id = 0

    print(f"\n📥 قراءة السجل (limit={HISTORY_LIMIT})...", flush=True)

    async with aiohttp.ClientSession() as http:
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

            # ─── file_id عبر forward إلى storage ───
            file_id = ""
            if BOT_TOKEN and STORAGE_CHANNEL:
                file_id = await get_bot_file_id_via_forward(
                    http,
                    BOT_TOKEN,
                    channel_id,
                    msg.id,
                    STORAGE_CHANNEL,
                )
                if not file_id:
                    failed_file_id += 1
                # rate limit: تأخير بسيط بين الطلبات
                await asyncio.sleep(0.5)

            if file_id:
                with_file_id += 1

            # ─── video_url ───
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
                    f"   ... {count} | "
                    f"file_id: {with_file_id} ✅ / {failed_file_id} ❌",
                    flush=True,
                )

    await client.stop()

    print(f"\n📊 إحصائيات:", flush=True)
    print(f"   حلقات: {count}", flush=True)
    print(f"   file_id: {with_file_id} ✅", flush=True)
    if failed_file_id:
        print(f"   فشل: {failed_file_id} ❌", flush=True)
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
