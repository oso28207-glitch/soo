#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - u.3seq.com/.cam
- جلسة 1: جمع روابط iframe
- جلسة 2: استخراج m3u8 (vinovo API + yt-dlp + CDP Mode)
- تحميل متوازي سريع (16 fragment في نفس الوقت)
- ضغط 144p (veryfast, crf 28) — نفس الإعدادات السابقة
- حد زمني 2:45 لتجنب تجاوز 3 ساعات GitHub Actions
- انتظار قصير بين الحلقات (15-30s)
"""

import os
import sys
import time
import json
import subprocess
import shutil
import asyncio
import random
import re
import tempfile
from datetime import datetime

TELEGRAM_API_ID = os.environ.get("API_ID", "")
TELEGRAM_API_HASH = os.environ.get("API_HASH", "")
TELEGRAM_CHANNEL = os.environ.get("CHANNEL", "")
STRING_SESSION = os.environ.get("STRING_SESSION", "")

INPUT_SERIES_NAME = os.environ.get("INPUT_SERIES_NAME", "").strip()
INPUT_SERIES_NAME_ARABIC = os.environ.get("INPUT_SERIES_NAME_ARABIC", "").strip()
INPUT_SEASON_NUM = os.environ.get("INPUT_SEASON_NUM", "").strip()
INPUT_START_EPISODE = os.environ.get("INPUT_START_EPISODE", "").strip()
INPUT_END_EPISODE = os.environ.get("INPUT_END_EPISODE", "").strip()

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() in ("true", "1", "yes")
KEEP_VIDEO = os.environ.get("KEEP_VIDEO", "false").lower() in ("true", "1", "yes")
SKIP_DOWNLOAD = os.environ.get("SKIP_DOWNLOAD", "false").lower() in ("true", "1", "yes")
SKIP_UPLOAD = os.environ.get("SKIP_UPLOAD", "false").lower() in ("true", "1", "yes")
SKIP_COMPRESS = os.environ.get("SKIP_COMPRESS", "false").lower() in ("true", "1", "yes")

# ===== حدود التشغيل =====
MIN_VALID_SIZE = 100 * 1024
MAX_RUNTIME_SECONDS = 2 * 3600 + 45 * 60   # 2:45
WAIT_BETWEEN_EPISODES_MIN = 15
WAIT_BETWEEN_EPISODES_MAX = 30

SCRIPT_START_TIME = time.time()


def elapsed_str():
    e = int(time.time() - SCRIPT_START_TIME)
    return f"{e//3600}h{(e%3600)//60}m{e%60}s"


def remaining_time():
    return max(0, MAX_RUNTIME_SECONDS - (time.time() - SCRIPT_START_TIME))


def time_exceeded():
    return (time.time() - SCRIPT_START_TIME) >= MAX_RUNTIME_SECONDS


def validate_env():
    if TEST_MODE:
        print("🧪 TEST_MODE")
        return True
    errors = []
    if not TELEGRAM_API_ID: errors.append("❌ API_ID is missing")
    if not TELEGRAM_API_HASH: errors.append("❌ API_HASH is missing")
    if not TELEGRAM_CHANNEL: errors.append("❌ CHANNEL is missing")
    if not STRING_SESSION: errors.append("❌ STRING_SESSION is missing")
    if errors:
        print("\n".join(errors))
        return False
    return True


if not validate_env():
    sys.exit(1)


def install_requirements():
    print("📦 Installing requirements...")
    reqs = [
        "yt-dlp>=2024.4.9",
        "seleniumbase>=4.30.0",
        "beautifulsoup4>=4.12.0",
        "curl_cffi>=0.5.10",
    ]
    if not (TEST_MODE and SKIP_UPLOAD):
        reqs += ["pyrogram>=2.0.0", "tgcrypto>=1.2.0"]
    for req in reqs:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", req, "--quiet"])
            print(f"  ✅ {req.split('>=')[0]}")
        except Exception:
            print(f"  ⚠️ Failed to install {req}")


install_requirements()

import yt_dlp
from seleniumbase import SB
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

app = None
if not (TEST_MODE and SKIP_UPLOAD):
    from pyrogram import Client
    from pyrogram.errors import FloodWait


# ============================================================
#  Telegram
# ============================================================
async def setup_telegram():
    global app
    if TEST_MODE and SKIP_UPLOAD:
        print("🧪 SKIP_UPLOAD: تخطي تليغرام")
        return True
    print("\n🔐 Connecting to Telegram...")
    try:
        app = Client(
            "github_uploader",
            api_id=int(TELEGRAM_API_ID),
            api_hash=TELEGRAM_API_HASH,
            session_string=STRING_SESSION.strip(),
            in_memory=True,
        )
        await app.start()
        me = await app.get_me()
        print(f"✅ Connected as {me.first_name}")
        return True
    except Exception as e:
        print(f"❌ Telegram failed: {e}")
        return False


# ============================================================
#  استخراج السيرفرات
# ============================================================
def extract_servers_from_html(html):
    servers = []
    for pattern, order in [
        (re.compile(r'<li[^>]*id=["\'](s_\d+)["\'][^>]*on[Cc]lick=["\']getServer2\([^,]+,\s*(\d+)\s*,\s*(\d+)\s*\)', re.IGNORECASE), "id_first"),
        (re.compile(r'on[Cc]lick=["\']getServer2\([^,]+,\s*(\d+)\s*,\s*(\d+)\s*\)[^>]*id=["\'](s_\d+)["\']', re.IGNORECASE), "click_first"),
    ]:
        for m in pattern.finditer(html):
            g = m.groups()
            if order == "id_first":
                servers.append({"id": g[0], "name": g[0], "video": g[1], "serverId": g[2]})
            else:
                servers.append({"id": g[2], "name": g[2], "video": g[0], "serverId": g[1]})
        if servers:
            break
    if not servers:
        pattern3 = re.compile(r'getServer2\([^,]+,\s*(\d+)\s*,\s*(\d+)\s*\)')
        for i, (video, sid) in enumerate(pattern3.findall(html)):
            servers.append({"id": f"s_{i}", "name": f"server_{i}", "video": video, "serverId": sid})
    for srv in servers:
        m = re.search(rf'id=["\']{re.escape(srv["id"])}["\'][^>]*>([^<]*)<', html)
        if m:
            name = m.group(1).strip().replace('\n', '')
            if name:
                srv["name"] = name
    return servers


def prioritize_servers(servers):
    """
    ✅ ترتيب السيرفرات: vinovo أولاً (الأسرع)، ثم vidaraa، ثم الباقي.
    """
    priority = {"vinovo": 0, "vidaraa": 1, "vids": 2, "v": 3}
    def key(s):
        name = s.get("name", "").lower().strip()
        return priority.get(name, 99)
    return sorted(servers, key=key)


# ============================================================
#  تحقق صارم
# ============================================================
def is_valid_video_url(url, source_url=None):
    if not url or not url.startswith("http"):
        return False
    if source_url and url.rstrip("/") == source_url.rstrip("/"):
        return False
    ul = url.lower()
    indicators = [".m3u8", ".mp4", ".ts", "/hls/", "/video/", "/stream/", "/master", "/playlist"]
    return any(ind in ul for ind in indicators)


# ============================================================
#  vinovo API المباشر
# ============================================================
def try_vinovo_api(iframe_url):
    if "vinovo.to" not in iframe_url:
        return None

    m = re.search(r'/e/([A-Za-z0-9]+)', iframe_url)
    if not m:
        return None
    file_code = m.group(1)

    base_url = iframe_url.split('/e/')[0]
    print(f"   🎯 [vinovo API] filecode={file_code}")

    try:
        r = cffi_requests.get(
            iframe_url, impersonate="chrome120", timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
        )

        token = None
        token_m = re.search(r'name="token"\s+content="([^"]+)"', r.text)
        if token_m:
            token = token_m.group(1)

        api_url = f"{base_url}/api/stream"
        headers = {
            "Content-Type": "application/json",
            "Referer": iframe_url,
            "Origin": base_url,
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        if token:
            headers["X-CSRF-TOKEN"] = token

        resp = cffi_requests.post(
            api_url,
            json={"filecode": file_code, "device": "web"},
            headers=headers,
            impersonate="chrome120",
            timeout=20,
            cookies=r.cookies,
        )

        print(f"   📊 HTTP: {resp.status_code}")

        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                print(f"   ⚠️ غير JSON: {resp.text[:150]}")
                return None

            streaming_url = data.get("streaming_url") or data.get("url") or data.get("file")
            if streaming_url:
                print(f"   ✅ streaming_url: {streaming_url[:130]}")
                return streaming_url
            else:
                print(f"   ⚠️ keys={list(data.keys())[:5]}")
        else:
            print(f"   ⚠️ {resp.text[:120]}")

    except Exception as e:
        print(f"   ⚠️ vinovo API: {str(e)[:120]}")

    return None


# ============================================================
#  CDP Mode
# ============================================================
def extract_m3u8_with_cdp(iframe_url):
    print(f"   🎬 [CDP] فتح {iframe_url}", flush=True)

    log_file = tempfile.mktemp(suffix="_m3u8.txt")
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("")

    def _log(url):
        try:
            with open(log_file, "a", encoding="utf-8") as fh:
                fh.write(url + "\n")
                fh.flush()
        except Exception:
            pass

    try:
        with SB(uc=True, xvfb=True, headless=False, incognito=True,
                ad_block_on=True, disable_csp=True,
                page_load_strategy="eager", locale_code="en") as sb:
            try:
                sb.activate_cdp_mode()
                try:
                    import mycdp

                    async def on_request(event):
                        try:
                            url = event.request.url
                            _log(url)
                            if ".m3u8" in url:
                                print(f"      ✅ m3u8: {url[:130]}", flush=True)
                        except Exception:
                            pass

                    async def on_response(event):
                        try:
                            url = event.response.url
                            _log(url)
                            if ".m3u8" in url:
                                print(f"      ✅ m3u8: {url[:130]}", flush=True)
                        except Exception:
                            pass

                    sb.cdp.add_handler(mycdp.network.RequestWillBeSent, on_request)
                    sb.cdp.add_handler(mycdp.network.ResponseReceived, on_response)
                except Exception as e:
                    print(f"      ⚠️ {str(e)[:100]}", flush=True)

                sb.cdp.open(iframe_url)
                sb.cdp.sleep(8)

                for _ in range(3):
                    try:
                        sb.cdp.click_if_visible("video")
                    except Exception:
                        pass
                    try:
                        sb.cdp.click_if_visible("button.vjs-big-play-button")
                    except Exception:
                        pass
                    sb.cdp.sleep(2)

                sb.cdp.sleep(10)

                try:
                    dom_m3u8 = sb.cdp.execute_script("""
                        return Array.from(document.querySelectorAll('video, source'))
                            .map(el => el.src || el.currentSrc || el.getAttribute('src'))
                            .filter(src => src && src.includes('.m3u8'))[0] || null;
                    """)
                    if dom_m3u8:
                        _log(dom_m3u8)
                except Exception:
                    pass

            except Exception as e:
                print(f"      ❌ {str(e)[:150]}", flush=True)

    except Exception as e:
        print(f"      ❌ {str(e)[:150]}", flush=True)

    urls = []
    try:
        with open(log_file, encoding="utf-8") as fh:
            urls = [u.strip() for u in fh.readlines() if u.strip()]
    except Exception:
        pass
    try:
        os.remove(log_file)
    except Exception:
        pass

    print(f"      📊 {len(urls)} رابط", flush=True)
    if not urls:
        return None

    master_url = best_index = any_m3u8 = None
    for url in urls:
        if ".m3u8" not in url:
            continue
        ul = url.lower()
        if "master.m3u8" in ul or "/master" in ul:
            if not master_url:
                master_url = url
        elif "index_" in ul or "playlist" in ul:
            if not best_index:
                best_index = url
        elif not any_m3u8:
            any_m3u8 = url

    result = master_url or best_index or any_m3u8
    if result:
        print(f"      🎯 {result[:130]}", flush=True)
        return result

    for url in urls:
        if ".mp4" in url:
            return url

    return None


# ============================================================
#  yt-dlp
# ============================================================
def try_ytdlp_extract(iframe_url):
    try:
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'skip_download': True,
            'format': 'best[height<=720]/best',
            'nocheckcertificate': True,
            'extractor_args': {'generic': ['impersonate']}
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(iframe_url, download=False)
            if info:
                candidate = None
                if info.get('url'):
                    candidate = info['url']
                elif info.get('formats'):
                    best = sorted(info['formats'], key=lambda f: f.get('height') or 0)[-1]
                    if best.get('url'):
                        candidate = best['url']

                if candidate and is_valid_video_url(candidate, source_url=iframe_url):
                    return candidate
                elif candidate:
                    print(f"   ⚠️ yt-dlp رابط غير صالح: {candidate[:80]}")
    except Exception as e:
        print(f"   ⚠️ yt-dlp: {str(e)[:100]}")
    return None


# ============================================================
#  الجلسة 1: جمع روابط iframe
# ============================================================
def collect_iframe_urls(episode_num, series_name):
    base_url = f"https://u.3seq.com/video/modablaj-{series_name}-episode-{episode_num:02d}"
    iframe_urls = []

    with SB(uc=True, xvfb=True, headless=False, incognito=True,
            ad_block_on=False, disable_csp=True,
            page_load_strategy="eager", locale_code="en") as sb:
        try:
            print(f"🖥️ [جلسة 1] فتح {base_url}")
            sb.open(base_url)
            time.sleep(4)

            final_url = sb.get_current_url()
            if not final_url.endswith('/'):
                final_url += '/'
            watch_url = final_url + '?do=watch'
            print(f"📺 {watch_url}")
            sb.open(watch_url)
            time.sleep(4)

            try:
                sb.wait_for_element("ul.serversList", timeout=25)
                print("✅ السيرفرات موجودة.")
            except Exception:
                print("⚠️ لا سيرفرات.")
                return iframe_urls

            page_src = sb.get_page_source()
            servers = extract_servers_from_html(page_src)
            if not servers:
                return iframe_urls

            # ✅ ترتيب: vinovo أولاً
            servers = prioritize_servers(servers)
            print(f"📦 {len(servers)} سيرفر (مرتبة حسب الأولوية):")
            for s in servers:
                print(f"   - {s['id']} | {s['name']}")

            for i, srv in enumerate(servers):
                print(f"\n🔄 [{i+1}/{len(servers)}] {srv['name']}")
                try:
                    old_src = None
                    try:
                        old_src = sb.find_element(".watch iframe").get_attribute("src")
                    except Exception:
                        pass

                    clicked = False
                    for method in ["uc_click", "js_click", "click"]:
                        try:
                            getattr(sb, method)(f"#{srv['id']}")
                            clicked = True
                            break
                        except Exception:
                            pass

                    if not clicked:
                        continue

                    new_src = None
                    for _ in range(10):
                        time.sleep(1)
                        try:
                            new_src = sb.find_element(".watch iframe").get_attribute("src")
                            if new_src and new_src != old_src:
                                break
                        except Exception:
                            pass

                    if not new_src or new_src == old_src:
                        print(f"   ⏱️ لم يتغير")
                        continue

                    print(f"   ✅ {new_src[:90]}")
                    iframe_urls.append({"server": srv["name"], "url": new_src})

                except Exception as e:
                    print(f"   ❌ {str(e)[:100]}")

            return iframe_urls

        except Exception as e:
            print(f"❌ {e}")
            return iframe_urls


# ============================================================
#  ✅ التنزيل المُحسَّن (16 fragment متوازي)
# ============================================================
def download_video(video_url, output_path, referer):
    """
    ✅ تحميل سريع جداً باستخدام:
    - concurrent_fragment_downloads: 16 (لملفات m3u8 المجزأة)
    - http_chunk_size: 10 MB (لتسريع التنزيل عبر HTTP)
    - buffersize: 1 MB
    - retries: 10
    """
    try:
        ydl_opts = {
            'format': 'best[height<=720]/best',
            'outtmpl': output_path,
            'quiet': False,
            'no_warnings': False,
            'retries': 10,
            'fragment_retries': 10,
            'socket_timeout': 20,
            'nocheckcertificate': True,
            # ✅ التحميل المتوازي
            'concurrent_fragment_downloads': 16,
            'http_chunk_size': 10485760,   # 10 MB
            'buffersize': 1048576,          # 1 MB
            'extractor_args': {'generic': 'impersonate'},
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': referer or 'https://u.3seq.com/',
                'Origin': 'https://u.3seq.com',
            },
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        if not os.path.exists(output_path):
            return False, "الملف غير موجود"
        size = os.path.getsize(output_path)
        if size < MIN_VALID_SIZE:
            return False, f"الملف صغير ({size} bytes)"
        return True, size
    except Exception as e:
        return False, str(e)[:200]


# ============================================================
#  ✅ الضغط — نفس الإعدادات السابقة (لا تغيير)
# ============================================================
def compress_to_144p(input_path, output_path):
    if not os.path.exists(input_path):
        return False
    input_mb = os.path.getsize(input_path) / (1024 * 1024)
    print(f"   🗜️ ضغط {input_mb:.2f} MB → 144p...")

    cmd = [
        'ffmpeg', '-i', input_path,
        '-vf', 'scale=-2:144',
        '-c:v', 'libx264',
        '-crf', '28',
        '-preset', 'veryfast',     # ✅ نفس الإعداد السابق
        '-c:a', 'aac',
        '-b:a', '64k',              # ✅ نفس الإعداد السابق
        '-movflags', '+faststart',
        '-y', output_path,
    ]
    try:
        start = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        elapsed = time.time() - start

        if result.returncode != 0 or not os.path.exists(output_path):
            print(f"   ❌ ffmpeg: {result.stderr[-200:]}")
            return False

        out_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"   ✅ {input_mb:.2f} MB → {out_mb:.2f} MB في {elapsed:.1f}s")
        return True
    except Exception as e:
        print(f"   ❌ {e}")
        return False


def create_thumbnail(video_path, thumb_path):
    cmd = ['ffmpeg', '-ss', '00:00:05', '-i', video_path,
           '-vframes', '1', '-vf', 'scale=320:180',
           '-f', 'image2', '-y', thumb_path]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30)
        return r.returncode == 0 and os.path.exists(thumb_path)
    except Exception:
        return False


def get_video_metadata(video_path):
    width, height, duration = 1280, 720, 0
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height,duration',
             '-of', 'csv=p=0', video_path],
            capture_output=True, text=True, timeout=10,
        )
        if probe.returncode == 0:
            parts = probe.stdout.strip().split(',')
            if len(parts) >= 2:
                try:
                    width, height = int(parts[0]), int(parts[1])
                except ValueError:
                    pass
            if len(parts) >= 3 and parts[2]:
                try:
                    duration = int(float(parts[2]))
                except ValueError:
                    pass
    except Exception:
        pass
    return width, height, duration


async def upload_video(file_path, caption, thumb_path=None):
    if TEST_MODE and SKIP_UPLOAD:
        print(f"🧪 SKIP_UPLOAD: {file_path} ({os.path.getsize(file_path)/(1024*1024):.2f} MB)")
        return True

    if app is None or not os.path.exists(file_path):
        return False

    file_mb = os.path.getsize(file_path) / (1024 * 1024)
    print(f"   📤 رفع {file_mb:.2f} MB...")

    width, height, duration = get_video_metadata(file_path)
    print(f"   📐 {width}x{height} | {duration}s")

    thumb = thumb_path if thumb_path and os.path.exists(thumb_path) else None

    try:
        start = time.time()
        await app.send_video(
            chat_id=TELEGRAM_CHANNEL,
            video=file_path,
            caption=caption,
            supports_streaming=True,
            width=width,
            height=height,
            duration=duration,
            thumb=thumb,
        )
        print(f"   ✅ رُفع في {time.time() - start:.1f}s")
        return True
    except FloodWait as e:
        print(f"   ⏳ FloodWait {e.value}s...")
        await asyncio.sleep(e.value)
        return await upload_video(file_path, caption, thumb_path)
    except Exception as e:
        print(f"   ❌ {str(e)[:200]}")
        return False


# ============================================================
#  معالجة حلقة
# ============================================================
async def process_episode(episode_num, series_name, series_name_arabic, season_num, download_dir):
    print(f"\n🎬 Episode {episode_num:02d}  [{elapsed_str()}]  ⏳ {remaining_time()//60}m left")

    temp_file = os.path.join(download_dir, f"temp_{episode_num:02d}.mp4")
    final_file = os.path.join(download_dir, f"final_{episode_num:02d}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_{episode_num:02d}.jpg")

    try:
        print(f"\n{'='*60}")
        print("📡 الجلسة 1: جمع روابط iframe")
        print(f"{'='*60}")

        iframe_urls = await asyncio.to_thread(collect_iframe_urls, episode_num, series_name)
        if not iframe_urls:
            return False, "لا توجد روابط"

        print(f"\n📋 {len(iframe_urls)} رابط iframe")

        downloaded_size = 0
        successful_iframe = None
        download_method = None

        for i, item in enumerate(iframe_urls):
            if time_exceeded():
                break

            print(f"\n{'='*60}")
            print(f"🎬 [{i+1}/{len(iframe_urls)}] {item['server']}")
            print(f"{'='*60}")

            candidates = []

            # 1) vinovo API
            if "vinovo.to" in item["url"]:
                print(f"   [1/3] vinovo API...")
                v = await asyncio.to_thread(try_vinovo_api, item["url"])
                if v:
                    candidates.append(("vinovo-API", v))

            # 2) yt-dlp
            print(f"   [2/3] yt-dlp...")
            v = await asyncio.to_thread(try_ytdlp_extract, item["url"])
            if v:
                candidates.append(("yt-dlp", v))

            # 3) CDP Mode
            print(f"   [3/3] CDP Mode...")
            v = await asyncio.to_thread(extract_m3u8_with_cdp, item["url"])
            if v:
                candidates.append(("CDP", v))

            if not candidates:
                print(f"   ❌ لا مرشحين")
                continue

            # ✅ نجرّب كل مرشح — الأولوية للترتيب أعلاه
            for source, url in candidates:
                if time_exceeded():
                    break

                print(f"\n   ⬇️ محاولة التنزيل ({source})...")
                t0 = time.time()
                ok, info = await asyncio.to_thread(
                    download_video, url, temp_file, item["url"]
                )
                dt = time.time() - t0

                if ok:
                    downloaded_size = info
                    successful_iframe = item["url"]
                    download_method = source
                    speed = (info / (1024*1024)) / max(dt, 0.1)
                    print(f"   ✅ ({source}) {info/(1024*1024):.2f} MB في {dt:.1f}s ≈ {speed:.1f} MB/s")
                    break
                else:
                    print(f"   ❌ ({source}) {info}")
                    if os.path.exists(temp_file):
                        try:
                            os.remove(temp_file)
                        except Exception:
                            pass

            if successful_iframe:
                break

        if not successful_iframe:
            return False, "فشل من جميع السيرفرات"

        print(f"\n🎥 نجح من: {download_method} | {downloaded_size/(1024*1024):.2f} MB")

        # ===== ضغط =====
        print(f"\n🗜️ ضغط...")
        if SKIP_COMPRESS:
            shutil.copy2(temp_file, final_file)
        else:
            if not compress_to_144p(temp_file, final_file):
                shutil.copy2(temp_file, final_file)

        if not os.path.exists(final_file):
            return False, "لا ملف نهائي"

        print(f"\n🖼️ Thumbnail...")
        create_thumbnail(final_file, thumb_file)

        print(f"\n📤 رفع...")
        caption = f"{series_name_arabic} الموسم {season_num} الحلقة {episode_num}"
        success = await upload_video(
            final_file, caption,
            thumb_file if os.path.exists(thumb_file) else None,
        )

        if not (TEST_MODE and KEEP_VIDEO):
            for f in [temp_file, final_file, thumb_file]:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception:
                    pass
        else:
            print(f"🧪 KEEP: {final_file}")

        return success, "تم" if success else "فشل الرفع"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"خطأ: {e}"


# ============================================================
#  الإعدادات + main
# ============================================================
def load_config():
    config = {"series_name": "", "series_name_arabic": "", "season_num": 1, "start_episode": 1, "end_episode": 1}
    if os.path.exists("series_config.json"):
        try:
            with open("series_config.json", 'r', encoding='utf-8') as f:
                fc = json.load(f)
            config.update({k: v for k, v in fc.items() if v not in (None, "")})
            print("📄 تم تحميل الإعدادات")
        except Exception as e:
            print(f"⚠️ {e}")

    if INPUT_SERIES_NAME: config["series_name"] = INPUT_SERIES_NAME
    if INPUT_SERIES_NAME_ARABIC: config["series_name_arabic"] = INPUT_SERIES_NAME_ARABIC
    if INPUT_SEASON_NUM: config["season_num"] = int(INPUT_SEASON_NUM)
    if INPUT_START_EPISODE: config["start_episode"] = int(INPUT_START_EPISODE)
    if INPUT_END_EPISODE: config["end_episode"] = int(INPUT_END_EPISODE)
    return config


async def main():
    print("=" * 60)
    print("🎬 معالج الفيديو - u.3seq.com/.cam")
    if TEST_MODE: print("🧪 TEST_MODE")
    if SKIP_UPLOAD: print("🧪 SKIP_UPLOAD")
    if SKIP_COMPRESS: print("🧪 SKIP_COMPRESS")
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS//60}m | انتظار: {WAIT_BETWEEN_EPISODES_MIN}-{WAIT_BETWEEN_EPISODES_MAX}s")
    print(f"⬇️ تحميل متوازي: 16 fragment + 10MB chunks")
    print("=" * 60)

    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg موجود")
    except Exception:
        print("❌ ffmpeg غير موجود")

    config = load_config()
    series_name = str(config.get("series_name", "")).strip().replace(' ', '-')
    series_name_arabic = str(config.get("series_name_arabic", "")).strip() or series_name
    season_num = int(config.get("season_num", 1))
    start_ep = int(config.get("start_episode", 1))
    end_ep = int(config.get("end_episode", 1))

    if not series_name:
        print("❌ اسم المسلسل مطلوب")
        return
    if end_ep - start_ep + 1 > 25:
        end_ep = start_ep + 24

    print(f"📺 {series_name} / {series_name_arabic}")
    print(f"🎬 الحلقات: {start_ep} → {end_ep}")

    if not await setup_telegram():
        return

    download_dir = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(download_dir, exist_ok=True)

    successful = 0
    failed = []
    skipped = []
    total = end_ep - start_ep + 1

    for ep in range(start_ep, end_ep + 1):
        if time_exceeded():
            print(f"\n⏰ الحد الزمني. المتبقي: {list(range(ep, end_ep+1))}")
            skipped = list(range(ep, end_ep + 1))
            break

        success, msg = await process_episode(ep, series_name, series_name_arabic, season_num, download_dir)
        if success:
            successful += 1
            print(f"✅ الحلقة {ep}  [{elapsed_str()}]")
        else:
            failed.append(ep)
            print(f"❌ الحلقة {ep}: {msg}  [{elapsed_str()}]")

        if ep < end_ep:
            if time_exceeded():
                skipped = list(range(ep + 1, end_ep + 1))
                break
            wait = random.randint(WAIT_BETWEEN_EPISODES_MIN, WAIT_BETWEEN_EPISODES_MAX)
            print(f"⏳ {wait}s...  [متبقي {remaining_time()//60}m]")
            await asyncio.sleep(wait)

    print(f"\n{'='*60}")
    print(f"⏱️ الإجمالي: {elapsed_str()}")
    print(f"✅ الناجحة: {successful}/{total}")
    if failed: print(f"❌ الفاشلة: {failed}")
    if skipped: print(f"⏭️ المتخطاة: {skipped}")
    print("=" * 60)

    if TEST_MODE and KEEP_VIDEO:
        print(f"🧪 {download_dir}")
    else:
        try:
            shutil.rmtree(download_dir)
        except Exception:
            pass

    if app:
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
