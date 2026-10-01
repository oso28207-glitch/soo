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
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAP_FILE = ROOT / "series_map.json"
STATE_FILE = ROOT / "upload_state.json"
CONFIG_FILE = ROOT / "series_config.json"
MAIN_SCRIPT = ROOT / "main.py"

MAX_RUNTIME_SECONDS = int(os.environ.get("MAX_RUNTIME_MINUTES", "330")) * 60

# ★★ إعدادات الوقت ★★
SECONDS_PER_EPISODE = 3 * 60        # 3 دقائق لكل حلقة (تحميل + ضغط + رفع)
SAFETY_MARGIN = 90                  # هامش أمان للإنهاء
MIN_RUN_TIME = 5 * 60               # لا تبدأ إذا المتبقي أقل من 5 دقائق
MAX_EPISODES_PER_CALL = 20          # حد أقصى للحلقات في استدعاء واحد

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
        print(f"⚠️ فشل قراءة {path.name}: {e}", flush=True)
        return default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def state_key(slug, season):
    return f"{slug}_s{season}"


def get_last_uploaded(state, slug, season):
    eps = state.get(state_key(slug, season), [])
    return max(eps) if eps else 0


def mark_uploaded(state, slug, season, episodes):
    key = state_key(slug, season)
    if key not in state:
        state[key] = []
    for ep in episodes:
        if ep not in state[key]:
            state[key].append(ep)
    state[key].sort()
    save_json(STATE_FILE, state)


def parse_uploaded_episodes(log_text, start_ep, end_ep):
    """يستخرج الحلقات المرفوعة من سجل main.py"""
    uploaded = set()

    # نمط 1: "✅ 15" أو "✅ S01E15"
    for m in re.finditer(r'✅\s+(?:S\d+E)?(\d{1,3})\b', log_text):
        try:
            ep = int(m.group(1))
            if start_ep <= ep <= end_ep:
                uploaded.add(ep)
        except Exception:
            pass

    # نمط 2: اربط "✅ رُفع في" بالحلقة من "🎬 Ep N"
    lines = log_text.split("\n")
    for i, line in enumerate(lines):
        if ("رُفع في" in line or "رُفعت" in line) and "✅" in line:
            for j in range(max(0, i - 40), i):
                m = re.search(r'🎬\s+(?:Ep|الحلقة)\s+(\d+)', lines[j])
                if m:
                    try:
                        ep = int(m.group(1))
                        if start_ep <= ep <= end_ep:
                            uploaded.add(ep)
                    except Exception:
                        pass
                    break

    # نمط 3: "✅ {series_arabic} S01E05" من auto_uploader نفسه
    for m in re.finditer(r'✅\s+\S+\s+S\d+E(\d{1,3})', log_text):
        try:
            ep = int(m.group(1))
            if start_ep <= ep <= end_ep:
                uploaded.add(ep)
        except Exception:
            pass

    return sorted(uploaded)


def run_main_for_range(series_arabic, slug, season, start_ep, end_ep):
    """يستدعي main.py عبر subprocess. يعيد (log_text, uploaded_episodes)"""
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

    num_eps = end_ep - start_ep + 1

    print(f"\n{'='*60}", flush=True)
    print(f"📺 {series_arabic} → {slug} | موسم {season} | حلقات {start_ep}-{end_ep}", flush=True)
    print(f"⏱️ متبقي: {remaining()//60}m | timeout: {num_eps * SECONDS_PER_EPISODE // 60}m", flush=True)
    print(f"{'='*60}", flush=True)

    env = os.environ.copy()
    env["INPUT_SERIES_NAME"] = slug
    env["INPUT_SERIES_NAME_ARABIC"] = series_arabic
    env["INPUT_SEASON_NUM"] = str(season)
    env["INPUT_START_EPISODE"] = str(start_ep)
    env["INPUT_END_EPISODE"] = str(end_ep)
    # ★★★ الإصلاحات الأساسية ★★★
    env["SKIP_PIP_INSTALL"] = "true"       # تخطي pip داخل main.py
    env["PYTHONUNBUFFERED"] = "1"          # عدم استخدام stdout buffer
    env["PYTHONIOENCODING"] = "utf-8"      # encoding صحيح

    # ★ timeout حسب عدد الحلقات الفعلي
    timeout = num_eps * SECONDS_PER_EPISODE + SAFETY_MARGIN
    timeout = min(timeout, remaining() - 30)
    timeout = max(timeout, 3 * 60)  # 3 دقائق على الأقل

    try:
        # ★ استخدم -u لـ unbuffered output
        result = subprocess.run(
            [sys.executable, "-u", str(MAIN_SCRIPT)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        log_text = (result.stdout or "") + "\n" + (result.stderr or "")
        print("─" * 40, flush=True)
        print("📜 سجل main.py:", flush=True)
        print("─" * 40, flush=True)
        print(log_text, flush=True)
        print("─" * 40, flush=True)

        uploaded = parse_uploaded_episodes(log_text, start_ep, end_ep)
        return log_text, uploaded

    except subprocess.TimeoutExpired as e:
        log_text = ""
        if e.stdout:
            log_text += e.stdout if isinstance(e.stdout, str) else e.stdout.decode("utf-8", "replace")
        if e.stderr:
            log_text += "\n" + (e.stderr if isinstance(e.stderr, str) else e.stderr.decode("utf-8", "replace"))

        print(f"\n⏰ timeout على main.py بعد {timeout//60}m", flush=True)
        print("─" * 40, flush=True)
        print("📜 السجل قبل الانتهاء:", flush=True)
        print("─" * 40, flush=True)
        print(log_text[-5000:], flush=True)  # آخر 5000 حرف
        print("─" * 40, flush=True)

        uploaded = parse_uploaded_episodes(log_text, start_ep, end_ep)
        return log_text, uploaded

    except Exception as e:
        print(f"❌ فشل تشغيل main.py: {e}", flush=True)
        return "", []


def series_list_from_map(series_map):
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


def calculate_episodes_for_time():
    """يحسب عدد الحلقات المناسب للوقت المتبقي"""
    rem = remaining()
    # احتفظ بـ MIN_RUN_TIME للمسلسل التالي
    available = max(0, rem - MIN_RUN_TIME)
    if available < SECONDS_PER_EPISODE:
        return 0
    n = available // SECONDS_PER_EPISODE
    return min(n, MAX_EPISODES_PER_CALL)


def main():
    print("=" * 60, flush=True)
    print("🤖 Auto Uploader (subprocess + unbuffered)", flush=True)
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS // 60}m", flush=True)
    print(f"📊 {SECONDS_PER_EPISODE // 60}m/حلقة | حد {MAX_EPISODES_PER_CALL} حلقة/استدعاء", flush=True)
    print("=" * 60, flush=True)

    if not MAIN_SCRIPT.exists():
        print(f"❌ {MAIN_SCRIPT.name} غير موجود", flush=True)
        sys.exit(1)

    series_map = load_json(MAP_FILE, {})
    state = load_json(STATE_FILE, {})
    series_list = series_list_from_map(series_map)

    print(f"\n📊 {len(series_list)} مسلسل في الخريطة", flush=True)
    print(f"   state: {len(state)} مفتاح\n", flush=True)

    if not series_list:
        print("⚠️ لا مسلسلات", flush=True)
        return

    total_uploaded = 0
    processed = 0

    for series_arabic, slug, season in series_list:
        # إذا الوقت المتبقي لا يكفي، توقف
        if remaining() < MIN_RUN_TIME:
            print(f"\n⏰ الوقت المتبقي أقل من {MIN_RUN_TIME//60} دقائق — إيقاف", flush=True)
            break

        # احسب عدد الحلقات المناسب للوقت المتبقي
        batch_size = calculate_episodes_for_time()
        if batch_size < 1:
            print(f"\n⏰ لا وقت لحلقة جديدة — إيقاف", flush=True)
            break

        last = get_last_uploaded(state, slug, season)
        start_ep = last + 1
        end_ep = start_ep + batch_size - 1

        if start_ep > 200:
            continue

        print(f"\n▶️ {series_arabic} S{season:02d}: {start_ep}-{end_ep} ({batch_size} حلقة)", flush=True)

        _, uploaded = run_main_for_range(
            series_arabic, slug, season, start_ep, end_ep
        )
        processed += 1

        if uploaded:
            mark_uploaded(state, slug, season, uploaded)
            total_uploaded += len(uploaded)
            print(f"\n✅ {series_arabic}: {len(uploaded)} حلقة مرفوعة ({uploaded})", flush=True)
        else:
            print(f"\nℹ️ {series_arabic} S{season:02d}: لا حلقات مرفوعة", flush=True)

    print(f"\n{'='*60}", flush=True)
    print(f"⏱️ {elapsed()}", flush=True)
    print(f"📺 معالجة: {processed} مسلسل", flush=True)
    print(f"✅ إجمالي المرفوع: {total_uploaded} حلقة", flush=True)
    print(f"{'='*60}", flush=True)


if __name__ == "__main__":
    main()
