#!/usr/bin/env python3
"""
Telegram Video Uploader - يدعم روابط embed من vidspeed, uqload, vipserver, mp4.okhd.site
مع الاعتماد على Selenium بشكل أساسي للمواقع غير المباشرة
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
        "selenium>=4.15.0",
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
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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

def is_direct_url(url):
    """تحديد ما إذا كان الرابط مباشرًا لملف فيديو (mp4, m3u8, mkv, ...)"""
    direct_extensions = ('.mp4', '.m3u8', '.mkv', '.avi', '.mov', '.ts')
    return url.lower().endswith(direct_extensions)

def extract_with_ytdlp(url):
    """استخدام yt-dlp فقط إذا كان الرابط مباشرًا (لأن المواقع embed غير مدعومة)"""
    if not is_direct_url(url):
        print("  ⏩ الرابط ليس مباشراً، تخطي yt-dlp (لن يعمل)")
        return None
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and 'url' in info:
                return info['url']
            if info and 'entries' and len(info['entries']) > 0:
                return info['entries'][0].get('url')
    except Exception as e:
        print(f"  yt-dlp فشل: {e}")
    return None

def extract_with_selenium(driver, url):
    """استخراج الرابط باستخدام Selenium مع دعم لجميع المواقع"""
    try:
        print(f"  🔄 تجربة Selenium مع: {url}")
        driver.get(url)
        # انتظار تحميل الصفحة بالكامل (حتى 30 ثانية)
        wait = WebDriverWait(driver, 30)
        
        # انتظار وجود أي iframe أو عنصر فيديو
        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
        except:
            pass
        
        time.sleep(5)  # تأمين إضافي
        
        # ----- البحث عن iframes -----
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            src = iframe.get_attribute("src")
            if src and ('embed' in src or 'player' in src or 'video' in src or 'okhd' in src):
                print(f"  📦 تم العثور على iframe: {src}")
                # فتح iframe مباشرة ومعالجته
                driver.get(src)
                time.sleep(8)
                return extract_with_selenium(driver, src)
        
        # ----- البحث عن عنصر الفيديو -----
        try:
            video = driver.find_element(By.TAG_NAME, "video")
            src = video.get_attribute("src")
            if src and src.startswith("http"):
                return src
        except:
            pass
        
        # ----- تنفيذ JavaScript للحصول على الرابط -----
        js_get_video = """
        var video = document.querySelector('video');
        if (video && video.src) return video.src;
        var sources = document.querySelectorAll('source');
        for (var i=0; i<sources.length; i++) {
            if (sources[i].src) return sources[i].src;
        }
        // البحث في data-src أو data-video
        var elements = document.querySelectorAll('[data-src], [data-video]');
        for (var i=0; i<elements.length; i++) {
            var src = elements[i].getAttribute('data-src') || elements[i].getAttribute('data-video');
            if (src && src.startsWith('http')) return src;
        }
        return null;
        """
        video_url = driver.execute_script(js_get_video)
        if video_url:
            return video_url
        
        # ----- البحث في النص عن روابط mp4 أو m3u8 -----
        page_source = driver.page_source
        patterns = [
            r'file:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
            r'src:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
            r'videoUrl:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
            r'url:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
            r'(https?://[^"\'\s]+\.mp4)',
            r'(https?://[^"\'\s]+\.m3u8)'
        ]
        for pattern in patterns:
            match = re.search(pattern, page_source, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    except Exception as e:
        print(f"  ❌ خطأ في Selenium: {e}")
        return None

def get_video_url(part_info):
    """
    الحصول على رابط الفيديو المباشر.
    إذا وُجد 'direct_url' يتم استخدامه مباشرة.
    وإذا كان الرابط مباشراً يستخدم yt-dlp.
    وإلا يستخدم Selenium.
    """
    if 'direct_url' in part_info and part_info['direct_url']:
        print(f"  🔗 استخدام الرابط المباشر المقدم: {part_info['direct_url'][:80]}...")
        return part_info['direct_url']
    
    url = part_info['url']
    
    # إذا كان الرابط مباشراً (ينتهي بـ mp4 إلخ)، استخدم yt-dlp
    if is_direct_url(url):
        print(f"  📡 الرابط مباشر، استخراج بواسطة yt-dlp...")
        video_url = extract_with_ytdlp(url)
        if video_url:
            return video_url
        # إذا فشل، نعتبر الرابط نفسه صالحاً
        return url
    
    # خلاف ذلك، استخدم Selenium فقط (لأن yt-dlp لا يدعم صفحات embed)
    print(f"  🌐 الرابط ليس مباشراً، استخدام Selenium للاستخراج...")
    driver = setup_selenium()
    if not driver:
        return None
    video_url = extract_with_selenium(driver, url)
    driver.quit()
    return video_url

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
    part_num = part_info['part']
    movie_name = part_info['movie_name']
    
    print(f"\n🎬 الجزء {part_num} - {movie_name}")
    print(f"🔗 الرابط: {part_info.get('url', part_info.get('direct_url', 'غير متوفر'))}")
    
    temp_file = os.path.join(download_dir, f"temp_part{part_num:02d}.mp4")
    final_file = os.path.join(download_dir, f"final_part{part_num:02d}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_part{part_num:02d}.jpg")

    video_url = get_video_url(part_info)
    if not video_url:
        return False, "فشل استخراج رابط الفيديو"

    referer = part_info.get('url', video_url)
    if not download_video(video_url, temp_file, referer_url=referer):
        return False, "فشل التنزيل"
    
    # ضغط (يمكن تعطيله إذا أردت توفير الوقت)
    if not compress_to_240p(temp_file, final_file):
        shutil.copy2(temp_file, final_file)
    
    create_thumbnail(final_file, thumb_file)
    
    caption = f"{movie_name} - الجزء {part_num}"
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
    print("🎬 رافع الأفلام إلى تليغرام (Selenium بشكل أساسي)")
    print("="*50)

    # التحقق من ffmpeg
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

    parts = sorted(parts, key=lambda x: x.get('part', 0))
    print(f"🎥 الفيلم: {movie_name}")
    print(f"📀 عدد الأجزاء: {len(parts)}")

    download_dir = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(download_dir, exist_ok=True)

    successful = 0
    failed = []

    for idx, part in enumerate(parts, start=1):
        part['movie_name'] = movie_name
        success, msg = await process_part(part, download_dir)
        if success:
            successful += 1
            print(f"✅ الجزء {part.get('part', idx)} اكتمل")
        else:
            failed.append(part.get('part', idx))
            print(f"❌ الجزء {part.get('part', idx)}: {msg}")

        if idx < len(parts):
            wait_time = random.randint(30, 60)
            print(f"⏳ انتظار {wait_time} ثانية...")
            await asyncio.sleep(wait_time)

    print(f"\n✅ الناجحة: {successful}/{len(parts)}")
    if failed:
        print(f"❌ الفاشلة: {failed}")

    try:
        shutil.rmtree(download_dir)
    except:
        pass

    await app.stop()
    print("🔌 تم قطع الاتصال بتليغرام")

if __name__ == "__main__":
    asyncio.run(main())
