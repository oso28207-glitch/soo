#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - u.3seq.com/.cam
- الجلسة 1: جمع روابط iframe (بالنقر)
- الجلسة 2: استخراج m3u8 عبر SeleniumBase CDP Mode
- ضغط الفيديو إلى 144p عبر ffmpeg
- رفع الفيديو إلى قناة تليغرام
- TEST_MODE متوفر
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
from urllib.parse import urlparse

# ===== التهيئة =====
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


def validate_env():
    if TEST_MODE:
        print("🧪 TEST_MODE مفعّل")
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
    ]
    if not TEST_MODE or not SKIP_UPLOAD:
        reqs += ["pyrogram>=2.0.0", "tgcrypto>=1.2.0"]
    for req in reqs:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", req, "--quiet"])
            print(f"  ✅ {req.split('>=')[0]}")
        except Exception:
            print(f"  ⚠️ Failed to install {req}")


install_requirements()

# ===== الاستيراد بعد التثبيت =====
import yt_dlp
from seleniumbase import SB
from bs4 import BeautifulSoup

app = None
Client = None
FloodWait = None
if not TEST_MODE or not SKIP_UPLOAD:
    from pyrogram import Client
    from pyrogram.errors import FloodWait


# ============================================================
#  Telegram
# ============================================================
async def setup_telegram():
    global app
    if TEST_MODE and SKIP_UPLOAD:
        print("🧪 TEST_MODE + SKIP_UPLOAD: تخطي تليغرام")
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
        print(f"✅ Connected as {me.first_name} (@{me.username or 'no-username'})")
        return True
    except Exception as e:
        print(f"❌ Telegram failed: {e}")
        return False


# ============================================================
#  استخراج السيرفرات من HTML
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


def extract_post_id_from_html(html):
    for pat in [
        r'vo_postID\s*=\s*["\']?(\d+)',
        r'wp-json/wp/v2/posts/(\d+)',
        r'shortlink[\'"]\s*href=[\'"][^\'"]*\?p=(\d+)',
    ]:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


# ============================================================
#  استخراج m3u8 عبر CDP Mode
# ============================================================
def extract_m3u8_with_cdp(iframe_url):
    print(f"   🎬 [CDP Mode] فتح {iframe_url}", flush=True)

    log_file = tempfile.mktemp(suffix="_m3u8.txt")
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("")

    def _log_to_file(url):
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
                            _log_to_file(url)
                            if ".m3u8" in url:
                                print(f"      ✅ m3u8 (Req): {url[:130]}", flush=True)
                        except Exception:
                            pass

                    async def on_response(event):
                        try:
                            url = event.response.url
                            _log_to_file(url)
                            if ".m3u8" in url:
                                print(f"      ✅ m3u8 (Res): {url[:130]}", flush=True)
                        except Exception:
                            pass

                    sb.cdp.add_handler(mycdp.network.RequestWillBeSent, on_request)
                    sb.cdp.add_handler(mycdp.network.ResponseReceived, on_response)
                    print("      ✅ معالجات CDP مسجلة", flush=True)
                except Exception as e:
                    print(f"      ⚠️ فشل تسجيل المعالجات: {str(e)[:120]}", flush=True)

                sb.cdp.open(iframe_url)
                print("      ⏳ انتظار التحميل (10s)...", flush=True)
                sb.cdp.sleep(10)

                for _ in range(3):
                    try:
                        sb.cdp.click_if_visible("video")
                        print("      🖱️ نقر على: video", flush=True)
                    except Exception:
                        pass
                    try:
                        sb.cdp.click_if_visible("button.vjs-big-play-button")
                        print("      🖱️ نقر على: vjs-big-play-button", flush=True)
                    except Exception:
                        pass
                    sb.cdp.sleep(2)

                print("      ⏳ انتظار إضافي (15s)...", flush=True)
                sb.cdp.sleep(15)

                try:
                    dom_m3u8 = sb.cdp.execute_script("""
                        return Array.from(document.querySelectorAll('video, source'))
                            .map(el => el.src || el.currentSrc || el.getAttribute('src'))
                            .filter(src => src && src.includes('.m3u8'))[0] || null;
                    """)
                    if dom_m3u8:
                        print(f"      ✅ m3u8 (DOM): {dom_m3u8[:130]}", flush=True)
                        _log_to_file(dom_m3u8)
                except Exception:
                    pass

            except Exception as e:
                print(f"      ❌ خطأ CDP Mode: {str(e)[:200]}", flush=True)

    except Exception as e:
        print(f"      ❌ خطأ في فتح المتصفح: {str(e)[:200]}", flush=True)

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

    print(f"      📊 عدد الروابط الملتقطة: {len(urls)}", flush=True)

    if not urls:
        print("      ❌ لم يتم اعتراض أي طلب.", flush=True)
        return None

    master_url = None
    best_index = None
    any_m3u8 = None

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
        print(f"      🎯 m3u8 نهائي: {result[:150]}", flush=True)
        return result

    for url in urls:
        if ".mp4" in url:
            print(f"      🎯 mp4 نهائي: {url[:150]}", flush=True)
            return url

    print("      ❌ لم يتم العثور على m3u8/mp4.", flush=True)
    return None


# ============================================================
#  yt-dlp كخيار احتياطي
# ============================================================
def try_ytdlp_extract(iframe_url):
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'format': 'best[height<=720]/best',
            'nocheckcertificate': True,
            'extractor_args': {'generic': ['impersonate']}
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(iframe_url, download=False)
            if info:
                if info.get('url'):
                    return info['url']
                if info.get('formats'):
                    best = sorted(info['formats'], key=lambda f: f.get('height') or 0)[-1]
                    if best.get('url'):
                        return best['url']
    except Exception as e:
        print(f"   ⚠️ yt-dlp: {str(e)[:120]}")
    return None


# ============================================================
#  الجلسة 1: جمع روابط iframe
# ============================================================
def collect_iframe_urls(episode_num, series_name):
    base_url = f"https://u.3seq.com/video/modablaj-{series_name}-episode-{episode_num:02d}"
    iframe_urls = []

    with SB(
        uc=True, xvfb=True, headless=False, incognito=True,
        ad_block_on=False, disable_csp=True,
        page_load_strategy="eager", locale_code="en",
    ) as sb:
        try:
            print(f"🖥️ [الجلسة 1] فتح {base_url}")
            sb.open(base_url)
            time.sleep(6)

            final_url = sb.get_current_url()
            print(f"🌐 النهائي: {final_url}")

            if not final_url.endswith('/'):
                final_url += '/'
            watch_url = final_url + '?do=watch'
            print(f"📺 صفحة المشاهدة: {watch_url}")
            sb.open(watch_url)
            time.sleep(6)

            try:
                sb.wait_for_element("ul.serversList", timeout=30)
                print("✅ قائمة السيرفرات موجودة.")
            except Exception:
                print("⚠️ لم يتم العثور على السيرفرات.")
                return iframe_urls

            page_src = sb.get_page_source()
            servers = extract_servers_from_html(page_src)
            if not servers:
                print("❌ لم نجد سيرفرات")
                return iframe_urls

            print(f"📦 عدد السيرفرات: {len(servers)}")
            for s in servers:
                print(f"   - {s['id']} | {s['name']}")

            for i, srv in enumerate(servers):
                print(f"\n🔄 [{i+1}/{len(servers)}] النقر على {srv['name']}")

                try:
                    old_src = None
                    try:
                        old_src = sb.find_element(".watch iframe").get_attribute("src")
                    except Exception:
                        pass
                    print(f"   src القديم: {old_src}")

                    clicked = False
                    for method in ["uc_click", "js_click", "click"]:
                        try:
                            getattr(sb, method)(f"#{srv['id']}")
                            clicked = True
                            print(f"   ✅ {method}")
                            break
                        except Exception:
                            pass

                    if not clicked:
                        print(f"   ❌ فشل النقر")
                        continue

                    new_src = None
                    for _ in range(15):
                        time.sleep(1)
                        try:
                            new_src = sb.find_element(".watch iframe").get_attribute("src")
                            if new_src and new_src != old_src:
                                break
                        except Exception:
                            pass

                    if not new_src or new_src == old_src:
                        print(f"   ⏱️ src لم يتغير")
                        continue

                    print(f"   ✅ iframe: {new_src}")
                    iframe_urls.append({
                        "server": srv["name"],
                        "url": new_src,
                    })

                except Exception as e:
                    print(f"   ❌ {str(e)[:120]}")

            return iframe_urls

        except Exception as e:
            print(f"❌ جلسة 1 فشلت: {e}")
            return iframe_urls


# ============================================================
#  ✅ تنزيل + ضغط + Thumbnail + رفع
# ============================================================
def download_video(video_url, output_path, referer):
    try:
        ydl_opts = {
            'format': 'best[height<=720]/best',
            'outtmpl': output_path,
            'quiet': False,
            'retries': 5,
            'fragment_retries': 5,
            'socket_timeout': 30,
            'nocheckcertificate': True,
            'extractor_args': {'generic': 'impersonate'},
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': referer or 'https://u.3seq.com/',
                'Origin': 'https://u.3seq.com',
            },
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            return True
        print(f"   ⚠️ الملف صغير جداً أو غير موجود: {output_path}")
        return False
    except Exception as e:
        print(f"❌ Download error: {e}")
        return False


def compress_to_144p(input_path, output_path):
    """ضغط الفيديو إلى 144p مع تسجيل تفصيلي."""
    if not os.path.exists(input_path):
        print("   ❌ الملف المصدر غير موجود")
        return False

    input_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    print(f"   🗜️ بدء الضغط إلى 144p (المصدر: {input_size_mb:.2f} MB)...")

    cmd = [
        'ffmpeg',
        '-i', input_path,
        '-vf', 'scale=-2:144',
        '-c:v', 'libx264',
        '-crf', '28',
        '-preset', 'veryfast',
        '-c:a', 'aac',
        '-b:a', '64k',
        '-movflags', '+faststart',
        '-y', output_path,
    ]

    try:
        start = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,  # ساعة كحد أقصى
        )
        elapsed = time.time() - start

        if result.returncode != 0:
            print(f"   ❌ فشل ffmpeg (code {result.returncode})")
            print(f"   📄 stderr: {result.stderr[-500:]}")
            return False

        if not os.path.exists(output_path):
            print("   ❌ الملف الناتج غير موجود")
            return False

        output_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        ratio = (1 - output_size_mb / input_size_mb) * 100
        print(f"   ✅ تم الضغط في {elapsed:.1f}s")
        print(f"   📊 {input_size_mb:.2f} MB → {output_size_mb:.2f} MB (توفير {ratio:.1f}%)")
        return True

    except subprocess.TimeoutExpired:
        print("   ❌ انتهت مهلة ffmpeg (ساعة)")
        return False
    except Exception as e:
        print(f"   ❌ خطأ في الضغط: {e}")
        return False


def create_thumbnail(video_path, thumb_path):
    """إنشاء صورة مصغرة من الفيديو."""
    if not os.path.exists(video_path):
        return False

    cmd = [
        'ffmpeg',
        '-ss', '00:00:05',
        '-i', video_path,
        '-vframes', '1',
        '-vf', 'scale=320:180',
        '-f', 'image2',
        '-y', thumb_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode == 0 and os.path.exists(thumb_path):
            print(f"   ✅ تم إنشاء Thumbnail: {os.path.getsize(thumb_path)} bytes")
            return True
        return False
    except Exception as e:
        print(f"   ⚠️ خطأ في Thumbnail: {e}")
        return False


def get_video_metadata(video_path):
    """استخراج العرض والارتفاع والمدة."""
    width, height, duration = 1280, 720, 0
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height,duration',
             '-of', 'csv=p=0', video_path],
            capture_output=True, text=True, timeout=15,
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
    except Exception as e:
        print(f"   ⚠️ ffprobe: {e}")
    return width, height, duration


async def upload_video(file_path, caption, thumb_path=None):
    """رفع الفيديو إلى تليغرام."""
    if TEST_MODE and SKIP_UPLOAD:
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f"🧪 SKIP_UPLOAD: {file_path} ({size_mb:.2f} MB)")
        return True

    if app is None:
        print("   ❌ لا يوجد اتصال بتليغرام")
        return False

    if not os.path.exists(file_path):
        print(f"   ❌ الملف غير موجود: {file_path}")
        return False

    file_size = os.path.getsize(file_path)
    file_size_mb = file_size / (1024 * 1024)
    print(f"   📤 بدء الرفع إلى تليغرام ({file_size_mb:.2f} MB)...")

    # استخراج الميتاداتا
    width, height, duration = get_video_metadata(file_path)
    print(f"   📐 الأبعاد: {width}x{height} | المدة: {duration}s")

    # التحقق من Thumbnail
    thumb = None
    if thumb_path and os.path.exists(thumb_path):
        thumb = thumb_path
        print(f"   🖼️ Thumbnail: {thumb_path}")
    else:
        print(f"   ⚠️ لا يوجد Thumbnail")

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
        elapsed = time.time() - start
        print(f"   ✅ تم الرفع بنجاح في {elapsed:.1f}s")
        return True

    except FloodWait as e:
        print(f"   ⏳ FloodWait: انتظار {e.value}s...")
        await asyncio.sleep(e.value)
        return await upload_video(file_path, caption, thumb_path)

    except Exception as e:
        print(f"   ❌ خطأ في الرفع: {str(e)[:200]}")
        return False


# ============================================================
#  معالجة حلقة
# ============================================================
async def process_episode(episode_num, series_name, series_name_arabic, season_num, download_dir):
    print(f"\n🎬 Episode {episode_num:02d}")

    temp_file = os.path.join(download_dir, f"temp_{episode_num:02d}.mp4")
    final_file = os.path.join(download_dir, f"final_{episode_num:02d}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_{episode_num:02d}.jpg")

    try:
        # ===== جلسة 1: جمع روابط iframe =====
        print(f"\n{'='*60}")
        print("📡 الجلسة 1: جمع روابط iframe")
        print(f"{'='*60}")

        iframe_urls = await asyncio.to_thread(
            collect_iframe_urls, episode_num, series_name
        )

        if not iframe_urls:
            return False, "لم نتمكن من جمع أي رابط iframe"

        print(f"\n📋 تم جمع {len(iframe_urls)} رابط iframe")

        # ===== جلسة 2: استخراج m3u8 =====
        video_url = None
        selected_iframe = None

        for i, item in enumerate(iframe_urls):
            print(f"\n{'='*60}")
            print(f"🎬 [{i+1}/{len(iframe_urls)}] {item['server']}: {item['url'][:100]}")
            print(f"{'='*60}")

            # ----- المحاولة 1: yt-dlp -----
            print(f"   [1/2] yt-dlp...")
            v_url = await asyncio.to_thread(try_ytdlp_extract, item["url"])
            if v_url:
                if ".m3u8" in v_url or ".mp4" in v_url or v_url.startswith("http"):
                    video_url = v_url
                    selected_iframe = item["url"]
                    print(f"   ✅ نجح yt-dlp")
                    break
                else:
                    print(f"   ⚠️ رابط غير صالح، نتجاهله")

            # ----- المحاولة 2: CDP Mode -----
            print(f"   [2/2] SeleniumBase CDP Mode...")
            v_url = await asyncio.to_thread(extract_m3u8_with_cdp, item["url"])
            if v_url:
                video_url = v_url
                selected_iframe = item["url"]
                print(f"   ✅ نجح CDP Mode")
                break

        if not video_url:
            return False, "فشل استخراج m3u8"

        print(f"\n{'='*60}")
        print(f"🎥 نجح الاستخراج!")
        print(f"🔗 {video_url[:150]}")
        print(f"📎 Referer: {selected_iframe}")
        print(f"{'='*60}")

        if SKIP_DOWNLOAD:
            print("🧪 SKIP_DOWNLOAD: تخطي التنزيل")
            return True, "استخراج فقط"

        # ===== تنزيل =====
        print(f"\n{'='*60}")
        print("⬇️ مرحلة التنزيل")
        print(f"{'='*60}")

        if not download_video(video_url, temp_file, referer=selected_iframe):
            return False, "فشل التنزيل"

        temp_size_mb = os.path.getsize(temp_file) / (1024 * 1024)
        print(f"✅ تم التنزيل: {temp_size_mb:.2f} MB")

        # ===== ضغط =====
        print(f"\n{'='*60}")
        print("🗜️ مرحلة الضغط إلى 144p")
        print(f"{'='*60}")

        if SKIP_COMPRESS:
            print("🧪 SKIP_COMPRESS: تخطي الضغط")
            shutil.copy2(temp_file, final_file)
            print(f"   📋 تم نسخ الملف الأصلي: {final_file}")
        else:
            if not compress_to_144p(temp_file, final_file):
                print("   ⚠️ فشل الضغط — سيتم استخدام الملف الأصلي")
                shutil.copy2(temp_file, final_file)
                print(f"   📋 تم نسخ الملف الأصلي: {final_file}")

        if not os.path.exists(final_file):
            return False, "الملف النهائي غير موجود بعد الضغط"

        final_size_mb = os.path.getsize(final_file) / (1024 * 1024)
        print(f"   📊 حجم الملف النهائي: {final_size_mb:.2f} MB")

        # ===== Thumbnail =====
        print(f"\n{'='*60}")
        print("🖼️ مرحلة إنشاء Thumbnail")
        print(f"{'='*60}")
        create_thumbnail(final_file, thumb_file)

        # ===== رفع =====
        print(f"\n{'='*60}")
        print("📤 مرحلة الرفع إلى تليغرام")
        print(f"{'='*60}")

        caption = f"{series_name_arabic} الموسم {season_num} الحلقة {episode_num}"
        success = await upload_video(
            final_file, caption,
            thumb_file if os.path.exists(thumb_file) else None,
        )

        # ===== تنظيف =====
        print(f"\n{'='*60}")
        print("🧹 مرحلة التنظيف")
        print(f"{'='*60}")

        if TEST_MODE and KEEP_VIDEO:
            print(f"🧪 KEEP_VIDEO: الاحتفاظ بـ {final_file}")
        else:
            for f in [temp_file, final_file, thumb_file]:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                        print(f"   🗑️ حذف: {os.path.basename(f)}")
                except Exception as e:
                    print(f"   ⚠️ فشل حذف {f}: {e}")

        return success, "تم بنجاح" if success else "فشل الرفع"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"خطأ: {e}"


# ============================================================
#  الإعدادات
# ============================================================
def load_config():
    config = {"series_name": "", "series_name_arabic": "", "season_num": 1, "start_episode": 1, "end_episode": 1}
    config_file = "series_config.json"
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
            config.update({k: v for k, v in file_config.items() if v not in (None, "")})
            print(f"📄 تم تحميل الإعدادات")
        except Exception as e:
            print(f"⚠️ {e}")

    if INPUT_SERIES_NAME: config["series_name"] = INPUT_SERIES_NAME
    if INPUT_SERIES_NAME_ARABIC: config["series_name_arabic"] = INPUT_SERIES_NAME_ARABIC
    if INPUT_SEASON_NUM: config["season_num"] = int(INPUT_SEASON_NUM)
    if INPUT_START_EPISODE: config["start_episode"] = int(INPUT_START_EPISODE)
    if INPUT_END_EPISODE: config["end_episode"] = int(INPUT_END_EPISODE)
    return config


# ============================================================
#  main
# ============================================================
async def main():
    print("=" * 60)
    print("🎬 معالج الفيديو - u.3seq.com/.cam")
    if TEST_MODE: print("🧪 TEST_MODE")
    if SKIP_UPLOAD: print("🧪 SKIP_UPLOAD")
    if SKIP_COMPRESS: print("🧪 SKIP_COMPRESS")
    print("=" * 60)

    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg موجود")
    except Exception:
        print("❌ ffmpeg غير موجود — قد يفشل الضغط")

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
    print(f"🗂️ الموسم: {season_num}")
    print(f"🎬 الحلقات: {start_ep} إلى {end_ep}")

    if not await setup_telegram():
        return

    download_dir = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(download_dir, exist_ok=True)

    successful = 0
    failed = []
    total = end_ep - start_ep + 1

    for ep in range(start_ep, end_ep + 1):
        success, msg = await process_episode(ep, series_name, series_name_arabic, season_num, download_dir)
        if success:
            successful += 1
            print(f"✅ الحلقة {ep} اكتملت")
        else:
            failed.append(ep)
            print(f"❌ الحلقة {ep}: {msg}")

        if ep < end_ep:
            wait_time = random.randint(10, 20) if TEST_MODE else random.randint(45, 90)
            print(f"⏳ انتظار {wait_time}s...")
            await asyncio.sleep(wait_time)

    print(f"\n{'='*60}")
    print(f"✅ الناجحة: {successful}/{total}")
    if failed:
        print(f"❌ الفاشلة: {failed}")
    print("=" * 60)

    if TEST_MODE and KEEP_VIDEO:
        print(f"🧪 الفيديوهات في: {download_dir}")
    else:
        try:
            shutil.rmtree(download_dir)
        except Exception:
            pass

    if app:
        await app.stop()
        print("🔌 تم قطع الاتصال بتليغرام")


if __name__ == "__main__":
    asyncio.run(main())
