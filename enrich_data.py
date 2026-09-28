#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_data.py — إثراء data.json بالتصنيفات والصور
★ تصنيف تلقائي محسّن + جلب صور متعدد المصادر ★
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
TIMEOUT = 8

# ═══════════════════════════════════════════════════════════════
# ★ قوائم الكلمات المفتاحية المحسّنة ★
# ═══════════════════════════════════════════════════════════════
TURKISH_KW = [
    # ★ كلمات عامة ★
    "تركي", "مدبلج", "تركية",
    # ★ مسلسلات تاريخية ★
    "قيامة", "عثمان", "أرطغرل", "حريم السلطان", "وادي الذئاب",
    "المؤسس عثمان", "قيامة أرطغرل", "ملحمة", "بني", "قبيلة",
    # ★ مسلسلات رومانسية مشهورة ★
    "لعبة حب", "التفاح الحرام", "كذبتي الحلوة", "حب للايجار",
    "الحب ورطة", "حياتي الرائعة", "احتمال حب", "ورود وذنوب",
    "النص الثاني", "الغرفة", "اسمه السعادة", "عائلة", 
    "في الظل", "كيزيلجيك", "الثمانينات", "على مر الزمان",
    "سنوات الضياع", "العشق الأسود", "الانتقام", "ياسمين", 
    "فاتن", "بين", "أمينة", "خديجة", "نور", "لمسة حب",
    "شمال وجنوب", "حكاية جزيرة", "جسور والجميلة", "الحياة جميلة",
    "منزل الحب", "أنت اطرق بابي", "قلعة", "خاطفة", "صفقة",
    "الخائن", "كان يا مكان", "مريم", "حكايتنا", "فتاة النافذة",
    "حب أعمى", "قلب الأسد", "الحفرة", "دموع وردة", "إيزيل",
    "العشق المشبوه", "عشق ودموع", "لا احد يعلم", "المدينة",
    "الطبيب المعجزة", "لعبة الحظ", "الأزهار الحزينة", "أسمر",
    # ★ مسلسلات جديدة ★
    "قلب الجبل", "زهرة الثالوث", "الأمانة", "حب على طريقة",
    "الطفل", "المعلم", "الوالدة", "سنوات", "طائر الرفراف",
    "أنت وطني", "وطني أنت", "الحب الطاهر", "ثلاثة أجساد",
    "غرفة الانتظار", "الجراح", "الخلية", "الحياة سر",
    "سجين الحب", "الوعد", "الوعد الحلو", "قلب الأم",
    "عائلة الحاج", "الوصية", "حكاية جزيرة", "جسر",
    "دموع الغجرية", "أمل الحياة", "فتاة القمر", "الرياض",
]

ARABIC_KW = [
    # ★ مسلسلات عربية معروفة ★
    "اتنين", "المصيدة", "الاختيار", "الحشاشين", "المداح",
    "جعفر العمدة", "بيت الرفاعي", "العتاولة", "نسل الأغراب",
    "مافيا", "بابا المجال", "كوبرا", "سيد الناس", "الهيبة",
    "أم الدنيا", "قصر السيد", "الأب الروحي", "لعبة نيوتن",
    "الملك", "موسى", "شقة 6", "الاختيار 3", "الاختيار 4",
    "بـ100 وش", "أبو العروسة", "نصيبي وقسمتك", "البرنس",
    "حكايات بنات", "السر", "الديفا", "الوعد", "الحرملك",
    "الطوفان", "الجزء الثاني", "الزوجة 18", "الهيبة الحصاد",
    "ولاد رزق", "الكنز", "الخلية", "الديزل", "حرب أهلية",
    "لما كنا صغيرين", "نسل الأغراب", "المداح أسطورة العشق",
    "المداح أسطورة الوادي", "طريق", "خيانة عهد", "الفتوة",
    "ما وراء الطبيعة", "يوم الدين", "الكنز 2", "الفيل الأزرق",
    # ★ كلمات عامة ★
    "مصري", "خليجي", "سوري", "لبناني", "مغربي", "كويتي",
    "سعودي", "إماراتي", "قطري", "بحريني", "عماني",
    "أردني", "فلسطيني", "عراقي", "تونسي", "جزائري",
]

MOVIE_KW = ["فيلم", "فيلمو", "movie", "film", "سينما"]


def load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {"posters": {}, "categories": {}}


def save_cache(cache):
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ═══════════════════════════════════════════════════════════════
# ★ التصنيف التلقائي — النسخة المحسّنة ★
# ═══════════════════════════════════════════════════════════════
def detect_type(name, episodes):
    """series أو movie"""
    name_lower = name.lower()

    if any(k in name or k in name_lower for k in MOVIE_KW):
        return "movie"

    if len(episodes) <= 1:
        if episodes:
            dur = episodes[0].get("duration", 0) or 0
            if dur >= 4800:  # 80 دقيقة
                return "movie"
        return "movie"

    if len(episodes) <= 3:
        long_count = sum(1 for e in episodes if (e.get("duration", 0) or 0) >= 4800)
        if long_count == len(episodes):
            return "movie"

    return "series"


def detect_origin(name, episodes):
    """
    ★ النسخة المحسّنة ★
    - أولاً: كلمة "مدبلج" أو "تركي" → turkish
    - ثانياً: كلمات مفتاحية تركية
    - ثالثاً: كلمات مفتاحية عربية
    - رابعاً: تحليل الحروف
    """
    name_lower = name.lower()

    # ★ أولاً: كلمات صريحة ★
    if "مدبلج" in name or "تركي" in name or "تركية" in name:
        return "turkish"

    # ★ ثانياً: كلمات مفتاحية تركية ★
    for kw in TURKISH_KW:
        if kw in name or kw.lower() in name_lower:
            return "turkish"

    # ★ ثالثاً: كلمات مفتاحية عربية ★
    for kw in ARABIC_KW:
        if kw in name or kw.lower() in name_lower:
            return "arabic"

    # ★ رابعاً: تحليل الحروف ★
    arabic_chars = len(re.findall(r"[\u0600-\u06FF]", name))
    english_chars = len(re.findall(r"[a-zA-Z]", name))

    if arabic_chars > 0 and english_chars == 0:
        # اسم عربي بالكامل — لكن قد يكون تركي مترجم
        # نستخدم heuristic: إذا كان الاسم طويلاً وفيه كلمات شائعة
        return "arabic"

    # ★ افتراضي: أجنبي ★
    return "foreign"


# ═══════════════════════════════════════════════════════════════
# جلب الصور
# ═══════════════════════════════════════════════════════════════
def clean_for_search(name):
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"^(مسلسل|مشاهدة|فيلم)\s+", "", name)
    name = re.sub(r"\s*(مدبلج|مترجم)\s*", " ", name)
    return name.strip()


def tmdb_search(session, name, year=""):
    if not TMDB_API_KEY:
        return ""
    clean = clean_for_search(name)
    if not clean:
        return ""

    for endpoint in ("tv", "movie"):
        try:
            params = {
                "api_key": TMDB_API_KEY,
                "query": clean,
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

    try:
        query = f"{clean} بوستر مسلسل"
        url = f"https://www.bing.com/images/search?q={quote(query)}&qft=+filterui:imagesize-large"
        r = session.get(url, headers=BING_HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return ""

        matches = re.findall(r'"murl":"(https?://[^"]+)"', r.text)
        for m_url in matches[:5]:
            m_url = m_url.replace("\\/", "/")
            if any(ext in m_url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                if not any(bad in m_url.lower() for bad in ["logo", "icon", "avatar"]):
                    return m_url
    except Exception:
        pass

    return ""


def make_placeholder_svg(name):
    first = name.strip()[:1] if name.strip() else "?"
    h = hash(name) % 360
    color1 = f"hsl({h}, 60%, 25%)"
    color2 = f"hsl({(h+40)%360}, 60%, 15%)"

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 450">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{color1}"/>
      <stop offset="100%" stop-color="{color2}"/>
    </linearGradient>
  </defs>
  <rect width="300" height="450" fill="url(#g)"/>
  <text x="150" y="225" font-family="Cairo, sans-serif" font-size="120"
        font-weight="900" fill="rgba(255,255,255,.9)"
        text-anchor="middle" dominant-baseline="middle">{first}</text>
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

    poster = tmdb_search(session, name, series.get("tmdb_year", ""))
    if poster:
        print(f"   ✅ TMDB: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    poster = bing_images(session, name)
    if poster:
        print(f"   🖼️  Bing: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    print(f"   ⚠️  Placeholder: {name}")
    poster = make_placeholder_svg(name)
    series["poster_url"] = poster
    cache["posters"][cache_key] = poster
    return series


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
def main():
    if not DATA_FILE.exists():
        print(f"❌ {DATA_FILE} غير موجود")
        raise SystemExit(1)

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    series_list = data.get("series", [])
    cache = load_cache()

    print(f"📚 {len(series_list)} عمل")
    print(f"🔧 {MAX_WORKERS} threads\n")

    session = requests.Session()
    session.headers.update({"Accept-Encoding": "gzip, deflate"})

    start = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(enrich_one, s, cache, session) for s in series_list]
        for _ in as_completed(futures):
            pass

    elapsed = time.time() - start
    print(f"\n⏱️  {elapsed:.1f}s")

    from collections import Counter
    types = Counter(s.get("type", "?") for s in series_list)
    origins = Counter(s.get("origin", "?") for s in series_list)
    with_poster = sum(
        1 for s in series_list
        if s.get("poster_url", "") and not s.get("poster_url", "").startswith("data:")
    )

    print(f"\n📊 الإحصائيات:")
    for k, v in types.items():
        print(f"   • {k}: {v}")
    for k, v in origins.items():
        print(f"   • {k}: {v}")
    print(f"   • صور حقيقية: {with_poster}/{len(series_list)}")

    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_cache(cache)
    print(f"\n💾 {DATA_FILE.name}")
    print(f"💾 Cache ({len(cache['posters'])} صورة)")


if __name__ == "__main__":
    main()
