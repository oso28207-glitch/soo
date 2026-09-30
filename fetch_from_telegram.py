#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_from_telegram.py — جالب البيانات من قنوات Telegram
★ إصلاح: كشف النمط "الاسم N" كحلقة مسلسل ★
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
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "15000"))
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


NAME_CORRECTIONS = {
    "النص التاني": ("النص", 2),
    "النص الثاني": ("النص", 2),
    "النص 2": ("النص", 2),
    "البيت بيتك": ("البيت بيتي", 1),
    "البيت بيتك 2": ("البيت بيتي", 2),
    "الخياط الموسم الثاني": ("الخياط", 2),
    "الخياط الموسم الأول": ("الخياط", 1),
}


def apply_name_correction(name, season):
    name = name.strip()
    if name in NAME_CORRECTIONS:
        corrected, cs = NAME_CORRECTIONS[name]
        return corrected, max(season, cs)
    return name, season


SYMBOL_CHARS = r'[_\-–—\[\]\(\)\{\}【】<>«»""\'\`\~\!\?\.,:;\/\\\|\+\=\^\&\*\%\$#@♦◆●▪▫◦•★☆✦✧✪✩✫✬✭✮✯]'

DECORATIVE_PATTERNS = [
    re.compile(r"[\U0001F300-\U0001F9FF]+"),
    re.compile(r"[★☆✦✧✪✩✫✬✭✮✯♦◆●▪▫◦•]+"),
    re.compile(r"[─═━┄┅┈┉]+"),
    re.compile(r"[◄►◄►▲▼◀▶]+"),
]


def normalize_text(text):
    if not text:
        return ""
    for pat in DECORATIVE_PATTERNS:
        text = pat.sub(" ", text)
    text = re.sub(SYMBOL_CHARS, " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


EPISODE_PATTERNS = [
    re.compile(r"(?:الحلقة|حلقة|الحلقه|حلقه)\s*(\d+)", re.I),
    re.compile(r"\b(?:Episode|EP)\s*(\d{1,4})\b", re.I),
    re.compile(r"\bE(\d{1,4})\b", re.I),
]

SEASON_PATTERNS = [
    re.compile(r"(?:الموسم|موسم)\s*(\d+)", re.I),
    re.compile(r"\bS(\d{1,2})\b", re.I),
]

PART_PATTERNS = [
    re.compile(r"(?:الجزء|جزء)\s*(\d+)", re.I),
    re.compile(r"\bPart\s*(\d+)\b", re.I),
]

MOVIE_PREFIXES = [re.compile(r"^(?:فيلم|فيلمو|movie|film)\s+", re.I)]
SERIES_PREFIXES = [re.compile(r"^(?:مسلسل|series)\s+", re.I)]


# ★★★ إصلاح: كشف "الاسم N" في النهاية ★★★
TRAILING_NUM = re.compile(r"^(.+?)\s+(\d{1,3})(?:\s+الاخير[هة]?)?\s*$", re.I)

# أعمال لا يجب تقسيمها (فيلم برقم في الاسم أو سلسلة أفلام)
MOVIE_EXCEPTIONS = {
    "يوم 13", "19 ب", "24 ساعة", "30 يوم", "24 ساعه",
    "الفيل الازرق", "الفيل الأزرق", "الكنز", "ولاد رزق",
    "الجزيرة", "جحيم في الهند", "ديدو",
    "ما تراه ليس كما يبدو",  # احتياطي
}


def parse_caption(caption):
    if not caption:
        return None
    lines = caption.strip().split("\n")
    raw = lines[0].strip() if lines else caption.strip()
    if not raw:
        return None
    text = normalize_text(raw)
    if not text:
        return None

    # 1) استخراج الحلقة بالكلمات المفتاحية
    episode = None
    for pat in EPISODE_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                episode = int(m.group(1))
                break
            except (ValueError, IndexError, TypeError):
                pass

    # 2) الموسم
    season = 1
    for pat in SEASON_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                season = int(m.group(1))
                break
            except (ValueError, IndexError, TypeError):
                pass

    # 3) الجزء
    part = None
    for pat in PART_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                part = int(m.group(1))
                break
            except (ValueError, IndexError, TypeError):
                pass

    # 4) البادئات
    is_movie_prefix = False
    for pat in MOVIE_PREFIXES:
        if pat.match(text):
            is_movie_prefix = True
            text = pat.sub("", text).strip()
            break

    is_series_prefix = False
    for pat in SERIES_PREFIXES:
        if pat.match(text):
            is_series_prefix = True
            text = pat.sub("", text).strip()
            break

    # ★★★ 5) إذا لم نجد حلقة صريحة، جرب نمط "الاسم N" في النهاية ★★★
    if episode is None and part is None:
        m = TRAILING_NUM.match(text)
        if m:
            base = m.group(1).strip()
            num = int(m.group(2))
            # التحقق من قائمة الاستثناءات
            base_norm = re.sub(r"\s+", " ", base).strip()
            if base_norm not in MOVIE_EXCEPTIONS and 1 <= num <= 200:
                # هذا حلقة مسلسل
                text = base_norm
                episode = num
                season = 1

    # 6) تحديد النوع
    if episode is not None:
        content_type = "series"
    elif season > 1:
        content_type = "series"
    elif part is not None:
        content_type = "movie"
    elif is_movie_prefix:
        content_type = "movie"
    elif is_series_prefix:
        content_type = "series"
    else:
        content_type = "movie"

    # 7) استخراج الاسم
    name = text
    name = re.sub(r"(?:الحلقة|حلقة|الحلقه|حلقه)\s*\d+", "", name, flags=re.I)
    name = re.sub(r"(?:الموسم|موسم)\s*\d+", "", name, flags=re.I)
    name = re.sub(r"(?:الجزء|جزء)\s*\d+", "", name, flags=re.I)
    name = re.sub(r"\bS\d{1,2}\s*E\d{1,4}\b", "", name, flags=re.I)
    name = re.sub(r"\bS\d{1,2}\b", "", name, flags=re.I)
    name = re.sub(r"\bE\d{1,4}\b", "", name, flags=re.I)
    name = re.sub(r"\b(?:Episode|EP|Part|Season)\s*\d+\b", "", name, flags=re.I)
    name = re.sub(r"\s+الاخير[هة]?\s*$", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" -–—.,")

    if not name or len(name) < 2:
        return None

    name, season = apply_name_correction(name, season)

    if content_type == "movie":
        season = 1
        episode = None

    return {
        "name": name,
        "season": season,
        "episode": episode,
        "content_type": content_type,
        "part": part,
    }


def load_progress():
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_message_id": 0, "forwarded_ids": [], "series_map": {}}


def save_progress(p):
    PROGRESS_FILE.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_duplicates(data):
    if not isinstance(data, dict):
        return {"channels": [], "series": []}
    seen_series = set()
    clean_series = []
    for s in data.get("series", []):
        if not isinstance(s, dict):
            continue
        name = s.get("name", "").strip()
        ctype = s.get("type", "series")
        name_key = f"M::{name}::{s.get('_source_channel','')}" if ctype == "movie" else f"S::{name}"
        if not name or name_key in seen_series:
            continue
        seen_series.add(name_key)
        clean_seasons = {}
        for sk, eps in s.get("seasons", {}).items():
            if not isinstance(eps, list):
                continue
            seen_keys = set()
            clean_eps = []
            for ep in eps:
                if not isinstance(ep, dict):
                    continue
                ch = str(ep.get("source_channel","")).strip()
                mid = str(ep.get("message_id","")).strip()
                key = f"{ch}|{mid}" if ch else mid
                if key and key in seen_keys:
                    continue
                if key:
                    seen_keys.add(key)
                clean_eps.append(ep)
            if clean_eps:
                clean_seasons[sk] = clean_eps
        s["seasons"] = clean_seasons
        clean_series.append(s)
    data["series"] = clean_series
    return data


def load_existing_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "series" in data:
                return clean_duplicates(data)
        except Exception as e:
            log.warning(f"data.json تالف: {e}")
    return {"channels": [], "series": []}


def save_data(data):
    clean_data = clean_duplicates(data)
    try:
        content = json.dumps(clean_data, ensure_ascii=False, indent=2)
        json.loads(content)
        DATA_FILE.write_text(content, encoding="utf-8")
        log.info(f"حفظ {DATA_FILE.name} ({DATA_FILE.stat().st_size / 1024:.1f} KB)")
    except Exception as e:
        log.error(f"فشل حفظ: {e}")


def find_or_create_series(data, name, content_type, channel):
    for s in data["series"]:
        if (s.get("name") == name and s.get("type") == content_type):
            if content_type == "movie":
                if s.get("_source_channel") == channel:
                    return s
            else:
                return s
    new_s = {
        "name": name,
        "type": content_type,
        "poster_url": "",
        "description": "",
        "seasons": {},
        "_source_channel": channel,
    }
    data["series"].append(new_s)
    return new_s


def add_episode(series, season, episode):
    sk = str(season)
    if sk not in series["seasons"]:
        series["seasons"][sk] = []
    existing = series["seasons"][sk]
    mid = episode.get("message_id")
    for ep in existing:
        if ep.get("message_id") == mid:
            ep.update(episode)
            return False
    existing.append(episode)
    existing.sort(key=lambda e: int(e.get("episode") or 0))
    return True


def extract_media_info(msg):
    media = None
    mtype = None
    if msg.video:
        media, mtype = msg.video, "video"
    elif msg.document:
        media, mtype = msg.document, "document"
    elif msg.animation:
        media, mtype = msg.animation, "animation"
    if not media:
        return None
    size = getattr(media, "file_size", 0) or 0
    if size / (1024 * 1024) > MAX_FILE_MB:
        return None
    return {
        "file_id": getattr(media, "file_id", ""),
        "file_unique_id": getattr(media, "file_unique_id", ""),
        "file_size": size,
        "file_name": getattr(media, "file_name", "") or "",
        "mime_type": getattr(media, "mime_type", "") or "video/mp4",
        "duration": getattr(media, "duration", 0) or 0,
        "width": getattr(media, "width", 0) or 0,
        "height": getattr(media, "height", 0) or 0,
        "media_type": mtype,
    }


async def process_message(client, msg, data, progress, channel):
    if not msg or not msg.caption:
        return False
    parsed = parse_caption(msg.caption)
    if not parsed:
        return False
    media = extract_media_info(msg)
    if not media:
        return False
    if media["file_size"] < 1024 * 1024:
        return False

    if channel.startswith("-100"):
        tg_url = f"https://t.me/c/{channel.replace('-100','')}/{msg.id}"
    elif channel.startswith("-"):
        tg_url = f"https://t.me/c/{channel.replace('-','')}/{msg.id}"
    else:
        tg_url = f"https://t.me/{channel}/{msg.id}"

    ep_num = parsed["episode"] if parsed["episode"] is not None else 1
    episode = {
        "message_id": str(msg.id),
        "episode": ep_num,
        "season": parsed["season"],
        "duration": media["duration"],
        "telegram_url": tg_url,
        "video_url": "",
        "file_id": media["file_id"],
        "file_unique_id": media["file_unique_id"],
        "file_size": media["file_size"],
        "mime_type": media["mime_type"],
        "file_name": media["file_name"],
        "thumb_url": "",
        "date": msg.date.isoformat() if msg.date else "",
        "source_channel": channel,
    }

    series = find_or_create_series(data, parsed["name"], parsed["content_type"], channel)
    added = add_episode(series, parsed["season"], episode)

    if added:
        icon = "🎬" if parsed["content_type"] == "movie" else "📺"
        info = f"جزء {parsed.get('part')}" if parsed.get("part") else (
            f"S{parsed['season']:02d}E{ep_num:02d}" if parsed["content_type"] == "series" else "فيلم"
        )
        log.info(f"{icon} [{parsed['name']}] {info} ({media['file_size']/1024/1024:.1f}MB) [{channel}]")
    return added


async def fetch_channel(client, channel, data, progress):
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
                await asyncio.sleep(min(e.value + SAFETY_BUFFER, MAX_DELAY))
            except Exception as e:
                errors += 1
                log.error(f"[{channel}] {msg.id}: {e}")
            if count % 100 == 0:
                log.info(f"[{channel}] {count} | {added} مضافة")
                save_data(data)
    except FloodWait as e:
        await asyncio.sleep(min(e.value + SAFETY_BUFFER, MAX_DELAY))
    except Exception as e:
        log.error(f"خطأ في {channel}: {e}")
    log.info(f"[{channel}] اكتمل: {count} | {added} مضافة | {skipped} متجاهلة")


def create_client():
    session = STRING_SESSION or STRING_SESSION2
    if not session:
        raise ValueError("يجب ضبط STRING_SESSION")
    return Client(
        name="fetch_session",
        api_id=int(API_ID),
        api_hash=API_HASH,
        session_string=session,
        in_memory=True,
        workers=4,
    )


async def main():
    log.info("بدء جلب البيانات")
    channels = [c for c in [CHANNEL_CLEAN, CHANNEL2_CLEAN] if c]
    if not channels:
        raise ValueError("يجب ضبط CHANNEL")
    log.info(f"القنوات: {', '.join('@' + c for c in channels)}")

    data = load_existing_data()
    data["channels"] = channels
    progress = load_progress()

    total_before = sum(len(eps) for s in data["series"] for eps in s.get("seasons", {}).values())
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
    except Exception as e:
        if "AUTH_KEY_DUPLICATED" in str(e) or "406" in str(e):
            log.error("AUTH_KEY_DUPLICATED")
            raise SystemExit(1)
        raise

    save_data(data)
    save_progress(progress)

    from collections import Counter
    types = Counter(s.get("type", "?") for s in data["series"])
    log.info(f"\nاكتمل:")
    log.info(f"   أعمال: {len(data['series'])}")
    for t, c in types.items():
        log.info(f"   {t}: {c}")


if __name__ == "__main__":
    asyncio.run(main())