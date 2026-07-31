#!/usr/bin/env python3
"""
تنزيل وضغط فيديو من lodynet.watch (بدون رفع تليجرام)
مع دعم كامل للغة العربية وترميز UTF-8
"""

import os
import sys
import time
import json
import subprocess
import shutil
import random
import re
from datetime import datetime
from urllib.parse import quote

# ===== تعيين ترميز الإخراج إلى UTF-8 لحل مشاكل الأحرف العربية =====
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')

# ===== تثبيت المتطلبات تلقائياً (اختياري) =====
def install_requirements():
    print("📦 Installing requirements...")
    reqs = [
        "yt-dlp>=2024.4.9",
        "selenium>=4.15.0",
        "beautifulsoup4>=4.12.0",
        "webdriver-manager>=4.0.0"
    ]
    for req in reqs:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", req, "--quiet"])
            print(f"  ✅ {req.split('>=')[0]}")
        except:
            print(f"  ⚠️ Failed to install {req}")

# قم بتعليق السطر التالي إذا كنت تفضل التثبيت اليدوي
install_requirements()

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import yt_dlp

# ===== إعداد Selenium باستخدام webdriver-manager =====
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
    
    try:
        # التحميل التلقائي لـ ChromeDriver المناسب لإصدار Chrome المثبت
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return driver
    except Exception as e:
        print(f"❌ فشل إعداد Selenium: {e}")
        return None

# ===== استخراج الفيديو من صفحة uqload (دالة مساعدة) =====
def extract_video_from_uqload_page(driver, url):
    """فتح صفحة Uqload واستخراج رابط الفيديو المباشر."""
    try:
        if 'uqload.to' in url:
            url = url.replace('uqload.to', 'uqload.is')
        print(f"🔄 فتح صفحة Uqload: {url}")
        driver.get(url)
        time.sleep(5)
        page_source = driver.page_source
        # البحث عن sources
        match = re.search(r'sources:\s*\[\s*"([^"]+\.mp4[^"]*)"\s*\]', page_source)
        if match:
            return match.group(1)
        match = re.search(r'(https?://[^"\']+\.mp4[^"\']*)', page_source)
        if match:
            return match.group(1)
        return None
    except Exception as e:
        print(f"❌ خطأ في uqload: {e}")
        return None

# ===== استخراج الفيديو من صفحة lodynet.watch =====
def extract_video_from_lodynet_page(driver, url):
    """فتح صفحة الحلقة واستخراج رابط الفيديو المباشر."""
    try:
        print(f"🔄 فتح صفحة lodynet: {url}")
        driver.get(url)
        time.sleep(5)  # انتظار تحميل الصفحة

        # 1. البحث عن عنصر video مباشر
        try:
            video_elem = driver.find_element(By.TAG_NAME, "video")
            src = video_elem.get_attribute("src")
            if src and src.startswith("http"):
                print(f"✅ تم العثور على فيديو مباشر: {src[:100]}...")
                return src
        except:
            pass

        # 2. البحث عن iframe يحتوي على مشغل فيديو
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            src = iframe.get_attribute("src")
            if src and ("uqload" in src or "ok.ru" in src or "vid" in src or "embed" in src):
                print(f"🔍 تم العثور على iframe: {src}")
                # فتح iframe في نفس المتصفح
                driver.get(src)
                time.sleep(5)
                # محاولة استخراج الفيديو من صفحة iframe
                page_source = driver.page_source
                # البحث عن رابط mp4
                match = re.search(r'(https?://[^"\']+\.mp4[^"\']*)', page_source)
                if match:
                    video_url = match.group(1)
                    print(f"✅ تم استخراج رابط mp4 من iframe: {video_url[:100]}...")
                    return video_url
                # البحث عن sources في JavaScript
                match = re.search(r'sources:\s*\[\s*"([^"]+\.mp4[^"]*)"\s*\]', page_source)
                if match:
                    video_url = match.group(1)
                    print(f"✅ تم استخراج رابط من sources: {video_url[:100]}...")
                    return video_url
                # إذا كان iframe من uqload، استخدم الدالة الخاصة
                if "uqload" in src:
                    return extract_video_from_uqload_page(driver, src)

        # 3. البحث عن أي رابط فيديو في الصفحة
        page_source = driver.page_source
        match = re.search(r'(https?://[^"\']+\.mp4[^"\']*)', page_source)
        if match:
            video_url = match.group(1)
            print(f"✅ تم العثور على رابط mp4 في الصفحة: {video_url[:100]}...")
            return video_url

        # 4. محاولة استخدام yt-dlp على الصفحة (كحل أخير)
        print("🔄 محاولة استخراج الرابط عبر yt-dlp...")
        try:
            # استخدام عنوان URL مشفر لتجنب مشاكل الترميز
            encoded_url = quote(url, safe=':/')
            ydl_opts = {'quiet': True, 'extract_flat': True, 'encoding': 'utf-8'}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(encoded_url, download=False)
                if info and 'url' in info:
                    return info['url']
                elif info and 'entries' in info and len(info['entries']) > 0:
                    return info['entries'][0]['url']
        except Exception as e:
            print(f"⚠️ فشل yt-dlp في استخراج الرابط: {e}")

        print("❌ لم يتم العثور على أي رابط فيديو.")
        return None

    except Exception as e:
        print(f"❌ خطأ في استخراج الفيديو: {e}")
        return None

# ===== دالة رئيسية لاستخراج الرابط =====
def get_video_url(page_url, use_ytdlp_direct=False):
    """تحاول استخراج رابط الفيديو من صفحة الحلقة."""
    # محاولة استخدام yt-dlp مباشرة (إذا كان مفعلاً)
    if use_ytdlp_direct:
        try:
            # استخدام عنوان URL مشفر
            encoded_url = quote(page_url, safe=':/')
            ydl_opts = {'quiet': True, 'extract_flat': True, 'encoding': 'utf-8'}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(encoded_url, download=False)
                if info and 'url' in info:
                    print(f"✅ تم الحصول على الرابط عبر yt-dlp مباشرة.")
                    return info['url'], page_url
                elif info and 'entries' in info and len(info['entries']) > 0:
                    return info['entries'][0]['url'], page_url
        except Exception as e:
            print(f"⚠️ فشل yt-dlp المباشر: {e}")

    driver = setup_selenium()
    if not driver:
        return None, None
    try:
        video_url = extract_video_from_lodynet_page(driver, page_url)
        if video_url:
            return video_url, page_url
        else:
            return None, None
    finally:
        driver.quit()

# ===== دوال التحميل والضغط =====
def download_video(video_url, output_path, referer):
    """تنزيل الفيديو باستخدام yt-dlp مع إضافة referer."""
    try:
        ydl_opts = {
            'format': 'best[height<=720]/best',
            'outtmpl': output_path,
            'quiet': False,
            'retries': 5,
            'fragment_retries': 5,
            'socket_timeout': 30,
            'extractor_args': {'generic': 'impersonate'},
            'encoding': 'utf-8',  # تحديد الترميز
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': referer,
                'Accept-Language': 'ar-SA,ar;q=0.9,en;q=0.8',  # إضافة تفضيل اللغة العربية
            }
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        return os.path.exists(output_path)
    except Exception as e:
        print(f"❌ Download error: {e}")
        return False

def compress_to_240p(input_path, output_path):
    """ضغط الفيديو إلى دقة 240p باستخدام ffmpeg."""
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
    """إنشاء صورة مصغرة من الفيديو (اختياري)."""
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

# ===== معالجة حلقة واحدة =====
def process_episode(episode_num, series_name_arabic, download_dir, config):
    """تحميل وضغط حلقة واحدة وحفظها محلياً."""
    domain = config.get("domain", "lodynet.watch")
    custom_url = config.get("custom_url")
    use_ytdlp_direct = config.get("use_ytdlp_direct", False)
    
    if custom_url:
        page_url = custom_url
    else:
        # بناء الرابط: https://lodynet.watch/مسلسل-إشراقة-السحر-مترجم-حلقة-126
        page_url = f"https://{domain}/{series_name_arabic}-حلقة-{episode_num}"
    
    print(f"\n🎬 Episode {episode_num}")
    print(f"🔗 Page URL: {page_url}")

    # استخراج رابط الفيديو
    video_url, referer = get_video_url(page_url, use_ytdlp_direct)
    if not video_url:
        return False, "فشل استخراج رابط الفيديو"

    # تحميل
    temp_file = os.path.join(download_dir, f"temp_{episode_num}.mp4")
    if not download_video(video_url, temp_file, referer):
        return False, "فشل التنزيل"

    # ضغط
    final_file = os.path.join(download_dir, f"{series_name_arabic}_e{episode_num:02d}_240p.mp4")
    if not compress_to_240p(temp_file, final_file):
        shutil.copy2(temp_file, final_file)
        print("⚠️ فشل الضغط، تم حفظ الملف الأصلي.")

    # إنشاء صورة مصغرة (اختياري)
    thumb_file = os.path.join(download_dir, f"thumb_{episode_num}.jpg")
    create_thumbnail(final_file, thumb_file)

    # تنظيف الملف المؤقت
    try:
        os.remove(temp_file)
    except:
        pass

    print(f"✅ تم حفظ الفيديو المضغوط في: {final_file}")
    return True, "تم بنجاح"

# ===== الدالة الرئيسية =====
def main():
    print("="*50)
    print("🎬 تنزيل وضغط فيديو من lodynet.watch")
    print("="*50)

    # التحقق من ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg موجود")
    except:
        print("❌ ffmpeg غير موجود. يرجى تثبيته.")
        return

    # قراءة الإعدادات
    config_file = "series_config.json"
    if not os.path.exists(config_file):
        print("❌ series_config.json غير موجود")
        return

    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)

    series_name_arabic = config.get("series_name_arabic", "").strip()
    if not series_name_arabic and not config.get("custom_url"):
        print("❌ يجب تحديد series_name_arabic أو custom_url في config")
        return

    start_ep = int(config.get("start_episode", 1))
    end_ep = int(config.get("end_episode", 1))

    # حماية من عدد كبير جداً
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
        success, msg = process_episode(ep, series_name_arabic, download_dir, config)
        if success:
            successful += 1
            print(f"✅ الحلقة {ep} اكتملت")
        else:
            failed.append(ep)
            print(f"❌ الحلقة {ep}: {msg}")

        # انتظار عشوائي بين الحلقات لتجنب الحظر
        wait_time = random.randint(30, 45)
        print(f"⏳ انتظار {wait_time} ثانية...")
        time.sleep(wait_time)

    print(f"\n✅ الناجحة: {successful}/{len(range(start_ep, end_ep+1))}")
    if failed:
        print(f"❌ الفاشلة: {failed}")
    print(f"📂 الملفات المحفوظة في: {download_dir}")

if __name__ == "__main__":
    main()
