#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_uploader.py — رافع المسلسلات التلقائي

★ يقرأ المسلسلات من data.json و series_map.json
★ يبحث عن حلقات جديدة على u.3seq.com
★ يحمّل + يضغط + يرفع للقناة
★ يحفظ التقدّم في upload_state.json
"""

import os
import sys
import json
import time
import random
import asyncio
import subprocess
import shutil
import tempfile
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# ═══════════════════════════════════════════════════════════════
# الإعدادات من البيئة
# ═══════════════════════════════════════════════════════════════
TELEGRAM_API_ID = os.environ.get("API_ID", "")
TELEGRAM_API_HASH = os.environ.get("API_HASH", "")
TELEGRAM_CHANNEL = os.environ.get("CHANNEL", "")
STRING_SESSION = os.environ.get("STRING_SESSION", "").strip()

# التحكم
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() in ("true", "1", "yes")
MAX_RUNTIME_SECONDS = int(os.environ.get("MAX_RUNTIME_MINUTES", "280")) * 60

# مسارات الملفات
ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
MAP_FILE = ROOT / "series_map.json"
STATE_FILE = ROOT / "upload_state.json"
CONFIG_FILE = ROOT / "series_config.json"

# الموقع
BASE_SITE = "https://u.3seq.com/video/modablaj-{slug}-episode-{ep:02d}"

# المهلات
MIN_EPISODE_DURATION = 900          # 15 دقيقة
WAIT_MIN, WAIT_MAX = 3, 6
EPISODE_TIMEOUT_MAX = 22 * 60
MIN_EPISODE_TIME = 4 * 60

# الضغط
COMPRESS_PRESET = "veryfast"
COMPRESS_CRF = 28
COMPRESS_THREADS = 2
COMPRESS_SCALE = 144

SCRIPT_START = time.time()


# ═══════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════
def elapsed_str():
    e = int(time.time() - SCRIPT_START)
    return f"{e//3600}h{(e%3600)//60}m{e%60}s"


def remaining():
    return max(0, MAX_RUNTIME_SECONDS - (time.time() - SCRIPT_START))


def exceeded():
    return (time.time() - SCRIPT_START) >= MAX_RUNTIME_SECONDS


def validate_env():
    if TEST_MODE:
        print("🧪 TEST_MODE")
        return True
    errs = []
    if not TELEGRAM_API_ID: errs.append("❌ API_ID")
    if not TELEGRAM_API_HASH: errs.append("❌ API_HASH")
    if not TELEGRAM_CHANNEL: errs.append("❌ CHANNEL")
    if not STRING_SESSION: errs.append("❌ STRING_SESSION")
    if errs:
        print("\n".join(errs))
        return False
    return True


# ═══════════════════════════════════════════════════════════════
# تحميل البيانات والتقدّم
# ═══════════════════════════════════════════════════════════════
def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ فشل قراءة {path.name}: {e}")
        return default


def save_json(path, data):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"💾 حفظ {path.name}")
    except Exception as e:
        print(f"⚠️ فشل حفظ {path.name}: {e}")


def load_state():
    """حالة الرفع: {slug: {"season": [ep1, ep2, ...]}}"""
    return load_json(STATE_FILE, {})


def save_state(state):
    save_json(STATE_FILE, state)


def is_uploaded(state, slug, season, episode):
    """هل رُفعت هذه الحلقة سابقاً؟"""
    if slug not in state:
        return False
    season_key = str(season)
    if season_key not in state[slug]:
        return False
    return episode in state[slug][season_key]


def mark_uploaded(state, slug, season, episode):
    """تسجيل حلقة كمرفوعة"""
    if slug not in state:
        state[slug] = {}
    season_key = str(season)
    if season_key not in state[slug]:
        state[slug][season_key] = []
    if episode not in state[slug][season_key]:
        state[slug][season_key].append(episode)
        state[slug][season_key].sort()


# ═══════════════════════════════════════════════════════════════
# اكتشاف الحلقات المتاحة
# ═══════════════════════════════════════════════════════════════
def probe_episode_exists(slug, episode, timeout=8):
    """يتحقق من وجود حلقة عبر HTTP request سريع"""
    try:
        from curl_cffi import requests as cffi
        url = BASE_SITE.format(slug=slug, ep=episode)
        r = cffi.get(url, impersonate="chrome120", timeout=timeout,
                     allow_redirects=True, verify=False)
        # إذا كان 200 أو 3xx فالموقع موجود
        if r.status_code in (200, 301, 302):
            # ابحث عن علامة 404
            text_lower = r.text[:5000].lower()
            if "404" in text_lower or "not found" in text_lower or "غير موجود" in r.text:
                return False
            return True
        return False
    except Exception:
        # إذا فشل الاتصال، نفترض أن الصفحة قد لا تكون موجودة
        return False


def discover_episodes_for_season(slug, season, state, max_ep=200):
    """
    يكتشف الحلقات المتاحة في موسم معين.
    يعيد قائمة بالأرقام الجديدة فقط.
    """
    new_episodes = []

    # ابدأ من آخر حلقة مرفوعة + 1
    season_key = str(season)
    uploaded_eps = []
    if slug in state and season_key in state[slug]:
        uploaded_eps = state[slug][season_key]

    if uploaded_eps:
        start = max(uploaded_eps) + 1
    else:
        start = 1

    print(f"   🔍 فحص الموسم {season} من الحلقة {start}...", flush=True)

    consecutive_fails = 0
    ep = start
    while ep <= max_ep and consecutive_fails < 3:
        if exceeded():
            break
        exists = probe_episode_exists(slug, ep)
        if exists:
            new_episodes.append(ep)
            consecutive_fails = 0
            ep += 1
        else:
            # جرّب حلقات متجاوزة (قد تكون هناك حلقة مفقودة)
            consecutive_fails += 1
            ep += 1

    return new_episodes


def find_available_seasons(slug, state, max_seasons=15):
    """
    يجد المواسم التي تحتوي على حلقات جديدة.
    يعيد قائمة بأرقام المواسم.
    """
    seasons_with_new = []

    for season in range(1, max_seasons + 1):
        if exceeded():
            break
        eps = discover_episodes_for_season(slug, season, state, max_ep=200)
        if eps:
            seasons_with_new.append((season, eps))
        elif season > 1:
            # إذا كان الموسم 2+ فارغ والموسم 1 يحتوي على حلقات، توقف
            break

    return seasons_with_new


# ═══════════════════════════════════════════════════════════════
# تحميل الحلقة (مبني على main.py)
# ═══════════════════════════════════════════════════════════════
def download_episode(slug, episode, out_path):
    """يحمّل حلقة من الموقع. يُعيد (success, size)"""
    # نستورد من main.py
    try:
        sys.path.insert(0, str(ROOT))
        # استخدم الدالة من main.py
        import main as uploader_module

        print(f"   📥 تحميل {slug} S01E{episode:02d}...", flush=True)
        iframe, cookies, result = uploader_module.process_episode_all_in_one(
            episode, slug, out_path
        )
        if result and result[1]:
            return True, result[0]
        return False, 0
    except Exception as e:
        print(f"   ❌ فشل التحميل: {e}", flush=True)
        return False, 0


# ═══════════════════════════════════════════════════════════════
# العملية الرئيسية
# ═══════════════════════════════════════════════════════════════
async def process_series(series_arabic, slug, state, uploader_module):
    """
    يعالج مسلسل واحد: يجد المواسم والحلقات الجديدة، يحمّلها ويرفعها.
    """
    print(f"\n{'='*60}")
    print(f"📺 {series_arabic}  →  {slug}")
    print(f"{'='*60}")

    # ابحث عن مواسم بها حلقات جديدة
    seasons = find_available_seasons(slug, state)
    if not seasons:
        print(f"✅ لا حلقات جديدة")
        return 0

    total_uploaded = 0
    for season, episodes in seasons:
        print(f"\n🎬 الموسم {season}: {len(episodes)} حلقة جديدة")
        for ep in episodes:
            if exceeded() or remaining() < MIN_EPISODE_TIME:
                print(f"⏰ لا وقت كافٍ")
                return total_uploaded

            if is_uploaded(state, slug, season, ep):
                continue

            # تحميل
            ddir = ROOT / f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            ddir.mkdir(exist_ok=True)
            tmp_ts = str(ddir / f"temp_{ep:02d}.ts")
            fin = str(ddir / f"final_{ep:02d}.mp4")
            thb = str(ddir / f"thumb_{ep:02d}.jpg")

            try:
                ok, size = download_episode(slug, ep, tmp_ts)
                if not ok or not os.path.exists(tmp_ts):
                    print(f"   ❌ فشل التحميل — توقف")
                    break

                # تحقق المدة
                duration = uploader_module.get_real_duration(tmp_ts)
                print(f"   🎞️ المدة: {duration}s")
                if duration < MIN_EPISODE_DURATION:
                    print(f"   ⚠️ مدة قصيرة — تجاهل")
                    continue

                # ضغط
                print(f"   🗜️ ضغط...")
                if not uploader_module.compress_144p(tmp_ts, fin):
                    shutil.copy2(tmp_ts, fin)

                # thumbnail
                uploader_module.thumb(fin, thb)

                # رفع
                final_dur = uploader_module.get_real_duration(fin)
                caption = f"{series_arabic} الموسم {season} الحلقة {ep}"
                ok = await uploader_module.upload(
                    fin, caption,
                    thb if os.path.exists(thb) else None,
                    override_duration=final_dur,
                )

                if ok:
                    mark_uploaded(state, slug, season, ep)
                    save_state(state)  # حفظ فوري
                    total_uploaded += 1
                    print(f"   ✅ {series_arabic} S{season:02d}E{ep:02d}")

            except Exception as e:
                print(f"   ❌ خطأ: {e}")
            finally:
                # تنظيف
                try:
                    shutil.rmtree(ddir, ignore_errors=True)
                except:
                    pass

            # انتظار
            await asyncio.sleep(random.randint(WAIT_MIN, WAIT_MAX))

    return total_uploaded


async def main():
    print("=" * 60)
    print("🤖 Auto Uploader — نسخة تلقائية من main.py")
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS // 60}m")
    print("=" * 60)

    # التحقق من البيئة
    if not validate_env():
        sys.exit(1)

    # تثبيت المكتبات
    sys.path.insert(0, str(ROOT))
    uploader_module = None
    try:
        import main as uploader_module
    except ImportError as e:
        print(f"❌ فشل استيراد main.py: {e}")
        sys.exit(1)

    # تحميل البيانات
    if not DATA_FILE.exists():
        print(f"❌ {DATA_FILE.name} غير موجود")
        sys.exit(1)

    data = load_json(DATA_FILE, {"series": []})
    series_map = load_json(MAP_FILE, {})
    state = load_state()

    print(f"\n📊 الإحصائيات:")
    print(f"   مسلسلات في data.json: {len(data.get('series', []))}")
    print(f"   mappings: {len([k for k in series_map if not k.startswith('_')])}")
    print(f"   في state: {len(state)} مسلسل")

    # الاتصال بـ Telegram
    if not TEST_MODE:
        if not await uploader_module.setup_telegram():
            print("❌ فشل الاتصال بـ Telegram")
            sys.exit(1)

    # الحصول على قائمة المسلسلات من data.json
    series_list = []
    for s in data.get("series", []):
        name = s.get("name", "").strip()
        if not name:
            continue
        slug = series_map.get(name)
        if not slug:
            # تخطى المسلسلات الأجنبية أو التي ليس لها mapping
            continue
        if isinstance(slug, dict):  # دعم الصيغة القديمة
            slug = slug.get("slug", "")
        if slug:
            series_list.append((name, slug))

    print(f"\n✅ {len(series_list)} مسلسل جاهز للفحص\n")

    if not series_list:
        print("⚠️ لا مسلسلات — تحقق من series_map.json")
        return

    # معالجة كل مسلسل
    total = 0
    try:
        for series_arabic, slug in series_list:
            if exceeded() or remaining() < MIN_EPISODE_TIME:
                print(f"\n⏰ لا وقت كافٍ — إيقاف مؤقت")
                break

            try:
                n = await process_series(series_arabic, slug, state, uploader_module)
                total += n
            except Exception as e:
                print(f"❌ خطأ في {series_arabic}: {e}")
                continue

    finally:
        # إيقاف الاتصال
        try:
            if uploader_module.app:
                await uploader_module.app.stop()
        except:
            pass

        # حفظ الحالة
        save_state(state)

    print(f"\n{'='*60}")
    print(f"⏱️ {elapsed_str()}")
    print(f"✅ رُفعت {total} حلقة جديدة")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())