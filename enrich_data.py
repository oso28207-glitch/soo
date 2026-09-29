#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_data.py — إثراء data.json بالتصنيفات والصور
تصنيف دقيق + جلب صور متعدد المصادر
"""

import os
import re
import json
import time
import requests
from pathlib import Path
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
CACHE_FILE = ROOT / ".poster_cache.json"

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"

MAX_WORKERS = 8
TIMEOUT = 10

# ═══════════════════════════════════════════════════════════════
# قوائم الكلمات — محدّثة بناءً على فحص الموقع
# ═══════════════════════════════════════════════════════════════
TURKISH_KW = [
    "مدبلج", "تركي", "تركية",
    # تاريخية
    "قيامة أرطغرل", "المؤسس عثمان", "حريم السلطان", "وادي الذئاب",
    "قيامة عثمان", "أرطغرل", "ملحمة", "قبيلة",
    # ★★★ مسلسلات تركية شائعة (مضافة) ★★★
    "حياتي الرائعة",
    "أوراق النسيان",
    "كذبتي الحلوة",
    "لعبة حب", "التفاح الحرام", "حب للايجار",
    "الحب ورطة", "احتمال حب", "ورود وذنوب", "الغرفة 309",
    "كيزيلجيك", "على مر الزمان", "سنوات الضياع", "العشق الأسود",
    "العشق المشبوه", "عشق ودموع", "جسور والجميلة", "أنت اطرق بابي",
    "كان يا مكان", "فتاة النافذة", "حب أعمى", "قلب الأسد",
    "الحفرة", "الطبيب المعجزة", "الأزهار الحزينة", "زهرة الثالوث",
    "طائر الرفراف", "ثلاثة أجساد", "سجين الحب", "دموع الغجرية",
    "فيلينتا", "الخياط", "المحافظ",
]

# ★★★ أعمال عربية صريحة — تُفحص قبل التركية ★★★
ARABIC_HARDCODED = [
    # مسلسلات مصرية (من فحص الموقع)
    "لام شمسية",
    "الحلانجي",
    "سيد الناس",
    "جوما",
    "إش إش",
    "اش اش",
    "ولد وبنت وشايب",
    "حالات نادرة",
    "قهوة المحطة",
    "خالد نور وولده نور خالد",
    "برغم القانون",
    "ما تراه ليس كما يبدو",
    "عهد أنيس",
    "قابيل",
    "لعبة نيوتن",
    # مسلسلات عربية شائعة
    "منورة باهلها", "منورة بأهلها", "الاخ الكبير", "الأخ الكبير",
    "النص", "البيت بيتي", "البيت بيتك", "صحاب الارض",
    "عين سحرية", "الست موناليزا", "مناعة",
    "كارثة طبيعية", "مملكة الحرير", "موعد مع الماضي",
    "بـ 100 وش", "ضربة معلم", "بدون سابق انذار",
    "فن الحرب", "حد اقصى", "الف ليله وليله",
    "اتنين غيرنا", "المصيدة", "الاختيار", "الحشاشين",
    "المداح", "جعفر العمدة", "بيت الرفاعي", "العتاولة",
    "نسل الأغراب", "الهيبة",
]

# أعمال أجنبية
FOREIGN_HARDCODED = [
    "افاتار", "آفاتار", "avatar",
    "بريكينغ باد", "breaking bad",
    "the last of us",
    "inception",
    "the batman",
]

MOVIE_KW = ["فيلم", "فيلمو", "movie", "film", "سينما"]


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


# ═══════════════════════════════════════════════════════════════
# تصنيف الأصل — محافظ جداً
# ═══════════════════════════════════════════════════════════════
def detect_origin(name: str, existing_type: str = "") -> str:
    name_lower = name.lower().strip()

    # 1) أجنبي صريح
    for kw in FOREIGN_HARDCODED:
        if kw in name or kw.lower() in name_lower:
            return "foreign"

    # 2) تركي صريح
    if "مدبلج" in name or "تركي" in name or "تركية" in name:
        return "turkish"

    # 3) عربي صريح (قبل التركي!)
    for kw in ARABIC_HARDCODED:
        if kw in name or kw.lower() in name_lower:
            return "arabic"

    # 4) تركي
    for kw in TURKISH_KW:
        if kw in name or kw.lower() in name_lower:
            return "turkish"

    # 5) حروف عربية فقط
    arabic_chars = len(re.findall(r"[\u0600-\u06FF]", name))
    english_chars = len(re.findall(r"[a-zA-Z]", name))

    if arabic_chars > 0 and english_chars == 0:
        return "arabic"

    return "foreign"


# ═══════════════════════════════════════════════════════════════
# ★★★ تصنيف النوع — احترام النوع المُحدّد ★★★
# ═══════════════════════════════════════════════════════════════
def detect_type(name, episodes, existing_type=""):
    """
    - إذا كان النوع المُحدّد "series" وعدد الحلقات > 1 → احترمه
    - إذا كان النوع المُحدّد "movie" وعدد الحلقات > 1 → صحّح إلى series
    - إذا لم يوجد نوع → احسبه من عدد الحلقات
    """
    n = len(episodes)

    if existing_type == "series":
        return "series"  # احترم دائماً
    if existing_type == "movie":
        if n > 1:
            return "series"  # صحّح
        return "movie"

    # لا نوع مُحدّد
    if n > 1:
        return "series"
    return "movie"


# ═══════════════════════════════════════════════════════════════
# تنظيف اسم البحث
# ═══════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════
# TMDB
# ═══════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════
# TVMaze
# ═══════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════
# ElCinema
# ═══════════════════════════════════════════════════════════════
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
            r.text, re.I,
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


# ═══════════════════════════════════════════════════════════════
# Bing Images
# ═══════════════════════════════════════════════════════════════
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
            url = f"https://www.bing.com/images/search?q={quote(query)}&qft=+filterui:imagesize-large"
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


# ═══════════════════════════════════════════════════════════════
# Placeholder SVG
# ═══════════════════════════════════════════════════════════════
def make_placeholder_svg(name, content_type=""):
    first = name.strip()[:1] if name.strip() else "?"
    h = hash(name) % 360
    color1 = f"hsl({h}, 55%, 22%)"
    color2 = f"hsl({(h+40)%360}, 55%, 12%)"
    color3 = f"hsl({(h+180)%360}, 70%, 60%)"

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 450">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{color1}"/>
      <stop offset="100%" stop-color="{color2}"/>
    </linearGradient>
  </defs>
  <rect width="300" height="450" fill="url(#g)"/>
  <circle cx="150" cy="180" r="60" fill="none" stroke="{color3}" stroke-width="3" opacity="0.4"/>
  <text x="150" y="200" font-family="Cairo, sans-serif" font-size="70"
        font-weight="900" fill="{color3}" text-anchor="middle"
        dominant-baseline="middle">{first}</text>
  <text x="150" y="330" font-family="Cairo, sans-serif" font-size="16"
        font-weight="600" fill="rgba(255,255,255,.5)"
        text-anchor="middle">TelegramFlix</text>
</svg>'''

    from urllib.parse import quote as q
    return "data:image/svg+xml;charset=utf-8," + q(svg, safe="")


# ═══════════════════════════════════════════════════════════════
# إثراء واحد
# ═══════════════════════════════════════════════════════════════
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

    existing_type = series.get("type", "")
    ctype = detect_type(name, episodes, existing_type)
    origin = detect_origin(name, ctype)

    series["type"] = ctype
    series["origin"] = origin
    series["category_slug"] = f"{ctype}-{origin}"

    existing = series.get("poster_url", "").strip()
    if existing and not existing.startswith("data:"):
        return series

    cache_key = f"{name}|{ctype}|{series.get('tmdb_year','')}"
    cached = cache["posters"].get(cache_key)
    if cached:
        series["poster_url"] = cached
        return series

    # 1. TMDB
    poster = tmdb_search(session, name, ctype, series.get("tmdb_year", ""))
    if poster:
        print(f"   TMDB: {name} [{ctype}/{origin}]")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # 2. TVMaze
    if ctype == "series":
        poster = tvmaze_search(session, name)
        if poster:
            print(f"   TVMaze: {name}")
            series["poster_url"] = poster
            cache["posters"][cache_key] = poster
            return series

    # 3. ElCinema
    poster = elcinema_search(session, name)
    if poster:
        print(f"   ElCinema: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # 4. Bing
    poster = bing_images(session, name, ctype)
    if poster:
        print(f"   Bing: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # 5. Placeholder
    print(f"   Placeholder: {name}")
    poster = make_placeholder_svg(name, ctype)
    series["poster_url"] = poster
    cache["posters"][cache_key] = poster
    return series


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
def main():
    if not DATA_FILE.exists():
        print(f"{DATA_FILE} غير موجود")
        raise SystemExit(1)

    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"data.json تالف: {e}")
        raise SystemExit(1)

    series_list = data.get("series", [])
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
        print(f"   {k}: {v}")
    for k, v in origins.items():
        print(f"   {k}: {v}")
    print(f"   صور حقيقية: {with_poster}/{len(series_list)}")
    print(f"   Placeholder: {placeholder_count}")

    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_cache(cache)
    print(f"\nحفظ {DATA_FILE.name}")
    print(f"حفظ Cache ({len(cache['posters'])} صورة)")


if __name__ == "__main__":
    main()