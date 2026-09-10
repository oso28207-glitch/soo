#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - u.3seq.com
يدعم TEST_MODE لاختبار السكريبت بدون تليغرام
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
from datetime import datetime
from urllib.parse import urlencode, urljoin

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

# ✅ متغير جديد لوضع الاختبار
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() in ("true", "1", "yes")
KEEP_VIDEO = os.environ.get("KEEP_VIDEO", "false").lower() in ("true", "1", "yes")
SKIP_DOWNLOAD = os.environ.get("SKIP_DOWNLOAD", "false").lower() in ("true", "1", "yes")


def validate_env():
    """في TEST_MODE لا نتحقق من متغيرات تليغرام"""
    if TEST_MODE:
        print("🧪 TEST_MODE مفعّل — لن يتم الاتصال بتليغرام")
        return True

    errors = []
    if not TELEGRAM_API_ID:
        errors.append("❌ API_ID is missing")
    if not TELEGRAM_API_HASH:
        errors.append("❌ API_HASH is missing")
    if not TELEGRAM_CHANNEL:
        errors.append("❌ CHANNEL is missing")
    if not STRING_SESSION:
        errors.append("❌ STRING_SESSION is missing")
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
        "curl_cffi>=0.5.10",
        "seleniumbase>=4.30.0",
        "beautifulsoup4>=4.12.0",
        "requests>=2.31.0",
    ]
    if not TEST_MODE:
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

# استيراد تليغرام فقط عند الحاجة
app = None
if not TEST_MODE:
    from pyrogram import Client
    from pyrogram.errors import FloodWait
else:
    Client = None
    FloodWait = None


# ============================================================
#  Telegram
# ============================================================
async def setup_telegram():
    global app
    if TEST_MODE:
        print("🧪 TEST_MODE: تخطي الاتصال بتليغرام")
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
        print(f"❌ Telegram connection failed: {e}")
        return False


# ============================================================
#  استخراج السيرفرات من HTML
# ============================================================
def extract_servers_from_html(html):
    servers = []

    pattern1 = re.compile(
        r'<li[^>]*id=["\'](s_\d+)["\'][^>]*on[Cc]lick=["\']getServer2\([^,]+,\s*(\d+)\s*,\s*(\d+)\s*\)',
        re.IGNORECASE
    )
    for m in pattern1.finditer(html):
        sid = m.group(1)
        servers.append({
            "id": sid,
            "name": sid,
            "video": m.group(2),
            "serverId": m.group(3),
        })

    if not servers:
        pattern2 = re.compile(
            r'on[Cc]lick=["\']getServer2\([^,]+,\s*(\d+)\s*,\s*(\d+)\s*\)[^>]*id=["\'](s_\d+)["\']',
            re.IGNORECASE
        )
        for m in pattern2.finditer(html):
            servers.append({
                "id": m.group(3),
                "name": m.group(3),
                "video": m.group(1),
                "serverId": m.group(2),
            })

    if not servers:
        pattern3 = re.compile(r'getServer2\([^,]+,\s*(\d+)\s*,\s*(\d+)\s*\)')
        for i, (video, sid) in enumerate(pattern3.findall(html)):
            servers.append({
                "id": f"s_{i}",
                "name": f"server_{i}",
                "video": video,
                "serverId": sid,
            })

    # إثراء الأسماء
    for srv in servers:
        m = re.search(
            rf'id=["\']{re.escape(srv["id"])}["\'][^>]*>([^<]*)<',
            html
        )
        if m:
            name = m.group(1).strip().replace('\n', '')
            if name:
                srv["name"] = name

    return servers


def extract_post_id_from_html(html):
    m = re.search(r'vo_postID\s*=\s*["\']?(\d+)', html)
    if m:
        return m.group(1)
    m = re.search(r'wp-json/wp/v2/posts/(\d+)', html)
    if m:
        return m.group(1)
    m = re.search(r'shortlink[\'"]\s*href=[\'"][^\'"]*\?p=(\d+)', html)
    if m:
        return m.group(1)
    return None


def extract_video_urls_from_html(html, base_url="https://u.3seq.com"):
    m3u8_list = list(set(re.findall(r'(https?://[^"\'\s<>]+\.m3u8[^"\'\s<>]*)', html)))
    mp4_list = list(set(re.findall(r'(https?://[^"\'\s<>]+\.mp4[^"\'\s<>]*)', html)))

    m3u8_esc = re.findall(r'(https?:\\?/\\?/[^"\'\s<>]+\.m3u8[^"\'\s<>]*)', html)
    for m in m3u8_esc:
        cleaned = m.replace("\\/", "/")
        if cleaned not in m3u8_list:
            m3u8_list.append(cleaned)

    iframe_list = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src")
            if src:
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = urljoin(base_url, src)
                iframe_list.append(src)
    except Exception:
        pass

    return m3u8_list, mp4_list, iframe_list


# ============================================================
#  AJAX
# ============================================================
def fetch_iframe2_ajax(sb, post_id, video, server_id, base_url="https://u.3seq.com"):
    ajax_url = f"{base_url}/wp-content/themes/vo2025/temp/ajax/iframe2.php"
    params = {"id": post_id, "video": video, "serverId": server_id}
    full_url = f"{ajax_url}?{urlencode(params)}"
    print(f"   📡 AJAX: {full_url}")

    try:
        fetch_script = """
        var callback = arguments[arguments.length - 1];
        var url = arguments[0];
        fetch(url, {
            method: "GET",
            credentials: "include",
            headers: {"X-Requested-With": "XMLHttpRequest"}
        })
        .then(r => r.text())
        .then(t => callback({ok: true, html: t}))
        .catch(e => callback({ok: false, error: e.toString()}));
        """
        sb.driver.set_script_timeout(30)
        result = sb.driver.execute_async_script(fetch_script, full_url)

        if not result or not result.get("ok"):
            err = result.get("error") if result else "no result"
            print(f"   ⚠️ فشل fetch: {err}")
            return None, None

        html = result.get("html", "")
        print(f"   📄 حجم الاستجابة: {len(html)} حرف")
        preview = html[:300].replace("\n", " ")
        print(f"   🔍 معاينة: {preview}")

        m3u8_list, mp4_list, iframe_list = extract_video_urls_from_html(html, base_url)

        if m3u8_list:
            return m3u8_list[0], None
        if mp4_list:
            return mp4_list[0], None
        if iframe_list:
            return None, iframe_list[0]

        return None, None

    except Exception as e:
        print(f"   ❌ خطأ في fetch: {e}")
        return None, None


# ============================================================
#  iframe
# ============================================================
def extract_from_iframe(sb, iframe_url):
    print(f"   🔍 فتح iframe: {iframe_url[:100]}")
    try:
        original_url = sb.get_current_url()
        sb.open(iframe_url)
        time.sleep(5)

        page_src = sb.get_page_source()
        m3u8_list, mp4_list, iframes = extract_video_urls_from_html(page_src, iframe_url)

        if m3u8_list:
            print(f"   ✅ m3u8: {m3u8_list[0][:120]}")
            sb.open(original_url)
            time.sleep(2)
            return m3u8_list[0]
        if mp4_list:
            print(f"   ✅ mp4: {mp4_list[0][:120]}")
            sb.open(original_url)
            time.sleep(2)
            return mp4_list[0]

        if iframes:
            print(f"   🔗 iframe متداخل: {iframes[0][:100]}")
            sb.open(iframes[0])
            time.sleep(5)
            page_src = sb.get_page_source()
            m3u8_list, mp4_list, _ = extract_video_urls_from_html(page_src, iframes[0])
            sb.open(original_url)
            time.sleep(2)
            if m3u8_list:
                return m3u8_list[0]
            if mp4_list:
                return mp4_list[0]

        sb.open(original_url)
        time.sleep(2)
        return None

    except Exception as e:
        print(f"   ⚠️ فشل فتح iframe: {e}")
        return None


# ============================================================
#  Selenium Work
# ============================================================
def _sync_selenium_work(episode_num, series_name):
    base_url = f"https://u.3seq.com/video/modablaj-{series_name}-episode-{episode_num:02d}"
    video_url = None
    selected_iframe = None

    with SB(
        uc=True,
        xvfb=True,
        headless=False,
        incognito=True,
        ad_block_on=False,
        disable_csp=True,
        page_load_strategy="eager",
        locale_code="en",
    ) as sb:
        try:
            print(f"🖥️ فتح {base_url}")
            sb.open(base_url)
            time.sleep(5)

            final_url = sb.get_current_url()
            print(f"🌐 الرابط النهائي: {final_url}")

            if not final_url.endswith('/'):
                final_url += '/'
            watch_url = final_url + '?do=watch'
            print(f"📺 تحميل صفحة المشاهدة: {watch_url}")
            sb.open(watch_url)
            time.sleep(5)

            try:
                sb.wait_for_element("ul.serversList", timeout=30)
                print("✅ تم العثور على قائمة السيرفرات.")
            except Exception:
                print("⚠️ لم يتم العثور على قائمة السيرفرات.")
                return None, None

            page_src = sb.get_page_source()
            print(f"📄 حجم HTML: {len(page_src)} حرف")

            post_id = extract_post_id_from_html(page_src)
            if not post_id:
                print("❌ لم نجد post_id")
                return None, None
            print(f"🔑 post_id = {post_id}")

            servers = extract_servers_from_html(page_src)

            if not servers:
                print("❌ لم نجد سيرفرات في HTML")
                m = re.search(r'<ul[^>]*serversList[^>]*>(.*?)</ul>', page_src, re.DOTALL)
                if m:
                    print(f"🔍 محتوى serversList: {m.group(1)[:500]}")
                return None, None

            print(f"📦 عدد السيرفرات: {len(servers)}")
            for s in servers:
                print(f"   - {s['id']} | {s['name']} | video={s['video']} serverId={s['serverId']}")

            for i, srv in enumerate(servers):
                print(f"\n🔄 محاولة السيرفر {i+1}/{len(servers)}: {srv['name']} (#{srv['id']})")

                # الطريقة 1: AJAX
                print(f"   [1/3] AJAX مباشر...")
                v_url, iframe_src = fetch_iframe2_ajax(
                    sb, post_id, srv["video"], srv["serverId"]
                )

                if v_url:
                    video_url = v_url
                    selected_iframe = iframe_src or watch_url
                    print(f"   ✅ نجحت الطريقة 1")
                    break

                # الطريقة 2: iframe
                if iframe_src:
                    print(f"   [2/3] فتح iframe...")
                    v_url = extract_from_iframe(sb, iframe_src)
                    if v_url:
                        video_url = v_url
                        selected_iframe = iframe_src
                        print(f"   ✅ نجحت الطريقة 2")
                        break

                # الطريقة 3: النقر
                print(f"   [3/3] النقر على الزر...")
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
                            print(f"      ✅ {method}")
                            break
                        except Exception:
                            pass

                    if not clicked:
                        print(f"      ❌ كل طرق النقر فشلت")
                        continue

                    new_src = None
                    for _ in range(20):
                        time.sleep(1)
                        try:
                            new_src = sb.find_element(".watch iframe").get_attribute("src")
                            if new_src and new_src != old_src:
                                break
                        except Exception:
                            pass

                    if not new_src or new_src == old_src:
                        print(f"      ⏱️ src لم يتغير")
                        continue

                    print(f"      ✅ iframe جديد: {new_src[:100]}")
                    v_url = extract_from_iframe(sb, new_src)
                    if v_url:
                        video_url = v_url
                        selected_iframe = new_src
                        print(f"   ✅ نجحت الطريقة 3")
                        break

                except Exception as e:
                    print(f"      ❌ خطأ: {e}")

            return video_url, selected_iframe

        except Exception as e:
            print(f"❌ خطأ Selenium: {e}")
            return None, None


# ============================================================
#  تنزيل + ضغط + رفع
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
            'extractor_args': {'generic': 'impersonate'},
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': referer or 'https://u.3seq.com/',
                'Origin': 'https://u.3seq.com',
            },
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        return os.path.exists(output_path)
    except Exception as e:
        print(f"❌ Download error: {e}")
        return False


def compress_to_144p(input_path, output_path):
    if not os.path.exists(input_path):
        return False
    cmd = [
        'ffmpeg', '-i', input_path,
        '-vf', 'scale=-2:144',
        '-c:v', 'libx264', '-crf', '28', '-preset', 'veryfast',
        '-c:a', 'aac', '-b:a', '64k',
        '-y', output_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=1800)
        return os.path.exists(output_path)
    except Exception:
        return False


def create_thumbnail(video_path, thumb_path):
    cmd = [
        'ffmpeg', '-i', video_path,
        '-ss', '00:00:05', '-vframes', '1', '-s', '320x180',
        '-f', 'image2', '-y', thumb_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
        return os.path.exists(thumb_path)
    except Exception:
        return False


async def upload_video(file_path, caption, thumb_path=None):
    if TEST_MODE:
        print(f"🧪 TEST_MODE: تخطي الرفع — الفيديو محفوظ في: {file_path}")
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f"   📊 حجم الفيديو: {size_mb:.2f} MB")
        print(f"   📝 التسمية: {caption}")
        return True

    if not app or not os.path.exists(file_path):
        return False
    try:
        width, height = 426, 240
        duration = 0
        try:
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height,duration',
                 '-of', 'csv=p=0', file_path],
                capture_output=True, text=True,
            )
            if probe.returncode == 0:
                parts = probe.stdout.strip().split(',')
                if len(parts) >= 2:
                    width, height = int(parts[0]), int(parts[1])
                if len(parts) >= 3 and parts[2]:
                    duration = int(float(parts[2]))
        except Exception:
            pass

        await app.send_video(
            chat_id=TELEGRAM_CHANNEL,
            video=file_path,
            caption=caption,
            supports_streaming=True,
            width=width,
            height=height,
            duration=duration,
            thumb=thumb_path if thumb_path and os.path.exists(thumb_path) else None,
        )
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await upload_video(file_path, caption, thumb_path)
    except Exception as e:
        print(f"❌ Upload error: {e}")
        return False


# ============================================================
#  معالجة حلقة
# ============================================================
async def process_episode(episode_num, series_name, series_name_arabic, season_num, download_dir):
    print(f"\n🎬 Episode {episode_num:02d}")
    print(f"🔗 Base URL: https://u.3seq.com/video/modablaj-{series_name}-episode-{episode_num:02d}")

    temp_file = os.path.join(download_dir, f"temp_{episode_num:02d}.mp4")
    final_file = os.path.join(download_dir, f"final_{episode_num:02d}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_{episode_num:02d}.jpg")

    try:
        video_url, selected_iframe = await asyncio.to_thread(
            _sync_selenium_work, episode_num, series_name
        )

        if not video_url:
            return False, "فشل استخراج رابط الفيديو من جميع السيرفرات"

        print(f"\n{'='*60}")
        print(f"🎥 نجح الاستخراج!")
        print(f"🔗 الرابط: {video_url}")
        print(f"📎 Referer: {selected_iframe}")
        print(f"{'='*60}")

        # في TEST_MODE يمكن تخطي التنزيل
        if SKIP_DOWNLOAD:
            print("🧪 SKIP_DOWNLOAD: تخطي التنزيل")
            return True, "تم استخراج الرابط فقط"

        # التنزيل
        if not download_video(video_url, temp_file, referer=selected_iframe):
            return False, "فشل التنزيل"

        print(f"✅ تم التنزيل: {os.path.getsize(temp_file)/(1024*1024):.2f} MB")

        # الضغط
        if not compress_to_144p(temp_file, final_file):
            shutil.copy2(temp_file, final_file)

        # Thumbnail
        create_thumbnail(final_file, thumb_file)

        # الرفع أو الحفظ
        caption = f"{series_name_arabic} الموسم {season_num} الحلقة {episode_num}"
        success = await upload_video(
            final_file, caption,
            thumb_file if os.path.exists(thumb_file) else None,
        )

        # التنظيف
        if TEST_MODE and KEEP_VIDEO:
            print(f"🧪 KEEP_VIDEO: الاحتفاظ بالفيديو: {final_file}")
        else:
            for f in [temp_file, final_file, thumb_file]:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception:
                    pass

        return success, "تم بنجاح" if success else "فشل الرفع"

    except Exception as e:
        return False, f"خطأ غير متوقع: {e}"


# ============================================================
#  الإعدادات
# ============================================================
def load_config():
    config = {
        "series_name": "",
        "series_name_arabic": "",
        "season_num": 1,
        "start_episode": 1,
        "end_episode": 1,
    }

    config_file = "series_config.json"
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
            config.update({k: v for k, v in file_config.items() if v not in (None, "")})
            print(f"📄 تم تحميل الإعدادات من {config_file}")
        except Exception as e:
            print(f"⚠️ فشل قراءة {config_file}: {e}")

    if INPUT_SERIES_NAME:
        config["series_name"] = INPUT_SERIES_NAME
    if INPUT_SERIES_NAME_ARABIC:
        config["series_name_arabic"] = INPUT_SERIES_NAME_ARABIC
    if INPUT_SEASON_NUM:
        config["season_num"] = int(INPUT_SEASON_NUM)
    if INPUT_START_EPISODE:
        config["start_episode"] = int(INPUT_START_EPISODE)
    if INPUT_END_EPISODE:
        config["end_episode"] = int(INPUT_END_EPISODE)

    return config


# ============================================================
#  main
# ============================================================
async def main():
    print("=" * 60)
    print("🎬 معالج الفيديو المتكامل - u.3seq.com")
    if TEST_MODE:
        print("🧪 TEST_MODE — لن يتم الاتصال بتليغرام")
    print("=" * 60)

    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg موجود")
    except Exception:
        print("⚠️ ffmpeg غير موجود — سيتم تخطي الضغط")

    config = load_config()

    series_name = str(config.get("series_name", "")).strip().replace(' ', '-')
    series_name_arabic = str(config.get("series_name_arabic", "")).strip() or series_name
    season_num = int(config.get("season_num", 1))
    start_ep = int(config.get("start_episode", 1))
    end_ep = int(config.get("end_episode", 1))

    if not series_name:
        print("❌ اسم المسلسل بالإنجليزية مطلوب")
        return

    if end_ep - start_ep + 1 > 25:
        print("⚠️ عدد الحلقات كبير، سيتم معالجة 25 فقط.")
        end_ep = start_ep + 24

    print(f"📺 المسلسل (EN): {series_name}")
    print(f"📺 المسلسل (AR): {series_name_arabic}")
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
            print(f"⏳ انتظار {wait_time} ثانية...")
            await asyncio.sleep(wait_time)

    print(f"\n{'='*60}")
    print(f"✅ الناجحة: {successful}/{total}")
    if failed:
        print(f"❌ الفاشلة: {failed}")
    print("=" * 60)

    if TEST_MODE and KEEP_VIDEO:
        print(f"🧪 الفيديوهات محفوظة في: {download_dir}")
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
