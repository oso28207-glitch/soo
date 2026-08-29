#!/usr/bin/env python3
"""
تنزيل وضغط فيديو من lodynet.watch/top، ثم رفعه إلى gofile.io للحصول على رابط مشاهدة مباشر.
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

# ===== تثبيت المتطلبات =====
def install_requirements():
    print("📦 Installing requirements...")
    reqs = [
        "yt-dlp>=2024.4.9",
        "selenium>=4.15.0",
        "beautifulsoup4>=4.12.0",
        "webdriver-manager>=4.0.0",
        "requests>=2.28.0",
        "json5>=0.9.0"
    ]
    for req in reqs:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", req, "--quiet"])
            print(f"  ✅ {req.split('>=')[0]}")
        except:
            print(f"  ⚠️ Failed to install {req}")

install_requirements()

import requests
import yt_dlp
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import json5

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
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return driver
    except Exception as e:
        print(f"❌ فشل إعداد Selenium: {e}")
        return None

# ===== استخراج PostData باستخدام json5 =====
def extract_post_data(html):
    start_match = re.search(r'PostData\s*=\s*\{', html)
    if not start_match:
        return None
    
    start_index = start_match.start()
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
    
    post_data_str = html[start_index:end_index]
    post_data_str = post_data_str.replace('PostData = ', '').strip()
    if post_data_str.endswith(';'):
        post_data_str = post_data_str[:-1]
    
    try:
        return json5.loads(post_data_str)
    except Exception as e:
        print(f"⚠️ فشل تحويل PostData: {e}")
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        return None

def get_page_html(url):
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

def decode_embed(embed_str):
    if not embed_str:
        return None
    try:
        decoded = base64.b64decode(embed_str).decode('utf-8')
        if decoded.startswith('http'):
            return decoded
    except:
        pass
    return embed_str

def extract_server_urls(post_data):
    servers = post_data.get('ServersWatch', [])
    urls = []
    for server in servers:
        embed = server.get('Embed')
        if embed:
            decoded = decode_embed(embed)
            if decoded:
                urls.append(decoded)
    return urls

# ===== التنزيل باستخدام requests =====
def download_with_requests(url, output_path, referer):
    """تنزيل الفيديو مباشرة باستخدام requests مع دعم التقدم."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': referer,
        'Accept-Language': 'ar-SA,ar;q=0.9,en;q=0.8',
    }
    try:
        with requests.get(url, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            block_size = 8192
            downloaded = 0
            with open(output_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=block_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            print(f"\r⏳ جاري التحميل: {percent:.1f}%", end='')
            print()
        return os.path.exists(output_path)
    except Exception as e:
        print(f"❌ فشل التنزيل عبر requests: {e}")
        return False

# ===== استخراج الفيديو المباشر باستخدام Selenium =====
def extract_direct_video_with_selenium(server_url, referer):
    driver = setup_selenium()
    if not driver:
        return None
    try:
        print(f"🔄 فتح السيرفر باستخدام Selenium: {server_url[:80]}...")
        driver.get(server_url)
        time.sleep(5)
        page_source = driver.page_source
        
        # البحث عن mp4
        match = re.search(r'(https?://[^"\']+\.mp4[^"\']*)', page_source)
        if match:
            return match.group(1)
        
        # البحث عن sources
        match = re.search(r'sources:\s*\[\s*"([^"]+\.mp4[^"]*)"\s*\]', page_source)
        if match:
            return match.group(1)
        
        # البحث عن رابط m3u8
        match = re.search(r'(https?://[^"\']+\.m3u8[^"\']*)', page_source)
        if match:
            return match.group(1)
        
        return None
    except Exception as e:
        print(f"❌ خطأ في Selenium: {e}")
        return None
    finally:
        driver.quit()

# ===== محاولة التنزيل باستخدام yt-dlp (كحل أخير) =====
def download_with_ytdlp(url, output_path, referer):
    try:
        safe_referer = re.sub(r'[^\x00-\x7F]+', '', referer) if referer else ''
        ydl_opts = {
            'format': 'best[height<=720]/best',
            'outtmpl': output_path,
            'quiet': False,
            'retries': 3,
            'fragment_retries': 3,
            'socket_timeout': 30,
            'extractor_args': {'generic': 'impersonate'},
            'encoding': 'utf-8',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': safe_referer,
                'Accept-Language': 'en-US,en;q=0.9',
            }
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return os.path.exists(output_path)
    except Exception as e:
        print(f"⚠️ فشل yt-dlp: {e}")
        return False

# ===== ضغط الفيديو =====
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

# ===== رفع الملف إلى gofile.io =====
def upload_file(file_path):
    """رفع الملف إلى gofile.io والحصول على رابط المشاهدة."""
    url = "https://api.gofile.io/uploadFile"
    try:
        with open(file_path, 'rb') as f:
            files = {'file': f}
            print("⏳ جاري رفع الملف إلى gofile.io ...")
            response = requests.post(url, files=files, timeout=120)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'ok':
                    download_page = data['data']['downloadPage']
                    print(f"✅ تم الرفع: {download_page}")
                    return download_page
                else:
                    print(f"⚠️ استجابة غير متوقعة: {data}")
                    return None
            else:
                print(f"⚠️ فشل الرفع: HTTP {response.status_code}")
                return None
    except Exception as e:
        print(f"❌ خطأ أثناء الرفع: {e}")
        return None

# ===== دالة التحميل والضغط والرفع الرئيسية =====
def download_episode(episode_num, series_name_arabic, download_dir, config):
    domain = config.get("domain", "lodynet.watch")
    page_url = f"https://{domain}/{series_name_arabic}-حلقة-{episode_num}"
    
    print(f"\n🎬 Episode {episode_num}")
    print(f"🔗 Page URL: {page_url}")

    # 1. الحصول على HTML
    html = get_page_html(page_url)
    if not html:
        alt_domain = 'lodynet.top' if 'lodynet.watch' in domain else 'lodynet.watch'
        alt_url = f"https://{alt_domain}/{series_name_arabic}-حلقة-{episode_num}"
        print(f"🔄 محاولة النطاق البديل: {alt_url}")
        html = get_page_html(alt_url)
        if html:
            domain = alt_domain
            page_url = alt_url
    if not html:
        return False, "فشل تحميل الصفحة", None

    # 2. استخراج PostData
    post_data = extract_post_data(html)
    if not post_data:
        return False, "فشل استخراج بيانات السيرفرات", None

    server_urls = extract_server_urls(post_data)
    if not server_urls:
        return False, "لا توجد سيرفرات", None

    print(f"🔍 تم العثور على {len(server_urls)} سيرفر.")

    temp_file = os.path.join(download_dir, f"temp_{episode_num}.mp4")
    downloaded = False

    for idx, server_url in enumerate(server_urls, 1):
        print(f"🔄 محاولة السيرفر {idx}: {server_url[:80]}...")
        
        # أولاً: نحاول استخراج رابط مباشر باستخدام Selenium
        direct_url = extract_direct_video_with_selenium(server_url, page_url)
        if direct_url:
            print(f"✅ تم استخراج رابط مباشر: {direct_url[:80]}...")
            if download_with_requests(direct_url, temp_file, page_url):
                downloaded = True
                break
            else:
                print("⚠️ فشل التنزيل عبر requests، نحاول yt-dlp...")
                if download_with_ytdlp(direct_url, temp_file, page_url):
                    downloaded = True
                    break
        
        # إذا لم نستطع استخراج رابط مباشر، نحاول yt-dlp مباشرة على رابط السيرفر
        print("🔄 محاولة التنزيل عبر yt-dlp على رابط السيرفر...")
        if download_with_ytdlp(server_url, temp_file, page_url):
            downloaded = True
            break

    if not downloaded:
        return False, "فشل التحميل من جميع السيرفرات", None

    # 3. ضغط الفيديو
    final_file = os.path.join(download_dir, f"{series_name_arabic}_e{episode_num:02d}_240p.mp4")
    if not compress_to_240p(temp_file, final_file):
        shutil.copy2(temp_file, final_file)
        print("⚠️ فشل الضغط، تم حفظ الملف الأصلي.")
        final_file = temp_file  # استخدم الملف الأصلي

    try:
        os.remove(temp_file)
    except:
        pass

    # 4. رفع الملف إلى gofile.io إذا كان مفعلاً في الإعدادات
    upload_enabled = config.get("upload", True)  # افتراضي True
    link = None
    if upload_enabled:
        link = upload_file(final_file)
        if not link:
            print("⚠️ فشل الرفع، سيتم حفظ الملف محلياً فقط.")
            link = f"📁 ملف محلي: {final_file}"
    else:
        print("⏭️ تم تعطيل الرفع في الإعدادات.")
        link = f"📁 ملف محلي: {final_file}"

    print(f"✅ تمت معالجة الحلقة {episode_num}")
    return True, "تم بنجاح", link

# ===== الدالة الرئيسية =====
def main():
    print("="*50)
    print("🎬 تنزيل، ضغط، ورفع فيديو من lodynet (مع رابط مباشر)")
    print("="*50)

    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg موجود")
    except:
        print("❌ ffmpeg غير موجود.")
        return

    config_file = "series_config.json"
    if not os.path.exists(config_file):
        print("❌ series_config.json غير موجود")
        return

    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)

    series_name_arabic = config.get("series_name_arabic", "").strip()
    if not series_name_arabic:
        print("❌ يجب تحديد series_name_arabic")
        return

    start_ep = int(config.get("start_episode", 1))
    end_ep = int(config.get("end_episode", 1))

    if end_ep - start_ep + 1 > 25:
        print("⚠️ عدد الحلقات كبير، سيتم معالجة 25 حلقة فقط.")
        end_ep = start_ep + 24

    print(f"📺 المسلسل: {series_name_arabic}")
    print(f"🎬 الحلقات: {start_ep} إلى {end_ep}")

    download_dir = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(download_dir, exist_ok=True)

    # ملف لحفظ الروابط
    links_file = os.path.join(download_dir, "direct_links.txt")
    with open(links_file, 'w', encoding='utf-8') as f:
        f.write(f"# روابط المشاهدة المباشرة للمسلسل: {series_name_arabic}\n")
        f.write(f"# تم الإنشاء في: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    successful = 0
    failed = []

    for ep in range(start_ep, end_ep + 1):
        success, msg, link = download_episode(ep, series_name_arabic, download_dir, config)
        if success:
            successful += 1
            print(f"✅ الحلقة {ep} اكتملت")
            if link:
                print(f"🔗 رابط المشاهدة: {link}")
                with open(links_file, 'a', encoding='utf-8') as f:
                    f.write(f"الحلقة {ep}: {link}\n")
        else:
            failed.append(ep)
            print(f"❌ الحلقة {ep}: {msg}")

        wait_time = random.randint(30, 45)
        print(f"⏳ انتظار {wait_time} ثانية...")
        time.sleep(wait_time)

    print(f"\n✅ الناجحة: {successful}/{len(range(start_ep, end_ep+1))}")
    if failed:
        print(f"❌ الفاشلة: {failed}")
    print(f"📂 الملفات المحفوظة في: {download_dir}")
    print(f"📄 الروابط محفوظة في: {links_file}")

if __name__ == "__main__":
    main()
