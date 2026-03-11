#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - معالج متكامل باستخدام Selenium لاستخراج الفيديو من w.eseeq.online
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
import base64
from datetime import datetime
from urllib.parse import urlparse

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
    """استخراج رابط src من كود iframe"""
    match = re.search(r'src=["\'](https?://[^"\']+)["\']', iframe_html)
    if match:
        return match.group(1)
    return None

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

def extract_video_from_uqload_page(driver, url):
    """فتح صفحة Uqload واستخراج رابط الفيديو المباشر"""
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

def decode_base64_url(encoded):
    """محاولة فك تشفير base64 في الرابط"""
    try:
        match = re.search(r'([A-Za-z0-9+/=]{20,})', encoded)
        if match:
            decoded = base64.b64decode(match.group(1)).decode('utf-8')
            print(f"🔓 تم فك تشفير base64: {decoded[:100]}...")
            return decoded
    except:
        pass
    return None

# ===== دالة استخراج الفيديو من w.eseeq.online (معدلة) =====
def get_video_from_eseeq(base_url):
    driver = setup_selenium()
    if not driver:
        return None, None

    try:
        print(f"🖥️ فتح صفحة الحلقة: {base_url}")
        driver.get(base_url)
        time.sleep(5)

        # انتظار ظهور زر التشغيل (play-video)
        try:
            play_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "play-video"))
            )
            print("✅ تم العثور على زر التشغيل.")
        except Exception as e:
            print(f"❌ لم يتم العثور على زر التشغيل: {e}")
            return None, None

        # حفظ النافذة الحالية
        main_window = driver.current_window_handle

        # النقر على الرابط (يفتح في نافذة جديدة)
        play_button.click()

        # انتظار حتى يتم فتح نافذة جديدة
        WebDriverWait(driver, 15).until(EC.number_of_windows_to_be(2))

        # التبديل إلى النافذة الجديدة
        new_window = [window for window in driver.window_handles if window != main_window][0]
        driver.switch_to.window(new_window)
        print(f"🔄 تم التبديل إلى النافذة الجديدة: {driver.current_url}")

        # انتظار تحميل الصفحة
        time.sleep(10)

        # الآن نبحث عن iframe المشغل
        video_url = None

        # البحث عن iframe الذي يحتوي على v.rmd.quest أو albaplayer
        try:
            iframe = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'v.rmd.quest') or contains(@src, 'albaplayer')]"))
            )
            src = iframe.get_attribute("src")
            if src:
                print(f"📦 تم العثور على iframe المناسب: {src}")
                video_url = src
        except:
            print("⚠️ لم يتم العثور على iframe يحتوي على 'v.rmd.quest' أو 'albaplayer'.")

        # إذا لم نجد، نبحث عن iframe بالمعرف srcFrame (كما في المثال)
        if not video_url:
            try:
                iframe = driver.find_element(By.ID, "srcFrame")
                src = iframe.get_attribute("src")
                if src:
                    print(f"📦 تم العثور على iframe بالمعرف 'srcFrame': {src}")
                    video_url = src
            except:
                pass

        # إذا لم نجد، نبحث في مصدر الصفحة
        if not video_url:
            page_source = driver.page_source
            match = re.search(r'<iframe[^>]+src=["\'](https?://[^"\']+v\.rmd\.quest[^"\']+)["\']', page_source)
            if match:
                video_url = match.group(1)
                print(f"🔍 تم استخراج رابط iframe من HTML: {video_url}")
            else:
                match = re.search(r'<iframe[^>]+src=["\'](https?://[^"\']+albaplayer[^"\']+)["\']', page_source)
                if match:
                    video_url = match.group(1)
                    print(f"🔍 تم استخراج رابط iframe من HTML: {video_url}")

        if video_url:
            # اختبر إذا كان الرابط يعمل مع yt-dlp
            if test_video_url(video_url):
                print(f"✅ الرابط يعمل وسيتم استخدامه.")
                referer = driver.current_url
                return video_url, referer
            else:
                print(f"⚠️ الرابط لا يعمل مباشرة، قد نحتاج إلى استخراج الفيديو من صفحة المشغل.")
                # قد نحتاج إلى فتح صفحة المشغل نفسها (مثل v.rmd.quest) واستخراج iframe داخلي
                if 'v.rmd.quest' in video_url or 'albaplayer' in video_url:
                    print(f"🔄 محاولة استخراج الفيديو من صفحة المشغل: {video_url}")
                    driver.get(video_url)
                    time.sleep(10)
                    # البحث عن iframe داخل هذه الصفحة (قد يكون uqload)
                    iframes_inner = driver.find_elements(By.TAG_NAME, "iframe")
                    for iframe_inner in iframes_inner:
                        src_inner = iframe_inner.get_attribute("src")
                        if src_inner and 'uqload' in src_inner:
                            uqload_video = extract_video_from_uqload_page(driver, src_inner)
                            if uqload_video:
                                referer = driver.current_url
                                return uqload_video, referer
                    # إذا لم نجد uqload، نحاول اختبار الرابط الأصلي مرة أخرى
                    if test_video_url(video_url):
                        return video_url, driver.current_url
                referer = driver.current_url
                return video_url, referer
        else:
            print("❌ فشل البحث: لم يتم العثور على أي رابط iframe.")
            # حفظ مصدر الصفحة للتشخيص
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("💾 تم حفظ مصدر الصفحة في debug_page.html للمساعدة في التشخيص.")
            return None, None

    except Exception as e:
        print(f"❌ خطأ رئيسي في استخراج الفيديو: {e}")
        return None, None
    finally:
        driver.quit()

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
    معالجة حلقة واحدة من w.eseeq.online
    """
    # بناء رابط الحلقة حسب النمط الصحيح للموقع الجديد
    # مثال: https://w.eseeq.online/video/ein-sehreya-1/
    base_url = f"https://w.eseeq.online/video/{series_name}-{episode_num}/"
    print(f"\n🎬 Episode {episode_num}")
    print(f"🔗 Base URL: {base_url}")
    
    temp_file = os.path.join(download_dir, f"temp_{episode_num}.mp4")
    final_file = os.path.join(download_dir, f"final_{episode_num}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_{episode_num}.jpg")

    # استخراج رابط الفيديو باستخدام Selenium
    video_url, referer = get_video_from_eseeq(base_url)
    if not video_url:
        return False, "فشل استخراج رابط الفيديو"
    
    # تنزيل الفيديو
    if not download_video(video_url, temp_file, referer=referer):
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
    print("🎬 معالج الفيديو المتكامل باستخدام Selenium (w.eseeq.online)")
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

    series_name = config.get("series_name", "").strip()  # مثل "ein-sehreya"
    series_name_arabic = config.get("series_name_arabic", "").strip()
    season_num = int(config.get("season_num", 1))
    start_ep = int(config.get("start_episode", 1))
    end_ep = int(config.get("end_episode", 1))

    if not series_name:
        print("❌ series_name مفقود في config")
        return

    # تقليل العدد للحماية
    if end_ep - start_ep + 1 > 25:
        print("⚠️ عدد الحلقات كبير جداً، سيتم معالجة 25 حلقه فقط.")
        end_ep = start_ep + 24

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
