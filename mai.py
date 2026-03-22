#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - يدعم أي رابط مباشر للفيديو
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
        "selenium>=4.15.0",
        "beautifulsoup4>=4.12.0"
    ]
    for req in reqs:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", req, "--quiet"])
            print(f"  ✅ {req.split('>=')[0]}")
        except:
            print(f"  ⚠️ Failed to install {req}")

install_requirements()

from pyrogram import Client
from pyrogram.errors import FloodWait
import yt_dlp
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup

app = None

# ===== إعداد Selenium =====
def setup_selenium():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--disable-notifications')
    chrome_options.add_argument('--ignore-certificate-errors')
    
    chromedriver_path = '/usr/bin/chromedriver'
    if not os.path.exists(chromedriver_path):
        chromedriver_path = shutil.which('chromedriver')
        if not chromedriver_path:
            print("❌ لم يتم العثور على chromedriver. تأكد من تثبيته.")
            return None
    
    try:
        service = Service(executable_path=chromedriver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return driver
    except Exception as e:
        print(f"❌ فشل إعداد Selenium: {e}")
        return None

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

def extract_src_from_iframe(iframe_html):
    match = re.search(r'src=["\'](https?://[^"\']+)["\']', iframe_html)
    if match:
        return match.group(1)
    return None

def test_video_url(url):
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and ('url' in info or 'entries' in info):
                return True
    except Exception:
        pass
    return False

def extract_video_from_uqload_page(driver, url):
    try:
        if 'uqload.to' in url:
            url = url.replace('uqload.to', 'uqload.is')
            print(f"🔄 تم تحويل الرابط إلى: {url}")
        
        print(f"🔄 فتح صفحة Uqload: {url}")
        driver.get(url)
        time.sleep(5)
        page_source = driver.page_source
        
        match = re.search(r'sources:\s*\[\s*"([^"]+\.mp4[^"]*)"\s*\]', page_source)
        if match:
            video_url = match.group(1)
            print(f"✅ تم استخراج رابط فيديو Uqload: {video_url[:100]}...")
            return video_url
        
        match = re.search(r'(https?://[^"\']+\.mp4[^"\']*)', page_source)
        if match:
            video_url = match.group(1)
            print(f"✅ تم العثور على رابط mp4: {video_url[:100]}...")
            return video_url
        
        print("❌ لم يتم العثور على رابط فيديو في صفحة Uqload.")
        return None
    except Exception as e:
        print(f"❌ خطأ في استخراج الفيديو من Uqload: {e}")
        return None

def extract_video_from_current_page(driver):
    """استخراج src من عنصر video في الصفحة الحالية"""
    try:
        video_element = driver.find_element(By.TAG_NAME, "video")
        video_url = video_element.get_attribute("src")
        if video_url:
            print(f"✅ تم العثور على رابط فيديو مباشر: {video_url[:100]}...")
            return video_url
    except:
        pass
    return None

def extract_video_from_page(driver, page_url):
    """
    محاولة استخراج رابط فيديو من أي صفحة (مباشرة).
    تعيد (video_url, referer)
    """
    driver.get(page_url)
    time.sleep(5)

    # 1. البحث عن iframe (مثل AlbaPlayer)
    try:
        iframe = driver.find_element(By.CSS_SELECTOR, ".aplr-player-content iframe")
        iframe_src = iframe.get_attribute("src")
        if iframe_src:
            print(f"📦 تم العثور على iframe: {iframe_src}")
            # معالجة iframe
            if 'uqload' in iframe_src:
                video_url = extract_video_from_uqload_page(driver, iframe_src)
                if video_url:
                    return video_url, iframe_src
            else:
                # فتح iframe
                driver.get(iframe_src)
                time.sleep(5)
                video_url = extract_video_from_current_page(driver)
                if video_url:
                    return video_url, iframe_src
    except:
        pass

    # 2. البحث عن عنصر video مباشرة
    video_url = extract_video_from_current_page(driver)
    if video_url:
        return video_url, page_url

    # 3. البحث عن روابط mp4 في الصفحة
    page_source = driver.page_source
    match = re.search(r'(https?://[^"\']+\.mp4[^"\']*)', page_source)
    if match:
        video_url = match.group(1)
        print(f"✅ تم العثور على رابط mp4 في الصفحة: {video_url[:100]}...")
        return video_url, page_url

    # 4. استخدام yt-dlp
    if test_video_url(page_url):
        print("✅ الرابط قابل للتنزيل عبر yt-dlp.")
        return page_url, page_url

    return None, None

def get_video_from_rmd(driver, base_url):
    """
    استخراج رابط الفيديو من صفحة الحلقة (أي رابط).
    """
    return extract_video_from_page(driver, base_url)

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
                'Referer': referer,
            }
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        return os.path.exists(output_path)
    except Exception as e:
        print(f"❌ Download error: {e}")
        return False

def compress_to_240p(input_path, output_path):
    if not os.path.exists(input_path):
        return False
    cmd = [
        'ffmpeg', '-i', input_path,
        '-vf', 'scale=-2:240',
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

# ===== معالجة حلقة واحدة =====
async def process_episode(episode_num, series_name, series_name_arabic, season_num, server_num, download_dir, direct_url=None):
    if direct_url:
        base_url = direct_url
        if episode_num is None:
            match = re.search(r'[eE](\d{2})', base_url)
            if match:
                episode_num = int(match.group(1))
            else:
                episode_num = 0
    else:
        base_url = f"https://v.rmd.quest/albaplayer/{series_name}-s{season_num:02d}e{episode_num:02d}/?serv={server_num}"

    print(f"\n🎬 معالجة الحلقة (رقم {episode_num if episode_num else 'غير محدد'})")
    print(f"🔗 الرابط: {base_url}")

    temp_file = os.path.join(download_dir, f"temp_{episode_num:02d}.mp4")
    final_file = os.path.join(download_dir, f"final_{episode_num:02d}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_{episode_num:02d}.jpg")

    driver = setup_selenium()
    if not driver:
        return False, "فشل إعداد Selenium"

    video_url, referer = get_video_from_rmd(driver, base_url)
    driver.quit()

    if not video_url:
        return False, "فشل استخراج رابط الفيديو"

    if not download_video(video_url, temp_file, referer=referer):
        return False, "فشل التنزيل"

    if not compress_to_240p(temp_file, final_file):
        shutil.copy2(temp_file, final_file)

    create_thumbnail(final_file, thumb_file)

    # بناء الكابشن
    caption_parts = [series_name_arabic]
    if season_num is not None and season_num != '':
        caption_parts.append(f"الموسم {season_num}")
    if episode_num is not None and episode_num != 0:
        caption_parts.append(f"الحلقة {episode_num}")
    caption = " ".join(caption_parts)

    success = await upload_video(final_file, caption, thumb_file if os.path.exists(thumb_file) else None)

    for f in [temp_file, final_file, thumb_file]:
        try:
            if os.path.exists(f):
                os.remove(f)
        except:
            pass

    return success, "تم بنجاح" if success else "فشل الرفع"

async def main():
    print("="*50)
    print("🎬 معالج الفيديو المتكامل (AlbaPlayer - v.rmd.quest)")
    print("="*50)

    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg موجود")
    except:
        print("❌ ffmpeg غير موجود")
        return

    if not shutil.which('chromedriver'):
        print("❌ chromedriver غير موجود. تأكد من تثبيته.")
        return

    if not await setup_telegram():
        return

    config_file = "series_config.json"
    if not os.path.exists(config_file):
        print("❌ series_config.json غير موجود")
        return

    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)

    series_name = config.get("series_name", "").strip()
    series_name_arabic = config.get("series_name_arabic", "").strip()
    season_num = config.get("season_num", None)
    episode_number = config.get("episode_number", None)
    episode_url = config.get("episode_url", "").strip()

    if season_num == '':
        season_num = None
    if episode_number == '':
        episode_number = None

    if not episode_url:
        print("❌ لم يتم توفير episode_url. الرابط مطلوب.")
        return

    print(f"📺 المسلسل: {series_name_arabic}")
    if season_num:
        print(f"📅 الموسم: {season_num}")
    if episode_number:
        print(f"🔢 رقم الحلقة: {episode_number}")

    download_dir = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(download_dir, exist_ok=True)

    success, msg = await process_episode(
        episode_num=episode_number,
        series_name=series_name,
        series_name_arabic=series_name_arabic,
        season_num=season_num,
        server_num=1,
        download_dir=download_dir,
        direct_url=episode_url
    )

    if success:
        print(f"\n✅ اكتملت المعالجة: {msg}")
    else:
        print(f"\n❌ فشلت المعالجة: {msg}")

    try:
        os.rmdir(download_dir)
    except:
        pass

    await app.stop()
    print("🔌 تم قطع الاتصال بتليغرام")

if __name__ == "__main__":
    asyncio.run(main())
