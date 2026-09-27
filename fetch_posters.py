#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_posters.py — جلب صور المسلسلات من TMDB
يقرأ data.json، يبحث عن كل مسلسل بدون صورة، ويضيف poster_url
"""

import os
import json
import time
import re
from pathlib import Path
from urllib.parse import quote

import requests

# ═══════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════
ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p/w500"

if not TMDB_API_KEY:
    print("⚠️ TMDB_API_KEY غير مضبوط — سيتم تخطّي جلب الصور")
    raise SystemExit(0)

# ═══════════════════════════════════════════════════════════════
# دوال مساعدة
# ═══════════════════════════════════════════════════════════════
def clean_name_for_search(name: str) -> str:
    """تنظيف اسم المسلسل للبحث"""
    name = re.sub(r"\s+", " ", name).strip()
    # إزالة كلمات زائدة
    name = re.sub(r"^(مسلسل|مشاهدة|فيلم)\s+", "", name)
    return name.strip()


def search_tmdb_tv(name: str) -> dict:
    """يبحث عن مسلسل في TMDB"""
    try:
        r = requests.get(
            f"{TMDB_BASE}/search/tv",
            params={
                "api_key": TMDB_API_KEY,
                "query": name,
                "language": "ar",
                "include_adult": False,
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if results:
            return results[0]
    except Exception as e:
        print(f"   ⚠️ TMDB search failed: {e}")
    return {}


def search_tmdb_movie(name: str) -> dict:
    """يبحث عن فيلم في TMDB (احتياطي)"""
    try:
        r = requests.get(
            f"{TMDB_BASE}/search/movie",
            params={
                "api_key": TMDB_API_KEY,
                "query": name,
                "language": "ar",
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if results:
            return results[0]
    except Exception as e:
        print(f"   ⚠️ TMDB movie search failed: {e}")
    return {}


def get_poster_url(item: dict) -> str:
    """يستخرج رابط الصورة من نتيجة TMDB"""
    poster_path = item.get("poster_path")
    if poster_path:
        return f"{TMDB_IMG_BASE}{poster_path}"
    return ""


def get_backdrop_url(item: dict) -> str:
    """يستخرج رابط الخلفية (backdrop) — جودة أعلى"""
    backdrop = item.get("backdrop_path")
    if backdrop:
        return f"https://image.tmdb.org/t/p/w780{backdrop}"
    return ""


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
def main():
    if not DATA_FILE.exists():
        print(f"❌ لم يُعثر على {DATA_FILE}")
        raise SystemExit(1)

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    series_list = data.get("series", [])

    print(f"📚 {len(series_list)} مسلسل")
    updated = 0
    skipped = 0

    for i, series in enumerate(series_list, 1):
        name = series.get("name", "").strip()
        existing = series.get("poster_url", "").strip()

        if existing:
            print(f"[{i}/{len(series_list)}] ⏭  {name} (لديه صورة)")
            skipped += 1
            continue

        if not name:
            continue

        print(f"[{i}/{len(series_list)}] 🔍 {name}...")
        clean = clean_name_for_search(name)

        # محاولة TV أولاً
        result = search_tmdb_tv(clean)

        # إذا لم ينجح، جرب movie
        if not result:
            result = search_tmdb_movie(clean)

        if result:
            poster = get_poster_url(result)
            if poster:
                series["poster_url"] = poster
                series["poster_backdrop"] = get_backdrop_url(result)
                series["tmdb_id"] = result.get("id")
                series["tmdb_overview"] = result.get("overview", "")
                series["tmdb_rating"] = result.get("vote_average", 0)
                series["tmdb_year"] = (result.get("first_air_date") or
                                        result.get("release_date") or "")[:4]
                updated += 1
                print(f"   ✅ {poster[:60]}...")
            else:
                print(f"   ⚠️ لا توجد صورة")
        else:
            print(f"   ⚠️ لم يُعثر على نتائج")

        # احترام حدود TMDB (40 طلب/10 ثواني)
        time.sleep(0.3)

    # حفظ
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n✨ اكتمل: {updated} محدّث، {skipped} متخطّى")
    print(f"💾 {DATA_FILE.name}")


if __name__ == "__main__":
    main()
