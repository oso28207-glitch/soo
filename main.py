#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - معالج متكامل لموقع u.3seq.cam
معدّل ليعمل على GitHub Actions مع دعم workflow_dispatch inputs
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

# ===== التهيئة والتحقق =====
TELEGRAM_API_ID = os.environ.get("API_ID", "")
TELEGRAM_API_HASH = os.environ.get("API_HASH", "")
TELEGRAM_CHANNEL = os.environ.get("CHANNEL", "")
STRING_SESSION = os.environ.get("STRING_SESSION", "")

# ===== قراءة الإعدادات من البيئة (workflow inputs) =====
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

# تثبيت الحزم الضرورية
def install_requirements():
    print("📦 Installing requirements...")
    reqs = [
        "pyrogram>=2.0.0",
        "tgcrypto>=1.2.0",
        "yt-dlp>=2024.4.9",
        "curl_cffi>=0.5.10",
        "seleniumbase>=4.30.0",
        "beautifulsoup4>=4.12.0"
    ]
    for req in reqs:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", req, "--quiet"])
            print(f"  ✅ {req.split('>=')[0]}")
        except:
            print(f"  ⚠️ Failed to install {req}")

install_requirements()

# استيراد المكتبات بعد التثبيت
from pyrogram import Client
from pyrogram.errors import FloodWait
import yt_dlp
from seleniumbase import SB
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException

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
            in_memory=True
        )
        await app.start()
        me = await app.get_me()
        print(f"✅ Connected as {me.first_name}")
        return True
    except Exception as e:
        print(f"❌ Telegram connection failed: {e}")
        return False


def extract_video_from_iframe(sb, iframe_url):
    """
    استخدام نفس جلسة المتصفح لفتح iframe واستخراج رابط الفيديو الحقيقي (.m3u8)
    """
    try:
        print(f"🔄 فتح iframe: {iframe_url}")
        sb.open(iframe_url)

        try:
            sb.wait_for_element("video", timeout=20)
            time.sleep(3)
        except:
            print("⚠️ لم يتم العثور على عنصر video خلال 20 ثانية.")

        video_src = None

        # الطريقة 1: عنصر video
        video_elements = sb.find_elements("video")
        if video_elements:
            video_src = video_elements[0].get_attribute("src")
            if video_src:
                print(f"✅ تم العثور على مصدر الفيديو: {video_src[:100]}...")
                return video_src

        # الطريقة 2: عناصر source
        source_elements = sb.find_elements("source")
        for source in source_elements:
            src = source.get_attribute("src")
            if src:
                video_src = src
                print(f"✅ تم العثور على مصدر بديل: {video_src[:100]}...")
                return video_src

        # الطريقة 3: regex داخل الصفحة
        page_source = sb.get_page_source()
        m3u8_matches = re.findall(r'(https?://[^"\']+\.m3u8[^"\']*)', page_source)
        if m3u8_matches:
            video_src = m3u8_matches[0]
            print(f"✅ تم العثور على رابط m3u8: {video_src[:100]}...")
            return video_src

        print("⚠️ لم يتم العثور على مصدر الفيديو.")
        return None

    except Exception as e:
        print(f"❌ خطأ في استخراج الفيديو من iframe: {e}")
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
            }
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
        '-y', output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=1800)
        return os.path.exists(output_path)
    except:
        return False


def create_thumbnail(video_path, thumb_path):
    cmd = [
        'ffmpeg', '-i', video_path,
        '-ss', '00:00:05', '-vframes', '1', '-s', '320x180',
        '-f', 'image2', '-y', thumb_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
        return os.path.exists(thumb_path)
    except:
        return False


async def upload_video(file_path, caption, thumb_path=None):
    if not app or not os.path.exists(file_path):
        return False
    try:
        width, height = 426, 240
        duration = 0
        try:
            probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                    '-show_entries', 'stream=width,height,duration',
                                    '-of', 'csv=p=0', file_path],
                                   capture_output=True, text=True)
            if probe.returncode == 0:
                parts = probe.stdout.strip().split(',')
                if len(parts) >= 2:
                    width, height = int(parts[0]), int(parts[1])
                if len(parts) >= 3 and parts[2]:
                    duration = int(float(parts[2]))
        except:
            pass

        await app.send_video(
            chat_id=TELEGRAM_CHANNEL,
            video=file_path,
            caption=caption,
            supports_streaming=True,
            width=width,
            height=height,
            duration=duration,
            thumb=thumb_path if thumb_path and os.path.exists(thumb_path) else None
        )
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await upload_video(file_path, caption, thumb_path)
    except Exception as e:
        print(f"❌ Upload error: {e}")
        return False


# ===== كود Selenium يعمل في thread منفصل =====

def _sync_selenium_work(episode_num, series_name):
    """
    كل عمليات Selenium تعمل داخل هذا الـ thread المنفصل.
    تعيد (video_url, selected_iframe) أو (None, None) عند الفشل.
    """
    base_url = f"https://u.3seq.cam/video/modablaj-{series_name}-episode-{episode_num:02d}"
    video_url = None
    selected_iframe = None

    with SB(uc=True, xvfb=True, incognito=True, headless=False, locale_code="en") as sb:
        print("🖥️ تشغيل Selenium للحصول على الرابط النهائي...")
        sb.open(base_url)

        start_time = time.time()
        current_url = sb.get_current_url()
        while current_url == base_url and time.time() - start_time < 10:
            time.sleep(1)
            current_url = sb.get_current_url()

        final_url = sb.get_current_url()
        print(f"🌐 الرابط النهائي: {final_url}")

        if not final_url.endswith('/'):
            final_url += '/'
        watch_url = final_url + '?do=watch'
        print(f"📺 جاري تحميل صفحة المشاهدة: {watch_url}")
        sb.open(watch_url)
        time.sleep(3)

        try:
            sb.wait_for_element("ul.serversList", timeout=30)
            print("✅ تم العثور على قائمة السيرفرات.")
        except TimeoutException:
            print("⚠️ لم يتم العثور على قائمة السيرفرات خلال 30 ثانية.")
            return None, None

        server_buttons = sb.find_elements("ul.serversList li")
        if not server_buttons:
            return None, None

        server_names = [btn.text.strip() for btn in server_buttons]
        print(f"📦 تم العثور على {len(server_buttons)} سيرفر: {', '.join(server_names)}")

        try:
            iframe_element = sb.find_element(".watch iframe")
        except NoSuchElementException:
            return None, None

        for idx in range(len(server_buttons)):
            try:
                btn = sb.find_elements("ul.serversList li")[idx]
                server_name = btn.text.strip()
                print(f"\n🔄 محاولة السيرفر {idx+1}/{len(server_buttons)}: {server_name}")

                old_src = iframe_element.get_attribute("src")
                print(f"   القديم: {old_src}")

                try:
                    sb.execute_script("arguments[0].click();", btn)
                except Exception as e:
                    print(f"⚠️ فشل النقر بالـ JS، نحاول بالطريقة العادية: {e}")
                    btn.click()

                try:
                    WebDriverWait(sb.driver, 20).until(
                        lambda d: d.find_element(By.CSS_SELECTOR, ".watch iframe").get_attribute("src") != old_src
                    )
                    print("✅ تم تغيير iframe بنجاح.")
                except TimeoutException:
                    print("⏱️ لم يتغير src خلال المهلة، ربما السيرفر لا يعمل.")
                    continue

                iframe_url = iframe_element.get_attribute("src")
                print(f"📦 iframe الجديد: {iframe_url}")

                if not iframe_url or iframe_url == old_src:
                    print(f"⚠️ السيرفر {server_name} لم يقدم iframe صالح")
                    continue

                video_url = extract_video_from_iframe(sb, iframe_url)
                if video_url:
                    selected_iframe = iframe_url
                    print(f"✅ تم العثور على فيديو من السيرفر {server_name}")
                    break
                else:
                    print(f"❌ السيرفر {server_name} لم يعطِ فيديو صالح")

            except StaleElementReferenceException:
                print("⚠️ عنصر قديم، نعيد الحصول عليه...")
                try:
                    iframe_element = sb.find_element(".watch iframe")
                except:
                    pass
                continue
            except Exception as e:
                print(f"⚠️ خطأ أثناء محاولة السيرفر: {e}")
                continue

    return video_url, selected_iframe


# ===== معالجة حلقة واحدة =====

async def process_episode(episode_num, series_name, series_name_arabic, season_num, download_dir):
    print(f"\n🎬 Episode {episode_num:02d}")
    print(f"🔗 Base URL: https://u.3seq.cam/video/modablaj-{series_name}-episode-{episode_num:02d}")

    temp_file = os.path.join(download_dir, f"temp_{episode_num:02d}.mp4")
    final_file = os.path.join(download_dir, f"final_{episode_num:02d}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_{episode_num:02d}.jpg")

    try:
        # ✅ تشغيل كل كود Selenium في thread منفصل
        video_url, selected_iframe = await asyncio.to_thread(
            _sync_selenium_work, episode_num, series_name
        )

        if not video_url:
            return False, "فشل استخراج رابط الفيديو من جميع السيرفرات"

        print(f"🎥 Video URL: {video_url}")

        if not download_video(video_url, temp_file, referer=selected_iframe):
            return False, "فشل التنزيل"

        if not compress_to_144p(temp_file, final_file):
            shutil.copy2(temp_file, final_file)

        create_thumbnail(final_file, thumb_file)

        caption = f"{series_name_arabic} الموسم {season_num} الحلقة {episode_num}"
        success = await upload_video(final_file, caption, thumb_file if os.path.exists(thumb_file) else None)

        for f in [temp_file, final_file, thumb_file]:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except:
                pass

        return success, "تم بنجاح" if success else "فشل الرفع"

    except Exception as e:
        return False, f"خطأ غير متوقع: {e}"


# ===== قراءة الإعدادات =====

def load_config():
    """
    الأولوية:
    1. متغيرات البيئة (workflow_dispatch inputs)
    2. series_config.json
    """
    config = {
        "series_name": "",
        "series_name_arabic": "",
        "season_num": 1,
        "start_episode": 1,
        "end_episode": 1,
    }

    # 1. من ملف الإعدادات إن وُجد
    config_file = "series_config.json"
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
            config.update({k: v for k, v in file_config.items() if v not in (None, "")})
            print(f"📄 تم تحميل الإعدادات من {config_file}")
        except Exception as e:
            print(f"⚠️ فشل قراءة {config_file}: {e}")

    # 2. تجاوز بمتغيرات البيئة (inputs)
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


# ===== الدالة الرئيسية =====

async def main():
    print("=" * 60)
    print("🎬 معالج الفيديو المتكامل - u.3seq.cam")
    print("=" * 60)

    # التحقق من ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg موجود")
    except:
        print("❌ ffmpeg غير موجود")
        return

    # قراءة الإعدادات
    config = load_config()

    series_name = str(config.get("series_name", "")).strip().replace(' ', '-')
    series_name_arabic = str(config.get("series_name_arabic", "")).strip()
    season_num = int(config.get("season_num", 1))
    start_ep = int(config.get("start_episode", 1))
    end_ep = int(config.get("end_episode", 1))

    if not series_name:
        print("❌ اسم المسلسل بالإنجليزية (series_name) مطلوب")
        return
    if not series_name_arabic:
        series_name_arabic = series_name

    # حد أقصى للحماية
    if end_ep - start_ep + 1 > 25:
        print("⚠️ عدد الحلقات كبير جداً، سيتم معالجة 25 حلقة فقط.")
        end_ep = start_ep + 24

    print(f"📺 المسلسل (EN): {series_name}")
    print(f"📺 المسلسل (AR): {series_name_arabic}")
    print(f"🗂️ الموسم: {season_num}")
    print(f"🎬 الحلقات: {start_ep} إلى {end_ep}")

    # الاتصال بتليغرام
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

        # انتظار عشوائي لتجنب الحظر
        if ep < end_ep:
            wait_time = random.randint(45, 90)
            print(f"⏳ انتظار {wait_time} ثانية...")
            await asyncio.sleep(wait_time)

    print(f"\n{'='*60}")
    print(f"✅ الناجحة: {successful}/{total}")
    if failed:
        print(f"❌ الفاشلة: {failed}")
    print("=" * 60)

    # تنظيف
    try:
        shutil.rmtree(download_dir)
    except:
        pass

    await app.stop()
    print("🔌 تم قطع الاتصال بتليغرام")


if __name__ == "__main__":
    asyncio.run(main())
