#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_uploader.py — رافع المسلسلات التلقائي

★ يقرأ المسلسلات من series_map.json
★ يبحث عن حلقات جديدة على u.3seq.com (مع دعم المواسم)
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
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# الإعدادات من البيئة
# ═══════════════════════════════════════════════════════════════
TELEGRAM_API_ID = os.environ.get("API_ID", "")
TELEGRAM_API_HASH = os.environ.get("API_HASH", "")
TELEGRAM_CHANNEL = os.environ.get("CHANNEL", "")
STRING_SESSION = os.environ.get("STRING_SESSION", "").strip()

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() in ("true", "1", "yes")
MAX_RUNTIME_SECONDS = int(os.environ.get("MAX_RUNTIME_MINUTES", "280")) * 60

# مسارات
ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
MAP_FILE = ROOT / "series_map.json"
STATE_FILE = ROOT / "upload_state.json"

# ⚠️ قوالب URL المحتملة على u.3seq.com
# سيجرّب السكربت كل قالب حتى يجد واحداً يعمل
URL_TEMPLATES = [
    # القالب الأساسي (موسم 1 بدون ذكر الموسم)
    "https://u.3seq.com/video/modablaj-{slug}-episode-{ep:02d}",
    # مع رقم الموسم في الرابط
    "https://u.3seq.com/video/modablaj-{slug}-season-{season}-episode-{ep:02d}",
    "https://u.3seq.com/video/modablaj-{slug}-{season}-episode-{ep:02d}",
    "https://u.3seq.com/video/modablaj-{slug}-s{season}-episode-{ep:02d}",
]

# المهلات
MIN_EPISODE_DURATION = 900
WAIT_MIN, WAIT_MAX = 3, 6
EPISODE_TIMEOUT_MAX = 22 * 60
MIN_EPISODE_TIME = 4 * 60

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
# قراءة/كتابة JSON
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


# ═══════════════════════════════════════════════════════════════
# الحالة (state)
# ═══════════════════════════════════════════════════════════════
def load_state():
    """{slug_season: [ep1, ep2, ...]}"""
    return load_json(STATE_FILE, {})


def state_key(slug, season):
    return f"{slug}_s{season}"


def is_uploaded(state, slug, season, ep):
    key = state_key(slug, season)
    return ep in state.get(key, [])


def mark_uploaded(state, slug, season, ep):
    key = state_key(slug, season)
    if key not in state:
        state[key] = []
    if ep not in state[key]:
        state[key].append(ep)
        state[key].sort()


# ═══════════════════════════════════════════════════════════════
# قوالب URL والتحقق
# ═══════════════════════════════════════════════════════════════
def get_url_candidates(slug, season, ep):
    """يولّد قوالب URL المحتملة للحلقة"""
    candidates = []
    for template in URL_TEMPLATES:
        try:
            url = template.format(slug=slug, season=season, ep=ep)
            if url not in candidates:
                candidates.append(url)
        except Exception:
            continue
    return candidates


def check_url_exists(url, timeout=10):
    """يتحقق من وجود URL عبر HTTP"""
    try:
        from curl_cffi import requests as cffi
        r = cffi.get(
            url, impersonate="chrome120", timeout=timeout,
            allow_redirects=True, verify=False,
        )
        if r.status_code != 200:
            return False, None
        text_lower = r.text[:8000].lower()
        # كشف صفحات 404
        if any(marker in text_lower for marker in [
            "404", "not found", "غير موجود", "لا يوجد", "page not found",
        ]):
            return False, None
        # تحقق من وجود "episode" في الرابط
        if "episode" not in url.lower():
            return False, None
        return True, url
    except Exception:
        return False, None


def find_working_url(slug, season, ep):
    """يبحث عن URL صالح للحلقة من بين القوالب"""
    for url in get_url_candidates(slug, season, ep):
        exists, valid = check_url_exists(url)
        if exists:
            return url
    return None


# ═══════════════════════════════════════════════════════════════
# اكتشاف الحلقات الجديدة
# ═══════════════════════════════════════════════════════════════
def discover_new_episodes(slug, season, state, max_ep=300):
    """
    يكتشف الحلقات الجديدة لموسم معين.
    يعيد (first_url_template, [new_eps]).
    """
    key = state_key(slug, season)
    uploaded = state.get(key, [])

    # ابدأ من آخر حلقة + 1
    start = max(uploaded) + 1 if uploaded else 1

    print(f"   🔍 فحص {slug} S{season:02d} بدءاً من الحلقة {start}...", flush=True)

    new_eps = []
    fails = 0
    ep = start

    while ep <= max_ep and fails < 3:
        if exceeded():
            break
        url = find_working_url(slug, season, ep)
        if url:
            new_eps.append(ep)
            fails = 0
            ep += 1
        else:
            fails += 1
            ep += 1

    return new_eps


# ═══════════════════════════════════════════════════════════════
# معالجة مسلسل واحد
# ═══════════════════════════════════════════════════════════════
async def process_series(series_name, slug, season, state, uploader_module):
    """يعالج مسلسل واحد: يكتشف الحلقات الجديدة، يحمّلها ويرفعها."""
    print(f"\n{'='*60}")
    print(f"📺 {series_name}  →  {slug}  |  الموسم {season}")
    print(f"{'='*60}")

    new_eps = discover_new_episodes(slug, season, state)
    if not new_eps:
        print(f"✅ لا حلقات جديدة")
        return 0

    print(f"   🎯 {len(new_eps)} حلقة جديدة: {new_eps[:20]}{'...' if len(new_eps) > 20 else ''}")

    uploaded_count = 0
    for ep in new_eps:
        if exceeded() or remaining() < MIN_EPISODE_TIME:
            print(f"⏰ لا وقت كافٍ — إيقاف")
            return uploaded_count

        if is_uploaded(state, slug, season, ep):
            continue

        print(f"\n🎬 {series_name} — S{season:02d}E{ep:02d}")
        print(f"   ⏳ متبقي: {remaining()//60}m")

        ddir = ROOT / f"dl_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ddir.mkdir(exist_ok=True)
        tmp_ts = str(ddir / f"temp_{ep:02d}.ts")
        fin = str(ddir / f"final_{ep:02d}.mp4")
        thb = str(ddir / f"thumb_{ep:02d}.jpg")

        try:
            # تحميل
            print(f"   📥 تحميل...", flush=True)
            try:
                iframe, cookies, result = uploader_module.process_episode_all_in_one(
                    ep, slug, tmp_ts
                )
            except Exception as e:
                print(f"   ❌ خطأ في التحميل: {e}")
                continue

            if not result or not result[1]:
                print(f"   ❌ فشل التحميل")
                continue

            size = result[0]
            print(f"   ✅ تم التحميل: {size/(1024*1024):.1f} MB")

            # فحص المدة
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
            caption = f"{series_name} الموسم {season} الحلقة {ep}"
            ok = await uploader_module.upload(
                fin, caption,
                thb if os.path.exists(thb) else None,
                override_duration=final_dur,
            )

            if ok:
                mark_uploaded(state, slug, season, ep)
                save_json(STATE_FILE, state)  # حفظ فوري
                uploaded_count += 1
                print(f"   ✅ رُفعت {series_name} S{season:02d}E{ep:02d}")
            else:
                print(f"   ❌ فشل الرفع")

        except Exception as e:
            print(f"   ❌ خطأ: {e}")
        finally:
            try:
                shutil.rmtree(ddir, ignore_errors=True)
            except:
                pass

        # انتظار
        await asyncio.sleep(random.randint(WAIT_MIN, WAIT_MAX))

    return uploaded_count


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
async def main():
    print("=" * 60)
    print("🤖 Auto Uploader — النسخة التلقائية")
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS // 60}m")
    print("=" * 60)

    if not validate_env():
        sys.exit(1)

    # استيراد main.py
    sys.path.insert(0, str(ROOT))
    try:
        import main as uploader_module
    except ImportError as e:
        print(f"❌ فشل استيراد main.py: {e}")
        sys.exit(1)

    # تحميل البيانات
    series_map = load_json(MAP_FILE, {})
    state = load_state()

    # استخراج قائمة المسلسلات (تجاهل المفاتيح الخاصة بـ _)
    series_list = []
    for name, value in series_map.items():
        if name.startswith("_"):
            continue
        if isinstance(value, str):
            # صيغة قديمة: "name": "slug"
            series_list.append((name, value, 1))
        elif isinstance(value, dict):
            slug = value.get("slug", "")
            season = int(value.get("season", 1))
            if slug:
                series_list.append((name, slug, season))

    print(f"\n📊 الإحصائيات:")
    print(f"   مسلسلات للفحص: {len(series_list)}")
    print(f"   حالة سابقة: {len(state)} مفتاح")

    if not series_list:
        print("⚠️ لا مسلسلات — تحقق من series_map.json")
        return

    # الاتصال بـ Telegram
    if not TEST_MODE:
        if not await uploader_module.setup_telegram():
            print("❌ فشل الاتصال بـ Telegram")
            sys.exit(1)

    # معالجة كل مسلسل
    total = 0
    try:
        for series_name, slug, season in series_list:
            if exceeded() or remaining() < MIN_EPISODE_TIME:
                print(f"\n⏰ لا وقت كافٍ — إيقاف")
                break
            try:
                n = await process_series(series_name, slug, season, state, uploader_module)
                total += n
            except Exception as e:
                print(f"❌ خطأ في {series_name}: {e}")
                continue
    finally:
        try:
            if uploader_module.app:
                await uploader_module.app.stop()
        except:
            pass
        save_json(STATE_FILE, state)

    print(f"\n{'='*60}")
    print(f"⏱️ {elapsed_str()}")
    print(f"✅ رُفعت {total} حلقة جديدة")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())