#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_data.py — إثراء data.json بالتصنيفات والصور
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
# قوائم الكلمات — محدّثة
# ═══════════════════════════════════════════════════════════════
TURKISH_KW = [
    "تركي", "مدبلج", "تركية",
    # مسلسلات تاريخية
    "قيامة", "عثمان", "أرطغرل", "حريم السلطان", "وادي الذئاب",
    "المؤسس عثمان", "قيامة أرطغرل", "ملحمة", "قبيلة",
    # مسلسلات رومانسية
    "لعبة حب", "التفاح الحرام", "كذبتي الحلوة", "حب للايجار",
    "الحب ورطة", "حياتي الرائعة", "احتمال حب", "ورود وذنوب",
    "النص الثاني", "الغرفة", "اسمه السعادة", "في الظل",
    "كيزيلجيك", "الثمانينات", "على مر الزمان", "سنوات الضياع",
    "العشق الأسود", "الانتقام", "ياسمين", "فاتن", "بين",
    "أمينة", "خديجة", "نور", "لمسة حب", "شمال وجنوب",
    "حكاية جزيرة", "جسور والجميلة", "الحياة جميلة",
    "منزل الحب", "أنت اطرق بابي", "قلعة", "خاطفة", "صفقة",
    "الخائن", "كان يا مكان", "مريم", "حكايتنا", "فتاة النافذة",
    "حب أعمى", "قلب الأسد", "الحفرة", "دموع وردة", "إيزيل",
    "العشق المشبوه", "عشق ودموع", "المدينة", "الطبيب المعجزة",
    "لعبة الحظ", "الأزهار الحزينة", "أسمر", "قلب الجبل",
    "زهرة الثالوث", "الأمانة", "الطفل", "المعلم", "الوالدة",
    "طائر الرفراف", "أنت وطني", "وطني أنت", "الحب الطاهر",
    "غرفة الانتظار", "الجراح", "الخلية", "سجين الحب",
    "الوعد", "قلب الأم", "عائلة الحاج", "الوصية", "جسر",
    "دموع الغجرية", "أمل الحياة", "فتاة القمر",
    # ★★★ الكلمات المُضافة ★★★
    "الخياط", "Terzi", "فيلينتا", "المحافظ",
]

ARABIC_KW = [
    "اتنين", "المصيدة", "الاختيار", "الحشاشين", "المداح",
    "جعفر العمدة", "بيت الرفاعي", "العتاولة", "نسل الأغراب",
    "مافيا", "بابا المجال", "كوبرا", "سيد الناس", "الهيبة",
    "أم الدنيا", "قصر السيد", "الأب الروحي", "لعبة نيوتن",
    "الملك", "موسى", "شقة 6", "البرنس", "السر",
    "الحرملك", "الطوفان", "ولاد رزق", "الكنز", "الديزل",
    "حرب أهلية", "خيانة عهد", "الفتوة", "الفيل الأزرق",
    "مصري", "خليجي", "سوري", "لبناني", "مغربي", "كويتي",
    "سعودي", "إماراتي", "قطري", "بحريني", "عماني",
    "أردني", "فلسطيني", "عراقي", "تونسي", "جزائري",
    # ★★★ مسلسلات الموقع ★★★
    "صحاب الارض", "عين سحرية", "الست موناليزا", "مناعة",
    "اوراق النسيان", "كارثة طبيعية", "النص",
    "اسود باهت", "ساعته وتاريخه", "مملكة الحرير",
    "موعد مع الماضي", "بـ 100 وش", "ضربة معلم",
    "الاخ الكبير", "بدون سابق انذار", "البيت بيتي",
    "منورة باهلها", "منورة بأهلها", "فن الحرب",
    "حد اقصى", "الف ليله وليله",
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
# التصنيف المحسّن
# ═══════════════════════════════════════════════════════════════
def detect_type(name, episodes):
    """
    series أو movie
    ★ الأولوية لعدد الحلقات ★
    """
    n = len(episodes)

    # أكثر من 3 حلقات = مسلسل
    if n > 3:
        return "series"

    # 2-3 حلقات: فحص المدة
    if 2 <= n <= 3:
        long_count = sum(1 for e in episodes if (e.get("duration", 0) or 0) >= 4800)
        if long_count == n:
            return "movie"
        return "series"

    # حلقة واحدة
    name_lower = name.lower()

    # ★★★ إشارة "فيلم" في الاسم ★★★
    if any(k in name or k in name_lower for k in MOVIE_KW):
        return "movie"

    # ★★★ فحص is_movie_hint ★★★
    if episodes and episodes[0].get("is_movie_hint"):
        return "movie"

    # فحص المدة
    if episodes:
        dur = episodes[0].get("duration", 0) or 0
        if dur >= 4800:
            return "movie"

    return "movie"


def detect_origin(name, episodes):
    """arabic أو turkish أو foreign"""
    name_lower = name.lower()

    # كلمات صريحة
    if "مدبلج" in name or "تركي" in name or "تركية" in name:
        return "turkish"

    # ★★★ "الخياط" صريحًا ★★★
    if name.strip() == "الخياط":
        return "turkish"

    # كلمات تركية
    for kw in TURKISH_KW:
        if kw in name or kw.lower() in name_lower:
            return "turkish"

    # كلمات عربية
    for kw in ARABIC_KW:
        if kw in name or kw.lower() in name_lower:
            return "arabic"

    # تحليل الحروف
    arabic_chars = len(re.findall(r"[\u0600-\u06FF]", name))
    english_chars = len(re.findall(r"[a-zA-Z]", name))

    if arabic_chars > 0 and english_chars == 0:
        return "arabic"

    return "foreign"


def clean_for_search(name):
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"^(?:مسلسل|مشاهدة|فيلم|فيلمو)\s+", "", name)
    name = re.sub(r"\s*(?:مدبلج|مترجم)\s*", " ", name)
    name = re.sub(r"\s*(?:الحلقة|حلقة|الحلقه|حلقه)\s*\d+.*$", "", name, flags=re.I)
    name = re.sub(r"\s*(?:الموسم|موسم)\s*\d+.*$", "", name, flags=re.I)
    name = re.sub(r"\s*S\d+E\d+.*$", "", name, flags=re.I)
    return name.strip()


# ═══════════════════════════════════════════════════════════════
# TMDB
# ═══════════════════════════════════════════════════════════════
def tmdb_search(session, name, year=""):
    if not TMDB_API_KEY:
        return ""
    clean = clean_for_search(name)
    if not clean:
        return ""

    queries = [clean]
    if clean.startswith("ال"):
        queries.append(clean[2:])
    parts = clean.split()
    if len(parts) > 2:
        queries.append(" ".join(parts[:2]))

    for query in queries:
        for endpoint in ("tv", "movie"):
            try:
                params = {
                    "api_key": TMDB_API_KEY,
                    "query": query,
                    "language": "ar",
                }
                if year:
                    if endpoint == "movie":
                        params["year"] = year
                    else:
                        params["first_air_date_year"] = year

                r = session.get(
                    f"{TMDB_BASE}/search/{endpoint}",
                    params=params,
                    timeout=TIMEOUT,
                )
                if r.status_code == 200:
                    results = r.json().get("results", [])
                    results.sort(key=lambda x: x.get("popularity", 0), reverse=True)
                    for result in results[:3]:
                        poster = result.get("poster_path")
                        if poster:
                            return f"{TMDB_IMG}{poster}"
            except Exception:
                pass

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
        for item in results[:3]:
            show = item.get("show", {})
            image = show.get("image") or {}
            poster = image.get("medium") or image.get("original")
            if poster:
                return poster
    except Exception:
        pass

    return ""


# ═══════════════════════════════════════════════════════════════
# ★★★ ElCinema — مصدر عربي ★★★
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
    """يبحث في ElCinema (موقع سينمائي عربي)"""
    clean = clean_for_search(name)
    if not clean:
        return ""

    try:
        url = f"https://elcinema.com/search?q={quote(clean)}"
        r = session.get(url, headers=ELCINEMA_HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return ""

        # استخراج أول صورة كبيرة
        matches = re.findall(
            r'<img[^>]+src="(https?://[^"]+\.(?:jpg|jpeg|png|webp))"',
            r.text, re.I,
        )
        for img_url in matches[:5]:
            if any(bad in img_url.lower() for bad in ["logo", "icon", "avatar", "banner"]):
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


def bing_images(session, name):
    clean = clean_for_search(name)
    if not clean:
        return ""

    queries = [
        f"{clean} بوستر مسلسل",
        f"{clean} مسلسل",
        f"{clean} poster series",
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
def make_placeholder_svg(name):
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

    ctype = detect_type(name, episodes)
    origin = detect_origin(name, episodes)

    series["type"] = ctype
    series["origin"] = origin
    series["category_slug"] = f"{ctype}-{origin}"

    existing = series.get("poster_url", "").strip()
    if existing and not existing.startswith("data:"):
        return series

    cache_key = f"{name}|{series.get('tmdb_year','')}"
    cached = cache["posters"].get(cache_key)
    if cached:
        series["poster_url"] = cached
        return series

    # 1. TMDB
    poster = tmdb_search(session, name, series.get("tmdb_year", ""))
    if poster:
        print(f"   TMDB: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # 2. TVMaze
    poster = tvmaze_search(session, name)
    if poster:
        print(f"   TVMaze: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # ★★★ 3. ElCinema ★★★
    poster = elcinema_search(session, name)
    if poster:
        print(f"   ElCinema: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # 4. Bing
    poster = bing_images(session, name)
    if poster:
        print(f"   Bing: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # 5. Placeholder
    print(f"   Placeholder: {name}")
    poster = make_placeholder_svg(name)
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