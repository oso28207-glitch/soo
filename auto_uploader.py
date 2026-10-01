#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_uploader.py — رافع تلقائي يستدعي main.py عبر subprocess
"""

import os
import sys
import json
import time
import re
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAP_FILE = ROOT / "series_map.json"
STATE_FILE = ROOT / "upload_state.json"
CONFIG_FILE = ROOT / "series_config.json"
MAIN_SCRIPT = ROOT / "main.py"

MAX_RUNTIME_SECONDS = int(os.environ.get("MAX_RUNTIME_MINUTES", "330")) * 60
EPISODES_PER_CALL = 15       # عدد الحلقات لكل استدعاء main.py
MIN_RUN_TIME = 6 * 60        # لا تبدأ تشغيلاً إذا كان المتبقي أقل من 6 دقائق

SCRIPT_START = time.time()


def elapsed():
    e = int(time.time() - SCRIPT_START)
    return f"{e//3600}h{(e%3600)//60}m{e%60}s"


def remaining():
    return max(0, MAX_RUNTIME_SECONDS - (time.time() - SCRIPT_START))


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ فشل قراءة {path.name}: {e}")
        return default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def state_key(slug, season):
    return f"{slug}_s{season}"


def get_last_uploaded(state, slug, season):
    """آخر حلقة مرفوعة من state (0 إذا لا يوجد)"""
    eps = state.get(state_key(slug, season), [])
    return max(eps) if eps else 0


def mark_uploaded(state, slug, season, episodes):
    """تسجيل حلقات جديدة في state"""
    key = state_key(slug, season)
    if key not in state:
        state[key] = []
    for ep in episodes:
        if ep not in state[key]:
            state[key].append(ep)
    state[key].sort()
    save_json(STATE_FILE, state)


def parse_uploaded_episodes(log_text, start_ep, end_ep):
    """
    يبحث عن الحلقات التي نجح رفعها في سجل main.py
    يبحث عن: "✅ 15" أو "✅ S01E15" أو "رُفع في"
    """
    uploaded = set()
    # نمط 1: "✅ 15" أو "✅ S01E15"
    for m in re.finditer(r'✅\s+(?:S\d+E)?(\d{1,3})\b', log_text):
        try:
            ep = int(m.group(1))
            if start_ep <= ep <= end_ep:
                uploaded.add(ep)
        except Exception:
            pass
    # نمط 2: في سطر نجاح الرفع: "✅ رُفع في ..."
    # نربطه برقم الحلقة من السطر السابق إذا أمكن
    lines = log_text.split("\n")
    for i, line in enumerate(lines):
        if "رُفع في" in line and "✅" in line:
            # ابحث في السطور السابقة عن رقم الحلقة
            for j in range(max(0, i - 30), i):
                m = re.search(r'🎬\s+Ep\s+(\d+)', lines[j])
                if m:
                    try:
                        ep = int(m.group(1))
                        if start_ep <= ep <= end_ep:
                            uploaded.add(ep)
                    except Exception:
                        pass
                    break
    return sorted(uploaded)


def run_main_for_range(series_arabic, slug, season, start_ep, end_ep):
    """
    يستدعي main.py لحلقات محددة عبر subprocess.
    يعيد: (log_text, uploaded_episodes)
    """
    # اكتب series_config.json
    config = {
        "series_name": slug,
        "series_name_arabic": series_arabic,
        "season_num": season,
        "start_episode": start_ep,
        "end_episode": end_ep,
    }
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n{'='*60}")
    print(f"📺 {series_arabic} → {slug} | موسم {season} | حلقات {start_ep}-{end_ep}")
    print(f"{'='*60}", flush=True)

    env = os.environ.copy()
    env["INPUT_SERIES_NAME"] = slug
    env["INPUT_SERIES_NAME_ARABIC"] = series_arabic
    env["INPUT_SEASON_NUM"] = str(season)
    env["INPUT_START_EPISODE"] = str(start_ep)
    env["INPUT_END_EPISODE"] = str(end_ep)
    # أضف تخطي pip إذا كنت مررت SKIP_PIP_INSTALL في workflow
    env.setdefault("SKIP_PIP_INSTALL", "true")

    # حد أقصى للوقت: 22 دقيقة لكل حلقة × عدد الحلقات، بحد أقصى ما تبقّى
    num_eps = end_ep - start_ep + 1
    timeout = min(num_eps * 22 * 60, remaining() - 60)
    timeout = max(timeout, 5 * 60)  # 5 دقائق على الأقل

    try:
        result = subprocess.run(
            [sys.executable, str(MAIN_SCRIPT)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        log_text = (result.stdout or "") + "\n" + (result.stderr or "")
        print(log_text, flush=True)

        uploaded = parse_uploaded_episodes(log_text, start_ep, end_ep)
        return log_text, uploaded

    except subprocess.TimeoutExpired as e:
        log_text = ""
        if e.stdout:
            log_text += e.stdout if isinstance(e.stdout, str) else e.stdout.decode("utf-8", "replace")
        if e.stderr:
            log_text += "\n" + (e.stderr if isinstance(e.stderr, str) else e.stderr.decode("utf-8", "replace"))
        print(f"⏰ timeout على main.py", flush=True)
        uploaded = parse_uploaded_episodes(log_text, start_ep, end_ep)
        return log_text, uploaded

    except Exception as e:
        print(f"❌ فشل تشغيل main.py: {e}", flush=True)
        return "", []


def series_list_from_map(series_map):
    """يستخرج قائمة (arabic_name, slug, season) من series_map.json"""
    out = []
    for name, value in series_map.items():
        if name.startswith("_"):
            continue
        if isinstance(value, str):
            out.append((name, value, 1))
        elif isinstance(value, dict):
            slug = value.get("slug", "")
            season = int(value.get("season", 1))
            if slug:
                out.append((name, slug, season))
    return out


def main():
    print("=" * 60)
    print("🤖 Auto Uploader (subprocess mode)")
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS // 60}m")
    print("=" * 60, flush=True)

    if not MAIN_SCRIPT.exists():
        print(f"❌ {MAIN_SCRIPT.name} غير موجود")
        sys.exit(1)

    series_map = load_json(MAP_FILE, {})
    state = load_json(STATE_FILE, {})
    series_list = series_list_from_map(series_map)

    print(f"\n📊 {len(series_list)} مسلسل في الخريطة")
    print(f"   state: {len(state)} مفتاح\n")

    if not series_list:
        print("⚠️ لا مسلسلات — تحقق من series_map.json")
        return

    total_uploaded = 0

    for series_arabic, slug, season in series_list:
        if remaining() < MIN_RUN_TIME:
            print(f"⏰ الوقت المتبقي أقل من {MIN_RUN_TIME//60} دقائق — إيقاف")
            break

        last = get_last_uploaded(state, slug, season)
        start_ep = last + 1
        end_ep = start_ep + EPISODES_PER_CALL - 1

        # إذا كانت هناك حلقات كثيرة جداً، لا تتجاوز 200 (بعدها توقف عن هذا الموسم)
        if start_ep > 200:
            continue

        print(f"\n▶️ {series_arabic} S{season:02d}: بدء من {start_ep} حتى {end_ep}")

        _, uploaded = run_main_for_range(
            series_arabic, slug, season, start_ep, end_ep
        )

        if uploaded:
            mark_uploaded(state, slug, season, uploaded)
            total_uploaded += len(uploaded)
            print(f"✅ {series_arabic}: {len(uploaded)} حلقة ({uploaded[:10]}{'...' if len(uploaded) > 10 else ''})")
        else:
            print(f"ℹ️ {series_arabic} S{season:02d}: لا حلقات جديدة")

    print(f"\n{'='*60}")
    print(f"⏱️ {elapsed()}")
    print(f"✅ إجمالي المرفوع: {total_uploaded} حلقة")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
