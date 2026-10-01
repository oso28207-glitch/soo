#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_uploader.py — رافع تلقائي مع إغلاق آمن
★ يغلق بأمان عند SIGTERM/SIGINT ★
"""

import os
import sys
import json
import time
import re
import signal
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAP_FILE = ROOT / "series_map.json"
STATE_FILE = ROOT / "upload_state.json"
CONFIG_FILE = ROOT / "series_config.json"
MAIN_SCRIPT = ROOT / "main.py"

MAX_RUNTIME_SECONDS = int(os.environ.get("MAX_RUNTIME_MINUTES", "330")) * 60
SECONDS_PER_EPISODE = 3 * 60
SAFETY_MARGIN = 90
MIN_RUN_TIME = 5 * 60
MAX_EPISODES_PER_CALL = 20

SCRIPT_START = time.time()

# ★★★ حالة الإغلاق الآمن ★★★
SHUTDOWN_REQUESTED = False
CURRENT_PROCESS = None


def on_signal(signum, frame):
    """معالج الإشارات — يستجيب لـ SIGTERM/SIGINT بأمان"""
    global SHUTDOWN_REQUESTED
    if SHUTDOWN_REQUESTED:
        print("\n⚠️ إشارة ثانية — إنهاء فوري", flush=True)
        sys.exit(1)
    SHUTDOWN_REQUESTED = True
    sig_name = signal.Signals(signum).name
    print(f"\n🛑 استُلمت {sig_name} — إنهاء آمن...", flush=True)

    # إنهاء العملية الفرعية بأمان
    global CURRENT_PROCESS
    if CURRENT_PROCESS and CURRENT_PROCESS.poll() is None:
        print("   ⏹️ إنهاء main.py بأمان...", flush=True)
        try:
            CURRENT_PROCESS.terminate()
            try:
                CURRENT_PROCESS.wait(timeout=15)
            except subprocess.TimeoutExpired:
                print("   ⚠️ main.py لم يستجب — قتل قسري", flush=True)
                CURRENT_PROCESS.kill()
        except Exception as e:
            print(f"   ⚠️ {e}", flush=True)


# تسجيل معالجات الإشارات
signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGINT, on_signal)


def elapsed():
    e = int(time.time() - SCRIPT_START)
    return f"{e//3600}h{(e%3600)//60}m{e%60}s"


def remaining():
    return max(0, MAX_RUNTIME_SECONDS - (time.time() - SCRIPT_START))


def check_shutdown():
    """يتحقق إذا كان يجب التوقف"""
    if SHUTDOWN_REQUESTED:
        print("🛑 طلب إغلاق معلّق — إيقاف", flush=True)
        return True
    if remaining() < MIN_RUN_TIME:
        print(f"⏰ الوقت المتبقي < {MIN_RUN_TIME//60}m — إيقاف", flush=True)
        return True
    return False


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    """حفظ ذرّي (atomic)"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


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
    uploaded = set()
    for m in re.finditer(r'✅\s+(?:S\d+E)?(\d{1,3})\b', log_text):
        try:
            ep = int(m.group(1))
            if start_ep <= ep <= end_ep:
                uploaded.add(ep)
        except Exception:
            pass

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
    return sorted(uploaded)


def run_main_for_range(series_arabic, slug, season, start_ep, end_ep):
    """يستدعي main.py عبر subprocess مع دعم الإغلاق الآمن"""
    global CURRENT_PROCESS

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
    env["SKIP_PIP_INSTALL"] = "true"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    timeout = num_eps * SECONDS_PER_EPISODE + SAFETY_MARGIN
    timeout = min(timeout, remaining() - 30)
    timeout = max(timeout, 3 * 60)

    try:
        CURRENT_PROCESS = subprocess.Popen(
            [sys.executable, "-u", str(MAIN_SCRIPT)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # line buffered
        )

        log_lines = []
        start_t = time.time()

        # قراءة الإخراج سطراً بسطر (live)
        while True:
            if SHUTDOWN_REQUESTED:
                print("\n🛑 إغلاق آمن لـ main.py...", flush=True)
                CURRENT_PROCESS.terminate()
                try:
                    CURRENT_PROCESS.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    CURRENT_PROCESS.kill()
                break

            if time.time() - start_t > timeout:
                print(f"\n⏰ timeout على main.py", flush=True)
                CURRENT_PROCESS.terminate()
                try:
                    CURRENT_PROCESS.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    CURRENT_PROCESS.kill()
                break

            line = CURRENT_PROCESS.stdout.readline()
            if not line:
                if CURRENT_PROCESS.poll() is not None:
                    break
                time.sleep(0.5)
                continue
            print(line, end="", flush=True)
            log_lines.append(line)

        # قراءة أي متبقٍ
        try:
            remaining_out = CURRENT_PROCESS.stdout.read()
            if remaining_out:
                print(remaining_out, end="", flush=True)
                log_lines.append(remaining_out)
        except Exception:
            pass

        CURRENT_PROCESS.wait(timeout=5)
        log_text = "".join(log_lines)
        uploaded = parse_uploaded_episodes(log_text, start_ep, end_ep)
        return log_text, uploaded

    except Exception as e:
        print(f"❌ فشل تشغيل main.py: {e}", flush=True)
        return "", []
    finally:
        CURRENT_PROCESS = None


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
    rem = remaining()
    available = max(0, rem - MIN_RUN_TIME)
    if available < SECONDS_PER_EPISODE:
        return 0
    n = available // SECONDS_PER_EPISODE
    return min(n, MAX_EPISODES_PER_CALL)


def main():
    print("=" * 60, flush=True)
    print("🤖 Auto Uploader — نسخة الإغلاق الآمن", flush=True)
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS // 60}m", flush=True)
    print(f"📊 {SECONDS_PER_EPISODE // 60}m/حلقة | حد {MAX_EPISODES_PER_CALL} حلقة/استدعاء", flush=True)
    print("=" * 60, flush=True)

    if not MAIN_SCRIPT.exists():
        print(f"❌ {MAIN_SCRIPT.name} غير موجود", flush=True)
        sys.exit(1)

    series_map = load_json(MAP_FILE, {})
    state = load_json(STATE_FILE, {})
    series_list = series_list_from_map(series_map)

    print(f"\n📊 {len(series_list)} مسلسل | state: {len(state)} مفتاح\n", flush=True)

    if not series_list:
        return

    total_uploaded = 0
    processed = 0

    try:
        for series_arabic, slug, season in series_list:
            if check_shutdown():
                break

            batch_size = calculate_episodes_for_time()
            if batch_size < 1:
                print(f"\n⏰ لا وقت لحلقة — إيقاف", flush=True)
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
                print(f"\n✅ {series_arabic}: {len(uploaded)} حلقة مرفوعة", flush=True)
            else:
                print(f"\nℹ️ {series_arabic} S{season:02d}: لا حلقات جديدة", flush=True)

    except KeyboardInterrupt:
        print("\n🛑 KeyboardInterrupt — إغلاق آمن", flush=True)
    finally:
        # حفظ الحالة دائماً حتى عند الإلغاء
        save_json(STATE_FILE, state)
        print(f"\n{'='*60}", flush=True)
        print(f"⏱️ {elapsed()}", flush=True)
        print(f"📺 معالجة: {processed} مسلسل", flush=True)
        print(f"✅ إجمالي المرفوع: {total_uploaded} حلقة", flush=True)
        if SHUTDOWN_REQUESTED:
            print("🛑 تم الإغلاق بأمان", flush=True)
        print(f"{'='*60}", flush=True)


if __name__ == "__main__":
    main()
