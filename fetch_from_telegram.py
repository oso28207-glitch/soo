#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_from_telegram.py — جالب البيانات من قنوات Telegram
تصنيف ذكي حسب بنية الـ Caption
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


def apply_name_correction(name: str, season: int) -> tuple:
    name = name.strip()
    if name in NAME_CORRECTIONS:
        corrected, corrected_season = NAME_CORRECTIONS[name]
        return corrected, max(season, corrected_season)
    return name, season


SYMBOL_CHARS = r'[_\-–—\[\]\(\)\{\}【】<>«»""\'\`\~\!\?\.,:;\/\\\|\+\=\^\&\*\%\$#@♦◆●▪▫◦•★☆✦✧✪✩✫✬✭✮✯]'

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

MOVIE_PREFIXES = [
    re.compile(r"^(?:فيلم|فيلمو|movie|film)\s+", re.I),
]

SERIES_PREFIXES = [
    re.compile(r"^(?:مسلسل|series)\s+", re.I),
]


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


def clean_duplicates(data: dict) -> dict:
    if not isinstance(data, dict):
        return {"channels": [], "series": []}
    seen_series = set()
    clean_series = []
    for s in data.get("series", []):
        if not isinstance(s, dict):
            continue
        name = s.get("name", "").strip()
        ctype = s.get("type", "series")
        if ctype == "movie":
            name_key = f"M::{name}::{s.get('_source_channel', '')}"
        else:
            name_key = f"S::{name}"
        if not name or name_key in seen_series:
            continue
        seen_series.add(name_key)
        clean_seasons = {}
        seasons = s.get("seasons", {})
        if isinstance(seasons, dict):
            for season_key, episodes in seasons.items():
                if not isinstance(episodes, list):
                    continue
                seen_keys = set()
                clean_eps = []
                for ep in episodes:
                    if not isinstance(ep, dict):
                        continue
                    ch = str(ep.get("source_channel", "")).strip()
                    mid = str(ep.get("message_id", "")).strip()
                    key = f"{ch}|{mid}" if ch else mid
                    if key and key in seen_keys:
                        continue
                    if key:
                        seen_keys.add(key)
                    clean_eps.append(ep)
                if clean_eps:
                    clean_seasons[season_key] = clean_eps
        s["seasons"] = clean_seasons
        clean_series.append(s)
    data["series"] = clean_series
    return data


def load_existing_data() -> dict:
    if DATA_FILE.exists():
        try:
            raw = DATA_FILE.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict) and "series" in data:
                return clean_duplicates(data)
        except Exception as e:
            log.warning(f"data.json تالف: {e}")
    return {"channels": [], "series": []}


def save_data(data: dict):
    clean_data = clean_duplicates(data)
    try:
        content = json.dumps(clean_data, ensure_ascii=False, indent=2)
        json.loads(content)
        DATA_FILE.write_text(content, encoding="utf-8")
        size_kb = DATA_FILE.stat().st_size / 1024
        log.info(f"حفظ {DATA_FILE.name} ({size_kb:.1f} KB)")
    except Exception as e:
        log.error(f"فشل حفظ: {e}")


def find_or_create_series(data: dict, name: str, content_type: str, channel: str) -> dict:
    for s in data["series"]:
        s_name = s.get("name", "")
        s_type = s.get("type", "")
        s_channel = s.get("_source_channel", "")
        if s_name == name and s_type == content_type:
            if content_type == "movie":
                if s_channel == channel:
                    return s
            else:
                return s
    new_series = {
        "name": name,
        "type": content_type,
        "poster_url": "",
        "description": "",
        "seasons": {},
        "_source_channel": channel,
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
    existing.sort(key=lambda e: int(e.get("episode") or 0))
    return True


def extract_media_info(msg) -> Optional[dict]:
    media = None
    media_type = None
    if msg.video:
        media, media_type = msg.video, "video"
    elif msg.document:
        media, media_type = msg.document, "document"
    elif msg.animation:
        media, media_type = msg.animation, "animation"
    if not media:
        return None
    size_bytes = getattr(media, "file_size", 0) or 0
    if size_bytes / (1024 * 1024) > MAX_FILE_MB:
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


async def process_message(client, msg, data, progress, channel) -> bool:
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
    episode_num = parsed["episode"] if parsed["episode"] is not None else 1
    episode = {
        "message_id": str(msg.id),
        "episode": episode_num,
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
    series = find_or_create_series(data, parsed["name"], parsed["content_type"], channel)
    added = add_episode(series, parsed["season"], episode)
    if added:
        icon = "🎬" if parsed["content_type"] == "movie" else "📺"
        ep_info = f"جزء {parsed.get('part')}" if parsed.get("part") else (
            f"S{parsed['season']:02d}E{episode_num:02d}"
            if parsed["content_type"] == "series"
            else "فيلم"
        )
        log.info(
            f"{icon} [{parsed['name']}] {ep_info} "
            f"({media_info['file_size'] / 1024 / 1024:.1f}MB) [{channel}]"
        )
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
                wait = min(e.value + SAFETY_BUFFER, MAX_DELAY)
                log.warning(f"FloodWait: {e.value}s")
                await asyncio.sleep(wait)
            except Exception as e:
                errors += 1
                log.error(f"[{channel}] {msg.id}: {e}")
            if count % 100 == 0:
                log.info(f"[{channel}] {count} رسالة | {added} مضافة")
                save_data(data)
    except FloodWait as e:
        await asyncio.sleep(min(e.value + SAFETY_BUFFER, MAX_DELAY))
    except Exception as e:
        log.error(f"خطأ في {channel}: {e}")
    log.info(f"[{channel}] اكتمل: {count} | {added} مضافة | {skipped} متجاهلة")


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
            log.error("AUTH_KEY_DUPLICATED")
            raise SystemExit(1)
        raise
    save_data(data)
    save_progress(progress)
    from collections import Counter
    types = Counter(s.get("type", "?") for s in data["series"])
    log.info(f"\nاكتمل الجلب:")
    log.info(f"   أعمال: {len(data['series'])}")
    for t, c in types.items():
        log.info(f"   {t}: {c}")


if __name__ == "__main__":
    asyncio.run(main())