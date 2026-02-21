#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - معالج متكامل باستخدام Selenium لاستخراج الفيديو من iframe
"""

import os
import sys
import time
import json
import subprocess
import shutil
import asyncio
import random
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
        "webdriver-manager>=4.0.1",
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
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup

app = None

# ===== إعداد Selenium =====
def setup_selenium():
    """إعداد متصفح Chrome في وضع headless مع خيارات لمنع اكتشاف adblock"""
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
    
    try:
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        # تنفيذ كود لإخفاء وجود selenium
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

def get_episode_page_with_selenium(base_url):
    """
    استخدام Selenium للحصول على:
    1. الرابط النهائي بعد إعادة التوجيه (مع الرمز)
    2. محتوى HTML الكامل لصفحة المشاهدة بعد تحميل JavaScript
    """
    driver = setup_selenium()
    if not driver:
        return None, None
    
    try:
        # الخطوة 1: الذهاب إلى الرابط الأساسي وانتظار إعادة التوجيه
        print("🖥️ تشغيل Selenium للحصول على الرابط النهائي...")
        driver.get(base_url)
        WebDriverWait(driver, 15).until(EC.url_changes(base_url))
        time.sleep(3)  # انتظار إضافي لتحميل المحتوى
        final_url = driver.current_url
        print(f"🌐 الرابط النهائي: {final_url}")
        
        # الخطوة 2: إضافة ?do=watch والذهاب إلى صفحة المشاهدة
        if not final_url.endswith('/'):
            final_url += '/'
        watch_url = final_url + '?do=watch'
        print(f"📺 جاري تحميل صفحة المشاهدة: {watch_url}")
        driver.get(watch_url)
        
        # انتظار تحميل iframe
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "iframe"))
        )
        time.sleep(2)  # انتظار إضافي للتأكد
        
        # الحصول على HTML الكامل بعد تحميل JavaScript
        page_html = driver.page_source
        return driver, watch_url, page_html  # نعيد driver أيضاً لاستخدامه لاحقاً
        
    except Exception as e:
        print(f"❌ خطأ في Selenium: {e}")
        driver.quit()
        return None, None, None

def extract_iframe_url_from_html(html):
    """استخراج رابط iframe من HTML"""
    soup = BeautifulSoup(html, 'html.parser')
    iframe = soup.find('iframe')
    if iframe and iframe.get('src'):
        iframe_url = iframe['src']
        if iframe_url.startswith('//'):
            iframe_url = 'https:' + iframe_url
        elif iframe_url.startswith('/'):
            iframe_url = 'https://z.3seq.cam' + iframe_url
        return iframe_url
    return None

def extract_video_from_iframe_with_selenium(driver, iframe_url):
    """
    استخدام نفس جلسة المتصفح لفتح iframe واستخراج رابط الفيديو الحقيقي (.m3u8)
    """
    try:
        print(f"🔄 فتح iframe: {iframe_url}")
        driver.get(iframe_url)
        
        # انتظار تحميل عنصر الفيديو أو مصدره
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "video"))
        )
        time.sleep(3)  # انتظار تحميل الفيديو
        
        # البحث عن مصدر الفيديو
        video_element = driver.find_element(By.TAG_NAME, "video")
        video_src = video_element.get_attribute("src")
        
        if video_src and video_src.startswith("http"):
            print(f"✅ تم العثور على مصدر الفيديو: {video_src[:100]}...")
            return video_src
        
        # إذا لم يجد src مباشرة، ابحث عن عناصر source داخل video
        source_elements = driver.find_elements(By.TAG_NAME, "source")
        for source in source_elements:
            src = source.get_attribute("src")
            if src and src.startswith("http"):
                print(f"✅ تم العثور على مصدر بديل: {src[:100]}...")
                return src
        
        # إذا لم نجد، نحاول استخراج من أداء الشبكة (قد لا يعمل في headless)
        print("⚠️ لم يتم العثور على مصدر الفيديو، قد يكون محمياً.")
        return None
        
    except Exception as e:
        print(f"❌ خطأ في استخراج الفيديو من iframe: {e}")
        return None

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

async def process_episode(episode_num, series_name, series_name_arabic, season_num, download_dir):
    """
    معالجة حلقة واحدة باستخدام Selenium بالكامل:
    1. الحصول على الرابط النهائي ومحتوى HTML لصفحة المشاهدة
    2. استخراج iframe
    3. استخدام نفس جلسة المتصفح لفتح iframe واستخراج رابط الفيديو
    4. تنزيل وضغط ورفع
    """
    base_url = f"https://z.3seq.cam/video/modablaj-{series_name}-episode-s{season_num:02d}e{episode_num:02d}"
    
    print(f"\n🎬 Episode {episode_num:02d}")
    print(f"🔗 Base URL: {base_url}")
    
    temp_file = os.path.join(download_dir, f"temp_{episode_num:02d}.mp4")
    final_file = os.path.join(download_dir, f"final_{episode_num:02d}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_{episode_num:02d}.jpg")

    # 1. استخدام Selenium للحصول على الرابط النهائي وHTML مع الاحتفاظ بالـ driver
    driver, watch_url, page_html = get_episode_page_with_selenium(base_url)
    if not driver or not watch_url or not page_html:
        return False, "فشل تحميل الصفحة عبر Selenium"
    
    print(f"📺 Watch URL: {watch_url}")
    
    # 2. استخراج iframe
    iframe_url = extract_iframe_url_from_html(page_html)
    if not iframe_url:
        driver.quit()
        return False, "لم يتم العثور على iframe في الصفحة"
    
    print(f"📦 تم العثور على iframe: {iframe_url}")
    
    # 3. استخدام نفس driver لفتح iframe واستخراج رابط الفيديو
    video_url = extract_video_from_iframe_with_selenium(driver, iframe_url)
    driver.quit()  # نغلق المتصفح بعد الانتهاء
    
    if not video_url:
        return False, "فشل استخراج رابط الفيديو من iframe"
    
    print(f"🎥 Video URL: {video_url}")
    
    # 4. تنزيل الفيديو باستخدام yt-dlp مع referer المناسب
    # نستخدم iframe_url كـ referer
    if not download_video(video_url, temp_file, referer=iframe_url):
        return False, "فشل التنزيل"
    
    # 5. ضغط الفيديو
    if not compress_to_240p(temp_file, final_file):
        shutil.copy2(temp_file, final_file)
    
    # 6. إنشاء صورة مصغرة
    create_thumbnail(final_file, thumb_file)
    
    # 7. رفع إلى تليغرام
    caption = f"{series_name_arabic} الموسم {season_num} الحلقة {episode_num}"
    success = await upload_video(final_file, caption, thumb_file if os.path.exists(thumb_file) else None)
    
    # 8. تنظيف
    for f in [temp_file, final_file, thumb_file]:
        try:
            if os.path.exists(f):
                os.remove(f)
        except:
            pass
    
    return success, "تم بنجاح" if success else "فشل الرفع"

async def main():
    print("="*50)
    print("🎬 معالج الفيديو المتكامل باستخدام Selenium (استخراج من iframe)")
    print("="*50)

    # التحقق من ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg موجود")
    except:
        print("❌ ffmpeg غير موجود")
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

    series_name = config.get("series_name", "").strip().replace(' ', '-')
    series_name_arabic = config.get("series_name_arabic", "").strip()
    season_num = int(config.get("season_num", 1))
    start_ep = int(config.get("start_episode", 1))
    end_ep = int(config.get("end_episode", 1))

    # تقليل العدد للحماية
    if end_ep - start_ep + 1 > 10:
        print("⚠️ عدد الحلقات كبير جداً، سيتم معالجة 10 حلقات فقط.")
        end_ep = start_ep + 9

    print(f"📺 المسلسل: {series_name_arabic}")
    print(f"🎬 الحلقات: {start_ep} إلى {end_ep}")

    download_dir = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(download_dir, exist_ok=True)

    successful = 0
    failed = []

    for ep in range(start_ep, end_ep + 1):
        success, msg = await process_episode(ep, series_name, series_name_arabic, season_num, download_dir)
        if success:
            successful += 1
            print(f"✅ الحلقة {ep} اكتملت")
        else:
            failed.append(ep)
            print(f"❌ الحلقة {ep}: {msg}")

        # انتظار عشوائي
        wait_time = random.randint(30, 45)
        print(f"⏳ انتظار {wait_time} ثانية...")
        await asyncio.sleep(wait_time)

    print(f"\n✅ الناجحة: {successful}/{len(range(start_ep, end_ep+1))}")
    if failed:
        print(f"❌ الفاشلة: {failed}")

    # تنظيف
    try:
        os.rmdir(download_dir)
    except:
        pass

    await app.stop()
    print("🔌 تم قطع الاتصال بتليغرام")

if __name__ == "__main__":
    asyncio.run(main())
