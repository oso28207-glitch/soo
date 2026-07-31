#!/usr/bin/env python3
"""
تنزيل وضغط فيديو من lodynet.watch/top
استخراج روابط السيرفرات من كود JavaScript في الصفحة مباشرة.
"""

import os
import sys
import time
import json
import subprocess
import shutil
import random
import re
import base64
from datetime import datetime
from urllib.parse import urlparse, quote

# ===== تثبيت المتطلبات =====
def install_requirements():
    print("📦 Installing requirements...")
    reqs = [
        "yt-dlp>=2024.4.9",
        "selenium>=4.15.0",
        "beautifulsoup4>=4.12.0",
        "webdriver-manager>=4.0.0",
        "requests>=2.28.0"
    ]
    for req in reqs:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", req, "--quiet"])
            print(f"  ✅ {req.split('>=')[0]}")
        except:
            print(f"  ⚠️ Failed to install {req}")

install_requirements()

import requests
from bs4 import BeautifulSoup
import yt_dlp
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ===== إعداد Selenium (كحل احتياطي) =====
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
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return driver
    except Exception as e:
        print(f"❌ فشل إعداد Selenium: {e}")
        return None

# ===== استخراج PostData من HTML (مُحسّن) =====
def extract_post_data(html):
    """استخراج كائن PostData من كود JavaScript في الصفحة."""
    # البحث عن بداية الكائن
    start_match = re.search(r'PostData\s*=\s*\{', html)
    if not start_match:
        return None
    
    start_index = start_match.start()
    # البحث عن نهاية الكائن
    brace_count = 0
    end_index = start_index
    in_string = False
    escape = False
    
    for i in range(start_index, len(html)):
        char = html[i]
        
        if escape:
            escape = False
            continue
        
        if char == '\\' and in_string:
            escape = True
            continue
        
        if char == '"' and not escape:
            in_string = not in_string
            continue
        
        if not in_string:
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_index = i + 1
                    break
    
    if brace_count != 0:
        return None
    
    # استخراج النص بين البداية والنهاية
    post_data_str = html[start_index:end_index]
    
    # إزالة الفواصل الزائدة (Trailing commas) التي قد تسبب مشكلة في JSON
    post_data_str = re.sub(r',\s*}', '}', post_data_str)
    post_data_str = re.sub(r',\s*]', ']', post_data_str)
    
    # استخراج الجزء الخاص بـ ServersWatch
    try:
        # محاولة تحويل النص إلى JSON
        data = json.loads(post_data_str.replace('PostData = ', ''))
        return data
    except json.JSONDecodeError as e:
        print(f"⚠️ فشل تحويل PostData إلى JSON: {e}")
        # حفظ الصفحة للتشخيص
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("💾 تم حفظ الصفحة في debug_page.html للمساعدة في التشخيص.")
        return None

def get_page_html(url):
    """الحصول على HTML الصفحة باستخدام requests."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'ar-SA,ar;q=0.9,en;q=0.8',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.encoding = 'utf-8'
        return resp.text
    except Exception as e:
        print(f"❌ فشل تحميل الصفحة: {e}")
        return None

# ===== فك تشفير Embed =====
def decode_embed(embed_str):
    """فك تشفير Embed إذا كان مشفراً (base64)."""
    if not embed_str:
        return None
    try:
        decoded = base64.b64decode(embed_str).decode('utf-8')
        if decoded.startswith('http'):
            return decoded
    except:
        pass
    return embed_str

# ===== استخراج قائمة روابط السيرفرات =====
def extract_server_urls(post_data):
    """استخراج روابط المشغل من PostData."""
    servers = post_data.get('ServersWatch', [])
    urls = []
    for server in servers:
        embed = server.get('Embed')
        if embed:
            decoded = decode_embed(embed)
            if decoded:
                urls.append(decoded)
    return urls

# ===== محاولة تنزيل الفيديو من رابط السيرفر =====
def download_video_from_server(server_url, output_path, referer):
    """محاولة تنزيل الفيديو من رابط السيرفر باستخدام yt-dlp."""
    try:
        ydl_opts = {
            'format': 'best[height<=720]/best',
            'outtmpl': output_path,
            'quiet': False,
            'retries': 5,
            'fragment_retries': 5,
            'socket_timeout': 30,
            'extractor_args': {'generic': 'impersonate'},
            'encoding': 'utf-8',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': referer,
                'Accept-Language': 'ar-SA,ar;q=0.9,en;q=0.8',
            }
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([server_url])
        return os.path.exists(output_path)
    except Exception as e:
        print(f"⚠️ فشل التحميل من {server_url}: {e}")
        return False

# ===== حل احتياطي: استخدام Selenium لاستخراج الفيديو من صفحة السيرفر =====
def extract_video_with_selenium(server_url, referer):
    """فتح صفحة السيرفر باستخدام Selenium واستخراج رابط الفيديو المباشر."""
    driver = setup_selenium()
    if not driver:
        return None
    try:
        print(f"🔄 فتح صفحة السيرفر باستخدام Selenium: {server_url}")
        driver.get(server_url)
        time.sleep(5)  # انتظار تحميل الصفحة
        page_source = driver.page_source
        
        # البحث عن رابط mp4
        match = re.search(r'(https?://[^"\']+\.mp4[^"\']*)', page_source)
        if match:
            video_url = match.group(1)
            print(f"✅ تم استخراج رابط mp4: {video_url[:100]}...")
            return video_url
        
        # البحث عن sources في JavaScript
        match = re.search(r'sources:\s*\[\s*"([^"]+\.mp4[^"]*)"\s*\]', page_source)
        if match:
            video_url = match.group(1)
            print(f"✅ تم استخراج رابط من sources: {video_url[:100]}...")
            return video_url
        
        print("❌ لم يتم العثور على رابط فيديو في صفحة السيرفر.")
        return None
    except Exception as e:
        print(f"❌ خطأ في Selenium: {e}")
        return None
    finally:
        driver.quit()

# ===== دالة التحميل الرئيسية =====
def download_episode(episode_num, series_name_arabic, download_dir, config):
    """تحميل حلقة واحدة باستخدام السيرفرات المستخرجة."""
    domain = config.get("domain", "lodynet.watch")
    # محاولة استخدام النطاقين: lodynet.watch أو lodynet.top
    page_url = f"https://{domain}/{series_name_arabic}-حلقة-{episode_num}"
    
    print(f"\n🎬 Episode {episode_num}")
    print(f"🔗 Page URL: {page_url}")

    # 1. الحصول على HTML الصفحة
    html = get_page_html(page_url)
    if not html:
        # محاولة النطاق البديل
        if 'lodynet.watch' in domain:
            alt_domain = 'lodynet.top'
        else:
            alt_domain = 'lodynet.watch'
        alt_url = f"https://{alt_domain}/{series_name_arabic}-حلقة-{episode_num}"
        print(f"🔄 محاولة النطاق البديل: {alt_url}")
        html = get_page_html(alt_url)
        if html:
            domain = alt_domain
            page_url = alt_url

    if not html:
        return False, "فشل تحميل الصفحة"

    # 2. استخراج PostData
    post_data = extract_post_data(html)
    if not post_data:
        return False, "فشل استخراج بيانات السيرفرات من الصفحة"
    
    # 3. استخراج روابط السيرفرات
    server_urls = extract_server_urls(post_data)
    if not server_urls:
        return False, "لم يتم العثور على أي سيرفر في الصفحة"
    
    print(f"🔍 تم العثور على {len(server_urls)} سيرفر.")
    
    # 4. محاولة التحميل من كل سيرفر
    temp_file = os.path.join(download_dir, f"temp_{episode_num}.mp4")
    downloaded = False
    for idx, server_url in enumerate(server_urls, 1):
        print(f"🔄 محاولة السيرفر {idx}: {server_url[:100]}...")
        
        # محاولة التحميل مباشرة باستخدام yt-dlp
        if download_video_from_server(server_url, temp_file, page_url):
            downloaded = True
            break
        
        # إذا فشل yt-dlp، نحاول Selenium لاستخراج رابط mp4 ثم التحميل
        print("🔄 محاولة استخراج الفيديو باستخدام Selenium...")
        video_url = extract_video_with_selenium(server_url, page_url)
        if video_url:
            if download_video_from_server(video_url, temp_file, page_url):
                downloaded = True
                break
    
    if not downloaded:
        return False, "فشل التحميل من جميع السيرفرات"

    # 5. ضغط الفيديو
    final_file = os.path.join(download_dir, f"{series_name_arabic}_e{episode_num:02d}_240p.mp4")
    if not compress_to_240p(temp_file, final_file):
        shutil.copy2(temp_file, final_file)
        print("⚠️ فشل الضغط، تم حفظ الملف الأصلي.")

    # تنظيف الملف المؤقت
    try:
        os.remove(temp_file)
    except:
        pass

    print(f"✅ تم حفظ الفيديو في: {final_file}")
    return True, "تم بنجاح"

# ===== دوال الضغط والصور المصغرة =====
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

# ===== الدالة الرئيسية =====
def main():
    print("="*50)
    print("🎬 تنزيل وضغط فيديو من lodynet.watch (طريقة متطورة)")
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
    if not series_name_arabic:
        print("❌ يجب تحديد series_name_arabic في config")
        return

    start_ep = int(config.get("start_episode", 1))
    end_ep = int(config.get("end_episode", 1))

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
        success, msg = download_episode(ep, series_name_arabic, download_dir, config)
        if success:
            successful += 1
            print(f"✅ الحلقة {ep} اكتملت")
        else:
            failed.append(ep)
            print(f"❌ الحلقة {ep}: {msg}")

        # انتظار عشوائي
        wait_time = random.randint(30, 45)
        print(f"⏳ انتظار {wait_time} ثانية...")
        time.sleep(wait_time)

    print(f"\n✅ الناجحة: {successful}/{len(range(start_ep, end_ep+1))}")
    if failed:
        print(f"❌ الفاشلة: {failed}")
    print(f"📂 الملفات المحفوظة في: {download_dir}")

if __name__ == "__main__":
    main()
