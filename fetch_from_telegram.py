#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_from_telegram.py — جالب بيانات المسلسلات من قناة Telegram

يقرأ الرسائل من قناة المصدر، يحلّل الـ captions، ويبني:
  - data.json              (قائمة المسلسلات والحلقات مع file_id)
  - forward_progress.json  (لتتبع التقدم واستئناف العمل)

المتغيرات البيئية:
  API_ID            — من https://my.telegram.org/apps
  API_HASH          — من https://my.telegram.org/apps
  CHANNEL           — قناة المصدر (مثل: shoofcima)
  STRING_SESSION    — جلسة Pyrogram (StringSession)
  STRING_SESSION2   — جلسة احتياطية (اختياري)
  STORAGE_CHANNEL   — قناة التخزين (مثل: -1001234567890)
  STREAM_BASE       — عنوان خادم البث (اختياري)
  BOT_TOKEN         — توكن البوت (اختياري)
  HISTORY_LIMIT     — حد الرسائل (افتراضي: 5000)
  MAX_FILE_MB       — أقصى حجم ملف (افتراضي: 2000)
"""

import os
import re
import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Optional

from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError
from pyrogram.enums import MessageMediaType

# ═══════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════
ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
PROGRESS_FILE = ROOT / "forward_progress.json"

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
CHANNEL = os.getenv("CHANNEL", "")
STRING_SESSION = os.getenv("STRING_SESSION", "")
STRING_SESSION2 = os.getenv("STRING_SESSION2", "")
STORAGE_CHANNEL = os.getenv("STORAGE_CHANNEL", "")
STREAM_BASE = os.getenv("STREAM_BASE", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "5000"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "2000"))

# إعدادات معدّل الطلبات (Rate Limiting)
BASE_DELAY = 4.0           # تأخير أساسي بين الرسائل (ثوانٍ)
MAX_DELAY = 30.0           # أقصى تأخير
MAX_RETRIES = 5            # عدد محاولات الإعادة
SAFETY_BUFFER = 5.0        # هامش أمان فوق retry_after

# ═══════════════════════════════════════════════════════════════
# إعداد السجل (Logging)
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch")


# ═══════════════════════════════════════════════════════════════
# أنماط تحليل الـ Captions
# ═══════════════════════════════════════════════════════════════
# أمثلة على الـ captions المتوقعة:
#   "المسلسل: اتنين غيرنا\nالموسم: 1\nالحلقة: 5"
#   "مسلسل المصيدة — الموسم 2 الحلقة 15"
#   "اتنين غيرنا S01E05"

PATTERNS = {
    "series_ar": re.compile(r"(?:المسلسل|مسلسل|اسم\s*المسلسل)\s*[:\-]?\s*(.+?)(?:\n|$)", re.I),
    "series_en": re.compile(r"^([^\n—\-:]+?)(?:\s*[—\-:]|\s*$)", re.I),
    "season_ar": re.compile(r"(?:الموسم|موسم)\s*[:\-]?\s*(\d+)", re.I),
    "season_en": re.compile(r"\bS(\d{1,2})\b", re.I),
    "season_word": re.compile(r"\b(?:Season|sez)\s*(\d{1,2})\b", re.I),
    "episode_ar": re.compile(r"(?:الحلقة|حلقة)\s*[:\-]?\s*(\d+)", re.I),
    "episode_en": re.compile(r"\bE(\d{1,3})\b", re.I),
    "episode_word": re.compile(r"\b(?:Episode|الحلقه)\s*[:\-]?\s*(\d{1,3})\b", re.I),
}

# أنماط لتنظيف اسم المسلسل
CLEANUP_PATTERNS = [
    re.compile(r"مشاهدة\s+مسلسل\s+"),
    re.compile(r"مسلسل\s+"),
    re.compile(r"\s*الحلقة\s*\d+.*$"),
    re.compile(r"\s*الموسم\s*\d+.*$"),
    re.compile(r"\s*S\d+E\d+.*$"),
    re.compile(r"\.mp4$"),
    re.compile(r"\.mkv$"),
    re.compile(r"\.avi$"),
    re.compile(r"\[[^\]]*\]"),
    re.compile(r"\([^)]*\)"),
    re.compile(r"_+"),
]


def clean_series_name(name: str) -> str:
    """تنظيف اسم المسلسل من الكلمات الزائدة"""
    if not name:
        return ""
    name = name.strip()
    for pat in CLEANUP_PATTERNS:
        name = pat.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "غير معروف"


def parse_caption(caption: str) -> Optional[dict]:
    """
    يحلّل الـ caption ويستخرج: اسم المسلسل، الموسم، رقم الحلقة
    """
    if not caption:
        return None

    caption = caption.strip()

    # ─── الموسم ───
    season = 1
    for key in ("season_ar", "season_en", "season_word"):
        m = PATTERNS[key].search(caption)
        if m:
            try:
                season = int(m.group(1))
                break
            except (ValueError, IndexError):
                pass

    # ─── رقم الحلقة ───
    episode = None
    for key in ("episode_ar", "episode_en", "episode_word"):
        m = PATTERNS[key].search(caption)
        if m:
            try:
                episode = int(m.group(1))
                break
            except (ValueError, IndexError):
                pass

    if episode is None:
        return None

    # ─── اسم المسلسل ───
    name = ""
    m = PATTERNS["series_ar"].search(caption)
    if m:
        name = m.group(1)
    else:
        m = PATTERNS["series_en"].search(caption)
        if m:
            name = m.group(1)

    name = clean_series_name(name)
    if not name or name == "غير معروف":
        return None

    return {"name": name, "season": season, "episode": episode}


# ═══════════════════════════════════════════════════════════════
# التخزين والتقدم
# ═══════════════════════════════════════════════════════════════
def load_progress() -> dict:
    """تحميل حالة التقدم من الملف"""
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"⚠️ فشل قراءة {PROGRESS_FILE}: {e}")
    return {"last_message_id": 0, "forwarded_ids": [], "series_map": {}}


def save_progress(progress: dict):
    """حفظ حالة التقدم"""
    PROGRESS_FILE.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_existing_data() -> dict:
    """تحميل data.json الحالي (للاستئناف)"""
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"⚠️ فشل قراءة {DATA_FILE}: {e}")
    return {"channel": CHANNEL, "stream_base": STREAM_BASE, "series": []}


def save_data(data: dict):
    """حفظ data.json"""
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    size_kb = DATA_FILE.stat().st_size / 1024
    log.info(f"💾 حفظ {DATA_FILE.name} ({size_kb:.1f} KB)")


def find_or_create_series(data: dict, name: str) -> dict:
    """يبحث عن مسلسل بالاسم أو ينشئ واحداً جديداً"""
    for s in data["series"]:
        if s.get("name") == name:
            return s
    new_series = {
        "name": name,
        "poster_url": "",
        "description": "",
        "seasons": {},
    }
    data["series"].append(new_series)
    return new_series


def add_episode(series: dict, season: int, episode: dict):
    """يضيف حلقة إلى المسلسل (يتجنب التكرار بـ message_id)"""
    season_key = str(season)
    if season_key not in series["seasons"]:
        series["seasons"][season_key] = []

    existing = series["seasons"][season_key]
    msg_id = episode.get("message_id")

    # تجنب التكرار
    for ep in existing:
        if ep.get("message_id") == msg_id:
            # تحديث البيانات إن وُجدت
            ep.update(episode)
            return False

    existing.append(episode)
    # ترتيب حسب رقم الحلقة
    existing.sort(key=lambda e: int(e.get("episode", 0)))
    return True


# ═══════════════════════════════════════════════════════════════
# استخراج معلومات الملف من الرسالة
# ═══════════════════════════════════════════════════════════════
def extract_media_info(msg) -> Optional[dict]:
    """
    يستخرج معلومات الفيديو/المستند من رسالة Pyrogram
    يعيد: {file_id, file_unique_id, size, duration, mime_type, file_name, thumb_url}
    """
    media = None
    media_type = None

    if msg.video:
        media = msg.video
        media_type = "video"
    elif msg.document:
        media = msg.document
        media_type = "document"
    elif msg.animation:
        media = msg.animation
        media_type = "animation"
    elif msg.audio:
        media = msg.audio
        media_type = "audio"

    if not media:
        return None

    # التحقق من حجم الملف
    size_bytes = getattr(media, "file_size", 0) or 0
    size_mb = size_bytes / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        log.warning(f"⚠️ الملف {size_mb:.1f}MB يتجاوز الحد ({MAX_FILE_MB}MB)")
        return None

    info = {
        "file_id": getattr(media, "file_id", ""),
        "file_unique_id": getattr(media, "file_unique_id", ""),
        "file_size": size_bytes,
        "file_name": getattr(media, "file_name", "") or "",
        "mime_type": getattr(media, "mime_type", "") or "video/mp4",
        "duration": getattr(media, "duration", 0) or 0,
        "width": getattr(media, "width", 0) or 0,
        "height": getattr(media, "height", 0) or 0,
        "thumb_url": "",
        "media_type": media_type,
    }

    return info


# ═══════════════════════════════════════════════════════════════
# معالجة رسالة واحدة
# ═══════════════════════════════════════════════════════════════
async def process_message(client: Client, msg, data: dict, progress: dict) -> bool:
    """
    يعالج رسالة واحدة: يحلل الـ caption، يستخرج معلومات الملف،
    ويضيفها إلى data.json
    يعيد True إذا تمت الإضافة بنجاح
    """
    # تجاهل الرسائل الفارغة
    if not msg or not msg.caption:
        return False

    # تحليل الـ caption
    parsed = parse_caption(msg.caption)
    if not parsed:
        return False

    # استخراج معلومات الملف
    media_info = extract_media_info(msg)
    if not media_info:
        return False

    # تجاهل الملفات الصغيرة جداً (< 1MB)
    if media_info["file_size"] < 1024 * 1024:
        return False

    # بناء كائن الحلقة
    tg_url = f"https://t.me/{CHANNEL}/{msg.id}" if not CHANNEL.startswith("-") \
             else f"https://t.me/c/{CHANNEL.replace('-100', '')}/{msg.id}"

    episode = {
        "message_id": str(msg.id),
        "episode": parsed["episode"],
        "season": parsed["season"],
        "duration": media_info["duration"],
        "telegram_url": tg_url,
        "video_url": "",  # يُبنى في build_all.py من file_id
        "file_id": media_info["file_id"],
        "file_unique_id": media_info["file_unique_id"],
        "file_size": media_info["file_size"],
        "mime_type": media_info["mime_type"],
        "file_name": media_info["file_name"],
        "thumb_url": media_info["thumb_url"],
        "date": msg.date.isoformat() if msg.date else "",
    }

    # إضافة إلى المسلسل
    series = find_or_create_series(data, parsed["name"])
    added = add_episode(series, parsed["season"], episode)

    if added:
        log.info(
            f"✅ [{parsed['name']}] S{parsed['season']:02d}E{parsed['episode']:02d} "
            f"({media_info['file_size'] / 1024 / 1024:.1f}MB)"
        )

    return added


# ═══════════════════════════════════════════════════════════════
# الجلب الرئيسي
# ═══════════════════════════════════════════════════════════════
async def fetch_history(client: Client, data: dict, progress: dict):
    """يجلب الرسائل من القناة ويعالجها"""
    log.info(f"📥 جلب حتى {HISTORY_LIMIT} رسالة من @{CHANNEL}")

    count = 0
    added = 0
    skipped = 0
    errors = 0
    last_id = 0

    try:
        async for msg in client.get_chat_history(CHANNEL, limit=HISTORY_LIMIT):
            count += 1
            last_id = msg.id

            # تأخير لتجنب FloodWait
            await asyncio.sleep(BASE_DELAY / 4)

            try:
                if await process_message(client, msg, data, progress):
                    added += 1
                else:
                    skipped += 1
            except FloodWait as e:
                wait = min(e.value + SAFETY_BUFFER, MAX_DELAY)
                log.warning(f"⏳ FloodWait: {e.value}s — انتظار {wait:.1f}s")
                await asyncio.sleep(wait)
            except Exception as e:
                errors += 1
                log.error(f"❌ خطأ في الرسالة {msg.id}: {e}")

            # طباعة تقدم كل 50 رسالة
            if count % 50 == 0:
                log.info(f"📊 تقدم: {count} رسالة | {added} مضافة | {skipped} متجاهلة | {errors} أخطاء")

            # حفظ دوري كل 100 رسالة
            if count % 100 == 0:
                progress["last_message_id"] = last_id
                save_data(data)
                save_progress(progress)

    except FloodWait as e:
        wait = min(e.value + SAFETY_BUFFER, MAX_DELAY)
        log.warning(f"⏳ FloodWait عام: {e.value}s")
        await asyncio.sleep(wait)
    except Exception as e:
        log.error(f"❌ خطأ في get_chat_history: {e}")

    progress["last_message_id"] = last_id

    log.info(f"\n📊 الإحصائيات:")
    log.info(f"   إجمالي الرسائل: {count}")
    log.info(f"   حلقات مضافة: {added}")
    log.info(f"   متجاهلة: {skipped}")
    log.info(f"   أخطاء: {errors}")


# ═══════════════════════════════════════════════════════════════
# إنشاء العميل
# ═══════════════════════════════════════════════════════════════
def create_client() -> Client:
    """ينشئ عميل Pyrogram مع أفضل جلسة متاحة"""
    session = STRING_SESSION or STRING_SESSION2
    if not session:
        raise ValueError("❌ يجب ضبط STRING_SESSION أو STRING_SESSION2")

    if not API_ID or not API_HASH:
        raise ValueError("❌ يجب ضبط API_ID و API_HASH")

    client = Client(
        name="fetch_session",
        api_id=int(API_ID),
        api_hash=API_HASH,
        session_string=session,
        in_memory=True,
        workers=4,
    )
    return client


# ═══════════════════════════════════════════════════════════════
# الدالة الرئيسية
# ═══════════════════════════════════════════════════════════════
async def main():
    log.info("🚀 بدء جلب البيانات من Telegram")

    # التحقق من المتغيرات
    if not CHANNEL:
        raise ValueError("❌ يجب ضبط CHANNEL")

    # تحميل البيانات والتقدم
    data = load_existing_data()
    data["channel"] = CHANNEL
    data["stream_base"] = STREAM_BASE
    progress = load_progress()

    log.info(f"📂 مسلسلات محمّلة: {len(data['series'])}")
    total_episodes = sum(
        len(eps) for s in data["series"] for eps in s.get("seasons", {}).values()
    )
    log.info(f"🎬 حلقات محمّلة: {total_episodes}")

    # إنشاء العميل والاتصال
    client = create_client()

    async with client:
        me = await client.get_me()
        log.info(f"✅ متصل كـ @{me.username or me.id}")

        # جلب الرسائل
        await fetch_history(client, data, progress)

    # الحفظ النهائي
    save_data(data)
    save_progress(progress)

    # إحصائيات نهائية
    total_series = len(data["series"])
    total_eps = sum(
        len(eps) for s in data["series"] for eps in s.get("seasons", {}).values()
    )
    with_file_id = sum(
        1
        for s in data["series"]
        for eps in s.get("seasons", {}).values()
        for ep in eps
        if ep.get("file_id")
    )

    log.info(f"\n✨ اكتمل الجلب:")
    log.info(f"   مسلسلات: {total_series}")
    log.info(f"   حلقات: {total_eps}")
    log.info(f"   مع file_id: {with_file_id}")


if __name__ == "__main__":
    asyncio.run(main())
