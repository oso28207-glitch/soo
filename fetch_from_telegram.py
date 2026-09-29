#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_from_telegram.py — جلب البيانات من قنوات Telegram"""

import os
import re
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional

from pyrogram import Client
from pyrogram.errors import FloodWait

from classify import detect_type

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
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "5000"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "2000"))

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
    "النص الموسم الثاني": ("النص", 2),
    "البيت بيتك": ("البيت بيتي", 1),
    "البيت بيتك 2": ("البيت بيتي", 2),
    "الخياط الموسم الثاني": ("الخياط", 2),
    "الخياط الموسم الأول": ("الخياط", 1),
}


def apply_name_correction(name: str, season: int):
    name = name.strip()
    if name in NAME_CORRECTIONS:
        corrected, corrected_season = NAME_CORRECTIONS[name]
        return corrected, max(season, corrected_season)
    return name, season


SYMBOL_CHARS = r'[_\-–—\[\]\(\)\{\}〖〗<>«»""\'\`\~\!\?\.,:;\/\\\|\+\=\^\&\*\%\$#@♦◆●▪▫◦•★☆✦✧✪✩✫✬✭✮✯]'
DECORATIVE_PATTERNS = [
    re.compile(r"[\U0001F300-\U0001F9FF]+"),
    re.compile(r"[★☆✦✧✪✩✫✬✭✮✯♦◆●▪▫◦•]+"),
    re.compile(r"[─═━┄┅┈┉]+"),
    re.compile(r"[◄►◄►▲▼◀▶]+"),
]


def normalize_text(text: str) -> str:
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
    re.compile(r"\bSeason\s*(\d{1,2})\b", re.I),
]
PART_PATTERNS = [
    re.compile(r"(?:الجزء|جزء)\s*(\d+)", re.I),
    re.compile(r"\bPart\s*(\d+)\b", re.I),
]
MOVIE_PREFIXES = [re.compile(r"^(?:فيلم|فيلمو|movie|film)\s+", re.I)]
SERIES_PREFIXES = [re.compile(r"^(?:مسلسل|series)\s+", re.I)]


def parse_caption(caption: str) -> Optional[dict]:
    if not caption:
        return None
    lines = caption.strip().split("\n")
    raw = lines[0].strip() if lines else caption.strip()
    if not raw:
        return None
    text = normalize_text(raw)
    if not text:
        return None

    episode = None
    for pat in EPISODE_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                episode = int(m.group(1))
                break
            except (ValueError, IndexError, TypeError):
                pass

    season = 1
    for pat in SEASON_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                season = int(m.group(1))
                break
            except (ValueError, IndexError, TypeError):
                pass

    part = None
    for pat in PART_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                part = int(m.group(1))
                break
            except (ValueError, IndexError, TypeError):
                pass

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

    episode_count = 1 if episode is not None else 1
    content_type = detect_type(text, episode_count)
    if is_movie_prefix:
        content_type = "movie"
    elif is_series_prefix:
        content_type = "series"

    name = text
    name = re.sub(r"(?:الحلقة|حلقة|الحلقه|حلقه)\s*\d+", "", name, flags=re.I)
    name = re.sub(r"(?:الموسم|موسم)\s*\d+", "", name, flags=re.I)
    name = re.sub(r"(?:الجزء|جزء)\s*\d+", "", name, flags=re.I)
    name = re.sub(r"\bS\d{1,2}\s*E\d{1,4}\b", "", name, flags=re.I)
    name = re.sub(r"\bS\d{1,2}\b", "", name, flags=re.I)
    name = re.sub(r"\bE\d{1,4}\b", "", name, flags=re.I)
    name = re.sub(r"\b(?:Episode|EP|Part|Season)\s*\d+\b", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" -–—.,")
    name = name.strip()
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


def load_existing_data() -> dict:
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "series" in data:
                return data
        except Exception as e:
            log.warning(f"data.json تالف: {e}")
    return {"channels": [], "series": []}


def save_data(data: dict):
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_or_create_series(data, name):
    for s in data.get("series", []):
        if s.get("name") == name:
            return s
    new_s = {
        "name": name,
        "type": "",
        "origin": "",
        "poster_url": "",
        "poster_backdrop": "",
        "tmdb_rating": 0,
        "tmdb_year": "",
        "tmdb_overview": "",
        "description": "",
        "seasons": {},
    }
    data.setdefault("series", []).append(new_s)
    return new_s


def add_episode(series, season_num, episode_num, ep_data):
    seasons = series.setdefault("seasons", {})
    skey = str(season_num)
    seasons.setdefault(skey, [])

    for existing in seasons[skey]:
        if (
            existing.get("message_id") == ep_data.get("message_id")
            and existing.get("source_channel") == ep_data.get("source_channel")
        ):
            return
    seasons[skey].append(ep_data)


def process_message(message, source_channel):
    if not message:
        return None
    caption = message.caption or message.text or ""
    parsed = parse_caption(caption)
    if not parsed:
        return None

    media = message.video or message.document or message.audio
    if not media:
        return None

    file_size = getattr(media, "file_size", 0) or 0
    if file_size and file_size > MAX_FILE_MB * 1024 * 1024:
        log.info(f"تخطي ملف كبير: {file_size / 1024 / 1024:.1f}MB")
        return None

    duration = getattr(media, "duration", 0) or 0
    file_id = getattr(media, "file_id", "") or ""
    file_unique_id = getattr(media, "file_unique_id", "") or ""

    thumb_url = ""
    if getattr(media, "thumbs", None):
        try:
            thumb_url = media.thumbs[0].file_id or ""
        except Exception:
            pass

    tg_url = ""
    try:
        if hasattr(message, "link") and message.link:
            tg_url = message.link
    except Exception:
        pass
    if not tg_url:
        ch = source_channel.lstrip("@")
        tg_url = f"https://t.me/{ch}/{message.id}"

    date_str = ""
    if getattr(message, "date", None):
        try:
            date_str = message.date.isoformat()
        except Exception:
            pass

    ep_data = {
        "message_id": message.id,
        "source_channel": source_channel,
        "file_id": file_id,
        "file_unique_id": file_unique_id,
        "file_size": file_size,
        "duration": duration,
        "thumb_url": thumb_url,
        "telegram_url": tg_url,
        "date": date_str,
    }

    return {
        "name": parsed["name"],
        "season": parsed["season"],
        "episode": parsed["episode"],
        "content_type": parsed["content_type"],
        "ep_data": ep_data,
    }


async def fetch_channel(client, channel, source_label, data, progress, limit):
    log.info(f"جلب من {source_label} ({channel}) ...")
    count = 0
    last_id = progress.get(f"last_id_{source_label}", 0)

    try:
        async for message in client.get_chat_history(channel, limit=limit):
            if message.id <= last_id:
                break
            try:
                result = process_message(message, channel)
                if result:
                    series = find_or_create_series(data, result["name"])
                    add_episode(
                        series,
                        result["season"],
                        result["episode"],
                        result["ep_data"],
                    )
                    count += 1
                    if count % 50 == 0:
                        log.info(f"  معالجة {count} حلقة...")
                progress[f"last_id_{source_label}"] = message.id
            except FloodWait as e:
                wait = e.value + 5
                log.warning(f"FloodWait: ننتظر {wait}s ...")
                await asyncio.sleep(wait)
            except Exception as e:
                log.error(f"خطأ في معالجة رسالة: {e}")
                continue
    except Exception as e:
        log.error(f"فشل جلب {source_label}: {e}")

    log.info(f"تم جلب {count} حلقة من {source_label}")
    return count


async def main():
    if not API_ID or not API_HASH:
        log.error("API_ID / API_HASH غير محددين")
        raise SystemExit(1)

    data = load_existing_data()
    progress = load_progress()

    log.info(f"بيانات موجودة: {len(data.get('series', []))} عمل")

    clients = []

    if STRING_SESSION and CHANNEL_CLEAN:
        try:
            c1 = Client(
                "fetcher1",
                api_id=int(API_ID),
                api_hash=API_HASH,
                session_string=STRING_SESSION,
            )
            await c1.start()
            clients.append((c1, CHANNEL_CLEAN, "ch1"))
        except Exception as e:
            log.error(f"فشل بدء client1: {e}")

    if STRING_SESSION2 and CHANNEL2_CLEAN:
        try:
            c2 = Client(
                "fetcher2",
                api_id=int(API_ID),
                api_hash=API_HASH,
                session_string=STRING_SESSION2,
            )
            await c2.start()
            clients.append((c2, CHANNEL2_CLEAN, "ch2"))
        except Exception as e:
            log.error(f"فشل بدء client2: {e}")

    if not clients:
        log.error("لا يوجد عملاء صالحون")
        raise SystemExit(1)

    total = 0
    for client, channel, label in clients:
        try:
            n = await fetch_channel(client, channel, label, data, progress, HISTORY_LIMIT)
            total += n
        finally:
            try:
                await client.stop()
            except Exception:
                pass

    save_data(data)
    save_progress(progress)

    log.info(f"✅ إجمالي الحلقات المضافة: {total}")
    log.info(f"حفظ {DATA_FILE.name} و {PROGRESS_FILE.name}")


if __name__ == "__main__":
    asyncio.run(main())