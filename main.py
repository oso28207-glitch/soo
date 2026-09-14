#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - u.3seq.com/.cam
v12 — Updated tools + expected duration + natural exit + resume + retries
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

# ===== الحدود الجديدة =====
MIN_VALID_SIZE = 100 * 1024
MIN_PARTIAL_ACCEPT = 30 * 1024 * 1024
MIN_EPISODE_DURATION = 900             # 15 دقيقة — الحد الأدنى للحلقة
NATURAL_EXIT_MIN_DURATION = 300        # 5 دقائق — لو انتهى طبيعياً، يكفي
MAX_RUNTIME_SECONDS = 165 * 60
WAIT_MIN, WAIT_MAX = 10, 20

# ✅ timeouts كافية
YTDLP_TIMEOUT = 3600                   # 60 دقيقة
FFMPEG_TIMEOUT = 3600                  # 60 دقيقة
STALL_TIMEOUT = 300                    # 5 دقائق
FILE_CREATE_TIMEOUT = 45
MAX_DOWNLOAD_ATTEMPTS = 3              # ✅ 3 محاولات مع resume

CF_SITES = ['vinovo.to', 'lulushort', 'luluvid']

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


# ============================================================
#  ✅ v12: أحدث الإصدارات
# ============================================================
def install_requirements():
    print("📦 Installing requirements (updated versions)...")
    reqs = [
        "yt-dlp[default,curl-cffi]>=2026.08.19",   # ✅ أحدث
        "seleniumbase>=4.52.0",                     # ✅ أحدث
        "beautifulsoup4>=4.13.0",
        "curl_cffi>=0.15.0",                        # ✅ مستقر
        "pyrogram>=2.0.106",                        # ✅ أحدث
        "tgcrypto>=1.2.5",
    ]
    for r in reqs:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install",
                                   "--upgrade", r, "--quiet"])
            print(f"  ✅ {r.split('>=')[0].split('[')[0]}")
        except Exception as e:
            print(f"  ⚠️ Failed: {r} ({str(e)[:60]})")


install_requirements()

import yt_dlp
from seleniumbase import SB
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

app = None
if not (TEST_MODE and SKIP_UPLOAD):
    from pyrogram import Client
    from pyrogram.errors import FloodWait


# ============================================================
#  Telegram
# ============================================================
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
#  Cookies
# ============================================================
def get_cookies_safe(sb):
    cookies_dict = {}
    try:
        for c in sb.driver.get_cookies():
            n = c.get("name", "")
            v = c.get("value", "")
            if n and v:
                cookies_dict[n] = v
    except Exception:
        pass

    if not cookies_dict:
        try:
            r = sb.driver.execute_cdp_cmd("Network.getAllCookies", {})
            for c in r.get("cookies", []):
                n = c.get("name", "")
                v = c.get("value", "")
                if n and v:
                    cookies_dict[n] = v
        except Exception:
            pass

    return cookies_dict


def sanitize_cookies(cookies_dict):
    if not cookies_dict:
        return {}
    clean = {}
    for k, v in cookies_dict.items():
        if not k or not v:
            continue
        k2 = str(k).strip().replace('\n', '').replace('\r', '')
        v2 = str(v).strip().replace('\n', '').replace('\r', '')
        if k2 and v2:
            clean[k2] = v2
    return clean


def get_all_cookies_string(cookies_dict):
    """✅ v12: كل الكوكيز بدون استثناء"""
    clean = sanitize_cookies(cookies_dict)
    if not clean:
        return ""
    parts = [f"{k}={v}" for k, v in clean.items()]
    s = "; ".join(parts)
    if len(s) > 6000:
        s = s[:6000]
    return s


# ============================================================
#  ✅ v12: استخراج المدة المتوقعة من m3u8
# ============================================================
def get_expected_duration(m3u8_url, referer, cookies_dict):
    """يستخرج المدة المتوقعة من m3u8 (مجموع EXTINF)."""
    try:
        cookie_str = get_all_cookies_string(cookies_dict)
        headers = {
            "Referer": referer,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        if cookie_str:
            headers["Cookie"] = cookie_str

        resp = cffi_requests.get(m3u8_url, headers=headers,
                                  impersonate="chrome120", timeout=15)
        if resp.status_code != 200:
            return 0

        total = 0.0
        for line in resp.text.splitlines():
            m = re.match(r'#EXTINF:([\d.]+)', line.strip())
            if m:
                total += float(m.group(1))
        return int(total)
    except Exception:
        return 0


# ============================================================
#  Extract servers
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
#  vinovo
# ============================================================
def try_vinovo_via_cdp(sb, iframe_url):
    if "vinovo.to" not in iframe_url:
        return None

    m = re.search(r'/e/([A-Za-z0-9]+)', iframe_url)
    if not m:
        return None
    file_code = m.group(1)
    base_url = iframe_url.split('/e/')[0]

    cookies_dict = get_cookies_safe(sb)
    print(f"      🍪 {len(cookies_dict)} كوكي لـ vinovo", flush=True)

    token = None
    try:
        html = sb.get_page_source()
        tm = re.search(r'name="token"\s+content="([^"]+)"', html)
        if tm:
            token = tm.group(1)
    except Exception:
        pass

    headers = {
        "Content-Type": "application/json",
        "Referer": iframe_url,
        "Origin": base_url,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    if token:
        headers["X-CSRF-TOKEN"] = token

    try:
        resp = cffi_requests.post(
            f"{base_url}/api/stream",
            json={"filecode": file_code, "device": "web"},
            headers=headers,
            cookies=cookies_dict,
            impersonate="chrome120",
            timeout=20,
        )
        print(f"      📊 vinovo API HTTP: {resp.status_code}", flush=True)
        if resp.status_code == 200:
            try:
                data = resp.json()
                su = data.get("streaming_url") or data.get("url") or data.get("file")
                if su:
                    print(f"      ✅ [vinovo] {su[:120]}", flush=True)
                    return su
            except Exception:
                pass
            mm = re.search(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', resp.text)
            if mm:
                print(f"      ✅ [vinovo regex] {mm.group(1)[:120]}", flush=True)
                return mm.group(1)
        elif resp.status_code == 403:
            print(f"      ⚠️ CF 403", flush=True)
    except Exception as e:
        print(f"      ⚠️ vinovo: {str(e)[:100]}", flush=True)

    return None


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
                sb.cdp.sleep(7)

                api_result = try_vinovo_via_cdp(sb, iframe_url)
                if api_result:
                    return api_result

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
                except Exception as e:
                    print(f"      ⚠️ evaluate: {str(e)[:100]}", flush=True)
                    result = None

                if result:
                    s = str(result)
                    if not s.startswith("HTTP_") and not s.startswith("ERROR"):
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
#  CDP — extract m3u8
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
    if any(s in iframe_url for s in CF_SITES):
        print(f"   ⏭️ yt-dlp: تخطي (CF site)")
        return None

    try:
        opts = {
            'quiet': True, 'no_warnings': True, 'skip_download': True,
            'format': 'best[height<=720]/best',
            'nocheckcertificate': True,
            'impersonate': 'chrome',
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
#  Session 1
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

            # ✅ ترتيب: vidsonic أولاً (الأكثر نجاحاً)، ثم luluvdo
            prio = {"vidsonic": 0, "luluvdo": 1, "vinovo": 2, "vidaraa": 3, "vids": 4, "v": 5, "playmate": 6}
            servers.sort(key=lambda s: prio.get(s.get("name", "").lower(), 99))

            print(f"📦 {len(servers)} سيرفر (مرتبة):")
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
#  Subprocess + stall detection
# ============================================================
def _check_file_created(out_path):
    for path in [out_path, out_path + ".part", out_path + ".ytdl", out_path + ".temp"]:
        if os.path.exists(path):
            try:
                if os.path.getsize(path) > 0:
                    return True
            except Exception:
                pass
    try:
        dir_name = os.path.dirname(out_path)
        base_name = os.path.basename(out_path)
        if os.path.exists(dir_name):
            for f in os.listdir(dir_name):
                if f.startswith(base_name) and f != out_path:
                    full = os.path.join(dir_name, f)
                    try:
                        if os.path.isfile(full) and os.path.getsize(full) > 0:
                            return True
                    except Exception:
                        pass
    except Exception:
        pass
    return False


def _get_current_size(out_path):
    total = 0
    try:
        if os.path.exists(out_path):
            total += os.path.getsize(out_path)
    except Exception:
        pass
    try:
        dir_name = os.path.dirname(out_path)
        base_name = os.path.basename(out_path)
        if os.path.exists(dir_name):
            for f in os.listdir(dir_name):
                if f.startswith(base_name) and f != out_path:
                    full = os.path.join(dir_name, f)
                    try:
                        if os.path.isfile(full):
                            total += os.path.getsize(full)
                    except Exception:
                        pass
    except Exception:
        pass
    return total


def run_with_stall_detection(cmd, out_path, total_timeout, stall_timeout, tag="proc"):
    """✅ v12: يعيد (ok, info, natural_exit)"""
    log_path = out_path + f".{tag}.log"
    try:
        log_file = open(log_path, 'w', encoding='utf-8', errors='replace')
    except Exception as e:
        return False, f"log_open_failed: {e}", False

    try:
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True)
    except Exception as e:
        log_file.close()
        return False, f"spawn_failed: {e}", False

    start = time.time()
    last_size = 0
    last_change = start
    best_size = 0
    last_report = start
    file_created = False

    try:
        while proc.poll() is None:
            time.sleep(3)
            now = time.time()

            size = _get_current_size(out_path)
            if not file_created:
                file_created = _check_file_created(out_path)

            if size > last_size:
                last_size = size
                last_change = now
                if size > best_size:
                    best_size = size

            if now - last_report > 30:
                el = now - start
                mb = size / (1024*1024)
                stall_s = now - last_change
                print(f"      ⏱️  {tag}: {mb:.1f} MB | {el:.0f}s | stall={stall_s:.0f}s", flush=True)
                last_report = now

            if not file_created and (now - start) > FILE_CREATE_TIMEOUT:
                print(f"      🚫 {tag}: لم يُنشأ ملف خلال {FILE_CREATE_TIMEOUT}s — إلغاء", flush=True)
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                log_file.close()
                _print_log_tail(log_path, 300)
                return False, f"no_file_{FILE_CREATE_TIMEOUT}s", False

            if now - start > total_timeout:
                print(f"      ⏰ {tag}: total timeout ({total_timeout}s), size={best_size/(1024*1024):.1f} MB", flush=True)
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                log_file.close()
                if best_size >= MIN_PARTIAL_ACCEPT:
                    print(f"      ♻️ قبول partial ({best_size/(1024*1024):.1f} MB)", flush=True)
                    return True, best_size, False
                return False, f"total_timeout@size={best_size}", False

            if now - last_change > stall_timeout and size > 0:
                print(f"      🛑 {tag}: stalled at {size/(1024*1024):.1f} MB", flush=True)
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                log_file.close()
                if best_size >= MIN_PARTIAL_ACCEPT:
                    print(f"      ♻️ قبول partial ({best_size/(1024*1024):.1f} MB)", flush=True)
                    return True, best_size, False
                return False, f"stalled@size={best_size}", False

    except Exception as e:
        try: proc.kill()
        except: pass
        log_file.close()
        return False, f"monitor_error: {e}", False

    try: log_file.close()
    except: pass

    exit_code = proc.returncode
    size = _get_current_size(out_path)
    natural_exit = (exit_code == 0)

    if size >= MIN_VALID_SIZE:
        return True, size, natural_exit
    _print_log_tail(log_path, 400)
    return False, f"exited@size={size}", natural_exit


def _print_log_tail(log_path, chars=400):
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
        '--no-part',
        '--retries', '10',                       # ✅ 10 بدل 5
        '--fragment-retries', '10',              # ✅ 10 بدل 5
        '--socket-timeout', '60',                # ✅ 60s بدل 30
        '--concurrent-fragments', '32',
        '--http-chunk-size', '10485760',
        '--buffer-size', '1M',
        '--no-check-certificate',
        '--continue',
        '--hls-use-mpegts',
        '--hls-prefer-native',                   # ✅ HLS native
        '--no-abort-on-error',                   # ✅ استمر عند فشل جزء
        '--file-access-retries', '10',           # ✅ إعادة محاولة الملف
        '--extractor-retries', '5',              # ✅ إعادة محاولة الاستخراج
        '--impersonate', 'chrome',
        '--extractor-args', 'generic:impersonate',
        '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        '--referer', referer,
        '--add-header', f'Origin:{origin}',
        '--add-header', 'Accept:*/*',
        '--add-header', 'Accept-Language:ar,en-US;q=0.9,en;q=0.8',
        '--add-header', 'Sec-Fetch-Site:cross-site',
        '--add-header', 'Sec-Fetch-Mode:cors',
        '--add-header', 'Sec-Fetch-Dest:empty',
    ]

    cookie_str = get_all_cookies_string(cookies_dict)
    if cookie_str:
        cmd += ['--add-header', f'Cookie:{cookie_str}']

    cmd += ['-f', 'best[height<=720]/best', '-o', out_path, url]
    return cmd


def build_ffmpeg_cmd(m3u8_url, out_path, referer, cookies_dict):
    origin = referer.split('/e/')[0] if '/e/' in referer else "https://u.3seq.com"

    cookie_str = get_all_cookies_string(cookies_dict)

    header_lines = [
        f"Referer: {referer}",
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept: */*",
        "Accept-Language: ar,en-US;q=0.9,en;q=0.8",
    ]
    if cookie_str:
        header_lines.append(f"Cookie: {cookie_str}")

    headers = "\r\n".join(header_lines) + "\r\n"

    cmd = [
        'ffmpeg',
        '-hide_banner',
        '-loglevel', 'warning',
        '-err_detect', 'ignore_err',
        '-fflags', '+discardcorrupt+genpts',
        '-analyzeduration', '100M',
        '-probesize', '100M',
        '-headers', headers,
        '-protocol_whitelist', 'file,http,https,tcp,tls,crypto,data',
        '-allowed_extensions', 'ALL',
        '-reconnect', '1',
        '-reconnect_streamed', '1',
        '-reconnect_at_eof', '1',                # ✅ إعادة الاتصال عند EOF
        '-reconnect_delay_max', '10',
        '-rw_timeout', '30000000',
        '-multiple_requests', '1',
        '-i', m3u8_url,
        '-c', 'copy',
        '-f', 'mpegts',
        '-y', out_path,
    ]
    return cmd


def download_video(url, out_path, referer, cookies_dict=None):
    """✅ v12: يعيد (ok, info, natural_exit)"""
    if os.path.exists(out_path):
        try: os.remove(out_path)
        except Exception: pass

    print(f"   [yt-dlp] timeout={YTDLP_TIMEOUT}s...", flush=True)
    cmd = build_ytdlp_cmd(url, out_path, referer, cookies_dict)
    ok, info, natural = run_with_stall_detection(cmd, out_path, YTDLP_TIMEOUT, STALL_TIMEOUT, "yt-dlp")
    if ok:
        return True, info, natural
    print(f"   ⚠️ yt-dlp: {info}", flush=True)

    if ".m3u8" not in url:
        return False, info, False

    # تنظيف الملفات الجزئية
    try:
        for f in [out_path, out_path + ".part", out_path + ".ytdl"]:
            if os.path.exists(f):
                os.remove(f)
    except Exception:
        pass

    print(f"   [ffmpeg] timeout={FFMPEG_TIMEOUT}s...", flush=True)
    cmd = build_ffmpeg_cmd(url, out_path, referer, cookies_dict)
    ok, info, natural = run_with_stall_detection(cmd, out_path, FFMPEG_TIMEOUT, STALL_TIMEOUT, "ffmpeg")
    if ok:
        return True, info, natural
    print(f"   ⚠️ ffmpeg: {info}", flush=True)

    return False, info, False


# ============================================================
#  Compression
# ============================================================
def compress_144p(inp, out):
    if not os.path.exists(inp):
        print("   ❌ الملف المصدر غير موجود")
        return False

    im = os.path.getsize(inp) / (1024 * 1024)
    print(f"   🗜️ {im:.2f} MB → 144p...")

    cmd = [
        'ffmpeg',
        '-err_detect', 'ignore_err',
        '-fflags', '+discardcorrupt+genpts',
        '-analyzeduration', '100M',
        '-probesize', '100M',
        '-i', inp,
        '-vf', 'scale=-2:144',
        '-c:v', 'libx264',
        '-crf', '28',
        '-preset', 'veryfast',
        '-c:a', 'aac',
        '-b:a', '64k',
        '-f', 'mp4',
        '-movflags', '+faststart',
        '-max_muxing_queue_size', '4096',
        '-y', out,
    ]

    try:
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        dt = time.time() - t0

        if r.returncode != 0:
            print(f"   ❌ ffmpeg code={r.returncode}")
            if r.stderr:
                print(f"      📋 {r.stderr[-300:]}")
            return False

        if not os.path.exists(out) or os.path.getsize(out) < 10 * 1024:
            print(f"   ❌ الناتج صغير جداً")
            return False

        om = os.path.getsize(out) / (1024 * 1024)
        print(f"   ✅ {im:.2f}→{om:.2f} MB في {dt:.1f}s")
        return True
    except subprocess.TimeoutExpired:
        print(f"   ❌ ffmpeg timeout")
        return False
    except Exception as e:
        print(f"   ❌ {e}")
        return False


# ============================================================
#  Metadata & Validation
# ============================================================
def meta(vp):
    w, h, d = 0, 0, 0
    try:
        p = subprocess.run(
            ['ffprobe', '-v', 'error',
             '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height',
             '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1',
             vp],
            capture_output=True, text=True, timeout=15,
        )
        if p.returncode != 0:
            return 0, 0, 0

        lines = [l.strip() for l in p.stdout.strip().split('\n') if l.strip()]
        if len(lines) >= 2:
            try:
                w = int(float(lines[0]))
                h = int(float(lines[1]))
            except (ValueError, IndexError):
                return 0, 0, 0
        if len(lines) >= 3:
            try:
                d = int(float(lines[2]))
            except ValueError:
                d = 0
    except Exception:
        return 0, 0, 0

    return w, h, d


def is_valid_video_file(vp):
    try:
        p = subprocess.run(
            ['ffprobe', '-v', 'error',
             '-select_streams', 'v:0',
             '-show_entries', 'stream=codec_type',
             '-of', 'csv=p=0', vp],
            capture_output=True, text=True, timeout=10,
        )
        return p.returncode == 0 and 'video' in p.stdout.lower()
    except Exception:
        return False


def thumb(vp, tp):
    for ss in ['00:00:05', '00:00:01', '00:00:00']:
        cmd = [
            'ffmpeg', '-err_detect', 'ignore_err',
            '-fflags', '+discardcorrupt',
            '-ss', ss,
            '-i', vp,
            '-vframes', '1',
            '-vf', 'scale=320:180',
            '-f', 'image2',
            '-y', tp,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30)
            if r.returncode == 0 and os.path.exists(tp) and os.path.getsize(tp) > 1024:
                return True
        except Exception:
            pass
    return False


# ============================================================
#  Upload
# ============================================================
async def upload(fp, caption, tp=None):
    if TEST_MODE and SKIP_UPLOAD:
        print(f"🧪 SKIP_UPLOAD: {fp} ({os.path.getsize(fp)/(1024*1024):.2f} MB)")
        return True

    if app is None or not os.path.exists(fp):
        print(f"   ❌ لا يوجد ملف")
        return False

    if not is_valid_video_file(fp):
        print(f"   ⚠️ الملف ليس فيديو صالح")

    w, h, d = meta(fp)
    if w == 0 or h == 0:
        w, h = 640, 360
    if d == 0:
        try:
            size_mb = os.path.getsize(fp) / (1024 * 1024)
            d = int(size_mb * 5)
        except Exception:
            d = 60

    mb = os.path.getsize(fp) / (1024 * 1024)
    print(f"   📤 رفع {mb:.2f} MB | {w}x{h} | {d}s...")

    t = tp if tp and os.path.exists(tp) else None

    try:
        t0 = time.time()
        await app.send_video(
            chat_id=TELEGRAM_CHANNEL,
            video=fp,
            caption=caption,
            supports_streaming=True,
            width=w,
            height=h,
            duration=d,
            thumb=t,
        )
        print(f"   ✅ رُفع في {time.time()-t0:.1f}s")
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await upload(fp, caption, tp)
    except Exception as e:
        print(f"   ❌ فشل رفع: {str(e)[:200]}")

    try:
        print(f"   🔄 محاولة ثانية بدون thumbnail...")
        await app.send_video(
            chat_id=TELEGRAM_CHANNEL,
            video=fp,
            caption=caption,
            supports_streaming=True,
            width=w,
            height=h,
            duration=d,
        )
        print(f"   ✅ رُفع في المحاولة الثانية")
        return True
    except Exception as e2:
        print(f"   ❌ فشلت الثانية: {str(e2)[:150]}")
        return False


# ============================================================
#  process_episode
# ============================================================
async def process_episode(ep, sn, sn_ar, season, ddir):
    print(f"\n🎬 Ep {ep:02d}  [{elapsed_str()}]  ⏳ {remaining()//60}m")

    tmp_ts = os.path.join(ddir, f"temp_{ep:02d}.ts")
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

        success_if = None
        dloaded = 0
        method = None
        partial_candidate = None

        for i, it in enumerate(iframes):
            if exceeded():
                break

            print(f"\n{'='*60}")
            print(f"🎬 [{i+1}/{len(iframes)}] {it['server']}")
            print(f"{'='*60}")

            cands = []
            skip_iframe = False

            if "vinovo.to" in it["url"]:
                print(f"   [1/3] vinovo CDP+cURL...")
                v = await asyncio.to_thread(try_vinovo_browser_fetch, it["url"])
                if v:
                    cands.append(("vinovo", v, None))

            print(f"   [2/3] yt-dlp discovery...")
            v = await asyncio.to_thread(try_ytdlp, it["url"])
            if v:
                cands.append(("yt-dlp-disc", v, None))

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

                # ✅ v12: المدة المتوقعة من m3u8
                expected_dur = 0
                if ".m3u8" in url:
                    expected_dur = await asyncio.to_thread(
                        get_expected_duration, url, it["url"], ck
                    )
                    if expected_dur > 0:
                        print(f"   📏 المدة المتوقعة: {expected_dur}s ({expected_dur//60}m)")

                # ✅ v12: محاولات متعددة مع resume
                attempt_success = False
                last_info = None
                last_natural = False

                for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
                    if exceeded():
                        break

                    print(f"\n   ⬇️ ({src}) attempt {attempt}/{MAX_DOWNLOAD_ATTEMPTS}...")
                    t0 = time.time()
                    ok, info, natural = await asyncio.to_thread(
                        download_video, url, tmp_ts, it["url"], ck
                    )
                    dt = time.time() - t0
                    last_info = info
                    last_natural = natural

                    if ok and isinstance(info, (int, float)):
                        size = int(info)
                        size_mb = size / (1024*1024)
                        speed = size_mb / max(dt, 0.1)
                        print(f"   📦 ({src}) {size_mb:.2f} MB في {dt:.1f}s ≈ {speed:.2f} MB/s")

                        actual_dur = 0
                        if os.path.exists(tmp_ts):
                            _, _, actual_dur = meta(tmp_ts)
                        print(f"   🎞️ مدة التنزيل: {actual_dur}s ({actual_dur//60}m{actual_dur%60}s) | انتهى طبيعياً: {natural}")

                        # ✅ v12: شروط القبول
                        is_complete = False
                        reason = ""

                        if natural and actual_dur >= NATURAL_EXIT_MIN_DURATION:
                            is_complete = True
                            reason = "انتهى طبيعياً"
                        elif actual_dur >= MIN_EPISODE_DURATION:
                            is_complete = True
                            reason = "المدة كافية"
                        elif expected_dur > 0 and actual_dur >= expected_dur - 60:
                            is_complete = True
                            reason = f"وصلنا للمدة المتوقعة ({expected_dur}s)"

                        if is_complete:
                            success_if = it["url"]
                            dloaded = size
                            method = src
                            attempt_success = True
                            print(f"   ✅ نجاح كامل ({reason})!")
                            break
                        else:
                            # partial — إذا انتهى طبيعياً، احفظه كمرشح
                            if natural and actual_dur >= NATURAL_EXIT_MIN_DURATION:
                                if size > (partial_candidate[1] if partial_candidate else 0):
                                    partial_path = os.path.join(ddir, f"partial_{ep:02d}_{src}.ts")
                                    try:
                                        if os.path.exists(partial_path):
                                            os.remove(partial_path)
                                        shutil.move(tmp_ts, partial_path)
                                        partial_candidate = (src, size, it["url"], partial_path, actual_dur)
                                        print(f"   ♻️ partial (طبيعي): {size_mb:.1f} MB / {actual_dur}s")
                                    except Exception as e:
                                        print(f"   ⚠️ نقل partial: {e}")
                                    attempt_success = True
                                    break
                            # ✅ resume — إذا لم ينته طبيعياً، حاول مرة أخرى
                            if not natural and attempt < MAX_DOWNLOAD_ATTEMPTS:
                                print(f"   🔄 resume: المحاولة {attempt+1}...")
                                continue
                            # فشل نهائي
                            if os.path.exists(tmp_ts):
                                try: os.remove(tmp_ts)
                                except Exception: pass
                    elif ok and not isinstance(info, (int, float)):
                        print(f"   ⚠️ ({src}) نجاح بدون حجم صالح: {info}")
                        if os.path.exists(tmp_ts):
                            try: os.remove(tmp_ts)
                            except: pass
                    else:
                        print(f"   ❌ ({src}) {info} في {dt:.1f}s")
                        if os.path.exists(tmp_ts):
                            try: os.remove(tmp_ts)
                            except: pass

                    if attempt_success:
                        break

                if success_if:
                    break

            if success_if:
                break

        # اختيار النتيجة
        if success_if:
            print(f"\n🎥 نجح كامل: {method} | {dloaded/(1024*1024):.2f} MB")
        elif partial_candidate:
            method, size, url, partial_path, dur = partial_candidate
            print(f"\n♻️ قبول partial: {method} | {size/(1024*1024):.2f} MB / {dur}s")
            try:
                if os.path.exists(tmp_ts):
                    os.remove(tmp_ts)
                shutil.move(partial_path, tmp_ts)
            except Exception as e:
                print(f"   ❌ نقل: {e}")
                return False, "partial move failed"
        else:
            return False, "فشل من جميع السيرفرات"

        print(f"\n🗜️ ضغط...")
        if SKIP_COMPRESS:
            shutil.copy2(tmp_ts, fin)
        else:
            if not compress_144p(tmp_ts, fin):
                print(f"   ⚠️ فشل الضغط — نسخ TS كما هو")
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
        else:
            print(f"🧪 KEEP: {fin}")

        return ok, "تم" if ok else "فشل الرفع"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"خطأ: {e}"


# ============================================================
#  Config
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


# ============================================================
#  Main
# ============================================================
async def main():
    print("=" * 60)
    print("🎬 Video Downloader v12")
    if TEST_MODE: print("🧪 TEST_MODE")
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS//60}m")
    print(f"⬇️ yt-dlp: {YTDLP_TIMEOUT}s | ffmpeg: {FFMPEG_TIMEOUT}s")
    print(f"🛑 stall: {STALL_TIMEOUT}s | file-create: {FILE_CREATE_TIMEOUT}s")
    print(f"📦 قبول partial ≥ {MIN_PARTIAL_ACCEPT//(1024*1024)} MB")
    print(f"🎞️ الحد الأدنى للحلقة: {MIN_EPISODE_DURATION}s ({MIN_EPISODE_DURATION//60}m)")
    print(f"✅ الخروج الطبيعي: {NATURAL_EXIT_MIN_DURATION}s ({NATURAL_EXIT_MIN_DURATION//60}m)")
    print(f"🔄 محاولات: {MAX_DOWNLOAD_ATTEMPTS} مع resume")
    print(f"📏 كشف المدة المتوقعة من m3u8")
    print("=" * 60)

    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ ffmpeg")
    except Exception:
        print("❌ ffmpeg")

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
