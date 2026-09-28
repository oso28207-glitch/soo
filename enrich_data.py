#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_data.py — إثراء data.json بالتصنيفات والصور
- تصنيف تلقائي (نوع + أصل)
- جلب صور من TMDB + Bing Images
- معالجة متوازية سريعة
- Cache لمنع الطلبات المكررة
"""

import os
import re
import json
import time
import requests
from pathlib import Path
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

# ═══════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════
ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
CACHE_FILE = ROOT / ".poster_cache.json"

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w500"

MAX_WORKERS = 8
TIMEOUT = 8

# ═══════════════════════════════════════════════════════════════
# كلمات مفتاحية للتصنيف
# ═══════════════════════════════════════════════════════════════
TURKISH_KW = [
    "قيامة", "عثمان", "أرطغرل", "حريم السلطان", "وادي الذئاب",
    "الأزهار الحزينة", "أسمر", "أنت اطرق بابي", "قلعة",
    "خاطفة", "صفقة", "الخائن", "مدبلج", "تركي", "Turkish",
    "كان يا مكان", "بين", "مريم", "حكايتنا", "فتاة النافذة",
    "حب أعمى", "قلب الأسد", "الحفرة", "قيامة عثمان",
    "دموع وردة", "إيزيل", "العشق المشبوه", "عشق ودموع",
    "لا احد يعلم", "المدينة", "الطبيب المعجزة",
]

ARABIC_KW = [
    "اتنين", "المصيدة", "الاختيار", "الحشاشين", "المداح",
    "جعفر العمدة", "بيت الرفاعي", "العتاولة", "نسل الأغراب",
    "مافيا", "بابا المجال", "كوبرا", "سيد الناس", "الهيبة",
    "عربي", "مصري", "خليجي", "سوري", "لبناني", "مغربي",
    "أم الدنيا", "قصر السيد", "الأب الروحي", "لعبة نيوتن",
]

MOVIE_KW = ["فيلم", "movie", "film", "فيلمو"]

# ═══════════════════════════════════════════════════════════════
# تحميل/حفظ الـ Cache
# ═══════════════════════════════════════════════════════════════
def load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except: pass
    return {"posters": {}, "categories": {}}


def save_cache(cache):
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ═══════════════════════════════════════════════════════════════
# التصنيف التلقائي
# ═══════════════════════════════════════════════════════════════
def detect_type(name, episodes):
    """
    يحدد نوع المحتوى: series أو movie
    - عدد حلقات <= 1 → فيلم
    - مدة > 80 دقيقة والحلقة غير مرقّمة → فيلم
    - كلمة "فيلم" في الاسم → فيلم
    """
    name_lower = name.lower()

    # إذا الاسم يحتوي "فيلم"
    if any(k in name or k in name_lower for k in MOVIE_KW):
        return "movie"

    # إذا حلقة واحدة فقط → فيلم
    if len(episodes) <= 1:
        # تحقق من المدة
        if episodes:
            dur = episodes[0].get("duration", 0) or 0
            if dur >= 4800:  # 80 دقيقة
                return "movie"
        return "movie"

    # إذا 2 حلقات والمدة > 80 دقيقة لكل منهما → ممكن فيلمين
    if len(episodes) <= 3:
        long_count = sum(1 for e in episodes if (e.get("duration", 0) or 0) >= 4800)
        if long_count >= len(episodes):
            return "movie"

    return "series"


def detect_origin(name, episodes):
    """
    يحدد الأصل: arabic أو turkish أو foreign
    """
    name_lower = name.lower()

    # كلمات تركية
    for kw in TURKISH_KW:
        if kw in name or kw.lower() in name_lower:
            return "turkish"

    # كلمات عربية
    for kw in ARABIC_KW:
        if kw in name or kw.lower() in name_lower:
            return "arabic"

    # إذا الاسم يحتوي حروفاً عربية (بدون كلمات إنجليزية) → عربي
    arabic_chars = len(re.findall(r"[\u0600-\u06FF]", name))
    english_chars = len(re.findall(r"[a-zA-Z]", name))
    if arabic_chars > 0 and english_chars == 0:
        # ربما عربي — خاصة إذا كان الاسم من قناة عربية
        return "arabic"

    # افتراضي: أجنبي
    return "foreign"


def detect_category_slug(name, episodes):
    """يُعيد slug للتصنيف: series-arabic, movie-turkish, etc."""
    ctype = detect_type(name, episodes)
    origin = detect_origin(name, episodes)
    return f"{ctype}-{origin}"


# ═══════════════════════════════════════════════════════════════
# جلب الصور — TMDB
# ═══════════════════════════════════════════════════════════════
def clean_for_search(name):
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"^(مسلسل|مشاهدة|فيلم)\s+", "", name)
    # إزالة "مدبلج" للبحث
    name = re.sub(r"\s*(مدبلج|مترجم)\s*", " ", name)
    return name.strip()


def tmdb_search(session, name, year=""):
    """يبحث في TMDB"""
    if not TMDB_API_KEY:
        return ""

    clean = clean_for_search(name)
    if not clean:
        return ""

    # جرب TV ثم Movie
    for endpoint in ("tv", "movie"):
        try:
            params = {
                "api_key": TMDB_API_KEY,
                "query": clean,
                "language": "ar",
            }
            if year:
                params["year"] = year if endpoint == "movie" else None
                if endpoint == "tv":
                    params["first_air_date_year"] = year

            r = session.get(
                f"{TMDB_BASE}/search/{endpoint}",
                params={k: v for k, v in params.items() if v},
                timeout=TIMEOUT,
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                # رتب حسب popularity
                results.sort(key=lambda x: x.get("popularity", 0), reverse=True)
                for result in results[:3]:
                    poster = result.get("poster_path")
                    if poster:
                        return f"{TMDB_IMG}{poster}"
        except Exception:
            pass

    return ""


# ═══════════════════════════════════════════════════════════════
# جلب الصور — Bing Images (بدون API key)
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
    """يبحث في Bing Images ويستخرج أول صورة كبيرة"""
    clean = clean_for_search(name)
    if not clean:
        return ""

    try:
        # أضف "بوستر" لتحسين النتائج
        query = f"{clean} بوستر مسلسل"
        url = f"https://www.bing.com/images/search?q={quote(query)}&qft=+filterui:imagesize-large"

        r = session.get(url, headers=BING_HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return ""

        # استخراج murl (media URL)
        matches = re.findall(r'"murl":"(https?://[^"]+)"', r.text)
        for m_url in matches[:5]:
            # تنظيف
            m_url = m_url.replace("\\/", "/")
            # تجاهل الصور الصغيرة أو من مواقع غير موثوقة
            if any(ext in m_url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                if not any(bad in m_url.lower() for bad in ["logo", "icon", "avatar"]):
                    return m_url
    except Exception:
        pass

    return ""


# ═══════════════════════════════════════════════════════════════
# Placeholder SVG كخيار أخير
# ═══════════════════════════════════════════════════════════════
def make_placeholder_svg(name):
    """يُنشئ SVG جميل كصورة احتياطية"""
    # أخذ أول حرف
    first = name.strip()[:1] if name.strip() else "?"

    # اختيار لون حسب hash الاسم
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

    # ترميز كـ data URI
    from urllib.parse import quote as q
    return "data:image/svg+xml;charset=utf-8," + q(svg, safe="")


# ═══════════════════════════════════════════════════════════════
# إثراء مسلسل واحد
# ═══════════════════════════════════════════════════════════════
def enrich_one(series, cache, session):
    """يُثري مسلسلاً واحداً: تصنيف + صورة"""
    name = series.get("name", "").strip()
    if not name:
        return series

    # ─── التصنيف ───
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

    # ─── الصورة ───
    existing = series.get("poster_url", "").strip()
    if existing and not existing.startswith("data:"):
        # تحقق من صلاحيتها
        series["poster_url"] = existing
        return series

    # من الـ cache؟
    cache_key = f"{name}|{series.get('tmdb_year','')}"
    cached = cache["posters"].get(cache_key)
    if cached:
        series["poster_url"] = cached
        return series

    # جرب TMDB أولاً
    poster = tmdb_search(session, name, series.get("tmdb_year", ""))
    if poster:
        print(f"   ✅ TMDB: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # Bing Images
    poster = bing_images(session, name)
    if poster:
        print(f"   🖼️  Bing: {name}")
        series["poster_url"] = poster
        cache["posters"][cache_key] = poster
        return series

    # Placeholder
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
        print(f"❌ لم يُعثر على {DATA_FILE}")
        raise SystemExit(1)

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    series_list = data.get("series", [])
    cache = load_cache()

    print(f"📚 {len(series_list)} مسلسل/فيلم")
    print(f"🔧 معالجة متوازية بـ {MAX_WORKERS} threads\n")

    # Session مشترك
    session = requests.Session()
    session.headers.update({"Accept-Encoding": "gzip, deflate"})

    # ─── معالجة متوازية ───
    start = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(enrich_one, s, cache, session): i
            for i, s in enumerate(series_list)
        }
        for fut in as_completed(futures):
            pass  # النتائج تُحدَّث في المكان

    elapsed = time.time() - start
    print(f"\n⏱️  الوقت: {elapsed:.1f}s")

    # ─── إحصائيات ───
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

    # ─── حفظ ───
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_cache(cache)
    print(f"\n💾 حفظ {DATA_FILE.name}")
    print(f"💾 حفظ Cache ({len(cache['posters'])} صورة)")


if __name__ == "__main__":
    main()
