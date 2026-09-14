#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - shhaiid4u.net
v16.1 — Fixed URL building + robust player-api extraction
"""

import os, sys, time, json, base64, subprocess, shutil, asyncio, random, re, tempfile
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, quote

TELEGRAM_API_ID = os.environ.get("API_ID", "")
TELEGRAM_API_HASH = os.environ.get("API_HASH", "")
TELEGRAM_CHANNEL = os.environ.get("CHANNEL", "")
STRING_SESSION = os.environ.get("STRING_SESSION", "")

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
MAX_RUNTIME_SECONDS = 165 * 60
WAIT_MIN, WAIT_MAX = 10, 20

YTDLP_TIMEOUT = 1800
STALL_TIMEOUT = 60

CURL_CFFI_WORKERS = 8

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
#  ✅✅ v16.1: بناء رابط صحيح بدون تكرار "الموسم"
# ============================================================
SEASON_AR_MAP = {
    1: "الاول", 2: "الثاني", 3: "الثالث", 4: "الرابع",
    5: "الخامس", 6: "السادس", 7: "السابع", 8: "الثامن",
    9: "التاسع", 10: "العاشر",
}


def build_episode_url(series_slug, episode_num, season_num=1):
    """
    يبني رابط صحيح:
    - إذا series_slug يحتوي على "الموسم" → لا نضيفه مرة أخرى
    - وإلا نضيف "الموسم-{اسم الموسم}"
    """
    sn = series_slug.strip().strip('-')

    # ✅ إذا كان الموسم موجوداً بالفعل، لا نضيفه
    if "الموسم" not in sn:
        season_ar = SEASON_AR_MAP.get(season_num, "الاول")
        sn = f"{sn}-الموسم-{season_ar}"

    full_path = f"/watch/{sn}-الحلقة-{episode_num}-مدبلجة"
    encoded = quote(full_path, safe='/-')
    return SITE_BASE + encoded


# ============================================================
#  ✅✅ v16.1: استخراج player-api مع debugging
# ============================================================
def extract_player_api(page_url, debug_html_path=None):
    """
    يفتح الصفحة، يستخرج player-api مع 4 أنماط regex مختلفة.
    يحفظ HTML للتشخيص إذا فشل.
    """
    print(f"   🔍 فتح الصفحة...", flush=True)
    api_url = None
    fallback_url = None
    cookies_dict = {}
    html_saved = False

    try:
        with SB(uc=True, xvfb=True, headless=False, incognito=True,
                ad_block_on=True, disable_csp=True,
                page_load_strategy="eager", locale_code="ar") as sb:
            try:
                sb.activate_cdp_mode()
                sb.cdp.open(page_url)
                sb.cdp.sleep(8)

                # التحقق من تحميل الصفحة بنجاح
                try:
                    title = sb.cdp.execute_script("return document.title || ''")
                    current_url = sb.cdp.execute_script("return window.location.href || ''")
                    print(f"   📄 title: {str(title)[:80]}", flush=True)
                    print(f"   🌐 current_url: {str(current_url)[:120]}", flush=True)
                except Exception:
                    pass

                # محاولة click لتشغيل أي lazy loading
                for sel in ["video", "button", "[data-player]", ".play", ".play-button"]:
                    try:
                        sb.cdp.click_if_visible(sel)
                    except Exception:
                        pass
                sb.cdp.sleep(3)

                html = sb.cdp.get_page_source()
                print(f"   📏 HTML size: {len(html) if html else 0}", flush=True)

                # ✅✅ 4 أنماط لـ player-api
                patterns = [
                    # 1) النمط الأصلي
                    r'data-player-api="([^"]+)"',
                    # 2) single quotes
                    r"data-player-api='([^']+)'",
                    # 3) مع مسافات
                    r'data-player-api\s*=\s*"([^"]+)"',
                    # 4) أي عنصر يحمل اللاحقة
                    r'data-player-api\s*=\s*[\'"]([^\'"]+)[\'"]',
                ]
                for pat in patterns:
                    m = re.search(pat, html)
                    if m:
                        api_url = m.group(1)
                        print(f"   ✅ player-api (نمط {patterns.index(pat)+1}): {api_url[:100]}", flush=True)
                        break

                # fallback
                for pat in [
                    r'data-player-fallback="([^"]+)"',
                    r"data-player-fallback='([^']+)'",
                ]:
                    m = re.search(pat, html)
                    if m:
                        fallback_url = m.group(1)
                        print(f"   ✅ player-fallback: {fallback_url[:100]}", flush=True)
                        break

                # إذا فشل، ابحث عن أي شيء يشبه API
                if not api_url:
                    alt_patterns = [
                        r'/media/api/[a-f0-9]+',
                        r'/api/player/[a-zA-Z0-9]+',
                        r'"player_api"\s*:\s*"([^"]+)"',
                        r'api["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                    ]
                    for pat in alt_patterns:
                        m = re.search(pat, html)
                        if m:
                            candidate = m.group(1) if m.lastindex else m.group(0)
                            if candidate.startswith('http'):
                                api_url = candidate
                            else:
                                api_url = SITE_BASE + candidate if candidate.startswith('/') else SITE_BASE + '/' + candidate
                            print(f"   ✅ API (بديل): {api_url[:100]}", flush=True)
                            break

                # احفظ HTML للتشخيص
                if not api_url and debug_html_path:
                    try:
                        with open(debug_html_path, 'w', encoding='utf-8') as f:
                            f.write(html or "")
                        html_saved = True
                        print(f"   💾 HTML محفوظ: {debug_html_path}", flush=True)
                    except Exception:
                        pass

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

                # إذا لم ينجح، اطبع جزءاً من HTML
                if not api_url and html:
                    # ابحث عن أي شيء فيه "player" أو "api"
                    candidates = re.findall(r'[\w-]*(?:player|api)[\w-]*', html[:50000])
                    print(f"   🔎 كلمات مفتاحية: {list(set(candidates))[:10]}", flush=True)

            except Exception as e:
                print(f"   ❌ {str(e)[:120]}", flush=True)
    except Exception as e:
        print(f"   ❌ {str(e)[:120]}", flush=True)

    return api_url, fallback_url, cookies_dict, html_saved


# ============================================================
#  API call
# ============================================================
def call_player_api(api_url, cookies_dict):
    print(f"   📡 API: {api_url[:90]}...", flush=True)

    headers = {
        "Referer": SITE_BASE + "/",
        "Origin": SITE_BASE,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    }

    try:
        r = cffi_requests.get(api_url, headers=headers,
                               cookies=cookies_dict,
                               impersonate="chrome120", timeout=20)
        print(f"   📡 API HTTP {r.status_code}", flush=True)
        if r.status_code != 200:
            print(f"   📋 {r.text[:200]}", flush=True)
            return None, None

        data = r.json()
        print(f"   📋 JSON keys: {list(data.keys())}", flush=True)

        stream_url = data.get("stream") or data.get("url") or data.get("file")
        player_url = data.get("player") or data.get("embed")

        if stream_url:
            print(f"   ✅ stream: {stream_url[:120]}", flush=True)
        if player_url:
            print(f"   ✅ player: {player_url[:120]}", flush=True)

        return stream_url, player_url

    except Exception as e:
        print(f"   ❌ API exc: {str(e)[:120]}", flush=True)
        return None, None


# ============================================================
#  HLS downloader
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
#  process_episode
# ============================================================
async def process_episode(ep, sn, sn_ar, season, ddir):
    print(f"\n🎬 Ep {ep:02d}  [{elapsed_str()}]  ⏳ {remaining()//60}m")
    tmp_ts = os.path.join(ddir, f"temp_{ep:02d}.ts")
    fin = os.path.join(ddir, f"final_{ep:02d}.mp4")
    thb = os.path.join(ddir, f"thumb_{ep:02d}.jpg")
    debug_html = os.path.join(ddir, f"debug_ep{ep:02d}.html")

    try:
        page_url = build_episode_url(sn, ep, season)
        print(f"   🔗 {page_url}", flush=True)

        api_url, fallback_url, cookies_dict, saved = await asyncio.to_thread(
            extract_player_api, page_url, debug_html
        )

        if not api_url and fallback_url:
            print(f"   🔄 استخدام fallback", flush=True)
            api_url = fallback_url

        if not api_url:
            if saved:
                return False, f"لا player-api (HTML: {debug_html})"
            return False, "لا player-api"

        stream_url, player_url = await asyncio.to_thread(
            call_player_api, api_url, cookies_dict
        )

        if not stream_url and player_url:
            print(f"   🔄 استخدام player URL كـ stream", flush=True)
            stream_url = player_url

        if not stream_url:
            return False, "لا stream URL"

        print(f"\n   ⬇️ تحميل...", flush=True)
        ok, info, _ = await asyncio.to_thread(
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
            return False, f"فشل: {info}"

        size = os.path.getsize(tmp_ts) if os.path.exists(tmp_ts) else 0
        print(f"   📦 {size/(1024*1024):.2f} MB", flush=True)

        print(f"\n🗜️ ضغط...")
        if SKIP_COMPRESS:
            shutil.copy2(tmp_ts, fin)
        else:
            if not compress_144p(tmp_ts, fin):
                shutil.copy2(tmp_ts, fin)

        if not os.path.exists(fin):
            return False, "لا ملف نهائي"

        print(f"\n🖼️ Thumbnail...")
        thumb(fin, thb)

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
#  helpers
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
#  main
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
    print("🎬 Video Downloader v16.1 — shhaiid4u.net")
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
