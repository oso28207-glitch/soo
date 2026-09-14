#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - u.3seq.com/.cam
v15.4 — Cross-domain cookies + fast-fail on 403
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

# ===== الحدود =====
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
MAX_DOWNLOAD_ATTEMPTS = 2

MAX_RESUME_ROUNDS = 15
RESUME_NO_PROGRESS_LIMIT = 3

MIN_ACCEPTABLE_SPEED = 300 * 1024
SPEED_CHECK_INTERVAL = 20
SPEED_GRACE_PERIOD = 30

DURATION_ACCEPT_RATIO = 0.95
CONSENSUS_TOLERANCE = 30

MIN_REAL_RATIO_AFTER_COMPRESS = 0.85
MIN_PARTIAL_REAL_DURATION = 600

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
#  ✅✅ v15.4: كوكيز كل النطاقات
# ============================================================
def get_cookies_safe(sb):
    """يجيب كل الكوكيز من كل النطاقات (لحل مشكلة tnmr.org)"""
    cookies_dict = {}
    try:
        r = sb.driver.execute_cdp_cmd("Network.getAllCookies", {})
        for c in r.get("cookies", []):
            n, v = c.get("name", ""), c.get("value", "")
            if n and v:
                cookies_dict[n] = v
    except Exception:
        pass
    if not cookies_dict:
        try:
            for c in sb.driver.get_cookies():
                n, v = c.get("name", ""), c.get("value", "")
                if n and v:
                    cookies_dict[n] = v
        except Exception:
            pass
    return cookies_dict


def get_cookies_full(sb):
    """يعيد كل الكوكيز مع domain/path/expiry لصيغة Netscape"""
    cookies = []
    try:
        r = sb.driver.execute_cdp_cmd("Network.getAllCookies", {})
        cookies = r.get("cookies", [])
    except Exception:
        pass
    if not cookies:
        try:
            cookies = sb.driver.get_cookies()
        except Exception:
            pass
    return cookies


def save_cookies_netscape(cookies_list, path):
    """يحفظ الكوكيز بصيغة Netscape مع كل domains"""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write("# Netscape HTTP Cookie File\n")
            for c in cookies_list:
                domain = c.get("domain", "")
                if not domain:
                    continue
                if not domain.startswith("."):
                    domain = "." + domain
                name = str(c.get("name", ""))
                value = str(c.get("value", "")).replace("\n", "").replace("\r", "")
                path_c = c.get("path", "/")
                secure = "TRUE" if c.get("secure", False) else "FALSE"
                expires = int(c.get("expiry", 0)) or 0
                f.write(f"{domain}\tTRUE\t{path_c}\t{secure}\t{expires}\t{name}\t{value}\n")
        return True
    except Exception:
        return False


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
    clean = sanitize_cookies(cookies_dict)
    if not clean:
        return ""
    s = "; ".join([f"{k}={v}" for k, v in clean.items()])
    return s[:8000]


# ============================================================
#  get_expected_duration (يحل master.m3u8)
# ============================================================
def get_expected_duration(m3u8_url, referer, cookies_dict):
    cookie_str = get_all_cookies_string(cookies_dict)
    headers = {
        "Referer": referer,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }
    if cookie_str:
        headers["Cookie"] = cookie_str

    def _sum_extinf(text, base_url):
        total = 0.0
        count = 0
        variants = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                m = re.match(r'#EXTINF:([\d.]+)', line)
                if m:
                    total += float(m.group(1))
                    count += 1
                continue
            if '.m3u8' in line:
                if line.startswith('http'):
                    variants.append(line)
                else:
                    variants.append(base_url.rstrip('/') + '/' + line.lstrip('/'))
        return total, count, variants

    def _fetch(url, depth=0):
        if depth > 3:
            return 0
        try:
            resp = cffi_requests.get(url, headers=headers,
                                      impersonate="chrome120", timeout=25)
            if resp.status_code != 200:
                return 0
            base_url = url.rsplit('/', 1)[0]
            total, count, variants = _sum_extinf(resp.text, base_url)
            if count > 0 and total > 0:
                return int(total)
            if variants:
                for v in variants[:3]:
                    d = _fetch(v, depth + 1)
                    if d > 0:
                        return d
            return 0
        except Exception:
            return 0

    for attempt in range(2):
        d = _fetch(m3u8_url)
        if d > 0:
            return d
        time.sleep(2)

    try:
        header_arg = f"Referer: {referer}\r\n"
        if cookie_str:
            header_arg += f"Cookie: {cookie_str}\r\n"
        header_arg += "User-Agent: Mozilla/5.0\r\n"
        p = subprocess.run(
            ['ffprobe', '-v', 'error',
             '-headers', header_arg,
             '-analyzeduration', '50M', '-probesize', '50M',
             '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', m3u8_url],
            capture_output=True, text=True, timeout=60,
        )
        if p.returncode == 0 and p.stdout.strip():
            try:
                return int(float(p.stdout.strip()))
            except Exception:
                pass
    except Exception:
        pass

    return 0


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


def try_vinovo_via_cdp(sb, iframe_url):
    if "vinovo.to" not in iframe_url:
        return None
    m = re.search(r'/e/([A-Za-z0-9]+)', iframe_url)
    if not m:
        return None
    file_code = m.group(1)
    base_url = iframe_url.split('/e/')[0]
    cookies_dict = get_cookies_safe(sb)
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
        "Referer": iframe_url, "Origin": base_url,
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    if token:
        headers["X-CSRF-TOKEN"] = token
    try:
        resp = cffi_requests.post(f"{base_url}/api/stream",
            json={"filecode": file_code, "device": "web"},
            headers=headers, cookies=cookies_dict,
            impersonate="chrome120", timeout=20)
        if resp.status_code == 200:
            try:
                data = resp.json()
                su = data.get("streaming_url") or data.get("url") or data.get("file")
                if su:
                    return su
            except Exception:
                pass
            mm = re.search(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', resp.text)
            if mm:
                return mm.group(1)
    except Exception:
        pass
    return None


def try_vinovo_browser_fetch(iframe_url):
    if "vinovo.to" not in iframe_url:
        return None
    try:
        with SB(uc=True, xvfb=True, headless=False, incognito=True,
                ad_block_on=True, disable_csp=True,
                page_load_strategy="eager", locale_code="en") as sb:
            try:
                sb.activate_cdp_mode()
                sb.cdp.open(iframe_url)
                sb.cdp.sleep(7)
                return try_vinovo_via_cdp(sb, iframe_url)
            except Exception:
                return None
    except Exception:
        return None


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
    cookies_full = []

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
                cookies_full = get_cookies_full(sb)
                print(f"      🍪 {len(cookies_dict)} كوكي (كل النطاقات)", flush=True)
                try:
                    dur = sb.cdp.execute_script("""
                        try {
                            var v = document.querySelector('video');
                            if (v && v.duration && isFinite(v.duration) && v.duration > 0) return v.duration;
                            if (window.__PM && window.__PM.duration) return window.__PM.duration;
                            return 0;
                        } catch(e) { return 0; }
                    """)
                    if dur:
                        try:
                            video_duration = float(dur)
                        except Exception:
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

    cookies_info = {"dict": cookies_dict, "list": cookies_full}

    if 0 < video_duration < 60:
        return None, video_duration, cookies_info
    if not urls:
        return None, video_duration, cookies_info

    all_m3u8 = [u for u in urls if ".m3u8" in u]
    master = [u for u in all_m3u8 if "master.m3u8" in u.lower() or "/master" in u.lower()]
    index_files = [u for u in all_m3u8 if "index-" in u.lower() or "playlist" in u.lower()]
    others = [u for u in all_m3u8 if u not in master and u not in index_files]

    ordered = master + index_files + others

    if ordered:
        print(f"      🎯 {ordered[0][:110]}", flush=True)
        return ordered, video_duration, cookies_info

    return None, video_duration, cookies_info


def try_ytdlp(iframe_url):
    if any(s in iframe_url for s in CF_SITES):
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
    except Exception:
        pass
    return None


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
            prio = {"luluvdo": 0, "vinovo": 1, "vidaraa": 2, "vids": 3, "v": 4, "vidsonic": 5, "playmate": 6}
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
                        continue
                    print(f"   ✅ {new[:90]}")
                    result.append({"server": srv["name"], "url": new})
                except Exception as e:
                    print(f"   ❌ {str(e)[:80]}")
            return result
        except Exception as e:
            print(f"❌ {e}")
            return result


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


def run_with_adaptive_monitoring(cmd, out_path, total_timeout, tag="proc"):
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
    last_speed_check = start
    last_speed_size = 0
    slow_count = 0

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

            if now - last_speed_check > SPEED_CHECK_INTERVAL:
                speed = (size - last_speed_size) / (now - last_speed_check)
                speed_kb = speed / 1024
                last_speed_check = now
                last_speed_size = size

                if (now - start) > SPEED_GRACE_PERIOD and size > 0:
                    if speed < MIN_ACCEPTABLE_SPEED:
                        slow_count += 1
                        if slow_count <= 3:
                            print(f"      🐌 {tag}: سرعة {speed_kb:.0f} KB/s (بطيء #{slow_count})", flush=True)
                        if slow_count >= 6 and (now - last_change) > STALL_TIMEOUT:
                            print(f"      🛑 {tag}: بطيء جداً — إلغاء", flush=True)
                            try:
                                proc.kill()
                                proc.wait(timeout=5)
                            except Exception:
                                pass
                            log_file.close()
                            if best_size >= MIN_PARTIAL_ACCEPT:
                                return True, best_size, False
                            return False, f"slow_speed@{best_size}", False
                    else:
                        slow_count = 0

            if not file_created and (now - start) > FILE_CREATE_TIMEOUT:
                print(f"      🚫 {tag}: لم يُنشأ ملف خلال {FILE_CREATE_TIMEOUT}s", flush=True)
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                log_file.close()
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
                    return True, best_size, False
                return False, f"total_timeout@{best_size}", False

            if now - last_change > STALL_TIMEOUT and size > 0:
                print(f"      🛑 {tag}: stalled at {size/(1024*1024):.1f} MB", flush=True)
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                log_file.close()
                if best_size >= MIN_PARTIAL_ACCEPT:
                    return True, best_size, False
                return False, f"stalled@{best_size}", False

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

    if size < 5000:
        try:
            if os.path.exists(out_path):
                with open(out_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()[:200]
                print(f"      🔍 محتوى الملف: {content[:200]}", flush=True)
        except Exception:
            pass
        _print_log_tail(log_path, 400)

    if size >= MIN_VALID_SIZE:
        return True, size, natural_exit
    return False, f"exited@{size}", natural_exit


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


# ============================================================
#  ✅✅ v15.4: build_ytdlp_cmd مع cookies file
# ============================================================
def build_ytdlp_cmd(url, out_path, referer, cookies_info, cookies_file=None):
    origin = referer.split('/e/')[0] if '/e/' in referer else "https://u.3seq.com"
    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '--no-warnings', '--no-playlist', '--no-part',
        '--retries', '20', '--fragment-retries', '50',
        '--retry-sleep', 'fragment:exp=1:20',
        '--socket-timeout', '60',
        '--concurrent-fragments', '8',
        '--http-chunk-size', '5242880',
        '--no-check-certificate', '--continue',
        '--hls-use-mpegts',
        '--hls-prefer-native',
        '--no-abort-on-error',
        '--file-access-retries', '10', '--extractor-retries', '5',
        '--impersonate', 'chrome',
        '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        '--referer', referer,
        '--add-header', f'Origin:{origin}',
        '--add-header', 'Accept:*/*',
        '--add-header', 'Sec-Fetch-Site:cross-site',
        '--add-header', 'Sec-Fetch-Mode:cors',
        '--add-header', 'Sec-Fetch-Dest:empty',
    ]
    # ✅ ملف Netscape مع كل domains
    if cookies_file and os.path.exists(cookies_file):
        cmd += ['--cookies', cookies_file]
    else:
        # fallback: header عادي
        cookie_str = ""
        if isinstance(cookies_info, dict):
            cookie_str = get_all_cookies_string(cookies_info.get("dict", {}))
        if cookie_str:
            cmd += ['--add-header', f'Cookie:{cookie_str}']
    cmd += ['-f', 'best[height<=720]/best', '-o', out_path, url]
    return cmd


def build_ffmpeg_cmd(m3u8_url, out_path, referer, cookies_info):
    origin = referer.split('/e/')[0] if '/e/' in referer else "https://u.3seq.com"
    cookie_str = ""
    if isinstance(cookies_info, dict):
        cookie_str = get_all_cookies_string(cookies_info.get("dict", {}))
    header_lines = [
        f"Referer: {referer}",
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept: */*",
    ]
    if cookie_str:
        header_lines.append(f"Cookie: {cookie_str}")
    headers = "\r\n".join(header_lines) + "\r\n"
    return [
        'ffmpeg', '-hide_banner', '-loglevel', 'warning',
        '-err_detect', 'ignore_err', '-fflags', '+discardcorrupt+genpts',
        '-analyzeduration', '100M', '-probesize', '100M',
        '-headers', headers,
        '-protocol_whitelist', 'file,http,https,tcp,tls,crypto,data',
        '-allowed_extensions', 'ALL',
        '-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_at_eof', '1',
        '-reconnect_delay_max', '10',
        '-rw_timeout', '30000000', '-multiple_requests', '1',
        '-i', m3u8_url, '-c', 'copy', '-f', 'mpegts', '-y', out_path,
    ]


# ============================================================
#  ✅✅ v15.4: download_with_resume مع fast-fail
# ============================================================
def download_with_resume(url, out_path, referer, cookies_info, expected_dur=0, cookies_file=None):
    last_size = 0
    no_progress = 0
    first_round_failed = False

    for round_num in range(MAX_RESUME_ROUNDS):
        if exceeded():
            break

        cur_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        cur_dur = 0
        if expected_dur > 0 and cur_size > 0:
            cur_dur = get_real_duration(out_path)
            if cur_dur >= int(expected_dur * DURATION_ACCEPT_RATIO):
                print(f"   ✅ اكتمل في round {round_num}: {cur_dur}/{expected_dur}s", flush=True)
                return True, cur_size, False

        print(f"\n   🔁 round {round_num+1}/{MAX_RESUME_ROUNDS} | "
              f"size={cur_size/(1024*1024):.1f} MB | dur={cur_dur}s", flush=True)

        cmd = build_ytdlp_cmd(url, out_path, referer, cookies_info, cookies_file)
        ok, info, natural = run_with_adaptive_monitoring(
            cmd, out_path, YTDLP_TIMEOUT, "yt-dlp"
        )

        new_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0

        if new_size <= cur_size:
            no_progress += 1
            print(f"   ⚠️ لا تقدم ({no_progress}/{RESUME_NO_PROGRESS_LIMIT})", flush=True)
            if round_num == 0 and no_progress >= 1:
                print(f"   🚫 فشل من أول محاولة (403 محتمل) — إيقاف", flush=True)
                first_round_failed = True
                break
            if no_progress >= RESUME_NO_PROGRESS_LIMIT:
                break
        else:
            no_progress = 0
            added = (new_size - cur_size) / (1024 * 1024)
            print(f"   ➕ أضاف {added:.1f} MB (المجموع {new_size/(1024*1024):.1f} MB)", flush=True)

        if natural and ok:
            break

        time.sleep(3)

    if os.path.exists(out_path):
        size = os.path.getsize(out_path)
        if size >= MIN_PARTIAL_ACCEPT:
            return True, size, False
    return False, ("403-fast-fail" if first_round_failed else "no progress after retries"), False


def download_video(url, out_path, referer, cookies_info=None, expected_dur=0):
    if os.path.exists(out_path):
        try: os.remove(out_path)
        except Exception: pass

    is_m3u8 = ".m3u8" in url

    # احفظ ملف كوكيز مؤقت
    cookies_file = None
    if cookies_info and isinstance(cookies_info, dict):
        cookies_list = cookies_info.get("list", [])
        if cookies_list:
            cookies_file = out_path + ".cookies.txt"
            save_cookies_netscape(cookies_list, cookies_file)

    print(f"   [yt-dlp+resume] timeout={YTDLP_TIMEOUT}s...", flush=True)
    ok, info, natural = download_with_resume(
        url, out_path, referer, cookies_info, expected_dur, cookies_file
    )
    if ok and isinstance(info, (int, float)):
        try:
            if cookies_file and os.path.exists(cookies_file):
                os.remove(cookies_file)
        except: pass
        return True, info, natural

    if is_m3u8:
        try:
            for f in [out_path + ".part", out_path + ".ytdl"]:
                if os.path.exists(f):
                    os.remove(f)
        except Exception:
            pass
        print(f"   [ffmpeg fallback] timeout={FFMPEG_TIMEOUT}s...", flush=True)
        cmd = build_ffmpeg_cmd(url, out_path, referer, cookies_info)
        ok, info, natural = run_with_adaptive_monitoring(cmd, out_path, FFMPEG_TIMEOUT, "ffmpeg")
        if ok:
            try:
                if cookies_file and os.path.exists(cookies_file):
                    os.remove(cookies_file)
            except: pass
            return True, info, natural
        print(f"   ⚠️ ffmpeg: {info}", flush=True)

    try:
        if cookies_file and os.path.exists(cookies_file):
            os.remove(cookies_file)
    except: pass

    return False, info, False


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


def meta(vp, accurate=False):
    w, h, d = 0, 0, 0
    try:
        cmd = ['ffprobe', '-v', 'error',
               '-select_streams', 'v:0',
               '-show_entries', 'stream=width,height',
               '-show_entries', 'format=duration',
               '-of', 'default=noprint_wrappers=1:nokey=1']
        if accurate:
            cmd += ['-analyzeduration', '100M', '-probesize', '100M']
        cmd.append(vp)
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


def get_real_duration(vp):
    try:
        p = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-count_packets',
             '-show_entries', 'stream=nb_read_packets,avg_frame_rate,r_frame_rate,duration',
             '-of', 'json', vp],
            capture_output=True, text=True, timeout=240,
        )
        if p.returncode == 0 and p.stdout.strip():
            try:
                data = json.loads(p.stdout)
                streams = data.get("streams", [])
                if streams:
                    s = streams[0]
                    nb = s.get("nb_read_packets")
                    fps_str = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/0"
                    if nb and fps_str and fps_str != "0/0":
                        try:
                            num, den = fps_str.split("/")
                            den_f = float(den) if den else 0
                            fps_f = float(num) / den_f if den_f != 0 else 0
                            if fps_f > 0:
                                d = int(int(nb) / fps_f)
                                if d > 0:
                                    return d
                        except Exception:
                            pass
                    dur = s.get("duration")
                    if dur:
                        try:
                            d2 = int(float(dur))
                            if d2 > 0:
                                return d2
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass
    _, _, d = meta(vp, accurate=True)
    return d


def is_valid_video_file(vp):
    try:
        p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                            '-show_entries', 'stream=codec_type',
                            '-of', 'csv=p=0', vp],
                           capture_output=True, text=True, timeout=10)
        return p.returncode == 0 and 'video' in p.stdout.lower()
    except Exception:
        return False


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


async def upload(fp, caption, tp=None, override_duration=None):
    if TEST_MODE and SKIP_UPLOAD:
        print(f"🧪 SKIP_UPLOAD: {fp} ({os.path.getsize(fp)/(1024*1024):.2f} MB)")
        return True
    if app is None or not os.path.exists(fp):
        return False

    w, h, real_d = meta(fp)
    if override_duration and override_duration > 0:
        d = int(override_duration)
        print(f"   ℹ️ المدة (override): {d}s")
    else:
        d = real_d
        if d > 0:
            print(f"   ℹ️ المدة (من MP4): {d}s")

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
        return await upload(fp, caption, tp, override_duration)
    except Exception as e:
        print(f"   ❌ فشل رفع: {str(e)[:200]}")
    try:
        print(f"   🔄 محاولة ثانية بدون thumbnail...")
        await app.send_video(chat_id=TELEGRAM_CHANNEL, video=fp, caption=caption,
                             supports_streaming=True, width=w, height=h, duration=d)
        return True
    except Exception as e2:
        print(f"   ❌ فشلت الثانية: {str(e2)[:150]}")
        return False


async def process_episode(ep, sn, sn_ar, season, ddir):
    print(f"\n🎬 Ep {ep:02d}  [{elapsed_str()}]  ⏳ {remaining()//60}m")
    tmp_ts = os.path.join(ddir, f"temp_{ep:02d}.ts")
    fin = os.path.join(ddir, f"final_{ep:02d}.mp4")
    thb = os.path.join(ddir, f"thumb_{ep:02d}.jpg")

    expected_dur_final = 0

    try:
        print(f"\n{'='*60}\n📡 جمع iframes\n{'='*60}")
        iframes = await asyncio.to_thread(collect_iframes, ep, sn)
        if not iframes:
            return False, "لا iframes"
        print(f"\n📋 {len(iframes)} iframe")

        success_if = None
        dloaded = 0
        method = None
        partials = []

        for i, it in enumerate(iframes):
            if exceeded():
                break
            print(f"\n{'='*60}\n🎬 [{i+1}/{len(iframes)}] {it['server']}\n{'='*60}")

            cands = []
            skip_iframe = False
            if "vinovo.to" in it["url"]:
                print(f"   [1/3] vinovo...")
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
                continue
            if not cands:
                print(f"   ❌ لا مرشحين")
                continue

            for src, url_or_list, ck in cands:
                if exceeded():
                    break

                urls_to_try = url_or_list if isinstance(url_or_list, list) else [url_or_list]

                for url_idx, url in enumerate(urls_to_try):
                    if exceeded():
                        break
                    if url_idx > 0:
                        print(f"\n   🔄 محاولة m3u8 بديل #{url_idx+1}...")

                    expected_dur = 0
                    if ".m3u8" in url:
                        ck_dict = ck.get("dict", {}) if isinstance(ck, dict) else (ck or {})
                        expected_dur = await asyncio.to_thread(
                            get_expected_duration, url, it["url"], ck_dict
                        )
                        if expected_dur > 0:
                            print(f"   📏 المدة المتوقعة: {expected_dur}s ({expected_dur//60}m)")
                        else:
                            print(f"   ⚠️ لا يمكن تحديد المدة المتوقعة من m3u8")

                    attempt_success = False
                    for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
                        if exceeded():
                            break
                        print(f"\n   ⬇️ ({src}) attempt {attempt}/{MAX_DOWNLOAD_ATTEMPTS}...")
                        t0 = time.time()
                        ok, info, natural = await asyncio.to_thread(
                            download_video, url, tmp_ts, it["url"], ck, expected_dur
                        )
                        dt = time.time() - t0

                        if ok and isinstance(info, (int, float)):
                            size = int(info)
                            size_mb = size / (1024*1024)
                            speed = size_mb / max(dt, 0.1)
                            print(f"   📦 ({src}) {size_mb:.2f} MB في {dt:.1f}s ≈ {speed:.2f} MB/s")

                            actual_dur = 0
                            if os.path.exists(tmp_ts):
                                actual_dur = await asyncio.to_thread(get_real_duration, tmp_ts)
                            print(f"   🎞️ المدة الحقيقية: {actual_dur}s ({actual_dur//60}m{actual_dur%60}s) | طبيعي: {natural}")

                            is_complete = False
                            reason = ""

                            if expected_dur > 0:
                                if actual_dur >= int(expected_dur * DURATION_ACCEPT_RATIO):
                                    is_complete = True
                                    reason = f"وصلنا {actual_dur}/{expected_dur}s"
                                else:
                                    reason = f"فقط {actual_dur}/{expected_dur}s ({int(actual_dur*100/max(expected_dur,1))}%)"
                            elif natural and actual_dur >= NATURAL_EXIT_MIN_DURATION:
                                is_complete = True
                                reason = "انتهى طبيعياً"
                            else:
                                reason = f"غير موثوق ({actual_dur}s) — طبيعي={natural}"

                            if is_complete:
                                success_if = it["url"]
                                dloaded = size
                                method = src
                                expected_dur_final = expected_dur
                                attempt_success = True
                                print(f"   ✅ نجاح كامل ({reason})!")
                                break
                            else:
                                partial_path = os.path.join(ddir, f"partial_{ep:02d}_{src}_{url_idx}.ts")
                                try:
                                    if os.path.exists(partial_path):
                                        os.remove(partial_path)
                                    shutil.move(tmp_ts, partial_path)
                                    partials.append((src, size, it["url"], partial_path, actual_dur, expected_dur))
                                    print(f"   ♻️ partial محفوظ: {size_mb:.1f} MB / {actual_dur}s (متوقع {expected_dur}s) — {reason}")
                                except Exception as e:
                                    print(f"   ⚠️ نقل: {e}")
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
            if success_if:
                break

        if not success_if and partials:
            print(f"\n🔍 تحليل partials ({len(partials)} مرشح):")

            scored = []
            for p in partials:
                src, size, url, path, real_dur, exp = p
                ratio = (real_dur / exp) if exp > 0 else 0
                scored.append((src, size, url, path, real_dur, exp, ratio))
                print(f"   - {src}: حقيقي={real_dur}s | متوقع={exp}s | نسبة={ratio:.0%} | حجم={size/(1024*1024):.1f} MB")

            with_exp = [p for p in scored if p[5] > 0]
            without_exp = [p for p in scored if p[5] == 0]

            if with_exp:
                best = max(with_exp, key=lambda p: (p[6], p[1]))
                src, size, url, path, real_dur, exp, ratio = best
                print(f"\n🏆 أفضل partial: {src} | حقيقي={real_dur}s | متوقع={exp}s | نسبة={ratio:.0%}")

                if real_dur < MIN_PARTIAL_REAL_DURATION:
                    print(f"   ❌ قصير جداً")
                    for p in scored:
                        try:
                            if os.path.exists(p[3]): os.remove(p[3])
                        except: pass
                    return False, f"كل الـ partials مقطوعة"

                if ratio < MIN_REAL_RATIO_AFTER_COMPRESS:
                    print(f"   ❌ النسبة منخفضة")
                    for p in scored:
                        try:
                            if os.path.exists(p[3]): os.remove(p[3])
                        except: pass
                    return False, f"حلقة مقطوعة ({ratio:.0%})"

                print(f"♻️ قبول partial")
                try:
                    if os.path.exists(tmp_ts): os.remove(tmp_ts)
                    shutil.move(path, tmp_ts)
                    success_if = url
                    dloaded = size
                    method = src
                    expected_dur_final = exp
                    for p in scored:
                        if p[3] != path:
                            try:
                                if os.path.exists(p[3]): os.remove(p[3])
                            except: pass
                except Exception as e:
                    return False, f"partial move: {e}"

            elif without_exp:
                print(f"\n⚠️ لا مدة متوقعة — رفض")
                for p in scored:
                    try:
                        if os.path.exists(p[3]): os.remove(p[3])
                    except: pass
                return False, f"لا مدة متوقعة"

        if not success_if:
            return False, "فشل من جميع السيرفرات"

        print(f"\n🎥 نجح: {method} | {dloaded/(1024*1024):.2f} MB")

        print(f"\n🗜️ ضغط...")
        if SKIP_COMPRESS:
            shutil.copy2(tmp_ts, fin)
        else:
            if not compress_144p(tmp_ts, fin):
                print(f"   ⚠️ فشل الضغط — نسخ TS")
                shutil.copy2(tmp_ts, fin)

        if not os.path.exists(fin):
            return False, "لا ملف نهائي"

        real_final_dur = await asyncio.to_thread(get_real_duration, fin)
        print(f"   🎞️ المدة الحقيقية النهائية: {real_final_dur}s")

        if expected_dur_final > 0:
            min_ok = int(expected_dur_final * MIN_REAL_RATIO_AFTER_COMPRESS)
            if real_final_dur < min_ok:
                pct = int(real_final_dur * 100 / max(expected_dur_final, 1))
                print(f"   ❌ رفض نهائي: {pct}%")
                try:
                    if os.path.exists(fin): os.remove(fin)
                    if os.path.exists(tmp_ts): os.remove(tmp_ts)
                    if os.path.exists(thb): os.remove(thb)
                except: pass
                return False, f"مقطع: {pct}%"

        print(f"\n🖼️ Thumbnail...")
        thumb(fin, thb)

        print(f"\n📤 رفع...")
        cap = f"{sn_ar} الموسم {season} الحلقة {ep}"
        ok = await upload(fin, cap,
                          thb if os.path.exists(thb) else None,
                          override_duration=real_final_dur)

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
    print("🎬 Video Downloader v15.4")
    if TEST_MODE: print("🧪 TEST_MODE")
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS//60}m")
    print(f"⬇️ yt-dlp: {YTDLP_TIMEOUT}s | ffmpeg: {FFMPEG_TIMEOUT}s | stall: {STALL_TIMEOUT}s")
    print(f"🔁 حلقة استئناف: {MAX_RESUME_ROUNDS} round")
    print(f"🍪 كوكيز كل النطاقات (Network.getAllCookies)")
    print(f"📄 Netscape cookies file لـ yt-dlp")
    print(f"🚫 fast-fail عند 403 من أول محاولة")
    print(f"⚡ concurrent-fragments: 8 | chunk-size: 5MB")
    print(f"📏 عتبة القبول: {int(DURATION_ACCEPT_RATIO*100)}% من المتوقعة")
    print(f"✅✅ تحقق نهائي: ≥ {int(MIN_REAL_RATIO_AFTER_COMPRESS*100)}%")
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
            print(f"\n⏰ حد زمني: {list(range(ep, e_ep+1))}")
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

    print(f"\n{'='*60}\n⏱️ {elapsed_str()}\n✅ {ok_n}/{total}")
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
