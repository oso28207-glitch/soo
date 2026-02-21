#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - Safe Version for GitHub Actions
"""
import os
import sys
import re
import time
import json
import subprocess
import shutil
import asyncio
import random
from datetime import datetime

# ===== CONFIGURATION =====
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

# تثبيت الحزم الضرورية فقط
def install_requirements():
    print("📦 Installing requirements...")
    reqs = ["pyrogram>=2.0.0", "tgcrypto>=1.2.0", "yt-dlp>=2024.4.9"]
    for req in reqs:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", req, "--quiet"])
        except:
            print(f"⚠️ Failed to install {req}")

install_requirements()

from pyrogram import Client
from pyrogram.errors import FloodWait
import yt_dlp

app = None

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

def get_video_url_via_ytdlp(episode_url):
    """استخراج رابط الفيديو باستخدام yt-dlp فقط (بدون تخمين)"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'format': 'best[height<=720]',  # نحاول الحصول على جودة منخفضة لتقليل الحجم
            'socket_timeout': 15,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(episode_url, download=False)
            if info and 'url' in info:
                return info['url']
            # بعض المواقع تعطي قائمة بالصيغ
            if 'formats' in info:
                # اختر أقل صيغة فيديو (أصغر حجم)
                formats = [f for f in info['formats'] if f.get('vcodec') != 'none']
                if formats:
                    # رتب حسب الدقة تصاعدياً
                    formats.sort(key=lambda f: f.get('height', 9999))
                    chosen = formats[0]
                    return chosen['url']
            return None
    except Exception as e:
        print(f"⚠️ yt-dlp error: {e}")
        return None

def download_video(video_url, output_path):
    """تنزيل الفيديو باستخدام yt-dlp"""
    try:
        ydl_opts = {
            'format': 'best[height<=720]/best',
            'outtmpl': output_path,
            'quiet': False,
            'retries': 5,
            'fragment_retries': 5,
            'socket_timeout': 30,
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
        subprocess.run(cmd, capture_output=True, timeout=1800)  # 30 دقيقة كحد أقصى
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
        width, height = 426, 240  # افتراضي
        duration = 0
        # محاولة الحصول على معلومات الفيديو
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
    """معالجة حلقة واحدة بطريقة آمنة"""
    # بناء رابط الحلقة (هذا افتراضي وقد يختلف حسب الموقع)
    # يجب تعديل هذا الجزء ليتناسب مع الموقع الفعلي
    episode_url = f"https://z.3seq.cam/video/modablaj-{series_name}-episode-s{season_num:02d}e{episode_num:02d}"
    # يمكن إضافة بعض المتغيرات لكن بدون تخمين مكثف
    # نجرب الرابط الأساسي فقط

    print(f"\n🎬 Episode {episode_num:02d}")
    temp_file = os.path.join(download_dir, f"temp_{episode_num:02d}.mp4")
    final_file = os.path.join(download_dir, f"final_{episode_num:02d}.mp4")
    thumb_file = os.path.join(download_dir, f"thumb_{episode_num:02d}.jpg")

    # 1. استخراج رابط الفيديو عبر yt-dlp
    video_url = get_video_url_via_ytdlp(episode_url)
    if not video_url:
        print("❌ Could not extract video URL")
        return False, "URL extraction failed"

    # 2. تنزيل الفيديو
    if not download_video(video_url, temp_file):
        return False, "Download failed"

    # 3. ضغط الفيديو
    if not compress_to_240p(temp_file, final_file):
        shutil.copy2(temp_file, final_file)  # استخدم الأصلي إذا فشل الضغط

    # 4. إنشاء صورة مصغرة
    create_thumbnail(final_file, thumb_file)

    # 5. رفع إلى تليغرام
    caption = f"{series_name_arabic} الموسم {season_num} الحلقة {episode_num}"
    success = await upload_video(final_file, caption, thumb_file if os.path.exists(thumb_file) else None)

    # 6. تنظيف
    for f in [temp_file, final_file, thumb_file]:
        try:
            if os.path.exists(f):
                os.remove(f)
        except:
            pass

    return success, "OK" if success else "Upload failed"

async def main():
    print("="*50)
    print("🎬 Safe Video Processor for GitHub Actions")
    print("="*50)

    # التحقق من ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except:
        print("❌ ffmpeg not found")
        return

    # الاتصال بتليغرام
    if not await setup_telegram():
        return

    # قراءة ملف الإعدادات
    config_file = "series_config.json"
    if not os.path.exists(config_file):
        print("❌ series_config.json not found")
        return

    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)

    series_name = config.get("series_name", "").strip()
    series_name_arabic = config.get("series_name_arabic", "").strip()
    season_num = int(config.get("season_num", 1))
    start_ep = int(config.get("start_episode", 1))
    end_ep = int(config.get("end_episode", 1))

    # تقليل العدد تلقائياً إذا كان كبيراً (حماية)
    if end_ep - start_ep + 1 > 10:
        print("⚠️ Too many episodes! Limiting to 10 to avoid timeout.")
        end_ep = start_ep + 9

    print(f"📺 Series: {series_name_arabic}")
    print(f"🎬 Episodes: {start_ep} to {end_ep}")

    download_dir = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(download_dir, exist_ok=True)

    successful = 0
    failed = []

    for ep in range(start_ep, end_ep + 1):
        success, msg = await process_episode(ep, series_name, series_name_arabic, season_num, download_dir)
        if success:
            successful += 1
            print(f"✅ Episode {ep} done")
        else:
            failed.append(ep)
            print(f"❌ Episode {ep}: {msg}")

        # انتظار عشوائي بين الحلقات لتجنب الظهور كبوت
        wait_time = random.randint(10, 20)
        print(f"⏳ Waiting {wait_time}s before next...")
        await asyncio.sleep(wait_time)

    print(f"\n✅ Successful: {successful}/{len(range(start_ep, end_ep+1))}")
    if failed:
        print(f"❌ Failed: {failed}")

    # تنظيف المجلد إن كان فارغاً
    try:
        os.rmdir(download_dir)
    except:
        pass

    await app.stop()
    print("🔌 Disconnected")

if __name__ == "__main__":
    asyncio.run(main())
