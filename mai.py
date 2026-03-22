#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - معالج متكامل باستخدام Selenium لاستخراج الفيديو من larozaa.xyz
يدعم معالجة عدة حلقات من ملف الإعدادات (نطاق + video_ids)
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
from selenium.webdriver.common.by import By

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

def try_extract_video_from_embed(driver, embed_url):
    """محاولة استخراج رابط فيديو مباشر من صفحة embed"""
    try:
        print(f"🔄 فتح embed: {embed_url}")
        driver.get(embed_url)
        time.sleep(5)
        
        # البحث عن عنصر <video>
        try:
            video = driver.find_element(By.TAG_NAME, "video")
            src = video.get_attribute("src")
            if src and src.startswith("http"):
                print(f"✅ تم العثور على فيديو في <video>: {src[:100]}...")
                return src
        except:
            pass
        
        # البحث عن عنصر <source>
        try:
            sources = driver.find_elements(By.TAG_NAME, "source")
            for src_elem in sources:
                src = src_elem.get_attribute("src")
                if src and src.startswith("http"):
                    print(f"✅ تم العثور على فيديو في <source>: {src[:100]}...")
                    return src
        except:
            pass
        
        # البحث عن أي رابط .mp4 أو .m3u8 في الصفحة
        page_source = driver.page_source
        mp4_matches = re.findall(r'(https?://[^"\']+\.mp4[^"\']*)', page_source)
        if mp4_matches:
            print(f"✅ تم العثور على رابط mp4: {mp4_matches[0][:100]}...")
            return mp4_matches[0]
        
        m3u8_matches = re.findall(r'(https?://[^"\']+\.m3u8[^"\']*)', page_source)
        if m3u8_matches:
            print(f"✅ تم العثور على رابط m3u8: {m3u8_matches[0][:100]}...")
            return m3u8_matches[0]
        
        print("⚠️ لم يتم العثور على رابط مباشر.")
        return None
    except Exception as e:
        print(f"❌ خطأ في استخراج الفيديو من embed: {e}")
        return None

def download_with_ytdlp(url, output_path, referer=None):
    """محاولة تنزيل فيديو باستخدام yt-dlp مع impersonate"""
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
            }
        }
        if referer:
            ydl_opts['http_headers']['Referer'] = referer
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return os.path.exists(output_path)
    except Exception as e:
        print(f"❌ yt-dlp error: {e}")
        return False

def get_embed_urls_from_larozaa(driver, video_page_url):
    """استخراج جميع عناوين embed من صفحة larozaa"""
    try:
        print(f"🖥️ فتح صفحة الفيديو: {video_page_url}")
        driver.get(video_page_url)
        time.sleep(5)
        
        servers = driver.find_elements(By.CSS_SELECTOR, "ul.WatchList li")
        if not servers:
            print("❌ لم يتم العثور على قائمة السيرفرات")
            return []
        
        embed_urls = []
        for li in servers:
            embed = li.get_attribute("data-embed-url")
            if embed:
                embed_urls.append(embed)
        print(f"📦 تم العثور على {len(embed_urls)} سيرفر")
        return embed_urls
    except Exception as e:
        print(f"❌ خطأ في استخراج السيرفرات: {e}")
        return []

def download_video_from_servers(embed_urls, output_path, driver):
    """تجربة السيرفرات حتى نجاح التنزيل"""
    for idx, embed_url in enumerate(embed_urls):
        print(f"\n🔄 تجربة السيرفر {idx+1}: {embed_url}")
        
        # محاولة استخراج رابط مباشر
        direct_url = try_extract_video_from_embed(driver, embed_url)
        if direct_url:
            print(f"✅ تم استخراج رابط مباشر، محاولة التنزيل...")
            if download_with_ytdlp(direct_url, output_path, referer=embed_url):
                return True
            else:
                print(f"⚠️ فشل التنزيل من الرابط المباشر.")
        else:
            print(f"⚠️ لم يتم العثور على رابط مباشر، محاولة تنزيل embed_url مباشرة...")
            if download_with_ytdlp(embed_url, output_path, referer=embed_url):
                return True
            else:
                print(f"⚠️ فشل تنزيل embed_url مباشرة.")
        
        # تأخير قبل المحاولة التالية
        time.sleep(3)
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

async def process_video(episode_num, video_url, series_name_arabic, season_num, download_dir):
    """معالجة حلقة واحدة"""
    print(f"\n🎬 Processing episode {episode_num}")
    print(f"🔗 Video page URL: {video_url}")
    
    temp_file = os.path.join(download_dir, f"temp_{episode_num:02d}.mp4")
    final_file = os.path.join(download_dir, f"final_{episode_num:02d}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_{episode_num:02d}.jpg")

    # إعداد Selenium
    driver = setup_selenium()
    if not driver:
        return False, "فشل إعداد Selenium"
    
    # استخراج قائمة السيرفرات
    embed_urls = get_embed_urls_from_larozaa(driver, video_url)
    if not embed_urls:
        driver.quit()
        return False, "لم يتم العثور على سيرفرات"
    
    # محاولة التنزيل من السيرفرات
    download_success = download_video_from_servers(embed_urls, temp_file, driver)
    driver.quit()
    
    if not download_success:
        return False, "فشل التنزيل من جميع السيرفرات"
    
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
    
    # استخراج قائمة الحلقات
    episodes = []
    
    # 1. إذا كانت هناك قائمة `episodes` جاهزة
    if "episodes" in config and config["episodes"]:
        episodes = config["episodes"]
    # 2. إذا كانت هناك `start_episode`, `end_episode` و `video_ids`
    elif "start_episode" in config and "end_episode" in config and "video_ids" in config:
        start = int(config["start_episode"])
        end = int(config["end_episode"])
        video_ids = config["video_ids"]
        expected_count = end - start + 1
        if len(video_ids) != expected_count:
            print(f"❌ عدد video_ids ({len(video_ids)}) لا يتطابق مع عدد الحلقات ({expected_count})")
            return
        # بناء قائمة الحلقات
        for idx, vid in enumerate(video_ids):
            ep_num = start + idx
            url = f"https://larozaa.xyz/play.php?vid={vid}"
            episodes.append({"num": ep_num, "url": url})
    # 3. دعم الحلقة الواحدة القديمة
    elif "video_url" in config:
        ep_num = config.get("episode_num", 1)
        episodes = [{"num": ep_num, "url": config["video_url"]}]
    else:
        print("❌ لم يتم العثور على بيانات الحلقات في config (episodes أو start_episode+video_ids أو video_url)")
        return

    if not episodes:
        print("❌ قائمة الحلقات فارغة")
        return

    print(f"📺 المسلسل: {series_name_arabic}")
    print(f"🎬 عدد الحلقات المطلوب معالجتها: {len(episodes)}")

    download_dir = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(download_dir, exist_ok=True)

    successful = 0
    failed = []

    for idx, ep in enumerate(episodes):
        ep_num = ep.get("num")
        ep_url = ep.get("url")
        if not ep_num or not ep_url:
            print(f"⚠️ تخطي حلقة غير مكتملة البيانات: {ep}")
            continue

        print(f"\n--- معالجة الحلقة {ep_num} ---")
        success, msg = await process_video(ep_num, ep_url, series_name_arabic, season_num, download_dir)
        if success:
            successful += 1
            print(f"✅ الحلقة {ep_num} اكتملت بنجاح")
        else:
            failed.append(ep_num)
            print(f"❌ الحلقة {ep_num} فشلت: {msg}")

        # انتظار عشوائي بين الحلقات
        if idx < len(episodes) - 1:
            wait_time = random.randint(30, 60)
            print(f"⏳ انتظار {wait_time} ثانية قبل الحلقة التالية...")
            await asyncio.sleep(wait_time)

    print(f"\n✅ الحلقات الناجحة: {successful}/{len(episodes)}")
    if failed:
        print(f"❌ الحلقات الفاشلة: {failed}")

    # تنظيف
    try:
        os.rmdir(download_dir)
    except:
        pass

    await app.stop()
    print("🔌 تم قطع الاتصال بتليغرام")

if __name__ == "__main__":
    asyncio.run(main())
