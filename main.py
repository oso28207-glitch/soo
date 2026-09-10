#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - u.3seq.cam
معالج محسّن مع SeleniumBase UC Mode + استخراج من iframe بدون مغادرة الصفحة
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


def validate_env():
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

TELEGRAM_API_ID = int(TELEGRAM_API_ID)


# ===== تثبيت الحزم =====
def install_requirements():
    print("📦 Installing requirements...")
    reqs = [
        "pyrogram>=2.0.0",
        "tgcrypto>=1.2.0",
        "yt-dlp>=2024.4.9",
        "curl_cffi>=0.5.10",
        "seleniumbase>=4.30.0",
        "beautifulsoup4>=4.12.0",
    ]
    for req in reqs:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", req, "--quiet"])
            print(f"  ✅ {req.split('>=')[0]}")
        except Exception:
            print(f"  ⚠️ Failed to install {req}")


install_requirements()

# ===== الاستيراد بعد التثبيت =====
from pyrogram import Client
from pyrogram.errors import FloodWait
import yt_dlp
from seleniumbase import SB
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)

app = None


# ===== دوال مساعدة =====
async def setup_telegram():
    global app
    print("\n🔐 Connecting to Telegram...")
    try:
        app = Client(
            "github_uploader",
            api_id=TELEGRAM_API_ID,
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


def browser_alive(sb):
    """فحص إن كان المتصفح حياً."""
    try:
        _ = sb.get_current_url()
        return True
    except Exception:
        return False


def extract_video_from_current_context(sb):
    """
    البحث عن مصدر الفيديو في السياق الحالي.
    يعيد (video_url, iframe_src) أو (None, None).
    """
    video_url = None

    # 1. عنصر video مباشر
    try:
        videos = sb.find_elements("video")
        for v in videos:
            src = v.get_attribute("src")
            if src:
                video_url = src
                break
    except Exception:
        pass

    # 2. عناصر source
    if not video_url:
        try:
            sources = sb.find_elements("source")
            for s in sources:
                src = s.get_attribute("src")
                if src:
                    video_url = src
                    break
        except Exception:
            pass

    # 3. روابط m3u8 داخل HTML
    if not video_url:
        try:
            page_src = sb.get_page_source()
            matches = re.findall(r'(https?://[^"\']+\.m3u8[^"\']*)', page_src)
            if matches:
                video_url = matches[0]
        except Exception:
            pass

    # 4. روابط mp4 داخل HTML
    if not video_url:
        try:
            page_src = sb.get_page_source()
            matches = re.findall(r'(https?://[^"\']+\.mp4[^"\']*)', page_src)
            if matches:
                video_url = matches[0]
        except Exception:
            pass

    return video_url


def try_extract_from_iframe_context(sb, iframe_src):
    """
    الدخول داخل iframe والبحث عن الفيديو ثم الخروج.
    """
    print(f"   🔍 الدخول داخل iframe...")
    try:
        # نحاول الدخول للـ iframe عن طريق selector أو index
        try:
            sb.switch_to_frame(".watch iframe")
        except Exception:
            sb.switch_to_frame(0)
        time.sleep(3)
        url = extract_video_from_current_context(sb)
        sb.switch_to_default_content()
        return url
    except Exception as e:
        print(f"   ⚠️ فشل الدخول للـ iframe: {e}")
        try:
            sb.switch_to_default_content()
        except Exception:
            pass
        return None


def try_extract_via_new_tab(sb, iframe_src, handle_before):
    """
    فتح رابط الـ iframe في تبويب جديد واستخراج الفيديو منه.
    """
    print(f"   🔍 فتح iframe في تبويب جديد...")
    try:
        sb.open_new_window()
        # ننتقل للتبويب الأخير
        handles = sb.driver.window_handles
        new_handle = handles[-1]
        sb.driver.switch_to.window(new_handle)
        sb.open(iframe_src)
        time.sleep(4)
        url = extract_video_from_current_context(sb)
        # إغلاق التبويب
        sb.driver.close()
        sb.driver.switch_to.window(handle_before)
        return url
    except Exception as e:
        print(f"   ⚠️ فشل فتح التبويب: {e}")
        try:
            handles = sb.driver.window_handles
            if len(handles) > 1:
                sb.driver.close()
            sb.driver.switch_to.window(handle_before)
        except Exception:
            pass
        return None


def download_video(video_url, output_path, referer):
    """تنزيل الفيديو باستخدام yt-dlp"""
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
                'Referer': referer,
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


# ===== كود Selenium (يعمل في thread منفصل) =====

def _sync_selenium_work(episode_num, series_name):
    """
    كل عمليات Selenium في thread منفصل.
    نستخدم sb.uc_click للنقر، و sb.switch_to_frame للاستخراج بدون مغادرة الصفحة.
    """
    base_url = f"https://u.3seq.cam/video/modablaj-{series_name}-episode-{episode_num:02d}"
    video_url = None
    selected_iframe = None

    with SB(
        uc=True,
        xvfb=True,
        headless=False,
        incognito=True,
        ad_block_on=True,     # ✅ يمنع الإعلانات الثقيلة التي تُسقط المتصفح
        disable_csp=True,     # ✅ يتجنب قيود CSP عند الدخول للـ iframe
        page_load_strategy="eager",
        locale_code="en",
    ) as sb:
        try:
            # ===== فتح الصفحة والانتقال لصفحة المشاهدة =====
            print(f"🖥️ فتح {base_url}")
            sb.open(base_url)

            start_time = time.time()
            current_url = sb.get_current_url()
            while current_url == base_url and time.time() - start_time < 15:
                time.sleep(1)
                current_url = sb.get_current_url()

            final_url = sb.get_current_url()
            print(f"🌐 الرابط النهائي: {final_url}")

            if not final_url.endswith('/'):
                final_url += '/'
            watch_url = final_url + '?do=watch'
            print(f"📺 تحميل صفحة المشاهدة: {watch_url}")
            sb.open(watch_url)
            time.sleep(4)

            # ===== انتظار قائمة السيرفرات =====
            try:
                sb.wait_for_element("ul.serversList", timeout=30)
                print("✅ تم العثور على قائمة السيرفرات.")
            except TimeoutException:
                print("⚠️ لم يتم العثور على قائمة السيرفرات.")
                return None, None

            # ===== استخراج معرّفات السيرفرات =====
            server_items = sb.find_elements("ul.serversList li")
            servers = []
            for item in server_items:
                sid = item.get_attribute("id")
                sname = (item.text or "").strip()
                onclick = item.get_attribute("onclick") or ""
                m = re.search(r'getServer2\([^,]+,\s*(\d+),\s*(\d+)\)', onclick)
                idx_num = (m.group(1), m.group(2)) if m else (None, None)
                servers.append({"id": sid, "name": sname, "idx": idx_num[0], "num": idx_num[1]})

            print(f"📦 عدد السيرفرات: {len(servers)}")
            for s in servers:
                print(f"   - {s['id']} | {s['name']} | idx={s['idx']} num={s['num']}")

            if not servers:
                return None, None

            # ===== نجرب كل سيرفر =====
            for i, srv in enumerate(servers):
                if not browser_alive(sb):
                    print(f"❌ المتصفح سقط قبل السيرفر {i+1}")
                    return None, None

                sid = srv["id"]
                sname = srv["name"]
                print(f"\n🔄 محاولة السيرفر {i+1}/{len(servers)}: {sname} (#{sid})")

                # src الحالي
                try:
                    old_src = sb.find_element(".watch iframe").get_attribute("src")
                except Exception:
                    old_src = None
                print(f"   القديم: {old_src}")

                # ===== النقر على الزر =====
                clicked = False
                click_errors = []

                # 1. uc_click — الأفضل لأنه يستخدم PyAutoGUI (لا JS)
                if not clicked:
                    try:
                        sb.uc_click(f"#{sid}", timeout=15)
                        clicked = True
                        print("   ✅ uc_click نجح")
                    except Exception as e:
                        click_errors.append(f"uc_click: {str(e)[:80]}")

                # 2. js_click — SeleniumBase native
                if not clicked and browser_alive(sb):
                    try:
                        sb.js_click(f"#{sid}")
                        clicked = True
                        print("   ✅ js_click نجح")
                    except Exception as e:
                        click_errors.append(f"js_click: {str(e)[:80]}")

                # 3. click عادي
                if not clicked and browser_alive(sb):
                    try:
                        sb.click(f"#{sid}")
                        clicked = True
                        print("   ✅ click نجح")
                    except Exception as e:
                        click_errors.append(f"click: {str(e)[:80]}")

                # 4. Fallback: استدعاء getServer2 مباشرة عبر JS
                if not clicked and browser_alive(sb) and srv["idx"] and srv["num"]:
                    try:
                        script = (
                            f"var el = document.getElementById('{sid}');"
                            f"if (el && el.onclick) {{ el.onclick(); }}"
                        )
                        sb.execute_script(script)
                        clicked = True
                        print("   ✅ onclick() نجح")
                    except Exception as e:
                        click_errors.append(f"onclick: {str(e)[:80]}")

                if not clicked:
                    print(f"   ❌ كل طرق النقر فشلت: {click_errors}")
                    continue

                # ===== انتظار تغير src =====
                new_src = None
                for _ in range(20):
                    time.sleep(1)
                    if not browser_alive(sb):
                        print("   ❌ المتصفح سقط أثناء الانتظار")
                        return None, None
                    try:
                        new_src = sb.find_element(".watch iframe").get_attribute("src")
                        if new_src and new_src != old_src:
                            break
                    except Exception:
                        pass

                if not new_src or new_src == old_src:
                    print("   ⏱️ src لم يتغير، نكمل")
                    continue

                print(f"   ✅ iframe جديد: {new_src}")

                # ===== استخراج الفيديو =====
                # المحاولة 1: الدخول داخل iframe (بدون مغادرة الصفحة)
                video_url = try_extract_from_iframe_context(sb, new_src)

                # المحاولة 2: فتح iframe في تبويب جديد
                if not video_url:
                    try:
                        handle_before = sb.driver.current_window_handle
                        video_url = try_extract_via_new_tab(sb, new_src, handle_before)
                    except Exception as e:
                        print(f"   ⚠️ فشل التبويب الجديد: {e}")

                if video_url:
                    selected_iframe = new_src
                    print(f"   ✅ تم استخراج الفيديو: {video_url[:120]}")
                    break
                else:
                    print(f"   ❌ لم يُستخرج فيديو من {sname}")

            return video_url, selected_iframe

        except Exception as e:
            print(f"❌ خطأ Selenium: {e}")
            return None, None


# ===== معالجة حلقة =====
async def process_episode(episode_num, series_name, series_name_arabic, season_num, download_dir):
    print(f"\n🎬 Episode {episode_num:02d}")
    print(f"🔗 Base URL: https://u.3seq.cam/video/modablaj-{series_name}-episode-{episode_num:02d}")

    temp_file = os.path.join(download_dir, f"temp_{episode_num:02d}.mp4")
    final_file = os.path.join(download_dir, f"final_{episode_num:02d}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_{episode_num:02d}.jpg")

    try:
        # تشغيل Selenium في thread منفصل (لأن SB() يدير event loop خاص به)
        video_url, selected_iframe = await asyncio.to_thread(
            _sync_selenium_work, episode_num, series_name
        )

        if not video_url:
            return False, "فشل استخراج رابط الفيديو من جميع السيرفرات"

        print(f"🎥 Video URL: {video_url[:120]}")

        if not download_video(video_url, temp_file, referer=selected_iframe):
            return False, "فشل التنزيل"

        if not compress_to_144p(temp_file, final_file):
            shutil.copy2(temp_file, final_file)

        create_thumbnail(final_file, thumb_file)

        caption = f"{series_name_arabic} الموسم {season_num} الحلقة {episode_num}"
        success = await upload_video(
            final_file, caption,
            thumb_file if os.path.exists(thumb_file) else None,
        )

        for f in [temp_file, final_file, thumb_file]:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass

        return success, "تم بنجاح" if success else "فشل الرفع"

    except Exception as e:
        return False, f"خطأ غير متوقع: {e}"


# ===== قراءة الإعدادات =====
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


# ===== main =====
async def main():
    print("=" * 60)
    print("🎬 معالج الفيديو المتكامل - u.3seq.cam")
    print("=" * 60)

    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg موجود")
    except Exception:
        print("❌ ffmpeg غير موجود")
        return

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
            wait_time = random.randint(45, 90)
            print(f"⏳ انتظار {wait_time} ثانية...")
            await asyncio.sleep(wait_time)

    print(f"\n{'='*60}")
    print(f"✅ الناجحة: {successful}/{total}")
    if failed:
        print(f"❌ الفاشلة: {failed}")
    print("=" * 60)

    try:
        shutil.rmtree(download_dir)
    except Exception:
        pass

    await app.stop()
    print("🔌 تم قطع الاتصال بتليغرام")


if __name__ == "__main__":
    asyncio.run(main())
