#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - u.3seq.com/.cam
Final v5 — no deadlock, resume, duration validation
"""

import os, sys, time, json, subprocess, shutil, asyncio, random, re, tempfile
from datetime import datetime

TELEGRAM_API_ID = os.environ.get("API_ID", "")
TELEGRAM_API_HASH = os.environ.get("API_HASH", "")
TELEGRAM_CHANNEL = os.environ.get("CHANNEL", "")
STRING_SESSION = os.environ.get("STRING_SESSION", "")

INPUT_SERIES_NAME = os.environ.get("INPUT_SERIES_NAME", "").strip()
INPUT_SERIES_NAME_ARABIC = os.environ.get("INPUT_SERIES_NAME_ARABIC", "").strip()
INPUT_SEASON_NUM = os.environ.get("INPUT_SEASON_NUM", "").strip()
INPUT_START_EPISODE = os.environ.get("INPUT_START_EPISODE", "").strip()
INPUT_END_EPISODE = os.environ.get("INPUT_END_EPISODE", "").strip()

TEST_MODE = os.environ.get("TEST_MODE", "false").lower() in ("true", "1", "yes")
KEEP_VIDEO = os.environ.get("KEEP_VIDEO", "false").lower() in ("true", "1", "yes")
SKIP_DOWNLOAD = os.environ.get("SKIP_DOWNLOAD", "false").lower() in ("true", "1", "yes")
SKIP_UPLOAD = os.environ.get("SKIP_UPLOAD", "false").lower() in ("true", "1", "yes")
SKIP_COMPRESS = os.environ.get("SKIP_COMPRESS", "false").lower() in ("true", "1", "yes")

# ✅ الحدود الجديدة
MIN_VALID_SIZE = 100 * 1024
MIN_PARTIAL_SIZE = 5 * 1024 * 1024
MIN_EPISODE_DURATION = 600           # ✅ 10 دقائق — أقصر من هذا = فشل
MAX_RUNTIME_SECONDS = 2 * 3600 + 45 * 60
WAIT_MIN, WAIT_MAX = 15, 30

DOWNLOAD_TIMEOUT = 900               # ✅ 15 دقيقة لكل مرشح
STALL_TIMEOUT = 90                   # ✅ 90s قبل اعتبار السيرفر متوقفاً
MAX_DOWNLOAD_ATTEMPTS = 3            # ✅ 3 محاولات مع resume

CF_SITES = ['luluvdo.com', 'vinovo.to', 'lulushort', 'luluvid']

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
    e = []
    if not TELEGRAM_API_ID: e.append("❌ API_ID")
    if not TELEGRAM_API_HASH: e.append("❌ API_HASH")
    if not TELEGRAM_CHANNEL: e.append("❌ CHANNEL")
    if not STRING_SESSION: e.append("❌ STRING_SESSION")
    if e:
        print("\n".join(e))
        return False
    return True


if not validate_env():
    sys.exit(1)


def install_requirements():
    print("📦 Installing requirements...")
    reqs = [
        "yt-dlp[default,curl-cffi]>=2024.11.18",   # ✅ extras للـ impersonation
        "seleniumbase>=4.30.0",
        "beautifulsoup4>=4.12.0",
        "curl_cffi>=0.7.0",
    ]
    if not (TEST_MODE and SKIP_UPLOAD):
        reqs += ["pyrogram>=2.0.0", "tgcrypto>=1.2.0"]
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
        app = Client("github_uploader", api_id=int(TELEGRAM_API_ID),
                     api_hash=TELEGRAM_API_HASH, session_string=STRING_SESSION.strip(),
                     in_memory=True)
        await app.start()
        me = await app.get_me()
        print(f"✅ Connected as {me.first_name}")
        return True
    except Exception as e:
        print(f"❌ {e}")
        return False


def check_ytdlp_version():
    try:
        r = subprocess.run([sys.executable, '-m', 'yt_dlp', '--version'],
                          capture_output=True, text=True, timeout=10)
        v = r.stdout.strip()
        print(f"📌 yt-dlp: {v}")
        r2 = subprocess.run([sys.executable, '-m', 'yt_dlp', '--help'],
                           capture_output=True, text=True, timeout=10)
        has_imp = '--impersonate' in r2.stdout
        print(f"{'✅' if has_imp else '⚠️'} --impersonate {'مدعوم' if has_imp else 'غير مدعوم'}")
        return has_imp
    except Exception as e:
        print(f"⚠️ فحص yt-dlp: {e}")
        return False


# ============================================================
#  Cookies
# ============================================================
def get_cookies_safe(sb):
    cookies_dict = {}
    try:
        for c in sb.driver.get_cookies():
            n = c.get("name", "")
            if n:
                cookies_dict[n] = c.get("value", "")
    except Exception:
        pass

    if not cookies_dict:
        try:
            r = sb.driver.execute_cdp_cmd("Network.getAllCookies", {})
            for c in r.get("cookies", []):
                n = c.get("name", "")
                if n:
                    cookies_dict[n] = c.get("value", "")
        except Exception:
            pass

    return cookies_dict


# ============================================================
#  استخراج السيرفرات
# ============================================================
def extract_servers(html):
    servers = []
    for pat, order in [
        (re.compile(r'<li[^>]*id=["\'](s_\d+)["\'][^>]*on[Cc]lick=["\']getServer2\([^,]+,\s*(\d+)\s*,\s*(\d+)\s*\)', re.I), "id_first"),
        (re.compile(r'on[Cc]lick=["\']getServer2\([^,]+,\s*(\d+)\s*,\s*(\d+)\s*\)[^>]*id=["\'](s_\d+)["\']', re.I), "click_first"),
    ]:
        for m in pat.finditer(html):
            g = m.groups()
            if order == "id_first":
                servers.append({"id": g[0], "name": g[0], "video": g[1], "serverId": g[2]})
            else:
                servers.append({"id": g[2], "name": g[2], "video": g[0], "serverId": g[1]})
        if servers:
            break
    if not servers:
        p3 = re.compile(r'getServer2\([^,]+,\s*(\d+)\s*,\s*(\d+)\s*\)')
        for i, (v, s) in enumerate(p3.findall(html)):
            servers.append({"id": f"s_{i}", "name": f"server_{i}", "video": v, "serverId": s})
    for srv in servers:
        m = re.search(rf'id=["\']{re.escape(srv["id"])}["\'][^>]*>([^<]*)<', html)
        if m:
            n = m.group(1).strip().replace('\n', '')
            if n:
                srv["name"] = n
    return servers


def is_valid_video_url(url, source_url=None):
    if not url or not url.startswith("http"):
        return False
    if source_url and url.rstrip("/") == source_url.rstrip("/"):
        return False
    ul = url.lower()
    return any(x in ul for x in [".m3u8", ".mp4", ".ts", "/hls/", "/master", "/playlist"])


# ============================================================
#  vinovo — fetch داخل المتصفح
# ============================================================
def try_vinovo_browser_fetch(iframe_url):
    if "vinovo.to" not in iframe_url:
        return None

    m = re.search(r'/e/([A-Za-z0-9]+)', iframe_url)
    if not m:
        return None
    file_code = m.group(1)
    base_url = iframe_url.split('/e/')[0]
    print(f"   🎯 [vinovo browser-fetch] filecode={file_code}")

    try:
        with SB(uc=True, xvfb=True, headless=False, incognito=True,
                ad_block_on=True, disable_csp=True,
                page_load_strategy="eager", locale_code="en") as sb:
            try:
                sb.activate_cdp_mode()
                sb.cdp.open(iframe_url)
                sb.cdp.sleep(8)

                fetch_js = f"""
                (async () => {{
                    try {{
                        const r = await fetch('{base_url}/api/stream', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{filecode: '{file_code}', device: 'web'}}),
                            credentials: 'include'
                        }});
                        if (!r.ok) return 'HTTP_' + r.status;
                        return await r.text();
                    }} catch(e) {{
                        return 'ERROR: ' + e.toString();
                    }}
                }})();
                """

                try:
                    result = sb.cdp.evaluate(fetch_js)
                    sb.cdp.sleep(1)
                    # أحيانًا evaluate يحتاج انتظار
                    if result and hasattr(result, '__await__'):
                        pass
                except Exception as e:
                    print(f"      ⚠️ evaluate: {str(e)[:100]}", flush=True)
                    result = None

                if result:
                    s = str(result)
                    print(f"      📊 استجابة: {s[:150]}", flush=True)
                    if s.startswith("HTTP_"):
                        print(f"      ⚠️ {s}", flush=True)
                    elif s.startswith("ERROR"):
                        print(f"      ⚠️ {s[:100]}", flush=True)
                    else:
                        try:
                            j = json.loads(result) if isinstance(result, str) else result
                            su = j.get("streaming_url") or j.get("url") or j.get("file")
                            if su:
                                print(f"      ✅ [vinovo] {su[:120]}", flush=True)
                                return su
                        except Exception:
                            mm = re.search(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', s)
                            if mm:
                                print(f"      ✅ [vinovo regex] {mm.group(1)[:120]}", flush=True)
                                return mm.group(1)
            except Exception as e:
                print(f"      ❌ {str(e)[:120]}", flush=True)
    except Exception as e:
        print(f"      ❌ {str(e)[:120]}", flush=True)

    return None


# ============================================================
#  CDP — استخراج m3u8 + cookies
# ============================================================
def extract_m3u8_cdp(iframe_url):
    print(f"   🎬 [CDP] {iframe_url[:90]}", flush=True)

    lf = tempfile.mktemp(suffix="_m3u8.txt")
    with open(lf, "w") as f:
        f.write("")

    def _log(u):
        try:
            with open(lf, "a", encoding="utf-8") as fh:
                fh.write(u + "\n")
                fh.flush()
        except Exception:
            pass

    video_duration = 0
    cookies_dict = {}

    try:
        with SB(uc=True, xvfb=True, headless=False, incognito=True,
                ad_block_on=True, disable_csp=True,
                page_load_strategy="eager", locale_code="en") as sb:
            try:
                sb.activate_cdp_mode()
                try:
                    import mycdp

                    async def on_req(e):
                        try:
                            u = e.request.url
                            _log(u)
                            if ".m3u8" in u:
                                print(f"      ✅ {u[:110]}", flush=True)
                        except Exception:
                            pass

                    async def on_res(e):
                        try:
                            _log(e.response.url)
                        except Exception:
                            pass

                    sb.cdp.add_handler(mycdp.network.RequestWillBeSent, on_req)
                    sb.cdp.add_handler(mycdp.network.ResponseReceived, on_res)
                except Exception:
                    pass

                sb.cdp.open(iframe_url)
                sb.cdp.sleep(6)

                for _ in range(3):
                    for sel in ["video", "button.vjs-big-play-button", ".jw-icon-display"]:
                        try:
                            sb.cdp.click_if_visible(sel)
                        except Exception:
                            pass
                    sb.cdp.sleep(2)

                sb.cdp.sleep(8)

                cookies_dict = get_cookies_safe(sb)
                print(f"      🍪 {len(cookies_dict)} كوكي", flush=True)

                try:
                    dur = sb.cdp.execute_script("""
                        try {
                            var v = document.querySelector('video');
                            if (v && v.duration && isFinite(v.duration)) return v.duration;
                            if (window.__PM && window.__PM.duration) return window.__PM.duration;
                            return 0;
                        } catch(e) { return 0; }
                    """)
                    if dur:
                        try:
                            video_duration = float(dur)
                        except (ValueError, TypeError):
                            pass
                except Exception:
                    pass

                try:
                    dom = sb.cdp.execute_script("""
                        return Array.from(document.querySelectorAll('video, source'))
                            .map(el => el.src || el.currentSrc).filter(s => s && s.includes('.m3u8'))[0] || null;
                    """)
                    if dom:
                        _log(dom)
                except Exception:
                    pass

            except Exception as e:
                print(f"      ❌ {str(e)[:120]}", flush=True)

    except Exception as e:
        print(f"      ❌ {str(e)[:120]}", flush=True)

    urls = []
    try:
        with open(lf, encoding="utf-8") as fh:
            urls = [u.strip() for u in fh.readlines() if u.strip()]
    except Exception:
        pass
    try:
        os.remove(lf)
    except Exception:
        pass

    print(f"      📊 {len(urls)} رابط | مدة: {video_duration:.0f}s | 🍪 {len(cookies_dict)}", flush=True)

    if 0 < video_duration < 60:
        print(f"      ⏭️ تريلر ({video_duration:.0f}s)", flush=True)
        return None, video_duration, cookies_dict

    if not urls:
        return None, video_duration, cookies_dict

    master = best_idx = any_m3u8 = None
    for u in urls:
        if ".m3u8" not in u:
            continue
        ul = u.lower()
        if "master.m3u8" in ul or "/master" in ul:
            if not master: master = u
        elif "index-" in ul or "playlist" in ul:
            if not best_idx: best_idx = u
        elif not any_m3u8:
            any_m3u8 = u

    result = master or best_idx or any_m3u8
    if result:
        print(f"      🎯 {result[:110]}", flush=True)
        return result, video_duration, cookies_dict

    return None, video_duration, cookies_dict


def try_ytdlp(iframe_url):
    """
    ✅ تخطي مواقع CF المعروفة (توفر الوقت).
    """
    if any(s in iframe_url for s in CF_SITES):
        print(f"   ⏭️ yt-dlp: تخطي (CF site)")
        return None

    try:
        opts = {
            'quiet': True, 'no_warnings': True, 'skip_download': True,
            'format': 'best[height<=720]/best',
            'nocheckcertificate': True,
            'impersonate': 'chrome',  # ✅ top-level
            'extractor_args': {'generic': ['impersonate']}
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(iframe_url, download=False)
            if info:
                c = None
                if info.get('url'):
                    c = info['url']
                elif info.get('formats'):
                    b = sorted(info['formats'], key=lambda f: f.get('height') or 0)[-1]
                    c = b.get('url')
                if c and is_valid_video_url(c, iframe_url):
                    return c
    except Exception as e:
        print(f"   ⚠️ yt-dlp: {str(e)[:90]}")
    return None


# ============================================================
#  الجلسة 1
# ============================================================
def collect_iframes(ep, series_name):
    base = f"https://u.3seq.com/video/modablaj-{series_name}-episode-{ep:02d}"
    result = []

    with SB(uc=True, xvfb=True, headless=False, incognito=True,
            ad_block_on=False, disable_csp=True,
            page_load_strategy="eager", locale_code="en") as sb:
        try:
            print(f"🖥️ [جلسة 1] {base}")
            sb.open(base)
            time.sleep(4)

            fu = sb.get_current_url()
            if not fu.endswith('/'):
                fu += '/'
            wu = fu + '?do=watch'
            print(f"📺 {wu}")
            sb.open(wu)
            time.sleep(4)

            try:
                sb.wait_for_element("ul.serversList", timeout=25)
                print("✅ السيرفرات")
            except Exception:
                print("⚠️ لا سيرفرات")
                return result

            html = sb.get_page_source()
            servers = extract_servers(html)
            if not servers:
                return result

            prio = {"luluvdo": 0, "vinovo": 1, "vidaraa": 2, "vids": 3, "vidsonic": 4, "v": 5}
            servers.sort(key=lambda s: prio.get(s.get("name", "").lower(), 99))

            print(f"📦 {len(servers)} سيرفر:")
            for s in servers:
                print(f"   - {s['name']}")

            for i, srv in enumerate(servers):
                print(f"\n🔄 [{i+1}/{len(servers)}] {srv['name']}")
                try:
                    old = None
                    try:
                        old = sb.find_element(".watch iframe").get_attribute("src")
                    except Exception:
                        pass

                    clicked = False
                    for m in ["uc_click", "js_click", "click"]:
                        try:
                            getattr(sb, m)(f"#{srv['id']}")
                            clicked = True
                            break
                        except Exception:
                            pass

                    if not clicked:
                        continue

                    new = None
                    for _ in range(10):
                        time.sleep(1)
                        try:
                            new = sb.find_element(".watch iframe").get_attribute("src")
                            if new and new != old:
                                break
                        except Exception:
                            pass

                    if not new or new == old:
                        print(f"   ⏱️ لم يتغير")
                        continue

                    print(f"   ✅ {new[:90]}")
                    result.append({"server": srv["name"], "url": new})

                except Exception as e:
                    print(f"   ❌ {str(e)[:80]}")

            return result
        except Exception as e:
            print(f"❌ {e}")
            return result


# ============================================================
#  ✅ subprocess بدون deadlock + resume
# ============================================================
def run_with_stall_detection(cmd, out_path, total_timeout, stall_timeout, tag="proc"):
    """
    ✅ الإصلاح: نكتب output إلى ملف (لا pipe → لا deadlock).
    ✅ الإرجاع: (bool, int | str)
    """
    log_path = out_path + f".{tag}.log"
    try:
        log_file = open(log_path, 'w', encoding='utf-8', errors='replace')
    except Exception as e:
        return False, f"log open failed: {e}"

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception as e:
        log_file.close()
        return False, f"spawn failed: {e}"

    start = time.time()
    last_size = 0
    last_change = start
    best_size = 0

    try:
        while proc.poll() is None:
            time.sleep(2)
            now = time.time()

            size = 0
            if os.path.exists(out_path):
                try:
                    size = os.path.getsize(out_path)
                except Exception:
                    pass
            if size > last_size:
                last_size = size
                last_change = now
                if size > best_size:
                    best_size = size

            # total timeout
            if now - start > total_timeout:
                print(f"      ⏰ {tag}: total timeout ({total_timeout}s)", flush=True)
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                log_file.close()
                _print_log_tail(log_path, 400)
                return False, f"total_timeout@size={best_size}"

            # stall
            if now - last_change > stall_timeout and size > 0:
                print(f"      🛑 {tag}: stalled at {size/(1024*1024):.2f} MB", flush=True)
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                log_file.close()
                _print_log_tail(log_path, 300)
                # ✅ إشارة خاصة للـ stall (مع الحجم) — نستخدم resume
                return False, f"stalled@size={best_size}"

    except Exception as e:
        try:
            proc.kill()
        except Exception:
            pass
        log_file.close()
        return False, f"monitor_error: {e}"

    try:
        log_file.close()
    except Exception:
        pass

    size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    if size >= MIN_VALID_SIZE:
        return True, size

    # فشل صريح — نطبع آخر السطور للمساعدة
    _print_log_tail(log_path, 300)
    return False, f"exited@size={size}"


def _print_log_tail(log_path, chars=300):
    """يطبع آخر الأحرف من ملف log للتشخيص."""
    try:
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            if content:
                tail = content[-chars:].replace('\n', ' | ')
                print(f"      📋 {tail}", flush=True)
    except Exception:
        pass


def build_ytdlp_cmd(url, out_path, referer, cookies_dict):
    origin = referer.split('/e/')[0] if '/e/' in referer else "https://u.3seq.com"

    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '--no-warnings',
        '--no-playlist',
        '--retries', '3',
        '--fragment-retries', '3',
        '--socket-timeout', '20',
        '--concurrent-fragments', '16',
        '--http-chunk-size', '10485760',
        '--buffer-size', '1M',
        '--no-check-certificate',
        '--continue',                    # ✅ استئناف
        '--impersonate', 'chrome',       # ✅ impersonation
        '--extractor-args', 'generic:impersonate',
        '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        '--referer', referer,
        '--add-header', f'Origin:{origin}',
        '--add-header', 'Accept:*/*',
        '--add-header', 'Sec-Fetch-Site:cross-site',
        '--add-header', 'Sec-Fetch-Mode:cors',
        '--add-header', 'Sec-Fetch-Dest:empty',
    ]

    if cookies_dict:
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies_dict.items() if k and v])
        if cookie_str:
            cmd += ['--add-header', f'Cookie:{cookie_str}']

    cmd += ['-f', 'best[height<=720]/best', '-o', out_path, url]
    return cmd


def build_ffmpeg_cmd(m3u8_url, out_path, referer, cookies_dict):
    origin = referer.split('/e/')[0] if '/e/' in referer else "https://u.3seq.com"

    cookie_str = ""
    if cookies_dict:
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies_dict.items() if k and v])

    headers = f"Referer: {referer}\r\nOrigin: {origin}\r\n"
    if cookie_str:
        headers += f"Cookie: {cookie_str}\r\n"
    headers += "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36\r\n"

    cmd = [
        'ffmpeg',
        '-headers', headers,
        '-user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
        '-reconnect', '1',
        '-reconnect_streamed', '1',
        '-reconnect_delay_max', '5',
        '-rw_timeout', '20000000',
        '-i', m3u8_url,
        '-c', 'copy',
        '-y', out_path,
    ]
    return cmd


def try_download_with_resume(url, out_path, referer, cookies_dict, tag="yt-dlp"):
    """
    ✅ يجرب التنزيل مع resume عند stall (لا يحذف الملف بين المحاولات).
    """
    is_m3u8 = '.m3u8' in url

    for attempt in range(MAX_DOWNLOAD_ATTEMPTS):
        if exceeded():
            return False, "global timeout"

        # في حالة ffmpeg لا يمكن الاستئناف — نحذف
        if tag == "ffmpeg" and attempt > 0 and os.path.exists(out_path):
            try: os.remove(out_path)
            except Exception: pass

        if is_m3u8 and tag == "yt-dlp":
            cmd = build_ytdlp_cmd(url, out_path, referer, cookies_dict)
        else:
            cmd = build_ffmpeg_cmd(url, out_path, referer, cookies_dict)

        print(f"   [{tag} attempt {attempt+1}/{MAX_DOWNLOAD_ATTEMPTS}]", flush=True)
        ok, info = run_with_stall_detection(
            cmd, out_path, DOWNLOAD_TIMEOUT, STALL_TIMEOUT, tag
        )

        if ok:
            return True, info

        # فحص إن كان stall مع تقدم — نعيد المحاولة (resume)
        if isinstance(info, str) and "stalled@size=" in info:
            try:
                partial = int(info.split("stalled@size=")[1])
                if partial >= MIN_PARTIAL_SIZE and attempt + 1 < MAX_DOWNLOAD_ATTEMPTS:
                    print(f"   🔄 resume من {partial/(1024*1024):.1f} MB...", flush=True)
                    continue
            except Exception:
                pass
        # أي خطأ آخر — خروج
        break

    return False, info


def download_video(url, out_path, referer, cookies_dict=None):
    """
    ✅ يجرّب yt-dlp ثم ffmpeg.
    ✅ الإرجاع موحّد: (bool, int | str)
    """
    # 1) yt-dlp
    ok, info = try_download_with_resume(url, out_path, referer, cookies_dict, tag="yt-dlp")
    if ok:
        return True, info
    print(f"   ⚠️ yt-dlp: {info}", flush=True)

    # 2) ffmpeg (احتياطي — فقط للـ m3u8)
    if ".m3u8" in url:
        if os.path.exists(out_path):
            try: os.remove(out_path)
            except Exception: pass
        ok, info = try_download_with_resume(url, out_path, referer, cookies_dict, tag="ffmpeg")
        if ok:
            return True, info
        print(f"   ⚠️ ffmpeg: {info}", flush=True)

    return False, info


# ============================================================
#  ضغط (بدون تغيير)
# ============================================================
def compress_144p(inp, out):
    if not os.path.exists(inp):
        return False
    im = os.path.getsize(inp) / (1024*1024)
    print(f"   🗜️ {im:.2f} MB → 144p...")
    cmd = [
        'ffmpeg', '-i', inp,
        '-vf', 'scale=-2:144',
        '-c:v', 'libx264', '-crf', '28', '-preset', 'veryfast',
        '-c:a', 'aac', '-b:a', '64k',
        '-movflags', '+faststart',
        '-y', out,
    ]
    try:
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0 or not os.path.exists(out):
            print(f"   ❌ {r.stderr[-180:]}")
            return False
        om = os.path.getsize(out) / (1024*1024)
        print(f"   ✅ {im:.2f}→{om:.2f} MB في {time.time()-t0:.1f}s")
        return True
    except Exception as e:
        print(f"   ❌ {e}")
        return False


def thumb(vp, tp):
    cmd = ['ffmpeg', '-ss', '00:00:05', '-i', vp, '-vframes', '1',
           '-vf', 'scale=320:180', '-f', 'image2', '-y', tp]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0 and os.path.exists(tp)
    except Exception:
        return False


def meta(vp):
    w, h, d = 1280, 720, 0
    try:
        p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                            '-show_entries', 'stream=width,height,duration',
                            '-of', 'csv=p=0', vp],
                           capture_output=True, text=True, timeout=15)
        if p.returncode == 0:
            parts = p.stdout.strip().split(',')
            if len(parts) >= 2:
                try: w, h = int(parts[0]), int(parts[1])
                except: pass
            if len(parts) >= 3 and parts[2]:
                try: d = int(float(parts[2]))
                except: pass
    except Exception:
        pass
    return w, h, d


async def upload(fp, caption, tp=None):
    if TEST_MODE and SKIP_UPLOAD:
        print(f"🧪 SKIP_UPLOAD: {fp} ({os.path.getsize(fp)/(1024*1024):.2f} MB)")
        return True
    if app is None or not os.path.exists(fp):
        return False

    mb = os.path.getsize(fp) / (1024*1024)
    print(f"   📤 {mb:.2f} MB...")
    w, h, d = meta(fp)
    t = tp if tp and os.path.exists(tp) else None
    try:
        t0 = time.time()
        await app.send_video(chat_id=TELEGRAM_CHANNEL, video=fp, caption=caption,
                             supports_streaming=True, width=w, height=h,
                             duration=d, thumb=t)
        print(f"   ✅ {time.time()-t0:.1f}s")
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await upload(fp, caption, tp)
    except Exception as e:
        print(f"   ❌ {str(e)[:150]}")
        return False


# ============================================================
#  معالجة حلقة
# ============================================================
async def process_episode(ep, sn, sn_ar, season, ddir):
    print(f"\n🎬 Ep {ep:02d}  [{elapsed_str()}]  ⏳ {remaining()//60}m")

    tmp = os.path.join(ddir, f"temp_{ep:02d}.mp4")
    fin = os.path.join(ddir, f"final_{ep:02d}.mp4")
    thb = os.path.join(ddir, f"thumb_{ep:02d}.jpg")

    try:
        print(f"\n{'='*60}")
        print("📡 جمع iframes")
        print(f"{'='*60}")

        iframes = await asyncio.to_thread(collect_iframes, ep, sn)
        if not iframes:
            return False, "لا iframes"

        print(f"\n📋 {len(iframes)} iframe")

        # ✅ نجمع كل النتائج (نجاح كامل + partial)
        full_success = None
        partial_candidate = None   # (method, size, url)

        for i, it in enumerate(iframes):
            if exceeded():
                break

            print(f"\n{'='*60}")
            print(f"🎬 [{i+1}/{len(iframes)}] {it['server']}")
            print(f"{'='*60}")

            cands = []
            skip_iframe = False

            # 1) vinovo — browser fetch
            if "vinovo.to" in it["url"]:
                print(f"   [1/3] vinovo browser-fetch...")
                v = await asyncio.to_thread(try_vinovo_browser_fetch, it["url"])
                if v:
                    cands.append(("vinovo-fetch", v, None))

            # 2) yt-dlp discovery
            print(f"   [2/3] yt-dlp discovery...")
            v = await asyncio.to_thread(try_ytdlp, it["url"])
            if v:
                cands.append(("yt-dlp-disc", v, None))

            # 3) CDP extraction + cookies
            print(f"   [3/3] CDP extraction...")
            v, dur, ck = await asyncio.to_thread(extract_m3u8_cdp, it["url"])
            if 0 < dur < 60:
                skip_iframe = True
            if v:
                cands.append(("CDP", v, ck))

            if skip_iframe and not cands:
                print(f"   ⏭️ تريلر")
                continue

            if not cands:
                print(f"   ❌ لا مرشحين")
                continue

            for src, url, ck in cands:
                if exceeded():
                    break

                print(f"\n   ⬇️ ({src}) total={DOWNLOAD_TIMEOUT}s stall={STALL_TIMEOUT}s...")
                t0 = time.time()
                ok, info = await asyncio.to_thread(
                    download_video, url, tmp, it["url"], ck
                )
                dt = time.time() - t0

                if ok and isinstance(info, (int, float)):
                    size = int(info)
                    size_mb = size / (1024*1024)
                    speed = size_mb / max(dt, 0.1)
                    print(f"   📦 ({src}) {size_mb:.2f} MB في {dt:.1f}s ≈ {speed:.2f} MB/s")

                    # ✅ فحص المدة
                    actual_dur = 0
                    if os.path.exists(tmp):
                        _, _, actual_dur = meta(tmp)

                    print(f"   🎞️ مدة التنزيل: {actual_dur}s ({actual_dur//60}m)")

                    if actual_dur >= MIN_EPISODE_DURATION:
                        full_success = (src, size, it["url"])
                        print(f"   ✅ نجاح كامل!")
                        break
                    else:
                        # partial — نحفظه كمرشح ونستمر بالبحث
                        if size > (partial_candidate[1] if partial_candidate else 0):
                            if partial_candidate and os.path.exists(tmp):
                                # نحفظه تحت اسم مختلف
                                partial_path = os.path.join(ddir, f"partial_{ep:02d}_{src}.mp4")
                                try:
                                    shutil.move(tmp, partial_path)
                                    partial_candidate = (src, size, it["url"], partial_path, actual_dur)
                                except Exception:
                                    partial_candidate = (src, size, it["url"], tmp, actual_dur)
                            else:
                                partial_candidate = (src, size, it["url"], tmp, actual_dur)
                            print(f"   ♻️ partial candidate: {size_mb:.2f} MB / {actual_dur}s")

                        # نظّف tmp للمحاولة التالية (إن لم ننقله)
                        if os.path.exists(tmp) and (not partial_candidate or partial_candidate[3] != tmp):
                            try: os.remove(tmp)
                            except Exception: pass
                        else:
                            # الملف نُقل بالفعل — نظّف tmp إن وُجد
                            if os.path.exists(tmp):
                                try: os.remove(tmp)
                                except Exception: pass

                elif ok and not isinstance(info, (int, float)):
                    print(f"   ⚠️ ({src}) نجاح بدون حجم: {info}")
                else:
                    print(f"   ❌ ({src}) {info} في {dt:.1f}s")
                    if os.path.exists(tmp):
                        try: os.remove(tmp)
                        except Exception: pass

            if full_success:
                break

        # ✅ اختيار النتيجة النهائية
        if full_success:
            method, size, url = full_success
            print(f"\n🎥 نجح كامل: {method} | {size/(1024*1024):.2f} MB")
        elif partial_candidate:
            method, size, url, partial_path, dur = partial_candidate
            print(f"\n♻️ قبول partial: {method} | {size/(1024*1024):.2f} MB / {dur}s")
            # ننقل partial إلى tmp
            try:
                if partial_path != tmp:
                    shutil.move(partial_path, tmp)
            except Exception as e:
                print(f"   ❌ فشل نقل partial: {e}")
                return False, "partial move failed"
        else:
            return False, "فشل من جميع السيرفرات"

        # ضغط
        print(f"\n🗜️ ضغط...")
        if SKIP_COMPRESS:
            shutil.copy2(tmp, fin)
        else:
            if not compress_144p(tmp, fin):
                shutil.copy2(tmp, fin)

        if not os.path.exists(fin):
            return False, "لا ملف نهائي"

        print(f"\n🖼️ Thumbnail...")
        thumb(fin, thb)

        print(f"\n📤 رفع...")
        cap = f"{sn_ar} الموسم {season} الحلقة {ep}"
        ok = await upload(fin, cap, thb if os.path.exists(thb) else None)

        if not (TEST_MODE and KEEP_VIDEO):
            for f in [tmp, fin, thb]:
                try:
                    if os.path.exists(f): os.remove(f)
                except: pass
        else:
            print(f"🧪 KEEP: {fin}")

        return ok, "تم" if ok else "فشل الرفع"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"خطأ: {e}"


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
    print("🎬 Video Downloader v5")
    if TEST_MODE: print("🧪 TEST_MODE")
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS//60}m")
    print(f"⬇️ Total: {DOWNLOAD_TIMEOUT}s | Stall: {STALL_TIMEOUT}s | Attempts: {MAX_DOWNLOAD_ATTEMPTS}")
    print(f"🎞️ الحد الأدنى للحلقة: {MIN_EPISODE_DURATION}s")
    print("=" * 60)

    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg")
    except Exception:
        print("❌ ffmpeg")

    check_ytdlp_version()

    cfg = load_config()
    sn = str(cfg.get("series_name", "")).strip().replace(' ', '-')
    snar = str(cfg.get("series_name_arabic", "")).strip() or sn
    season = int(cfg.get("season_num", 1))
    s_ep = int(cfg.get("start_episode", 1))
    e_ep = int(cfg.get("end_episode", 1))

    if not sn:
        print("❌ اسم المسلسل")
        return
    if e_ep - s_ep + 1 > 25:
        e_ep = s_ep + 24

    print(f"📺 {sn} / {snar}")
    print(f"🎬 {s_ep} → {e_ep}")

    if not await setup_telegram():
        return

    ddir = f"downloads_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(ddir, exist_ok=True)

    ok_n = 0
    failed = []
    skipped = []
    total = e_ep - s_ep + 1

    for ep in range(s_ep, e_ep + 1):
        if exceeded():
            print(f"\n⏰ حد زمني. متبقي: {list(range(ep, e_ep+1))}")
            skipped = list(range(ep, e_ep + 1))
            break

        ok, msg = await process_episode(ep, sn, snar, season, ddir)
        if ok:
            ok_n += 1
            print(f"✅ {ep}  [{elapsed_str()}]")
        else:
            failed.append(ep)
            print(f"❌ {ep}: {msg}  [{elapsed_str()}]")

        if ep < e_ep:
            if exceeded():
                skipped = list(range(ep + 1, e_ep + 1))
                break
            w = random.randint(WAIT_MIN, WAIT_MAX)
            print(f"⏳ {w}s... [متبقي {remaining()//60}m]")
            await asyncio.sleep(w)

    print(f"\n{'='*60}")
    print(f"⏱️ {elapsed_str()}")
    print(f"✅ {ok_n}/{total}")
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
