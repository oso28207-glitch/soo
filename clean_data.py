#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clean_data.py — تنظيف شامل لـ data.json وإعادة تصنيف كل الأعمال"""

import json
import shutil
from pathlib import Path
from collections import defaultdict
from datetime import datetime

from classify import detect_origin, detect_type

ROOT          = Path(__file__).resolve().parent
DATA_FILE     = ROOT / "data.json"
PROGRESS_FILE = ROOT / "forward_progress.json"

def safe_int(v, d=0):
    try:
        if v is None: return d
        if isinstance(v, str):
            v = v.strip()
            if not v: return d
        return int(v)
    except (ValueError, TypeError):
        return d

def safe_str(v):
    return "" if v is None else str(v).strip()

# ═══════════════════════════════════════════════════════════════
def clean_episodes(episodes, season_default=1):
    if not isinstance(episodes, list):
        return []
    seen, out = set(), []
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        mid = safe_str(ep.get("message_id"))
        ch  = safe_str(ep.get("source_channel"))
        fid = safe_str(ep.get("file_id"))
        if not mid and not fid:
            continue
        key = f"{ch}|{mid}" if ch else (mid or fid)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "message_id":     safe_int(mid, 0),
            "source_channel": ch,
            "file_id":        fid,
            "file_unique_id": safe_str(ep.get("file_unique_id")),
            "file_size":      safe_int(ep.get("file_size"), 0),
            "duration":       safe_int(ep.get("duration"), 0),
            "season":         safe_int(ep.get("season"), season_default),
            "episode":        safe_int(ep.get("episode"), 0),
            "date":           safe_str(ep.get("date")),
            "telegram_url":   safe_str(ep.get("telegram_url")),
            "thumb_url":      safe_str(ep.get("thumb_url")),
        })
    return out

def sort_episodes(eps):
    return sorted(eps, key=lambda e: (
        safe_int(e.get("season"), 1),
        safe_int(e.get("episode"), 0),
        safe_int(e.get("message_id"), 0),
    ))

def clean_one_series(s):
    if not isinstance(s, dict):
        return None
    name = safe_str(s.get("name"))
    if not name or len(name) < 2:
        return None
    all_eps = []
    seasons_in = s.get("seasons", {})
    if isinstance(seasons_in, dict):
        for sk, eps in seasons_in.items():
            all_eps.extend(clean_episodes(eps, safe_int(sk, 1)))
    elif isinstance(seasons_in, list):
        all_eps.extend(clean_episodes(seasons_in, 1))
    if not all_eps:
        return None
    all_eps = sort_episodes(all_eps)
    count = len(all_eps)
    new_type   = detect_type(name, count)
    new_origin = detect_origin(name)
    seasons_out = defaultdict(list)
    for ep in all_eps:
        seasons_out[str(safe_int(ep.get("season"), 1))].append(ep)
    seasons_out = {k: seasons_out[k] for k in sorted(seasons_out, key=lambda x: safe_int(x, 1))}
    latest = ""
    for ep in all_eps:
        d = safe_str(ep.get("date"))
        if d and d > latest:
            latest = d
    if not latest:
        ids = [safe_int(e.get("message_id"), 0) for e in all_eps]
        latest = str(max(ids)) if ids else "0"
    return {
        "name": name,
        "type": new_type,
        "origin": new_origin,
        "category_slug": f"{new_type}-{new_origin}",
        "poster_url":      safe_str(s.get("poster_url")),
        "poster_backdrop": safe_str(s.get("poster_backdrop")),
        "tmdb_rating":   s.get("tmdb_rating") or 0,
        "tmdb_year":     s.get("tmdb_year") or "",
        "tmdb_overview": safe_str(s.get("tmdb_overview")),
        "description":   safe_str(s.get("description")),
        "seasons": seasons_out,
        "_episode_count": count,
        "_latest": latest,
    }

def merge_duplicates(series_list):
    merged = {}
    for s in series_list:
        key = f"{s['type']}::{s['name'].strip()}"
        if key not in merged:
            merged[key] = s
            continue
        ex = merged[key]
        for sk, eps in s["seasons"].items():
            ex["seasons"].setdefault(sk, []).extend(eps)
        if not ex.get("poster_url") and s.get("poster_url"):
            ex["poster_url"] = s["poster_url"]
        if not ex.get("poster_backdrop") and s.get("poster_backdrop"):
            ex["poster_backdrop"] = s["poster_backdrop"]
    out = []
    for s in merged.values():
        all_eps = []
        for sk, eps in s["seasons"].items():
            all_eps.extend(clean_episodes(eps, safe_int(sk, 1)))
        all_eps = sort_episodes(all_eps)
        if not all_eps:
            continue
        seasons_out = defaultdict(list)
        for ep in all_eps:
            seasons_out[str(safe_int(ep.get("season"), 1))].append(ep)
        s["seasons"] = {k: seasons_out[k] for k in sorted(seasons_out, key=lambda x: safe_int(x, 1))}
        s["_episode_count"] = len(all_eps)
        out.append(s)
    for s in out:
        s["type"]   = detect_type(s["name"], s["_episode_count"])
        s["origin"] = detect_origin(s["name"])
        s["category_slug"] = f"{s['type']}-{s['origin']}"
    return out

# ═══════════════════════════════════════════════════════════════
def run(verbose=True):
    if not DATA_FILE.exists():
        if verbose: print(f"[clean] {DATA_FILE.name} غير موجود — تخطي")
        return False
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[clean] data.json تالف: {e}")
        return False

    if isinstance(raw, list):
        series_raw = raw
        wrapper = {"channels": [], "series": raw}
    else:
        series_raw = raw.get("series", [])
        wrapper = raw

    if verbose:
        print(f"[clean] خام: {len(series_raw)}")

    cleaned = [c for c in (clean_one_series(s) for s in series_raw) if c]
    cleaned = merge_duplicates(cleaned)

    series_n = sum(1 for s in cleaned if s["type"] == "series")
    movies_n = sum(1 for s in cleaned if s["type"] == "movie")
    if verbose:
        print(f"[clean] بعد التنظيف: {len(cleaned)} (مسلسلات={series_n} أفلام={movies_n})")

    for s in cleaned:
        s.pop("_episode_count", None)
        s.pop("_latest", None)

    def latest_key(s):
        latest = ""
        for eps in s["seasons"].values():
            for ep in eps:
                d = safe_str(ep.get("date"))
                if d and d > latest:
                    latest = d
        return latest or "0"
    cleaned.sort(key=latest_key, reverse=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        shutil.copy2(DATA_FILE, DATA_FILE.with_name(f"data.backup_{ts}.json"))
    except Exception:
        pass

    wrapper["series"] = cleaned
    DATA_FILE.write_text(
        json.dumps(wrapper, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if verbose:
        print(f"[clean] ✅ {DATA_FILE.name}")

    if PROGRESS_FILE.exists():
        try:
            prog = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            if isinstance(prog, dict):
                prog.pop("series_map", None)
                prog.setdefault("last_message_id", 0)
                fw = prog.get("forwarded_ids", [])
                if isinstance(fw, list):
                    prog["forwarded_ids"] = sorted(set(safe_int(x, 0) for x in fw if safe_int(x, 0) > 0))
                PROGRESS_FILE.write_text(
                    json.dumps(prog, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if verbose: print(f"[clean] ✅ {PROGRESS_FILE.name}")
        except Exception as e:
            print(f"[clean] تحذير progress: {e}")

    return True

if __name__ == "__main__":
    run()