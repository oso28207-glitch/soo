#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - معالج متكامل باستخدام Selenium لاستخراج الفيديو من larozaa.xyz
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

def test_video_url(url):
    """اختبار ما إذا كان الرابط قابلاً للتنزيل باستخدام yt-dlp (بدون تحميل)"""
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

def extract_video_from_embed(driver, embed_url):
    """فتح صفحة embed واستخراج رابط الفيديو المباشر"""
    try:
        print(f"🔄 فتح embed: {embed_url}")
        driver.get(embed_url)
        time.sleep(5)  # انتظار تحميل الصفحة
        page_source = driver.page_source
        
        # 1. البحث عن عنصر <video>
        try:
            video = driver.find_element(By.TAG_NAME, "video")
            src = video.get_attribute("src")
            if src and src.startswith("http"):
                print(f"✅ تم العثور على فيديو في <video>: {src[:100]}...")
                return src
        except:
            pass
        
        # 2. البحث عن عنصر <source>
        try:
            source = driver.find_element(By.TAG_NAME, "source")
            src = source.get_attribute("src")
            if src and src.startswith("http"):
                print(f"✅ تم العثور على فيديو في <source>: {src[:100]}...")
                return src
        except:
            pass
        
        # 3. البحث عن رابط .mp4 في الصفحة
        match = re.search(r'(https?://[^"\']+\.mp4[^"\']*)', page_source)
        if match:
            video_url = match.group(1)
            print(f"✅ تم العثور على رابط mp4: {video_url[:100]}...")
            return video_url
        
        # 4. إذا لم نجد، نعيد embed_url لاستخدام yt-dlp
        print("⚠️ لم يتم العثور على رابط مباشر، سيتم استخدام embed_url مع yt-dlp.")
        return embed_url
    except Exception as e:
        print(f"❌ خطأ في استخراج الفيديو من embed: {e}")
        return embed_url  # نعيد embed_url لاستخدام yt-dlp

def get_video_from_larozaa(driver, video_page_url):
    """
    استخراج رابط الفيديو من صفحة larozaa.
    video_page_url: رابط صفحة المشاهدة مثل https://larozaa.xyz/play.php?vid=72c5aacd6
    """
    try:
        print(f"🖥️ فتح صفحة الفيديو: {video_page_url}")
        driver.get(video_page_url)
        time.sleep(5)
        
        # البحث عن قائمة السيرفرات
        try:
            servers = driver.find_elements(By.CSS_SELECTOR, "ul.WatchList li")
            if not servers:
                print("❌ لم يتم العثور على قائمة السيرفرات")
                return None, None
            
            # اختيار السيرفر النشط (active) أو الأول
            embed_url = None
            for li in servers:
                if "active" in li.get_attribute("class"):
                    embed_url = li.get_attribute("data-embed-url")
                    break
            if not embed_url:
                embed_url = servers[0].get_attribute("data-embed-url")
            
            if not embed_url:
                print("❌ لم يتم العثور على رابط embed")
                return None, None
            
            print(f"📦 تم العثور على embed URL: {embed_url}")
        except Exception as e:
            print(f"❌ خطأ في استخراج embed: {e}")
            return None, None
        
        # استخراج الفيديو من embed
        video_url = extract_video_from_embed(driver, embed_url)
        return video_url, embed_url
        
    except Exception as e:
        print(f"❌ خطأ رئيسي في استخراج الفيديو: {e}")
        return None, None

def download_video(video_url, output_path, referer):
    """تنزيل الفيديو باستخدام yt-dlp مع impersonation وإضافة referer"""
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

async def process_video(video_url, series_name_arabic, season_num, episode_num, download_dir):
    """
    معالجة فيديو واحد من larozaa
    """
    print(f"\n🎬 Processing episode {episode_num}")
    print(f"🔗 Video page URL: {video_url}")
    
    temp_file = os.path.join(download_dir, f"temp_{episode_num:02d}.mp4")
    final_file = os.path.join(download_dir, f"final_{episode_num:02d}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_{episode_num:02d}.jpg")

    # إعداد Selenium واستخراج الفيديو
    driver = setup_selenium()
    if not driver:
        return False, "فشل إعداد Selenium"
    
    video_url_direct, referer = get_video_from_larozaa(driver, video_url)
    driver.quit()

    if not video_url_direct:
        return False, "فشل استخراج رابط الفيديو"
    
    # تنزيل الفيديو
    if not download_video(video_url_direct, temp_file, referer=referer):
        return False, "فشل التنزيل"
    
    # ضغط الفيديو
    if not compress_to_240p(temp_file, final_file):
        shutil.copy2(temp_file, final_file)
    
    # إنشاء صورة مصغرة
    create_thumbnail(final_file, thumb_file)
    
    # رفع إلى تليغرام
    caption = f"{series_name_arabic} الموسم {season_num} الحلقة {episode_num}"
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
    print("🎬 معالج الفيديو المتكامل (larozaa.xyz)")
    print("="*50)

    # التحقق من ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg موجود")
    except:
        print("❌ ffmpeg غير موجود")
        return

    # التحقق من توفر chromedriver
    if not shutil.which('chromedriver'):
        print("❌ chromedriver غير موجود. تأكد من تثبيته.")
        return

    # الاتصال بتليغرام
    if not await setup_telegram():
        return

    # قراءة ملف الإعدادات
    config_file = "series_config.json"
    if not os.path.exists(config_file):
        print("❌ series_config.json غير موجود")
        return

    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)

    series_name_arabic = config.get("series_name_arabic", "").strip()
    season_num = int(config.get("season_num", 1))
    episode_num = int(config.get("episode_num", 1))
    video_url = config.get("video_url", "").strip()

    if not series_name_arabic:
        print("❌ series_name_arabic مفقود في config")
        return
    if not video_url:
        print("❌ video_url مفقود في config")
        return

    print(f"📺 المسلسل: {series_name_arabic}")
    print(f"🎬 الحلقة: {episode_num} (الموسم {season_num})")
    print(f"🔗 رابط المشاهدة: {video_url}")

    download_dir = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(download_dir, exist_ok=True)

    success, msg = await process_video(video_url, series_name_arabic, season_num, episode_num, download_dir)
    if success:
        print(f"✅ تم رفع الحلقة بنجاح")
    else:
        print(f"❌ فشل الرفع: {msg}")

    # تنظيف
    try:
        os.rmdir(download_dir)
    except:
        pass

    await app.stop()
    print("🔌 تم قطع الاتصال بتليغرام")

if __name__ == "__main__":
    asyncio.run(main())
