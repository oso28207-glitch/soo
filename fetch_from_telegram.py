#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_from_telegram.py — جالب بيانات المسلسلات من قنوات Telegram
يدعم قناتين + حماية من التكرار + تنظيف محسّن للأسماء
"""

import os
import re
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional

from pyrogram import Client
from pyrogram.errors import FloodWait

# ═══════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════
ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
PROGRESS_FILE = ROOT / "forward_progress.json"

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
CHANNEL = (os.getenv("CHANNEL") or "").strip()
CHANNEL2 = (os.getenv("CHANNEL2") or "").strip()
CHANNEL_CLEAN = CHANNEL.lstrip("@")
CHANNEL2_CLEAN = CHANNEL2.lstrip("@") if CHANNEL2 else ""

STRING_SESSION = os.getenv("STRING_SESSION", "")
STRING_SESSION2 = os.getenv("STRING_SESSION2", "")
STORAGE_CHANNEL = os.getenv("STORAGE_CHANNEL", "")
STREAM_BASE = os.getenv("STREAM_BASE", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "5000"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "2000"))

BASE_DELAY = 4.0
MAX_DELAY = 30.0
SAFETY_BUFFER = 5.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch")


# ═══════════════════════════════════════════════════════════════
# ★★★ أنماط التنظيف المُحسّنة — الإصلاح الرئيسي ★★★
# ═══════════════════════════════════════════════════════════════
CLEANUP_PATTERNS = [
    # إزالة البادئات
    re.compile(r"^(?:مشاهدة|تحميل)\s+", re.I),
    re.compile(r"^(?:مسلسل|فيلم|فيلمو)\s+", re.I),

    # ★★★ إزالة "حلقة N" و "الحلقة N" بجميع الصيغ ★★★
    re.compile(r"\s+(?:الحلقة|حلقة|الحلقه|حلقه)\s*\d+.*$", re.I),

    # إزالة "الموسم N" و "موسم N"
    re.compile(r"\s+(?:الموسم|موسم)\s*\d+.*$", re.I),

    # إزالة "S01E01" أو "S01"
    re.compile(r"\s+S\d+\s*E\d+.*$", re.I),
    re.compile(r"\s+S\d+\s*$", re.I),

    # إزالة "E01" في النهاية
    re.compile(r"\s+E\d+\s*$", re.I),

    # إزالة الامتدادات
    re.compile(r"\.(?:mp4|mkv|avi|mov|wmv|flv|webm)$", re.I),

    # إزالة الأقواس والرموز
    re.compile(r"\[[^\]]*\]"),
    re.compile(r"\([^)]*\)"),
    re.compile(r"【[^】]*】"),
    re.compile(r"_+"),

    # إزالة الشرطات في النهاية
    re.compile(r"\s*[-–—]+\s*$"),
    re.compile(r"^\s*[-–—]+\s*"),
]


def clean_series_name(name: str) -> str:
    """تنظيف اسم المسلسل من الكلمات الزائدة"""
    if not name:
        return ""
    name = name.strip()
    for pat in CLEANUP_PATTERNS:
        name = pat.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "غير معروف"


# ═══════════════════════════════════════════════════════════════
# أنماط تحليل الـ Captions
# ═══════════════════════════════════════════════════════════════
PATTERNS = {
    "series_ar": re.compile(r"(?:المسلسل|مسلسل|اسم\s*المسلسل)\s*[:\-]?\s*(.+?)(?:\n|$)", re.I),
    "series_en": re.compile(r"^([^\n—\-:]+?)(?:\s*[—\-:]|\s*$)", re.I),
    "season_ar": re.compile(r"(?:الموسم|موسم)\s*[:\-]?\s*(\d+)", re.I),
    "season_en": re.compile(r"\bS(\d{1,2})\b", re.I),
    "episode_ar": re.compile(r"(?:الحلقة|حلقة|الحلقه|حلقه)\s*[:\-]?\s*(\d+)", re.I),
    "episode_en": re.compile(r"\bE(\d{1,3})\b", re.I),
    "episode_word": re.compile(r"\b(?:Episode)\s*[:\-]?\s*(\d{1,3})\b", re.I),
}


def parse_caption(caption: str) -> Optional[dict]:
    if not caption:
        return None
    caption = caption.strip()

    # الموسم
    season = 1
    for key in ("season_ar", "season_en"):
        m = PATTERNS[key].search(caption)
        if m:
            try:
                season = int(m.group(1))
                break
            except (ValueError, IndexError):
                pass

    # الحلقة
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

    # اسم المسلسل
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
# التخزين مع حماية شاملة
# ═══════════════════════════════════════════════════════════════
def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_message_id": 0, "forwarded_ids": [], "series_map": {}}


def save_progress(progress: dict):
    PROGRESS_FILE.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clean_duplicates(data: dict) -> dict:
    """إزالة التكرار من جميع المستويات"""
    if not isinstance(data, dict):
        return {"channels": [], "series": []}

    seen_series = set()
    clean_series = []

    for s in data.get("series", []):
        if not isinstance(s, dict):
            continue
        name = s.get("name", "").strip()
        if not name or name in seen_series:
            continue
        seen_series.add(name)

        # إزالة تكرار الحلقات
        clean_seasons = {}
        seasons = s.get("seasons", {})
        if isinstance(seasons, dict):
            for season_key, episodes in seasons.items():
                if not isinstance(episodes, list):
                    continue
                seen_mids = set()
                clean_eps = []
                for ep in episodes:
                    if not isinstance(ep, dict):
                        continue
                    mid = str(ep.get("message_id", "")).strip()
                    if mid and mid in seen_mids:
                        continue
                    if mid:
                        seen_mids.add(mid)
                    clean_eps.append(ep)
                if clean_eps:
                    clean_seasons[season_key] = clean_eps

        s["seasons"] = clean_seasons
        clean_series.append(s)

    data["series"] = clean_series
    return data


def load_existing_data() -> dict:
    """حماية ضد الملف التالف"""
    if DATA_FILE.exists():
        try:
            raw = DATA_FILE.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict) and "series" in data:
                return clean_duplicates(data)
        except Exception as e:
            log.warning(f"data.json تالف - سيتم إعادة البناء: {e}")
    return {"channels": [], "stream_base": STREAM_BASE, "series": []}


def save_data(data: dict):
    """حفظ آمن مع التحقق"""
    clean_data = clean_duplicates(data)
    try:
        content = json.dumps(clean_data, ensure_ascii=False, indent=2)
        json.loads(content)
        DATA_FILE.write_text(content, encoding="utf-8")
        size_kb = DATA_FILE.stat().st_size / 1024
        log.info(f"حفظ {DATA_FILE.name} ({size_kb:.1f} KB)")
    except Exception as e:
        log.error(f"فشل حفظ data.json: {e}")


def find_or_create_series(data: dict, name: str) -> dict:
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


def add_episode(series: dict, season: int, episode: dict) -> bool:
    season_key = str(season)
    if season_key not in series["seasons"]:
        series["seasons"][season_key] = []
    existing = series["seasons"][season_key]
    msg_id = episode.get("message_id")

    for ep in existing:
        if ep.get("message_id") == msg_id:
            ep.update(episode)
            return False

    existing.append(episode)
    existing.sort(key=lambda e: int(e.get("episode", 0)))
    return True


# ═══════════════════════════════════════════════════════════════
# استخراج معلومات الملف
# ═══════════════════════════════════════════════════════════════
def extract_media_info(msg) -> Optional[dict]:
    media = None
    media_type = None

    if msg.video:
        media, media_type = msg.video, "video"
    elif msg.document:
        media, media_type = msg.document, "document"
    elif msg.animation:
        media, media_type = msg.animation, "animation"
    elif msg.audio:
        media, media_type = msg.audio, "audio"

    if not media:
        return None

    size_bytes = getattr(media, "file_size", 0) or 0
    size_mb = size_bytes / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        return None

    return {
        "file_id": getattr(media, "file_id", ""),
        "file_unique_id": getattr(media, "file_unique_id", ""),
        "file_size": size_bytes,
        "file_name": getattr(media, "file_name", "") or "",
        "mime_type": getattr(media, "mime_type", "") or "video/mp4",
        "duration": getattr(media, "duration", 0) or 0,
        "width": getattr(media, "width", 0) or 0,
        "height": getattr(media, "height", 0) or 0,
        "media_type": media_type,
    }


# ═══════════════════════════════════════════════════════════════
# معالجة رسالة
# ═══════════════════════════════════════════════════════════════
async def process_message(client: Client, msg, data: dict, progress: dict, channel: str) -> bool:
    if not msg or not msg.caption:
        return False

    parsed = parse_caption(msg.caption)
    if not parsed:
        return False

    media_info = extract_media_info(msg)
    if not media_info:
        return False

    if media_info["file_size"] < 1024 * 1024:
        return False

    if channel.startswith("-100"):
        tg_url = f"https://t.me/c/{channel.replace('-100', '')}/{msg.id}"
    elif channel.startswith("-"):
        tg_url = f"https://t.me/c/{channel.replace('-', '')}/{msg.id}"
    else:
        tg_url = f"https://t.me/{channel}/{msg.id}"

    episode = {
        "message_id": str(msg.id),
        "episode": parsed["episode"],
        "season": parsed["season"],
        "duration": media_info["duration"],
        "telegram_url": tg_url,
        "video_url": "",
        "file_id": media_info["file_id"],
        "file_unique_id": media_info["file_unique_id"],
        "file_size": media_info["file_size"],
        "mime_type": media_info["mime_type"],
        "file_name": media_info["file_name"],
        "thumb_url": "",
        "date": msg.date.isoformat() if msg.date else "",
        "source_channel": channel,
    }

    series = find_or_create_series(data, parsed["name"])
    added = add_episode(series, parsed["season"], episode)

    if added:
        log.info(
            f"[{parsed['name']}] S{parsed['season']:02d}E{parsed['episode']:02d} "
            f"({media_info['file_size'] / 1024 / 1024:.1f}MB) [{channel}]"
        )
    return added


# ═══════════════════════════════════════════════════════════════
# جلب قناة واحدة
# ═══════════════════════════════════════════════════════════════
async def fetch_channel(client: Client, channel: str, data: dict, progress: dict):
    log.info(f"جلب من @{channel}")
    count = added = skipped = errors = 0

    try:
        async for msg in client.get_chat_history(channel, limit=HISTORY_LIMIT):
            count += 1
            await asyncio.sleep(BASE_DELAY / 4)

            try:
                if await process_message(client, msg, data, progress, channel):
                    added += 1
                else:
                    skipped += 1
            except FloodWait as e:
                wait = min(e.value + SAFETY_BUFFER, MAX_DELAY)
                log.warning(f"FloodWait: {e.value}s")
                await asyncio.sleep(wait)
            except Exception as e:
                errors += 1
                log.error(f"[{channel}] رسالة {msg.id}: {e}")

            if count % 100 == 0:
                log.info(f"[{channel}] {count} رسالة | {added} مضافة")
                save_data(data)

    except FloodWait as e:
        await asyncio.sleep(min(e.value + SAFETY_BUFFER, MAX_DELAY))
    except Exception as e:
        log.error(f"خطأ في {channel}: {e}")

    log.info(f"[{channel}] اكتمل: {count} رسالة | {added} مضافة | {skipped} متجاهلة")


# ═══════════════════════════════════════════════════════════════
# إنشاء العميل
# ═══════════════════════════════════════════════════════════════
def create_client() -> Client:
    session = STRING_SESSION or STRING_SESSION2
    if not session:
        raise ValueError("يجب ضبط STRING_SESSION")
    if not API_ID or not API_HASH:
        raise ValueError("يجب ضبط API_ID و API_HASH")

    return Client(
        name="fetch_session",
        api_id=int(API_ID),
        api_hash=API_HASH,
        session_string=session,
        in_memory=True,
        workers=4,
    )


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════
async def main():
    log.info("بدء جلب البيانات")

    channels = []
    if CHANNEL_CLEAN:
        channels.append(CHANNEL_CLEAN)
    if CHANNEL2_CLEAN:
        channels.append(CHANNEL2_CLEAN)

    if not channels:
        raise ValueError("يجب ضبط CHANNEL على الأقل")

    log.info(f"القنوات: {', '.join('@' + c for c in channels)}")

    data = load_existing_data()
    data["channels"] = channels
    data["stream_base"] = STREAM_BASE
    progress = load_progress()

    total_before = sum(
        len(eps) for s in data["series"] for eps in s.get("seasons", {}).values()
    )
    log.info(f"محمّل: {len(data['series'])} عمل | {total_before} حلقة")

    client = create_client()
    try:
        async with client:
            me = await client.get_me()
            log.info(f"متصل كـ @{me.username or me.id}")
            for ch in channels:
                try:
                    await fetch_channel(client, ch, data, progress)
                except Exception as e:
                    log.error(f"فشل {ch}: {e}")
                    continue
    except Exception as e:
        err = str(e)
        if "AUTH_KEY_DUPLICATED" in err or "406" in err:
            log.error("AUTH_KEY_DUPLICATED - الجلسة مستخدمة في مكان آخر")
            raise SystemExit(1)
        raise

    save_data(data)
    save_progress(progress)

    total_series = len(data["series"])
    total_eps = sum(
        len(eps) for s in data["series"] for eps in s.get("seasons", {}).values()
    )
    with_file_id = sum(
        1 for s in data["series"]
        for eps in s.get("seasons", {}).values()
        for ep in eps if ep.get("file_id")
    )

    log.info(f"\nاكتمل الجلب:")
    log.info(f"   أعمال: {total_series}")
    log.info(f"   حلقات: {total_eps}")
    log.info(f"   مع file_id: {with_file_id}")


if __name__ == "__main__":
    asyncio.run(main())