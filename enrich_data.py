#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""enrich_data.py — إثراء data.json بالتصنيفات والصور"""

import os
import re
import json
import time
import base64
import requests
from pathlib import Path
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

from classify import detect_origin, detect_type

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
CACHE_FILE = ROOT / ".poster_cache.json"
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"
MAX_WORKERS = 8
TIMEOUT = 10


def load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"posters": {}, "categories": {}}


def save_cache(cache):
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clean_for_search(name):
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"^(?:مسلسل|مشاهدة|فيلم|فيلمو)\s+", "", name)
    name = re.sub(r"\s*(?:مدبلج|مترجم)\s*", " ", name)
    name = re.sub(r"(?:الحلقة|حلقة|الحلقه|حلقه)\s*\d+", "", name, flags=re.I)
    name = re.sub(r"(?:الموسم|موسم)\s*\d+", "", name, flags=re.I)
    name = re.sub(r"(?:الجزء|جزء)\s*\d+", "", name, flags=re.I)
    name = re.sub(r"\bS\d{1,2}E\d{1,4}\b", "", name, flags=re.I)
    return name.strip()


def normalize_arabic(text):
    if not text:
        return ""
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"[ىي]", "ي", text)
    text = re.sub(r"[ةه]", "ه", text)
    text = re.sub(r"ـ+", "", text)
    return text.strip().lower()


def score_tmdb_result(result, query):
    title = result.get("name") or result.get("title") or ""
    original = result.get("original_name") or result.get("original_title") or ""
    n_title = normalize_arabic(title)
    n_original = normalize_arabic(original)
    n_query = normalize_arabic(query)
    if not n_query:
        return 0
    if n_title == n_query or n_original == n_query:
        return 100
    if n_title.startswith(n_query) or n_query.startswith(n_title):
        return 85
    if n_query in n_title or n_query in n_original:
        return 70
    q_words = set(n_query.split())
    t_words = set(n_title.split())
    o_words = set(n_original.split())
    all_target = t_words | o_words
    if q_words and all_target:
        overlap = len(q_words & all_target) / max(len(q_words), 1)
        return int(overlap * 60)
    return 0


def tmdb_search(session, name, content_type="", year=""):
    if not TMDB_API_KEY:
        return ""
    clean = clean_for_search(name)
    if not clean:
        return ""
    queries = [clean]
    if clean.startswith("ال") and len(clean) > 3:
        queries.append(clean[2:])
    if clean.endswith("ة"):
        queries.append(clean[:-1])

    if content_type == "movie":
        endpoints = ["movie", "tv"]
    elif content_type == "series":
        endpoints = ["tv", "movie"]
    else:
        endpoints = ["tv", "movie"]

    best_poster = ""
    best_score = 0
    for query in queries:
        for endpoint in endpoints:
            try:
                params = {
                    "api_key": TMDB_API_KEY,
                    "query": query,
                    "language": "ar",
                }
                r = session.get(
                    f"{TMDB_BASE}/search/{endpoint}",
                    params=params,
                    timeout=TIMEOUT,
                )
                if r.status_code != 200:
                    continue
                results = r.json().get("results", [])
                for result in results[:5]:
                    score = score_tmdb_result(result, clean)
                    poster = result.get("poster_path")
                    if poster and score > best_score:
                        best_score = score
                        best_poster = f"{TMDB_IMG}{poster}"
                        if best_score >= 85:
                            return best_poster
            except Exception:
                continue
    if best_score >= 40:
        return best_poster
    return ""


def tvmaze_search(session, name):
    clean = clean_for_search(name)
    if not clean:
        return ""
    try:
        url = f"https://api.tvmaze.com/search/shows?q={quote(clean)}"
        r = session.get(url, timeout=TIMEOUT)
        if r.status_code != 200:
            return ""
        results = r.json()
        if not results:
            return ""
        best = results[0]
        score = score_tmdb_result(
            {"name": best.get("show", {}).get("name", "")},
            clean,
        )
        if score >= 40:
            image = best.get("show", {}).get("image") or {}
            poster = image.get("medium") or image.get("original")
            if poster:
                return poster
    except Exception:
        pass
    return ""


ELCINEMA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en;q=0.9",
}


def elcinema_search(session, name):
    clean = clean_for_search(name)
    if not clean:
        return ""
    try:
        url = f"https://elcinema.com/search?q={quote(clean)}"
        r = session.get(url, headers=ELCINEMA_HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return ""
        matches = re.findall(
            r'<img[^>]+src="(https?://[^"]+\.(?:jpg|jpeg|png|webp))"',
            r.text,
            re.I,
        )
        for img_url in matches[:8]:
            if any(bad in img_url.lower() for bad in [
                "logo", "icon", "avatar", "banner", "loading"
            ]):
                continue
            return img_url
    except Exception:
        pass
    return ""


BING_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en;q=0.9",
}


def bing_images(session, name, content_type=""):
    clean = clean_for_search(name)
    if not clean:
        return ""
    type_hint = ""
    if content_type == "movie":
        type_hint = "فيلم"
    elif content_type == "series":
        type_hint = "مسلسل"
    queries = [
        f"{clean} {type_hint} بوستر".strip(),
        f"{clean} بوستر",
        f"{clean} مسلسل",
        f"{clean} poster",
    ]
    for query in queries:
        try:
            url = (
                f"https://www.bing.com/images/search?q={quote(query)}"
                f"&qft=+filterui:imagesize-large"
            )
            r = session.get(url, headers=BING_HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            matches = re.findall(r'"murl":"(https?://[^"]+)"', r.text)
            for m_url in matches[:8]:
                m_url = m_url.replace("\\/", "/")
                if any(ext in m_url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    if not any(bad in m_url.lower() for bad in [
                        "logo", "icon", "avatar", "emoji", "flag", "banner"
                    ]):
                        return m_url
        except Exception:
            continue
    return ""


def make_placeholder_svg(name, content_type=""):
    first = name.strip()[:1] if name.strip() else "?"
    h = hash(name) % 360
    color1 = f"hsl({h}, 55%, 22%)"
    color2 = f"hsl({(h + 40) % 360}, 55%, 15%)"
    label = "فيلم" if content_type == "movie" else "مسلسل"
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="300" height="450" viewBox="0 0 300 450">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="{color1}"/><stop offset="100%" stop-color="{color2}"/>
</linearGradient></defs>
<rect width="300" height="450" fill="url(#g)"/>
<text x="150" y="200" font-family="Arial,sans-serif" font-size="72" font-weight="bold" fill="rgba(255,255,255,0.9)" text-anchor="middle">{first}</text>
<text x="150" y="270" font-family="Arial,sans-serif" font-size="18" fill="rgba(255,255,255,0.6)" text-anchor="middle">{label}</text>
</svg>'''
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def enrich_one(series, cache, session):
    name = series.get("name", "").strip()
    if not name:
        return series

    episodes = []
    seasons = series.get("seasons", {})
    if isinstance(seasons, dict):
        for eps in seasons.values():
            if isinstance(eps, list):
                episodes.extend(eps)

    ctype = detect_type(name, len(episodes))
    origin = detect_origin(name)

    series["type"] = ctype
    series["origin"] = origin
    series["category_slug"] = f"{ctype}-{origin}"

    existing = series.get("poster_url", "").strip()
    if existing and not existing.startswith("data:"):
        return series

    cache_key = f"{name}|{ctype}|{series.get('tmdb_year', '')}"
    cached = cache["posters"].get(cache_key)
    if cached:
        series["poster_url"] = cached
        return series

    poster = tmdb_search(session, name, ctype, series.get("tmdb_year", ""))
    if poster:
        print(f"  TMDB: {name} [{ctype}/{origin}]")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    if ctype == "series":
        poster = tvmaze_search(session, name)
        if poster:
            print(f"  TVMaze: {name}")
            series["poster_url"] = poster
            cache["posters"][cache_key] = poster
            return series

    poster = elcinema_search(session, name)
    if poster:
        print(f"  ElCinema: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    poster = bing_images(session, name, ctype)
    if poster:
        print(f"  Bing: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    print(f"  Placeholder: {name}")
    poster = make_placeholder_svg(name, ctype)
    series["poster_url"] = poster
    cache["posters"][cache_key] = poster
    return series


def main():
    try:
        import clean_data
        clean_data.run(verbose=True)
    except Exception as e:
        print(f"[enrich] تحذير التنظيف: {e}")

    if not DATA_FILE.exists():
        print(f"{DATA_FILE} غير موجود")
        raise SystemExit(1)

    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"data.json تالف: {e}")
        raise SystemExit(1)

    series_list = data.get("series", []) if isinstance(data, dict) else data
    cache = load_cache()

    print(f"{len(series_list)} عمل")
    print(f"{MAX_WORKERS} threads\n")

    session = requests.Session()
    session.headers.update({"Accept-Encoding": "gzip, deflate"})

    start = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(enrich_one, s, cache, session) for s in series_list]
        for _ in as_completed(futures):
            pass
    elapsed = time.time() - start
    print(f"\nالوقت: {elapsed:.1f}s")

    from collections import Counter
    types = Counter(s.get("type", "?") for s in series_list)
    origins = Counter(s.get("origin", "?") for s in series_list)
    with_poster = sum(
        1 for s in series_list
        if s.get("poster_url", "") and not s.get("poster_url", "").startswith("data:")
    )
    placeholder_count = sum(
        1 for s in series_list
        if s.get("poster_url", "").startswith("data:")
    )

    print(f"\nالإحصائيات:")
    for k, v in types.items():
        print(f"  {k}: {v}")
    for k, v in origins.items():
        print(f"  {k}: {v}")
    print(f"  صور حقيقية: {with_poster}/{len(series_list)}")
    print(f"  Placeholder: {placeholder_count}")

    if isinstance(data, dict):
        data["series"] = series_list
        out = data
    else:
        out = series_list

    DATA_FILE.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_cache(cache)
    print(f"\nحفظ {DATA_FILE.name}")


if __name__ == "__main__":
    main()