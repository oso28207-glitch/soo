#!/usr/bin/env python3
"""
fetch_from_telegram.py — v2 (Rate-limit aware)
- يحترم حدود Telegram (retry_after)
- يتباطأ تلقائياً عند الوصول للحد
- يحفظ التقدم للاستئناف
- يعيد المحاولة عند الفشل
"""
import os
import re
import sys
import json
import time
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
PROGRESS_FILE = Path("forward_progress.json")  # لحفظ التقدم

# ═══════════════════════════════════════════════════════════
#  Rate Limiting
# ═══════════════════════════════════════════════════════════
MIN_DELAY = 4.0              # ثانية بين كل طلب (آمن: ~15/دقيقة)
MAX_DELAY = 30.0             # حد أقصى للتأخير التلقائي
RETRY_MAX = 5                # محاولات إعادة عند الفشل
RATE_LIMIT_SAFETY = 5        # ثواني إضافية فوق retry_after

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
    if STORAGE_CHANNEL:
        print(f"📦 Storage channel: {STORAGE_CHANNEL}", flush=True)
    else:
        print(f"❌ STORAGE_CHANNEL غير محدّد!", flush=True)
        sys.exit(1)

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
#  حفظ/قراءة التقدم
# ═══════════════════════════════════════════════════════════
def load_progress():
    """يقرأ file_id المحفوظة مسبقاً"""
    if not PROGRESS_FILE.exists():
        return {}
    try:
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        return data.get("file_ids", {})  # {message_id: file_id}
    except Exception:
        return {}


def save_progress(file_ids: dict):
    """يحفظ file_id لاستخدامها في التشغيل التالي"""
    try:
        PROGRESS_FILE.write_text(
            json.dumps(
                {"file_ids": file_ids, "saved_at": time.time()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"⚠️ فشل حفظ التقدم: {e}", flush=True)


# ═══════════════════════════════════════════════════════════
#  forwardMessage مع احترام retry_after
# ═══════════════════════════════════════════════════════════
class RateLimiter:
    """يتتبع التأخير الديناميكي بين الطلبات"""
    def __init__(self):
        self.delay = MIN_DELAY
        self.last_request = 0.0
        self.total_requests = 0

    def get_delay_until(self):
        """وقت الانتظار حتى الطلب التالي"""
        elapsed = time.time() - self.last_request
        wait = max(0, self.delay - elapsed)
        return wait

    def mark(self):
        self.last_request = time.time()
        self.total_requests += 1

    def slow_down(self, extra):
        """يزيد التأخير بعد rate limit"""
        self.delay = min(MAX_DELAY, self.delay + extra)
        print(f"      ⏸️ زيادة التأخير إلى {self.delay:.1f}s", flush=True)

    def speed_up(self):
        """يعود تدريجياً للتأخير الأدنى بعد نجاح متتالي"""
        if self.delay > MIN_DELAY:
            self.delay = max(MIN_DELAY, self.delay - 0.5)


async def get_bot_file_id_with_retry(
    session: aiohttp.ClientSession,
    bot_token: str,
    source_chat_id: int,
    message_id: int,
    storage_chat_id: str,
    limiter: RateLimiter,
    cached_file_id: str = "",
) -> str:
    """
    ينسخ الرسالة إلى قناة التخزين، يستخرج file_id، ثم يحذفها.
    - يحترم retry_after من Telegram
    - يعيد المحاولة تلقائياً عند الفشل
    - يستخدم cached_file_id إن وُجد
    """
    # إذا كانت محفوظة، استخدمها مباشرة
    if cached_file_id:
        return cached_file_id

    base = f"https://api.telegram.org/bot{bot_token}"

    for attempt in range(1, RETRY_MAX + 1):
        # احترم التأخير الأساسي
        wait = limiter.get_delay_until()
        if wait > 0:
            await asyncio.sleep(wait)

        # forwardMessage
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
            print(f"      ⚠️ exception: {e}", flush=True)
            await asyncio.sleep(MIN_DELAY)
            continue

        limiter.mark()

        # ─── معالجة الردود ───
        if data.get("ok"):
            new_msg = data["result"]
            new_msg_id = new_msg["message_id"]

            # استخرج file_id
            file_id = ""
            if "video" in new_msg:
                file_id = new_msg["video"]["file_id"]
            elif "document" in new_msg:
                file_id = new_msg["document"]["file_id"]
            elif "animation" in new_msg:
                file_id = new_msg["animation"]["file_id"]

            # احذف الرسالة
            try:
                async with session.post(
                    f"{base}/deleteMessage",
                    json={"chat_id": storage_chat_id, "message_id": new_msg_id},
                    timeout=15,
                ) as r:
                    pass
            except Exception:
                pass

            # نجاح → تسريع تدريجي
            limiter.speed_up()
            return file_id

        # ─── Rate limit ───
        err = data.get("description", "")
        m = re.search(r"retry after (\d+)", err)
        if m:
            retry_after = int(m.group(1))
            wait_time = retry_after + RATE_LIMIT_SAFETY
            print(
                f"      🚫 Rate limit (محاولة {attempt}/{RETRY_MAX})"
                f" — انتظار {wait_time}s...",
                flush=True,
            )
            limiter.slow_down(extra=2.0)
            await asyncio.sleep(wait_time)
            continue

        # ─── أخطاء أخرى ───
        if "not enough rights" in err.lower():
            print(f"      ❌ البوت ليس Admin!", flush=True)
            return ""
        if "message to forward not found" in err.lower():
            return ""
        if "chat not found" in err.lower():
            print(f"      ❌ قناة التخزين غير موجودة!", flush=True)
            return ""

        print(f"      ⚠️ فشل: {err[:100]}", flush=True)
        await asyncio.sleep(MIN_DELAY)
        return ""

    # استنفدت المحاولات
    print(f"      ❌ استنفدت المحاولات للرسالة {message_id}", flush=True)
    return ""


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════
async def main():
    # ─── اقرأ التقدم السابق ───
    cached_ids = load_progress()
    if cached_ids:
        print(f"💾 تم العثور على {len(cached_ids)} file_id محفوظة", flush=True)

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
    from_cache = 0
    failed_file_id = 0

    limiter = RateLimiter()
    start_time = time.time()

    # افتح ملف التخزين المؤقت
    new_cached_ids = dict(cached_ids)

    print(f"\n📥 قراءة السجل (limit={HISTORY_LIMIT})...", flush=True)
    print(f"⏱️ التأخير الأساسي: {MIN_DELAY}s بين الطلبات\n", flush=True)

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

            # ─── file_id مع التخزين المؤقت ───
            file_id = ""
            if BOT_TOKEN and STORAGE_CHANNEL:
                # إن كانت محفوظة مسبقاً، استخدمها
                cached = cached_ids.get(str(msg.id), "")
                if cached:
                    file_id = cached
                    from_cache += 1
                else:
                    file_id = await get_bot_file_id_with_retry(
                        http, BOT_TOKEN, channel_id, msg.id,
                        STORAGE_CHANNEL, limiter,
                    )
                    if file_id:
                        new_cached_ids[str(msg.id)] = file_id

                    # احفظ التقدم كل 25 حلقة
                    if count % 25 == 0 and count > 0:
                        save_progress(new_cached_ids)

                if file_id and not cached:
                    with_file_id += 1
                elif not file_id:
                    failed_file_id += 1

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

            # ─── سجل التقدم كل 25 ───
            if count % 25 == 0:
                elapsed = time.time() - start_time
                rate = count / elapsed if elapsed > 0 else 0
                print(
                    f"   ... {count} | "
                    f"✅ جديد: {with_file_id} | "
                    f"💾 محفوظ: {from_cache} | "
                    f"❌ فشل: {failed_file_id} | "
                    f"⏱️ {elapsed:.0f}s (~{rate:.2f}/s)",
                    flush=True,
                )

    # احفظ التقدم النهائي
    save_progress(new_cached_ids)
    await client.stop()

    elapsed = time.time() - start_time
    print(f"\n📊 إحصائيات:", flush=True)
    print(f"   حلقات: {count}", flush=True)
    print(f"   ✅ file_id جديدة: {with_file_id}", flush=True)
    print(f"   💾 من التخزين المؤقت: {from_cache}", flush=True)
    if failed_file_id:
        print(f"   ❌ فشل: {failed_file_id}", flush=True)
    print(f"   متجاهلة: {skipped}", flush=True)
    print(f"   مسلسلات: {len(series_map)}", flush=True)
    print(f"   ⏱️ الوقت: {elapsed:.0f}s ({elapsed/60:.1f} دقيقة)", flush=True)
    print(f"   💾 إجمالي file_id محفوظة: {len(new_cached_ids)}", flush=True)

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
