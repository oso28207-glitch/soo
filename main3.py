#!/usr/bin/env python3
"""
Telegram Video Uploader - يدعم روابط embed من vidspeed, uqload, vipserver وغيرها
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

def extract_video_from_generic_page(driver, url):
    """
    محاولة استخراج رابط الفيديو المباشر من أي صفحة embed.
    تدعم: vidspeed, uqload, vipserver وغيرها.
    """
    try:
        print(f"🔄 فتح الصفحة: {url}")
        driver.get(url)
        time.sleep(5)  # انتظار التحميل الأولي

        page_source = driver.page_source

        # 1. البحث عن iframe داخل الصفحة
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        if iframes:
            for iframe in iframes:
                iframe_src = iframe.get_attribute("src")
                if iframe_src and ("video" in iframe_src or "embed" in iframe_src or "player" in iframe_src):
                    print(f"📦 تم العثور على iframe: {iframe_src}")
                    # الانتقال إلى iframe
                    driver.switch_to.frame(iframe)
                    time.sleep(3)
                    try:
                        video = driver.find_element(By.TAG_NAME, "video")
                        vid_src = video.get_attribute("src")
                        if vid_src and vid_src.startswith("http"):
                            driver.switch_to.default_content()
                            return vid_src
                    except:
                        pass
                    driver.switch_to.default_content()
                    # تجربة فتح iframe مباشرة
                    driver.get(iframe_src)
                    time.sleep(5)
                    return extract_video_from_generic_page(driver, iframe_src)  # استدعاء ذاتي للمعالجة

        # 2. البحث عن عنصر <video> مباشرة
        try:
            video_elements = driver.find_elements(By.TAG_NAME, "video")
            for video in video_elements:
                src = video.get_attribute("src")
                if src and src.startswith("http"):
                    return src
        except:
            pass

        # 3. البحث عن مصفوفة sources في JavaScript
        match = re.search(r'sources:\s*\[\s*"([^"]+\.mp4[^"]*)"\s*\]', page_source)
        if match:
            return match.group(1)
        match = re.search(r'file:\s*["\']([^"\']+\.mp4[^"\']*)["\']', page_source)
        if match:
            return match.group(1)
        match = re.search(r'(https?://[^"\']+\.mp4[^"\']*)', page_source)
        if match:
            return match.group(1)

        # 4. محاولة استخدام yt-dlp كحل أخير (لكشف الرابط)
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and 'url' in info and info['url'].startswith('http'):
                    return info['url']
                if info and 'entries' in info and info['entries']:
                    return info['entries'][0]['url']
        except:
            pass

        print("❌ لم يتم العثور على رابط فيديو.")
        return None
    except Exception as e:
        print(f"❌ خطأ في استخراج الفيديو: {e}")
        return None

def download_video(video_url, output_path, referer_url):
    """تنزيل الفيديو باستخدام yt-dlp مع إضافة referer"""
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
                'Referer': referer_url,
            }
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        return os.path.exists(output_path)
    except Exception as e:
        print(f"❌ Download error: {e}")
        return False

def compress_to_240p(input_path, output_path):
    """ضغط الفيديو إلى 240p"""
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

async def process_part(part_info, download_dir):
    """
    معالجة جزء واحد من الفيلم.
    part_info = {'url': '...', 'part': 1, 'movie_name': 'افاتار'}
    """
    url = part_info['url']
    part_num = part_info['part']
    movie_name = part_info['movie_name']
    
    print(f"\n🎬 الجزء {part_num} - {movie_name}")
    print(f"🔗 الرابط: {url}")
    
    temp_file = os.path.join(download_dir, f"temp_part{part_num:02d}.mp4")
    final_file = os.path.join(download_dir, f"final_part{part_num:02d}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_part{part_num:02d}.jpg")
    
    # إعداد Selenium
    driver = setup_selenium()
    if not driver:
        return False, "فشل إعداد Selenium"
    
    video_url = extract_video_from_generic_page(driver, url)
    driver.quit()
    
    if not video_url:
        return False, "فشل استخراج رابط الفيديو"
    
    print(f"✅ تم استخراج الرابط المباشر: {video_url[:100]}...")
    
    # تنزيل الفيديو
    if not download_video(video_url, temp_file, referer_url=url):
        return False, "فشل التنزيل"
    
    # ضغط الفيديو
    if not compress_to_240p(temp_file, final_file):
        shutil.copy2(temp_file, final_file)
    
    # إنشاء صورة مصغرة
    create_thumbnail(final_file, thumb_file)
    
    # رفع إلى تليغرام
    caption = f"{movie_name} - الجزء {part_num}"
    success = await upload_video(final_file, caption, thumb_file if os.path.exists(thumb_file) else None)
    
    # تنظيف
    for f in [temp_file, final_file, thumb_file]:
        try:
            if os.path.exists(f):
                os.remove(f)
        except:
            pass
    
    return success, "تم بنجاح" if success else "فشل الرفع"

async def main():
    print("="*50)
    print("🎬 رافع الأفلام إلى تليغرام (يدعم vidspeed, uqload, vipserver)")
    print("="*50)

    # التحقق من ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg موجود")
    except:
        print("❌ ffmpeg غير موجود")
        return

    # التحقق من chromedriver
    if not shutil.which('chromedriver'):
        print("❌ chromedriver غير موجود. تأكد من تثبيته.")
        return

    # الاتصال بتليغرام
    if not await setup_telegram():
        return

    # قراءة ملف الإعدادات
    config_file = "movie_config.json"
    if not os.path.exists(config_file):
        print("❌ movie_config.json غير موجود")
        return

    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)

    movie_name = config.get("movie_name", "فيلم").strip()
    parts = config.get("parts", [])
    if not parts:
        print("❌ لا توجد أجزاء محددة في movie_config.json")
        return

    # ترتيب الأجزاء حسب رقم الجزء (تأمين)
    parts = sorted(parts, key=lambda x: x.get('part', 0))

    print(f"🎥 الفيلم: {movie_name}")
    print(f"📀 عدد الأجزاء: {len(parts)}")

    download_dir = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(download_dir, exist_ok=True)

    successful = 0
    failed = []

    for idx, part in enumerate(parts, start=1):
        # إضافة اسم الفيلم لكل جزء (لتجنب اعتماده على المتغير العام إذا كان هناك أجزاء مختلفة)
        part['movie_name'] = movie_name
        
        success, msg = await process_part(part, download_dir)
        if success:
            successful += 1
            print(f"✅ الجزء {part.get('part', idx)} اكتمل")
        else:
            failed.append(part.get('part', idx))
            print(f"❌ الجزء {part.get('part', idx)}: {msg}")

        # انتظار عشوائي بين الأجزاء
        wait_time = random.randint(30, 45)
        print(f"⏳ انتظار {wait_time} ثانية...")
        await asyncio.sleep(wait_time)

    print(f"\n✅ الناجحة: {successful}/{len(parts)}")
    if failed:
        print(f"❌ الفاشلة: {failed}")

    # تنظيف المجلد المؤقت
    try:
        shutil.rmtree(download_dir)
    except:
        pass

    await app.stop()
    print("🔌 تم قطع الاتصال بتليغرام")

if __name__ == "__main__":
    asyncio.run(main())
