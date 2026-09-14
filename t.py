#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - shhaiid4u.net
v16.0 — API-based extraction (no iframes needed)
"""

import os, sys, time, json, base64, subprocess, shutil, asyncio, random, re, tempfile
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, quote

TELEGRAM_API_ID = os.environ.get("API_ID", "")
TELEGRAM_API_HASH = os.environ.get("API_HASH", "")
TELEGRAM_CHANNEL = os.environ.get("CHANNEL", "")
STRING_SESSION = os.environ.get("STRING_SESSION", "")

# ===== إعدادات الموقع =====
SITE_BASE = "https://shhaiid4u.net"

INPUT_SERIES_NAME = os.environ.get("INPUT_SERIES_NAME", "").strip()
INPUT_SERIES_NAME_ARABIC = os.environ.get("INPUT_SERIES_NAME_ARABIC", "").strip()
INPUT_SEASON_NUM = os.environ.get("INPUT_SEASON_NUM", "").strip()
INPUT_START_EPISODE = os.environ.get("INPUT_START_EPISODE", "").strip()
INPUT_END_EPISODE = os.environ.get("INPUT_END_EPISODE", "").strip()

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() in ("true", "1", "yes")
KEEP_VIDEO = os.environ.get("KEEP_VIDEO", "false").lower() in ("true", "1", "yes")
SKIP_UPLOAD = os.environ.get("SKIP_UPLOAD", "false").lower() in ("true", "1", "yes")
SKIP_COMPRESS = os.environ.get("SKIP_COMPRESS", "false").lower() in ("true", "1", "yes")

MIN_VALID_SIZE = 100 * 1024
MIN_PARTIAL_ACCEPT = 30 * 1024 * 1024
MIN_EPISODE_DURATION = 900
NATURAL_EXIT_MIN_DURATION = 600
MAX_RUNTIME_SECONDS = 165 * 60
WAIT_MIN, WAIT_MAX = 10, 20

YTDLP_TIMEOUT = 1800
FFMPEG_TIMEOUT = 1800
STALL_TIMEOUT = 60
FILE_CREATE_TIMEOUT = 30

MIN_ACCEPTABLE_SPEED = 300 * 1024
SPEED_CHECK_INTERVAL = 20
SPEED_GRACE_PERIOD = 30

DURATION_ACCEPT_RATIO = 0.95
MIN_REAL_RATIO_AFTER_COMPRESS = 0.85
MIN_PARTIAL_REAL_DURATION = 600

CURL_CFFI_WORKERS = 8
CURL_CFFI_TIMEOUT = 60
BROWSER_FETCH_BATCH = 6

SCRIPT_START = time.time()


def elapsed_str():
    e = int(time.time() - SCRIPT_START)
    return f"{e//3600}h{(e%3600)//60}m{e%60}s"


def remaining():
    return max(0, MAX_RUNTIME_SECONDS - (time.time() - SCRIPT_START))


def exceeded():
    return (time.time() - SCRIPT_START) >= MAX_RUNTIME_SECONDS


def validate_env():
    if TEST_MODE:
        print("🧪 TEST_MODE")
        return True
    errs = []
    if not TELEGRAM_API_ID: errs.append("❌ API_ID")
    if not TELEGRAM_API_HASH: errs.append("❌ API_HASH")
    if not TELEGRAM_CHANNEL: errs.append("❌ CHANNEL")
    if not STRING_SESSION: errs.append("❌ STRING_SESSION")
    if errs:
        print("\n".join(errs))
        return False
    return True


if not validate_env():
    sys.exit(1)


def install_requirements():
    print("📦 Installing requirements...")
    reqs = [
        "yt-dlp[default,curl-cffi]>=2026.08.19",
        "seleniumbase>=4.52.0",
        "beautifulsoup4>=4.13.0",
        "curl_cffi>=0.15.0",
    ]
    if not (TEST_MODE and SKIP_UPLOAD):
        reqs += ["pyrogram>=2.0.106", "tgcrypto>=1.2.5"]
    for r in reqs:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install",
                                   "--upgrade", r, "--quiet"])
            print(f"  ✅ {r.split('>=')[0].split('[')[0]}")
        except Exception:
            print(f"  ⚠️ Failed: {r}")


install_requirements()

import yt_dlp
from seleniumbase import SB
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

app = None
if not (TEST_MODE and SKIP_UPLOAD):
    from pyrogram import Client
    from pyrogram.errors import FloodWait


async def setup_telegram():
    global app
    if TEST_MODE and SKIP_UPLOAD:
        print("🧪 SKIP_UPLOAD")
        return True
    print("\n🔐 Connecting...")
    try:
        app = Client("github_uploader",
                     api_id=int(TELEGRAM_API_ID),
                     api_hash=TELEGRAM_API_HASH,
                     session_string=STRING_SESSION.strip(),
                     in_memory=True)
        await app.start()
        me = await app.get_me()
        print(f"✅ Connected as {me.first_name}")
        return True
    except Exception as e:
        print(f"❌ {e}")
        return False


# ============================================================
#  ✅ v16.0: بناء رابط الحلقة من shhaiid4u.net
# ============================================================
def build_episode_url(series_name, episode_num):
    """
    يبني رابط الحلقة على shhaiid4u.net
    مثال: https://shhaiid4u.net/watch/مسلسل-احتمال-حب-الموسم-الاول-الحلقة-65-مدبلجة
    """
    # تنسيق الرابط: /watch/{series-slug}-الموسم-الاول-الحلقة-{ep}-مدبلجة
    base_slug = series_name.replace(' ', '-')
    # نحتاج إلى صياغة دقيقة
    ep_slug = f"الحلقة-{episode_num}-مدبلجة"
    season_slug = "الموسم-الاول"  # يمكن تعديله حسب الحاجة

    full_path = f"/watch/{base_slug}-{season_slug}-{ep_slug}"
    return SITE_BASE + quote(full_path, safe='/-')


# ============================================================
#  ✅ v16.0: استخراج player API من الصفحة
# ============================================================
def extract_player_api(page_url):
    """
    يفتح الصفحة ويستخرج data-player-api و data-player-fallback
    يرجع (api_url, fallback_url, cookies_dict)
    """
    print(f"   🔍 فتح الصفحة: {page_url[:80]}...", flush=True)
    api_url = None
    fallback_url = None
    cookies_dict = {}

    try:
        with SB(uc=True, xvfb=True, headless=False, incognito=True,
                ad_block_on=True, disable_csp=True,
                page_load_strategy="eager", locale_code="ar") as sb:
            try:
                sb.activate_cdp_mode()
                sb.cdp.open(page_url)
                sb.cdp.sleep(6)

                # استخرج العناصر المخفية
                html = sb.cdp.get_page_source()

                # ابحث عن data-player-api
                m = re.search(r'data-player-api="([^"]+)"', html)
                if m:
                    api_url = m.group(1)
                    print(f"   ✅ player-api: {api_url[:80]}", flush=True)

                m2 = re.search(r'data-player-fallback="([^"]+)"', html)
                if m2:
                    fallback_url = m2.group(1)
                    print(f"   ✅ player-fallback: {fallback_url[:80]}", flush=True)

                # جيب الكوكيز
                try:
                    r = sb.driver.execute_cdp_cmd("Network.getAllCookies", {})
                    for c in r.get("cookies", []):
                        n, v = c.get("name", ""), c.get("value", "")
                        if n and v:
                            cookies_dict[n] = v
                except Exception:
                    pass

                print(f"   🍪 {len(cookies_dict)} كوكي", flush=True)

            except Exception as e:
                print(f"   ❌ {str(e)[:120]}", flush=True)
    except Exception as e:
        print(f"   ❌ {str(e)[:120]}", flush=True)

    return api_url, fallback_url, cookies_dict


# ============================================================
#  ✅ v16.0: استدعاء API للحصول على رابط البث
# ============================================================
def call_player_api(api_url, cookies_dict):
    """
    يستدعي API ويعيد (stream_url, player_url)
    """
    print(f"   📡 استدعاء API: {api_url[:80]}...", flush=True)

    headers = {
        "Referer": SITE_BASE,
        "Origin": SITE_BASE,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        r = cffi_requests.get(api_url, headers=headers,
                               cookies=cookies_dict,
                               impersonate="chrome120", timeout=20)
        if r.status_code != 200:
            print(f"   ❌ API HTTP {r.status_code}", flush=True)
            return None, None

        data = r.json()
        if data.get("status") != "ok":
            print(f"   ❌ API status: {data.get('status')}", flush=True)
            return None, None

        stream_url = data.get("stream")
        player_url = data.get("player")

        if stream_url:
            print(f"   ✅ stream: {stream_url[:100]}", flush=True)
        if player_url:
            print(f"   ✅ player: {player_url[:100]}", flush=True)

        return stream_url, player_url

    except Exception as e:
        print(f"   ❌ API exc: {str(e)[:120]}", flush=True)
        return None, None


# ============================================================
#  ✅ v16.0: تحميل HLS عبر curl_cffi
# ============================================================
def download_hls_with_curl_cffi(m3u8_url, out_path, referer, cookies_dict, expected_dur=0):
    print(f"   [curl_cffi HLS] {m3u8_url[:80]}...", flush=True)

    headers = {
        "Referer": referer,
        "Origin": SITE_BASE,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies_dict.items()])[:8000]
    if cookie_str:
        headers["Cookie"] = cookie_str

    try:
        r = cffi_requests.get(m3u8_url, headers=headers,
                               impersonate="chrome120", timeout=30, verify=False)
        if r.status_code != 200:
            return False, f"m3u8_fail: HTTP {r.status_code}", False
        m3u8_text = r.text
    except Exception as e:
        return False, f"m3u8_exc: {e}", False

    def _parse(text, b_url):
        segs = []
        variants = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if '.m3u8' in line:
                variants.append(urljoin(b_url + '/', line))
                continue
            if line.endswith('.ts') or '.ts?' in line or 'seg' in line.lower():
                segs.append(urljoin(b_url + '/', line))
        return segs, variants

    base_url = m3u8_url.rsplit('/', 1)[0]
    segments, variants = _parse(m3u8_text, base_url)

    if not segments and variants:
        for v in variants[:3]:
            try:
                rv = cffi_requests.get(v, headers=headers,
                                        impersonate="chrome120", timeout=30, verify=False)
                if rv.status_code == 200:
                    vb = v.rsplit('/', 1)[0]
                    segments, _ = _parse(rv.text, vb)
                    if segments:
                        break
            except Exception:
                pass

    if not segments:
        return False, "no_segments", False

    print(f"   ⬇️ {len(segments)} segment عبر curl_cffi...", flush=True)
    seg_dir = tempfile.mkdtemp(prefix="hls_curl_")
    seg_paths = {}
    failed = 0
    total_bytes = 0

    def _dl(idx_url):
        idx, url = idx_url
        try:
            rr = cffi_requests.get(url, headers=headers,
                                    impersonate="chrome120", timeout=60, verify=False)
            if rr.status_code == 200 and len(rr.content) > 100:
                p = os.path.join(seg_dir, f"seg_{idx:06d}.ts")
                with open(p, 'wb') as f:
                    f.write(rr.content)
                return (idx, p, len(rr.content))
        except Exception:
            pass
        return (idx, None, 0)

    with ThreadPoolExecutor(max_workers=CURL_CFFI_WORKERS) as ex:
        futures = {ex.submit(_dl, (i, s)): i for i, s in enumerate(segments)}
        done = 0
        for fut in as_completed(futures):
            idx, path, size = fut.result()
            done += 1
            if path:
                seg_paths[idx] = path
                total_bytes += size
            else:
                failed += 1
            if done % 30 == 0 or done == len(segments):
                print(f"      📦 {done}/{len(segments)} | {total_bytes/(1024*1024):.1f} MB | فشل: {failed}", flush=True)

    if not seg_paths:
        try: shutil.rmtree(seg_dir, ignore_errors=True)
        except: pass
        return False, f"all_segments_failed", False

    sorted_segs = [seg_paths[k] for k in sorted(seg_paths.keys())]
    concat_file = os.path.join(seg_dir, "concat.txt")
    with open(concat_file, 'w') as f:
        for p in sorted_segs:
            f.write(f"file '{p}'\n")

    concat_cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'warning',
                  '-f', 'concat', '-safe', '0', '-i', concat_file,
                  '-c', 'copy', '-f', 'mpegts', '-y', out_path]
    try:
        r = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not os.path.exists(out_path):
            try: shutil.rmtree(seg_dir, ignore_errors=True)
            except: pass
            return False, "concat_failed", False
    except Exception as e:
        try: shutil.rmtree(seg_dir, ignore_errors=True)
        except: pass
        return False, f"concat_err: {e}", False

    final_size = os.path.getsize(out_path)
    print(f"   ✅ ملف نهائي: {final_size/(1024*1024):.1f} MB", flush=True)

    try: shutil.rmtree(seg_dir, ignore_errors=True)
    except: pass
    return True, final_size, False


# ============================================================
#  ✅ v16.0: تحميل مباشر بـ yt-dlp
# ============================================================
def download_with_ytdlp(stream_url, out_path, referer, cookies_dict):
    print(f"   [yt-dlp] {stream_url[:80]}...", flush=True)

    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies_dict.items()])[:8000]

    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '--no-warnings', '--no-playlist', '--no-part',
        '--retries', '20', '--fragment-retries', '50',
        '--retry-sleep', 'fragment:exp=1:20',
        '--socket-timeout', '60',
        '--concurrent-fragments', '8',
        '--no-check-certificate', '--continue',
        '--hls-use-mpegts',
        '--hls-prefer-native',
        '--no-abort-on-error',
        '--file-access-retries', '10', '--extractor-retries', '5',
        '--impersonate', 'chrome',
        '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        '--referer', referer,
        '--add-header', f'Origin:{SITE_BASE}',
        '--add-header', 'Accept:*/*',
    ]
    if cookie_str:
        cmd += ['--add-header', f'Cookie:{cookie_str}']
    cmd += ['-f', 'best[height<=720]/best', '-o', out_path, stream_url]

    log_path = out_path + ".ytdlp.log"
    try:
        log_file = open(log_path, 'w', encoding='utf-8', errors='replace')
    except Exception as e:
        return False, f"log_open: {e}"

    try:
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True)
    except Exception as e:
        log_file.close()
        return False, f"spawn: {e}"

    start = time.time()
    last_size = 0
    last_change = start
    best_size = 0

    try:
        while proc.poll() is None:
            time.sleep(3)
            now = time.time()
            size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
            if size > last_size:
                last_size = size
                last_change = now
                if size > best_size:
                    best_size = size

            if now - last_change > STALL_TIMEOUT and size > 0:
                print(f"      🛑 yt-dlp stalled at {size/(1024*1024):.1f} MB", flush=True)
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                log_file.close()
                if best_size >= MIN_PARTIAL_ACCEPT:
                    return True, best_size
                return False, f"stalled@{best_size}"

            if now - start > YTDLP_TIMEOUT:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                log_file.close()
                if best_size >= MIN_PARTIAL_ACCEPT:
                    return True, best_size
                return False, f"timeout@{best_size}"

        log_file.close()
        size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        if size >= MIN_VALID_SIZE:
            return True, size
        return False, f"exited@{size}"

    except Exception as e:
        try: proc.kill()
        except: pass
        log_file.close()
        return False, f"monitor: {e}"


# ============================================================
#  ✅ v16.0: معالجة الحلقة
# ============================================================
async def process_episode(ep, sn, sn_ar, season, ddir):
    print(f"\n🎬 Ep {ep:02d}  [{elapsed_str()}]  ⏳ {remaining()//60}m")
    tmp_ts = os.path.join(ddir, f"temp_{ep:02d}.ts")
    fin = os.path.join(ddir, f"final_{ep:02d}.mp4")
    thb = os.path.join(ddir, f"thumb_{ep:02d}.jpg")

    try:
        # 1) بناء رابط الحلقة
        page_url = build_episode_url(sn, ep)
        print(f"   🔗 {page_url[:100]}", flush=True)

        # 2) استخراج API
        api_url, fallback_url, cookies_dict = await asyncio.to_thread(
            extract_player_api, page_url
        )

        if not api_url:
            print(f"   ❌ لم يتم العثور على player-api", flush=True)
            return False, "لا player-api"

        # 3) استدعاء API
        stream_url, player_url = await asyncio.to_thread(
            call_player_api, api_url, cookies_dict
        )

        if not stream_url:
            print(f"   ❌ فشل الحصول على stream URL", flush=True)
            return False, "لا stream URL"

        # 4) تحميل الفيديو (جرّب curl_cffi أولاً)
        print(f"\n   ⬇️ تحميل...", flush=True)
        ok, info = await asyncio.to_thread(
            download_hls_with_curl_cffi,
            stream_url, tmp_ts, page_url, cookies_dict, 0
        )

        if not ok:
            print(f"   ⚠️ curl_cffi فشل: {info} — جرّب yt-dlp", flush=True)
            ok, info = await asyncio.to_thread(
                download_with_ytdlp,
                stream_url, tmp_ts, page_url, cookies_dict
            )

        if not ok:
            print(f"   ❌ فشل التحميل: {info}", flush=True)
            return False, f"فشل: {info}"

        size = os.path.getsize(tmp_ts) if os.path.exists(tmp_ts) else 0
        print(f"   📦 {size/(1024*1024):.2f} MB", flush=True)

        # 5) الضغط
        print(f"\n🗜️ ضغط...")
        if SKIP_COMPRESS:
            shutil.copy2(tmp_ts, fin)
        else:
            if not compress_144p(tmp_ts, fin):
                print(f"   ⚠️ فشل الضغط — نسخ TS")
                shutil.copy2(tmp_ts, fin)

        if not os.path.exists(fin):
            return False, "لا ملف نهائي"

        # 6) Thumbnail
        print(f"\n🖼️ Thumbnail...")
        thumb(fin, thb)

        # 7) رفع
        print(f"\n📤 رفع...")
        cap = f"{sn_ar} الموسم {season} الحلقة {ep}"
        ok = await upload(fin, cap, thb if os.path.exists(thb) else None)

        if not (TEST_MODE and KEEP_VIDEO):
            for f in [tmp_ts, fin, thb]:
                try:
                    if os.path.exists(f): os.remove(f)
                except: pass
        return ok, "تم" if ok else "فشل الرفع"
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"خطأ: {e}"


# ============================================================
#  الضغط والميتا والرفع
# ============================================================
def compress_144p(inp, out):
    if not os.path.exists(inp):
        return False
    im = os.path.getsize(inp) / (1024 * 1024)
    print(f"   🗜️ {im:.2f} MB → 144p...")
    cmd = [
        'ffmpeg', '-err_detect', 'ignore_err',
        '-fflags', '+discardcorrupt+genpts',
        '-analyzeduration', '100M', '-probesize', '100M',
        '-i', inp, '-vf', 'scale=-2:144',
        '-c:v', 'libx264', '-crf', '28', '-preset', 'veryfast',
        '-c:a', 'aac', '-b:a', '64k',
        '-f', 'mp4', '-movflags', '+faststart',
        '-max_muxing_queue_size', '4096', '-y', out,
    ]
    try:
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 10 * 1024:
            print(f"   ❌ ffmpeg code={r.returncode}")
            return False
        om = os.path.getsize(out) / (1024 * 1024)
        print(f"   ✅ {im:.2f}→{om:.2f} MB في {time.time()-t0:.1f}s")
        return True
    except Exception as e:
        print(f"   ❌ {e}")
        return False


def meta(vp):
    w, h, d = 0, 0, 0
    try:
        cmd = ['ffprobe', '-v', 'error',
               '-select_streams', 'v:0',
               '-show_entries', 'stream=width,height',
               '-show_entries', 'format=duration',
               '-of', 'default=noprint_wrappers=1:nokey=1', vp]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if p.returncode != 0:
            return 0, 0, 0
        lines = [l.strip() for l in p.stdout.strip().split('\n') if l.strip()]
        if len(lines) >= 2:
            try:
                w, h = int(float(lines[0])), int(float(lines[1]))
            except Exception:
                return 0, 0, 0
        if len(lines) >= 3:
            try:
                d = int(float(lines[2]))
            except Exception:
                d = 0
    except Exception:
        return 0, 0, 0
    return w, h, d


def thumb(vp, tp):
    for ss in ['00:00:05', '00:00:01', '00:00:00']:
        cmd = ['ffmpeg', '-err_detect', 'ignore_err', '-fflags', '+discardcorrupt',
               '-ss', ss, '-i', vp, '-vframes', '1', '-vf', 'scale=320:180',
               '-f', 'image2', '-y', tp]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30)
            if r.returncode == 0 and os.path.exists(tp) and os.path.getsize(tp) > 1024:
                return True
        except Exception:
            pass
    return False


async def upload(fp, caption, tp=None):
    if TEST_MODE and SKIP_UPLOAD:
        print(f"🧪 SKIP_UPLOAD: {fp}")
        return True
    if app is None or not os.path.exists(fp):
        return False

    w, h, d = meta(fp)
    if w == 0 or h == 0:
        w, h = 640, 360
    if d == 0:
        try:
            d = int(os.path.getsize(fp) / (1024 * 1024) * 5)
        except Exception:
            d = 60

    mb = os.path.getsize(fp) / (1024 * 1024)
    print(f"   📤 رفع {mb:.2f} MB | {w}x{h} | {d}s...")
    t = tp if tp and os.path.exists(tp) else None
    try:
        t0 = time.time()
        await app.send_video(chat_id=TELEGRAM_CHANNEL, video=fp, caption=caption,
                             supports_streaming=True, width=w, height=h,
                             duration=d, thumb=t)
        print(f"   ✅ رُفع في {time.time()-t0:.1f}s")
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await upload(fp, caption, tp)
    except Exception as e:
        print(f"   ❌ فشل رفع: {str(e)[:200]}")
    try:
        await app.send_video(chat_id=TELEGRAM_CHANNEL, video=fp, caption=caption,
                             supports_streaming=True, width=w, height=h, duration=d)
        return True
    except Exception as e2:
        print(f"   ❌ فشلت الثانية: {str(e2)[:150]}")
        return False


# ============================================================
#  Main
# ============================================================
def load_config():
    c = {"series_name": "", "series_name_arabic": "", "season_num": 1,
         "start_episode": 1, "end_episode": 1}
    if os.path.exists("series_config.json"):
        try:
            with open("series_config.json", 'r', encoding='utf-8') as f:
                fc = json.load(f)
            c.update({k: v for k, v in fc.items() if v not in (None, "")})
            print("📄 الإعدادات")
        except Exception as e:
            print(f"⚠️ {e}")
    if INPUT_SERIES_NAME: c["series_name"] = INPUT_SERIES_NAME
    if INPUT_SERIES_NAME_ARABIC: c["series_name_arabic"] = INPUT_SERIES_NAME_ARABIC
    if INPUT_SEASON_NUM: c["season_num"] = int(INPUT_SEASON_NUM)
    if INPUT_START_EPISODE: c["start_episode"] = int(INPUT_START_EPISODE)
    if INPUT_END_EPISODE: c["end_episode"] = int(INPUT_END_EPISODE)
    return c


async def main():
    print("=" * 60)
    print("🎬 Video Downloader v16.0 — shhaiid4u.net")
    if TEST_MODE: print("🧪 TEST_MODE")
    print("=" * 60)

    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg")
    except Exception:
        print("❌ ffmpeg")

    cfg = load_config()
    sn = str(cfg.get("series_name", "")).strip()
    snar = str(cfg.get("series_name_arabic", "")).strip() or sn
    season = int(cfg.get("season_num", 1))
    s_ep = int(cfg.get("start_episode", 1))
    e_ep = int(cfg.get("end_episode", 1))
    if not sn:
        print("❌ اسم المسلسل")
        return

    print(f"📺 {sn} / {snar}")
    print(f"🎬 {s_ep} → {e_ep}")

    if not await setup_telegram():
        return

    ddir = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(ddir, exist_ok=True)

    ok_n = 0
    failed = []
    skipped = []

    for ep in range(s_ep, e_ep + 1):
        if exceeded():
            skipped = list(range(ep, e_ep + 1))
            break
        ok, msg = await process_episode(ep, sn, snar, season, ddir)
        if ok:
            ok_n += 1
            print(f"✅ {ep}  [{elapsed_str()}]")
        else:
            failed.append(ep)
            print(f"❌ {ep}: {msg}  [{elapsed_str()}]")
        if ep < e_ep and not exceeded():
            w = random.randint(WAIT_MIN, WAIT_MAX)
            print(f"⏳ {w}s...")
            await asyncio.sleep(w)

    print(f"\n{'='*60}\n⏱️ {elapsed_str()}\n✅ {ok_n}/{e_ep-s_ep+1}")
    if failed: print(f"❌ {failed}")
    if skipped: print(f"⏭️ {skipped}")
    print("=" * 60)

    if TEST_MODE and KEEP_VIDEO:
        print(f"🧪 {ddir}")
    else:
        try: shutil.rmtree(ddir)
        except: pass
    if app:
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
