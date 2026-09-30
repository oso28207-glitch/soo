#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_data.py — إثراء data.json بالتصنيفات والصور
★ إضافة: صور جوجل كمصدر احتياطي ★
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

MAX_WORKERS = 6
TIMEOUT = 12

# ═══════════════════════════════════════════════════════════════
# قوائم الكلمات
# ═══════════════════════════════════════════════════════════════
TURKISH_KW = [
    "مدبلج", "تركي", "تركية",
    "قيامة أرطغرل", "المؤسس عثمان", "حريم السلطان", "وادي الذئاب",
    "قيامة عثمان", "أرطغرل", "ملحمة", "قبيلة",
    "حياتي الرائعة", "أوراق النسيان", "كذبتي الحلوة",
    "لعبة حب", "التفاح الحرام", "حب للايجار",
    "الحب ورطة", "احتمال حب", "ورود وذنوب", "الغرفة 309",
    "كيزيلجيك", "على مر الزمان", "سنوات الضياع", "العشق الأسود",
    "العشق المشبوه", "عشق ودموع", "جسور والجميلة", "أنت اطرق بابي",
    "كان يا مكان", "فتاة النافذة", "حب أعمى", "قلب الأسد",
    "الحفرة", "الطبيب المعجزة", "الأزهار الحزينة", "زهرة الثالوث",
    "طائر الرفراف", "ثلاثة أجساد", "سجين الحب", "دموع الغجرية",
    "فيلينتا", "الخياط", "المحافظ",
]

ARABIC_HARDCODED = [
    # مسلسلات مصرية من الموقع
    "ولد وبنت وشايب",
    "حالات نادرة",
    "قهوة المحطة",
    "خالد نور وولده نور خالد",
    "برغم القانون",
    "عهد انيس",
    "قابيل",
    "لعبة نيوتن",
    "ما تراه ليس كما يبدو",
    "لام شمسية", "الحلانجي", "سيد الناس", "جوما", "إش إش", "اش اش",
    # مسلسلات عربية شائعة
    "منورة باهلها", "منورة بأهلها", "الاخ الكبير", "الأخ الكبير",
    "النص", "البيت بيتي", "البيت بيتك", "صحاب الارض",
    "عين سحرية", "الست موناليزا", "مناعة",
    "كارثة طبيعية", "مملكة الحرير", "موعد مع الماضي",
    "بـ 100 وش", "ضربة معلم", "بدون سابق انذار",
    "فن الحرب", "حد اقصى", "الف ليله وليله",
    "اتنين غيرنا", "المصيدة", "الاختيار", "الحشاشين",
    "المداح", "جعفر العمدة", "بيت الرفاعي", "العتاولة",
    "نسل الأغراب", "الهيبة", "عايشة الدور", "قلبي ومفتاحه",
    "حكيم باشا", "جرح قديم",
]

FOREIGN_HARDCODED = [
    "افاتار", "آفاتار", "avatar",
    "بريكينغ باد", "breaking bad",
    "the last of us", "inception", "the batman",
]

MOVIE_KW = ["فيلم", "فيلمو", "movie", "film", "سينما"]

MOVIE_EXCEPTIONS = {
    "يوم 13", "19 ب", "24 ساعة", "الفيل الازرق", "الكنز", "ولاد رزق",
}


def load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"posters": {}, "categories": {}}


def save_cache(cache):
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def detect_origin(name, existing_type=""):
    name_lower = name.lower().strip()
    for kw in FOREIGN_HARDCODED:
        if kw in name or kw.lower() in name_lower:
            return "foreign"
    if "مدبلج" in name or "تركي" in name or "تركية" in name:
        return "turkish"
    for kw in ARABIC_HARDCODED:
        if kw in name or kw.lower() in name_lower:
            return "arabic"
    for kw in TURKISH_KW:
        if kw in name or kw.lower() in name_lower:
            return "turkish"
    arabic_chars = len(re.findall(r"[\u0600-\u06FF]", name))
    english_chars = len(re.findall(r"[a-zA-Z]", name))
    if arabic_chars > 0 and english_chars == 0:
        return "arabic"
    return "foreign"


def detect_type(name, episodes, existing_type=""):
    n = len(episodes)
    if n > 1:
        return "series"
    if existing_type == "series":
        return "series"
    name_lower = name.lower()
    if any(k in name or k in name_lower for k in MOVIE_KW):
        return "movie"
    for kw in FOREIGN_HARDCODED:
        if kw in name or kw.lower() in name_lower:
            return "movie"
    if episodes:
        dur = episodes[0].get("duration", 0) or 0
        if dur >= 4800:
            return "movie"
    return "movie"


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
    nt = normalize_arabic(title)
    no = normalize_arabic(original)
    nq = normalize_arabic(query)
    if not nq:
        return 0
    if nt == nq or no == nq:
        return 100
    if nt.startswith(nq) or nq.startswith(nt):
        return 85
    if nq in nt or nq in no:
        return 70
    qw = set(nq.split())
    tw = set(nt.split())
    ow = set(no.split())
    all_t = tw | ow
    if qw and all_t:
        return int(len(qw & all_t) / max(len(qw), 1) * 60)
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
    endpoints = ["tv", "movie"] if content_type != "movie" else ["movie", "tv"]

    best_poster = ""
    best_score = 0
    for query in queries:
        for ep in endpoints:
            try:
                params = {"api_key": TMDB_API_KEY, "query": query, "language": "ar"}
                r = session.get(f"{TMDB_BASE}/search/{ep}", params=params, timeout=TIMEOUT)
                if r.status_code != 200:
                    continue
                for result in r.json().get("results", [])[:5]:
                    sc = score_tmdb_result(result, clean)
                    poster = result.get("poster_path")
                    if poster and sc > best_score:
                        best_score = sc
                        best_poster = f"{TMDB_IMG}{poster}"
                if best_score >= 85:
                    return best_poster
            except Exception:
                continue
    return best_poster if best_score >= 40 else ""


def tvmaze_search(session, name):
    clean = clean_for_search(name)
    if not clean:
        return ""
    try:
        r = session.get(f"https://api.tvmaze.com/search/shows?q={quote(clean)}", timeout=TIMEOUT)
        if r.status_code != 200:
            return ""
        results = r.json()
        if results:
            best = results[0]
            score = score_tmdb_result({"name": best.get("show", {}).get("name", "")}, clean)
            if score >= 40:
                image = best.get("show", {}).get("image") or {}
                return image.get("medium") or image.get("original") or ""
    except Exception:
        pass
    return ""


ELCINEMA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.9",
}


def elcinema_search(session, name):
    clean = clean_for_search(name)
    if not clean:
        return ""
    try:
        r = session.get(f"https://elcinema.com/search?q={quote(clean)}", headers=ELCINEMA_HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return ""
        matches = re.findall(r'<img[^>]+src="(https?://[^"]+\.(?:jpg|jpeg|png|webp))"', r.text, re.I)
        for url in matches[:8]:
            if any(bad in url.lower() for bad in ["logo", "icon", "avatar", "banner", "loading", "blank"]):
                continue
            return url
    except Exception:
        pass
    return ""


BING_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.9",
}


def bing_images(session, name, content_type=""):
    clean = clean_for_search(name)
    if not clean:
        return ""
    type_hint = "فيلم" if content_type == "movie" else "مسلسل"
    queries = [
        f"{clean} {type_hint} بوستر",
        f"{clean} بوستر",
        f"{clean} poster",
    ]
    for query in queries:
        try:
            url = f"https://www.bing.com/images/search?q={quote(query)}&qft=+filterui:imagesize-large"
            r = session.get(url, headers=BING_HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            matches = re.findall(r'"murl":"(https?://[^"]+)"', r.text)
            for url_img in matches[:8]:
                url_img = url_img.replace("\\/", "/")
                if any(ext in url_img.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    if not any(bad in url_img.lower() for bad in ["logo", "icon", "avatar", "emoji", "flag", "banner", "blank"]):
                        return url_img
        except Exception:
            continue
    return ""


# ★★★ جوجل صور — مصدر جديد ★★★
GOOGLE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}


def google_images(session, name, content_type=""):
    """يبحث في Google Images (scraping)"""
    clean = clean_for_search(name)
    if not clean:
        return ""

    type_hint = "بوستر مسلسل" if content_type == "series" else "بوستر فيلم"
    queries = [
        f"{clean} {type_hint}",
        f"{clean} بوستر",
    ]

    for query in queries:
        try:
            # استخدم tbm=isch لبحث الصور
            url = f"https://www.google.com/search?q={quote(query)}&tbm=isch&hl=ar"
            r = session.get(url, headers=GOOGLE_HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                continue

            # استخراج روابط الصور من النتيجة
            # Google يُرجع الصور داخل img src أو داخل JavaScript
            # نبحث عن صور jpg/png
            patterns = [
                r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp))"',
                r"'(https?://[^']+\.(?:jpg|jpeg|png|webp))'",
                r'src="(https?://[^"]+)"',
            ]

            candidates = []
            for pat in patterns:
                candidates.extend(re.findall(pat, r.text))

            for url_img in candidates[:20]:
                url_img = url_img.replace("\\/", "/").replace("\\u003d", "=").replace("\\u0026", "&")
                if not any(ext in url_img.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    continue
                if any(bad in url_img.lower() for bad in [
                    "logo", "icon", "avatar", "emoji", "flag", "banner",
                    "gstatic", "google", "youtube", "ggpht", "ytimg",
                    "sprite", "spacer", "blank",
                ]):
                    continue
                # طول معقول للصورة
                if len(url_img) < 40:
                    continue
                candidates = [url_img]
                break

            if candidates:
                return candidates[0]

        except Exception:
            continue

    return ""


def make_placeholder_svg(name, content_type=""):
    first = name.strip()[:1] if name.strip() else "?"
    h = hash(name) % 360
    c1 = f"hsl({h}, 55%, 22%)"
    c2 = f"hsl({(h+40)%360}, 55%, 12%)"
    c3 = f"hsl({(h+180)%360}, 70%, 60%)"
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 450">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{c1}"/><stop offset="100%" stop-color="{c2}"/>
  </linearGradient></defs>
  <rect width="300" height="450" fill="url(#g)"/>
  <circle cx="150" cy="180" r="60" fill="none" stroke="{c3}" stroke-width="3" opacity="0.4"/>
  <text x="150" y="200" font-family="Cairo, sans-serif" font-size="70" font-weight="900" fill="{c3}"
        text-anchor="middle" dominant-baseline="middle">{first}</text>
  <text x="150" y="330" font-family="Cairo, sans-serif" font-size="16" font-weight="600"
        fill="rgba(255,255,255,.5)" text-anchor="middle">TelegramFlix</text>
</svg>'''
    from urllib.parse import quote as q
    return "data:image/svg+xml;charset=utf-8," + q(svg, safe="")


def enrich_one(series, cache, session):
    name = series.get("name", "").strip()
    if not name:
        return series

    episodes = []
    for eps in series.get("seasons", {}).values():
        if isinstance(eps, list):
            episodes.extend(eps)

    ctype = detect_type(name, episodes, series.get("type", ""))
    origin = detect_origin(name, ctype)
    series["type"] = ctype
    series["origin"] = origin
    series["category_slug"] = f"{ctype}-{origin}"

    existing = series.get("poster_url", "").strip()
    if existing and not existing.startswith("data:"):
        return series

    cache_key = f"{name}|{ctype}|v3"
    cached = cache["posters"].get(cache_key)
    if cached:
        series["poster_url"] = cached
        return series

    # 1) TMDB
    poster = tmdb_search(session, name, ctype, series.get("tmdb_year", ""))
    if poster:
        print(f"   TMDB: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # 2) TVMaze (مسلسلات فقط)
    if ctype == "series":
        poster = tvmaze_search(session, name)
        if poster:
            print(f"   TVMaze: {name}")
            series["poster_url"] = poster
            cache["posters"][cache_key] = poster
            return series

    # 3) ElCinema
    poster = elcinema_search(session, name)
    if poster:
        print(f"   ElCinema: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # 4) Bing Images
    poster = bing_images(session, name, ctype)
    if poster:
        print(f"   Bing: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # 5) ★★★ Google Images — جديد ★★★
    poster = google_images(session, name, ctype)
    if poster:
        print(f"   Google: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # 6) Placeholder
    print(f"   Placeholder: {name}")
    poster = make_placeholder_svg(name, ctype)
    series["poster_url"] = poster
    cache["posters"][cache_key] = poster
    return series


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

    from collections import Counter
    types = Counter(s.get("type", "?") for s in series_list)
    origins = Counter(s.get("origin", "?") for s in series_list)
    with_poster = sum(1 for s in series_list if s.get("poster_url", "") and not s.get("poster_url", "").startswith("data:"))
    placeholder = sum(1 for s in series_list if s.get("poster_url", "").startswith("data:"))

    print(f"\nالوقت: {elapsed:.1f}s")
    print(f"الإحصائيات:")
    for k, v in types.items():
        print(f"   {k}: {v}")
    for k, v in origins.items():
        print(f"   {k}: {v}")
    print(f"   صور حقيقية: {with_poster}/{len(series_list)}")
    print(f"   Placeholder: {placeholder}")

    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    save_cache(cache)
    print(f"\nحفظ {DATA_FILE.name}")
    print(f"حفظ Cache ({len(cache['posters'])} صورة)")


if __name__ == "__main__":
    main()