#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - u.3seq.com/.cam
v16.5 — Fix: cffi Session for HTML+m3u8+segments (preserve cookies) + correct Origin
"""

import os, sys, time, json, base64, subprocess, shutil, asyncio, random, re, tempfile
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

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

MIN_VALID_SIZE = 100 * 1024
MIN_PARTIAL_ACCEPT = 30 * 1024 * 1024
MIN_EPISODE_DURATION = 900
NATURAL_EXIT_MIN_DURATION = 600
MAX_RUNTIME_SECONDS = 165 * 60
WAIT_MIN, WAIT_MAX = 10, 20

YTDLP_TIMEOUT = 1800
YTDLP_TIMEOUT_IFRAME = 90
FFMPEG_TIMEOUT = 1800
STALL_TIMEOUT = 60
FILE_CREATE_TIMEOUT = 30

MAX_RESUME_ROUNDS = 15
RESUME_NO_PROGRESS_LIMIT = 3

MIN_ACCEPTABLE_SPEED = 300 * 1024
SPEED_CHECK_INTERVAL = 20
SPEED_GRACE_PERIOD = 30

HTML_SNIFF_SECONDS = 25
HTML_SNIFF_MAX_SIZE = 5 * 1024 * 1024

DURATION_ACCEPT_RATIO = 0.95
MIN_REAL_RATIO_AFTER_COMPRESS = 0.85
MIN_PARTIAL_REAL_DURATION = 600

CURL_CFFI_WORKERS = 8

BROWSER_FETCH_BATCH = 6
PARENT_WAIT_SECONDS = 20
JWPLAYER_WAIT_SECONDS = 45

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


def get_cookies_safe(sb):
    cookies_dict = {}
    try:
        cdp_cookies = sb.cdp.get_all_cookies()
        for c in cdp_cookies:
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
    try:
        return sb.cdp.get_all_cookies()
    except Exception:
        pass
    try:
        r = sb.driver.execute_cdp_cmd("Network.getAllCookies", {})
        return r.get("cookies", [])
    except Exception:
        pass
    try:
        return sb.driver.get_cookies()
    except Exception:
        return []


def save_cookies_netscape(cookies_list, path):
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


def origin_of(url):
    """استخرج origin كامل من URL"""
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return ""


def get_expected_duration(m3u8_url, referer, cookies_dict):
    cookie_str = get_all_cookies_string(cookies_dict)
    headers = {
        "Referer": referer,
        "Origin": origin_of(referer),
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


# ============================================================
#  JS fetch helpers (fallback داخل المتصفح)
# ============================================================
def _js_fetch_text(sb, url, timeout=40):
    url_json = json.dumps(url)
    js = """
    (function(){
        window.__hlsText = null;
        window.__hlsTextDone = false;
        fetch(%s, {credentials: 'include', mode: 'cors'})
            .then(r => r.text().then(t => {
                window.__hlsText = {status: r.status, text: t};
                window.__hlsTextDone = true;
            }))
            .catch(e => {
                window.__hlsText = {status: -1, error: String(e)};
                window.__hlsTextDone = true;
            });
    })();
    """ % url_json
    try:
        sb.cdp.execute_script(js)
    except Exception:
        return None
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(0.3)
        try:
            done = sb.cdp.execute_script("return window.__hlsTextDone === true")
        except Exception:
            done = False
        if done:
            try:
                return sb.cdp.execute_script("return window.__hlsText")
            except Exception:
                return None
    return None


def _extract_m3u8_from_perf(sb):
    urls_found = []
    try:
        urls = sb.cdp.execute_script("""
            try {
                return performance.getEntriesByType('resource')
                    .map(e => e.name)
                    .filter(u => u.includes('.m3u8') || u.includes('/hls/')
                              || u.includes('master') || u.includes('playlist'));
            } catch(e) { return []; }
        """)
        if urls and isinstance(urls, list):
            urls_found = [u for u in urls if u]
    except Exception:
        pass
    return urls_found


def _extract_all_urls_from_perf(sb):
    try:
        urls = sb.cdp.execute_script("""
            try {
                return performance.getEntriesByType('resource').map(e => e.name);
            } catch(e) { return []; }
        """)
        if urls and isinstance(urls, list):
            return [u for u in urls if u]
    except Exception:
        pass
    return []


def _extract_m3u8_from_jwplayer(sb):
    for js in [
        """try {
            if (typeof jwplayer === 'undefined') return null;
            var p = jwplayer();
            if (!p) return null;
            var pl = p.getPlaylist ? p.getPlaylist() : null;
            if (pl && pl[0] && pl[0].sources) {
                for (var i=0;i<pl[0].sources.length;i++) {
                    var f = pl[0].sources[i].file;
                    if (f && f.indexOf('m3u8')>=0) return f;
                }
            }
            return null;
        } catch(e) { return null; }""",
        """try {
            if (typeof jwplayer === 'undefined') return null;
            var p = jwplayer();
            if (!p || !p.getConfig) return null;
            var cfg = p.getConfig();
            if (cfg && cfg.playlist && cfg.playlist[0]) {
                var s = cfg.playlist[0].sources || [];
                for (var i=0;i<s.length;i++) {
                    if (s[i].file && s[i].file.indexOf('m3u8')>=0) return s[i].file;
                }
            }
            return null;
        } catch(e) { return null; }""",
        """try {
            var v = document.querySelector('video');
            if (v) {
                var s = v.src || v.currentSrc;
                if (s && s.indexOf('m3u8')>=0) return s;
            }
            return null;
        } catch(e) { return null; }""",
    ]:
        try:
            u = sb.cdp.execute_script(js)
            if u and isinstance(u, str) and 'http' in u and 'm3u8' in u.lower():
                return u
        except Exception:
            pass
    return None


def _set_referer_header(sb, referer):
    try:
        sb.driver.execute_cdp_cmd("Network.enable", {})
    except Exception:
        pass
    try:
        sb.driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {
            "headers": {
                "Referer": referer,
                "Origin": origin_of(referer),
            }
        })
        print(f"      ✅ تم ضبط Referer", flush=True)
        return True
    except Exception as e:
        print(f"      ⚠️ set_referer: {str(e)[:80]}", flush=True)
        return False


# ============================================================
#  ✅ v16.5: cffi Session — HTML + m3u8 + segments في نفس الجلسة
# ============================================================
def extract_m3u8_from_html(html, iframe_url=None):
    """استخراج m3u8 من HTML الـ embed"""
    if not html:
        return []
    found = []

    def _add(u):
        if not u:
            return
        u = u.replace('\\/', '/').strip()
        if u.startswith('http') and ('.m3u8' in u.lower() or 'master' in u.lower()):
            if u not in found:
                found.append(u)

    for m in re.finditer(r'(https?:[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*)', html):
        _add(m.group(1))
    for m in re.finditer(r'["\']file["\']\s*:\s*["\']([^"\']+)["\']', html):
        _add(m.group(1))
    for m in re.finditer(
        r'["\']sources["\']\s*:\s*\[[^\]]*?["\']file["\']\s*:\s*["\']([^"\']+)["\']',
        html, re.DOTALL):
        _add(m.group(1))
    for m in re.finditer(
        r'jwplayer\s*\([^)]*\)\s*\.\s*setup\s*\(\s*\{[^}]*?["\']file["\']\s*:\s*["\']([^"\']+)["\']',
        html, re.DOTALL):
        _add(m.group(1))
    for name in ['videoUrl', 'fileUrl', 'streamUrl', 'hlsUrl', 'm3u8',
                 'source', 'videoSrc', 'file', 'url']:
        for m in re.finditer(
            rf'["\']?{name}["\']?\s*[:=]\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
            html):
            _add(m.group(1))
    for m in re.finditer(r'data-(?:src|file|url|video)\s*=\s*["\']([^"\']+\.m3u8[^"\']*)["\']', html):
        _add(m.group(1))

    return found


def create_cffi_session(cookies_dict):
    """إنشاء session cffi مع الكوكيز"""
    session = cffi_requests.Session(impersonate="chrome120")
    for k, v in sanitize_cookies(cookies_dict).items():
        try:
            session.cookies.set(k, v)
        except Exception:
            pass
    return session


def fetch_with_session(session, url, referer, accept="*/*",
                        extra_headers=None, timeout=25):
    """طلب HTTP عبر session cffi مع headers صحيحة"""
    ref_origin = origin_of(referer) or "https://v.vidsp.net"
    headers = {
        "Referer": ref_origin + "/",
        "Origin": ref_origin,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }
    if extra_headers:
        headers.update(extra_headers)
    try:
        r = session.get(url, headers=headers, timeout=timeout, verify=False)
        return r
    except Exception as e:
        print(f"      ❌ cffi get: {str(e)[:100]}", flush=True)
        return None


def fetch_embed_and_m3u8_via_cffi(iframe_url, referer, cookies_dict,
                                    out_dir=None):
    """
    ✅ v16.5: جلب embed HTML + m3u8 في نفس الـ Session.
    Returns:
        (m3u8_content, m3u8_base_url, session) or (None, None, session)
    """
    ref_origin = origin_of(referer) or "https://u.3seq.cam"
    session = create_cffi_session(cookies_dict)

    # --- HTML fetch (navigate mode) ---
    html_headers = {
        "Referer": referer,
        "Origin": ref_origin,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "iframe",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    try:
        r_html = session.get(iframe_url, headers=html_headers,
                              timeout=25, verify=False, allow_redirects=True)
        print(f"      📄 [cffi] embed: HTTP {r_html.status_code} | {len(r_html.text)} bytes", flush=True)
    except Exception as e:
        print(f"      ❌ [cffi] embed: {str(e)[:100]}", flush=True)
        return None, None, session

    if r_html.status_code != 200:
        return None, None, session

    html = r_html.text
    if out_dir:
        try:
            dbg = os.path.join(out_dir, "embed_debug.html")
            with open(dbg, 'w', encoding='utf-8') as fh:
                fh.write(html)
            print(f"      💾 HTML → {dbg}", flush=True)
        except Exception:
            pass

    # جلب m3u8
    extracted = extract_m3u8_from_html(html, iframe_url)
    if not extracted:
        print(f"      ⚠️ لا m3u8 في HTML", flush=True)
        return None, None, session

    m3u8_url = extracted[0]
    print(f"      ✨ استُخرج m3u8: {m3u8_url[:100]}", flush=True)
    print(f"      🍪 session cookies (before m3u8): {len(session.cookies)}", flush=True)

    # جلب m3u8 في نفس الجلسة
    r_m3u8 = fetch_with_session(session, m3u8_url, referer,
                                  accept="application/vnd.apple.mpegurl,application/x-mpegURL,*/*")
    if r_m3u8 is None:
        return None, None, session

    print(f"      📄 [cffi] m3u8: HTTP {r_m3u8.status_code} | {len(r_m3u8.text)} bytes", flush=True)
    if r_m3u8.status_code != 200:
        # طبع أول 200 حرف من الرد للتشخيص
        snippet = (r_m3u8.text or "")[:200].replace("\n", " ")
        print(f"      ⚠️ رد m3u8: {snippet}", flush=True)
        return None, None, session

    m3u8_base = m3u8_url.rsplit('/', 1)[0]
    return r_m3u8.text, m3u8_base, session


def parse_m3u8_content(text, base_url):
    """Parse m3u8 → (segments, variants)"""
    segs = []
    variants = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '.m3u8' in line:
            u = line if line.startswith('http') else urljoin(base_url + '/', line)
            variants.append(u)
            continue
        if line.endswith('.ts') or '.ts?' in line or '/seg' in line.lower() or 'segment' in line.lower():
            u = line if line.startswith('http') else urljoin(base_url + '/', line)
            segs.append(u)
    return segs, variants


def download_segments_with_session(session, segments, out_path, referer,
                                     expected_dur=0):
    """تحميل الـ segments عبر cffi session مع نفس الـ headers"""
    print(f"   ⬇️ {len(segments)} segment عبر cffi session...", flush=True)
    seg_dir = tempfile.mkdtemp(prefix="hls_curl_")
    seg_paths = {}
    failed = 0
    total_bytes = 0

    ref_origin = origin_of(referer) or "https://v.vidsp.net"
    headers = {
        "Referer": ref_origin + "/",
        "Origin": ref_origin,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }

    def _dl(idx_url):
        idx, url = idx_url
        try:
            rr = session.get(url, headers=headers, timeout=60, verify=False)
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
        return None

    sorted_segs = [seg_paths[k] for k in sorted(seg_paths.keys())]
    concat_file = os.path.join(seg_dir, "concat.txt")
    with open(concat_file, 'w') as f:
        for p in sorted_segs:
            f.write(f"file '{p}'\n")

    print(f"   🔗 دمج {len(sorted_segs)} segment...", flush=True)
    concat_cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'warning',
                  '-f', 'concat', '-safe', '0', '-i', concat_file,
                  '-c', 'copy', '-f', 'mpegts', '-y', out_path]
    try:
        r = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not os.path.exists(out_path):
            print(f"   ❌ concat code={r.returncode}", flush=True)
            try: shutil.rmtree(seg_dir, ignore_errors=True)
            except: pass
            return None
    except Exception as e:
        print(f"   ❌ concat: {e}", flush=True)
        try: shutil.rmtree(seg_dir, ignore_errors=True)
        except: pass
        return None

    final_size = os.path.getsize(out_path)
    print(f"   ✅ ملف نهائي: {final_size/(1024*1024):.1f} MB", flush=True)
    try: shutil.rmtree(seg_dir, ignore_errors=True)
    except: pass
    return (final_size, True)


def extract_and_download_via_browser(iframe_url, out_path, expected_dur=0,
                                      watch_url=None):
    print(f"   🌐 [Browser HLS] {iframe_url[:80]}", flush=True)
    if watch_url:
        print(f"      🌐 [Parent] {watch_url[:80]}", flush=True)

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
    m3u8_urls = []
    download_result = None
    all_perf_urls = []

    out_dir = os.path.dirname(out_path)

    try:
        with SB(uc=True, xvfb=True, headless=False, incognito=True,
                ad_block_on=False,
                disable_csp=True,
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
                                print(f"      ✅ [net] {u[:110]}", flush=True)
                        except Exception:
                            pass

                    sb.cdp.add_handler(mycdp.network.RequestWillBeSent, on_req)
                except Exception as e:
                    print(f"      ⚠️ handler: {str(e)[:80]}", flush=True)

                # ═════ الخطوة 1: جمع كوكيز من الصفحة الأم ═════
                if watch_url:
                    try:
                        sb.cdp.open(watch_url)
                        sb.cdp.sleep(5)
                        for sel in ["#s_0", ".serversList li", "ul.serversList li"]:
                            try:
                                sb.cdp.click_if_visible(sel)
                                break
                            except Exception:
                                pass
                        print(f"      ⏳ انتظار {PARENT_WAIT_SECONDS}s على الصفحة الأم...", flush=True)
                        sb.cdp.sleep(PARENT_WAIT_SECONDS)
                        cookies_dict = get_cookies_safe(sb)
                        cookies_full = get_cookies_full(sb)
                        print(f"      🍪 بعد الأم: {len(cookies_dict)} كوكي", flush=True)
                    except Exception as e:
                        print(f"      ⚠️ parent: {str(e)[:80]}", flush=True)

                # ═════ الخطوة 2: v16.5 — cffi Session للـ HTML + m3u8 ═════
                cffi_session = None
                cffi_m3u8_content = None
                cffi_m3u8_base = None

                if cookies_dict and watch_url:
                    print(f"      🎯 [v16.5] جلب HTML + m3u8 عبر cffi Session...", flush=True)
                    cffi_m3u8_content, cffi_m3u8_base, cffi_session = \
                        fetch_embed_and_m3u8_via_cffi(
                            iframe_url, watch_url, cookies_dict, out_dir
                        )

                # ═════ الخطوة 3: إذا حصلنا على m3u8 → حمّل الـ segments عبر نفس الـ Session ═════
                if cffi_m3u8_content and cffi_session:
                    segments, variants = parse_m3u8_content(cffi_m3u8_content, cffi_m3u8_base or "")
                    # إن كان master، اجلب أول variant
                    if not segments and variants:
                        print(f"      📋 master → {len(variants)} variant", flush=True)
                        for v in variants[:3]:
                            rv = fetch_with_session(cffi_session, v, watch_url,
                                                     accept="application/vnd.apple.mpegurl,application/x-mpegURL,*/*")
                            if rv and rv.status_code == 200:
                                v_base = v.rsplit('/', 1)[0]
                                segments, _ = parse_m3u8_content(rv.text, v_base)
                                if segments:
                                    print(f"      ✅ variant: {len(segments)} segment", flush=True)
                                    cffi_m3u8_url = v
                                    cffi_m3u8_base = v_base
                                    m3u8_urls = [v]
                                    break

                    if segments:
                        if not m3u8_urls:
                            m3u8_urls = [cffi_m3u8_base + "/master.m3u8"]
                        print(f"      🎯 تحميل {len(segments)} segment عبر نفس cffi session", flush=True)
                        download_result = download_segments_with_session(
                            cffi_session, segments, out_path, watch_url, expected_dur
                        )
                    else:
                        print(f"      ⚠️ cffi: لم أستخرج segments", flush=True)

                # ═════ الخطوة 4: إن فشل cffi، جرّب المتصفح ═════
                if not download_result:
                    print(f"      🔀 fallback: فتح iframe في المتصفح", flush=True)
                    _set_referer_header(sb, watch_url or "https://u.3seq.cam/")
                    try:
                        sb.cdp.open(iframe_url)
                    except Exception as e:
                        print(f"      ⚠️ open iframe: {str(e)[:80]}", flush=True)

                    print(f"      ⏳ انتظار JW Player ({JWPLAYER_WAIT_SECONDS}s)...", flush=True)
                    for tick in range(JWPLAYER_WAIT_SECONDS // 3):
                        sb.cdp.sleep(3)
                        try:
                            r = sb.cdp.execute_script(
                                "return (typeof jwplayer !== 'undefined') ? 'yes' : 'no'"
                            )
                            if r == 'yes':
                                print(f"      ✅ jwplayer بعد {(tick+1)*3}s", flush=True)
                                break
                        except Exception:
                            pass

                    for cycle in range(4):
                        for sel in ["video", "button.vjs-big-play-button",
                                    ".jw-icon-playback", ".jw-display-icon-container",
                                    ".jw-icon-display", "[class*='play']",
                                    ".vjs-big-play-button", ".jwplayer"]:
                            try:
                                sb.cdp.click_if_visible(sel)
                            except Exception:
                                pass
                        try:
                            sb.cdp.execute_script("""
                                try {
                                    if (typeof jwplayer !== 'undefined') {
                                        var p = jwplayer();
                                        if (p && p.play) p.play(true);
                                    }
                                    var v = document.querySelector('video');
                                    if (v) { v.muted = true; if (v.play) v.play(); }
                                } catch(e){}
                            """)
                        except Exception:
                            pass
                        sb.cdp.sleep(3)
                    sb.cdp.sleep(5)

                    cookies_dict = get_cookies_safe(sb) or cookies_dict
                    cookies_full = get_cookies_full(sb) or cookies_full

                    all_perf_urls = _extract_all_urls_from_perf(sb)
                    print(f"      🔍 performance: {len(all_perf_urls)} resource", flush=True)
                    for u in all_perf_urls[:15]:
                        print(f"         → {u[:100]}", flush=True)

                    urls = []
                    try:
                        with open(lf, encoding="utf-8") as fh:
                            urls = [u.strip() for u in fh.readlines() if u.strip()]
                    except Exception:
                        pass

                    print(f"      📋 CDP handler: {len(urls)} رابط", flush=True)

                    all_m3u8 = [u for u in urls if ".m3u8" in u]
                    for u in all_perf_urls:
                        if ".m3u8" in u and u not in all_m3u8:
                            all_m3u8.append(u)
                    for u in m3u8_urls:
                        if u not in all_m3u8:
                            all_m3u8.append(u)

                    # محاولة jwplayer API كملاذ أخير
                    if not all_m3u8:
                        jw_url = _extract_m3u8_from_jwplayer(sb)
                        if jw_url:
                            print(f"      🎯 JW Player API → {jw_url[:110]}", flush=True)
                            all_m3u8 = [jw_url]

                    m3u8_urls = all_m3u8

                print(f"      📊 m3u8: {len(m3u8_urls)} | 🍪 {len(cookies_dict)}", flush=True)

                if not download_result and m3u8_urls:
                    print(f"      🎯 {m3u8_urls[0][:110]}", flush=True)
                    print(f"      ⚠️ سيتم استخدام fallback download_video (cffi/yt-dlp/ffmpeg)", flush=True)
                elif not download_result:
                    print(f"      ⚠️ لا m3u8 — fallback إلى iframe", flush=True)
                    m3u8_urls = [iframe_url]

            except Exception as e:
                print(f"      ❌ {str(e)[:150]}", flush=True)
    except Exception as e:
        print(f"      ❌ {str(e)[:150]}", flush=True)

    try:
        os.remove(lf)
    except Exception:
        pass

    return m3u8_urls, video_duration, cookies_dict, cookies_full, download_result


# ============================================================
#  yt-dlp + ffmpeg (fallbacks)
# ============================================================
def build_ytdlp_cmd(url, out_path, referer, cookies_info, cookies_file=None):
    origin = origin_of(referer) or "https://u.3seq.com"
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
    if cookies_file and os.path.exists(cookies_file):
        cmd += ['--cookies', cookies_file]
    else:
        cookie_str = ""
        if isinstance(cookies_info, dict):
            cookie_str = get_all_cookies_string(cookies_info.get("dict", {}))
        if cookie_str:
            cmd += ['--add-header', f'Cookie:{cookie_str}']
    cmd += ['-f', 'best[height<=720]/best', '-o', out_path, url]
    return cmd


def build_ffmpeg_cmd(m3u8_url, out_path, referer, cookies_info):
    origin = origin_of(referer) or "https://u.3seq.com"
    cookie_str = ""
    if isinstance(cookies_info, dict):
        cookie_str = get_all_cookies_string(cookies_info.get("dict", {}))
    header_lines = [
        f"Referer: {origin}/",
        f"Origin: {origin}",
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


def _is_html_file(path, max_size=HTML_SNIFF_MAX_SIZE):
    try:
        if not os.path.exists(path):
            return False
        sz = os.path.getsize(path)
        if sz == 0 or sz > max_size:
            return False
        with open(path, 'rb') as fh:
            head = fh.read(500)
        hl = head.lower()
        return (b'<!doctype' in hl or b'<html' in hl or b'<head>' in hl
                or b'<?xml' in head or b'<body' in hl)
    except Exception:
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
                            print(f"      🐌 {tag}: {speed_kb:.0f} KB/s", flush=True)
                        if slow_count >= 6 and (now - last_change) > STALL_TIMEOUT:
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
                if not _is_html_file(out_path):
                    pass

            if now - start > total_timeout:
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
    if size >= MIN_VALID_SIZE:
        return True, size, natural_exit
    return False, f"exited@{size}", natural_exit


def download_hls_with_curl_cffi(m3u8_url, out_path, referer, cookies_info, expected_dur=0):
    """fallback — cffi مباشر على m3u8 (بدون session)"""
    print(f"   [curl_cffi HLS] {m3u8_url[:80]}...", flush=True)
    cookie_str = ""
    if isinstance(cookies_info, dict):
        cookie_str = get_all_cookies_string(cookies_info.get("dict", {}))

    ref_origin = origin_of(referer) or "https://v.vidsp.net"

    headers = {
        "Referer": ref_origin + "/",
        "Origin": ref_origin,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,*/*",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }
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

    segments, variants = parse_m3u8_content(m3u8_text, m3u8_url.rsplit('/', 1)[0])

    if not segments and variants:
        for v in variants[:3]:
            try:
                rv = cffi_requests.get(v, headers=headers,
                                        impersonate="chrome120", timeout=30, verify=False)
                if rv.status_code == 200:
                    vb = v.rsplit('/', 1)[0]
                    segments, _ = parse_m3u8_content(rv.text, vb)
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


def download_video(url, out_path, referer, cookies_info=None, expected_dur=0,
                   is_iframe_fallback=False):
    if os.path.exists(out_path):
        try: os.remove(out_path)
        except Exception: pass

    is_m3u8 = ".m3u8" in url

    if is_m3u8:
        ok, info, natural = download_hls_with_curl_cffi(
            url, out_path, referer, cookies_info, expected_dur
        )
        if ok and isinstance(info, (int, float)) and info >= MIN_VALID_SIZE:
            return True, info, natural
        if not ok:
            print(f"   ⚠️ curl_cffi: {info}", flush=True)

    if os.path.exists(out_path):
        try: os.remove(out_path)
        except Exception: pass

    cookies_file = None
    if cookies_info and isinstance(cookies_info, dict):
        cookies_list = cookies_info.get("list", [])
        if cookies_list:
            cookies_file = out_path + ".cookies.txt"
            save_cookies_netscape(cookies_list, cookies_file)

    print(f"   [yt-dlp] timeout="
          f"{YTDLP_TIMEOUT_IFRAME if is_iframe_fallback else YTDLP_TIMEOUT}s...",
          flush=True)
    timeout = YTDLP_TIMEOUT_IFRAME if is_iframe_fallback else YTDLP_TIMEOUT
    cmd = build_ytdlp_cmd(url, out_path, referer, cookies_info, cookies_file)
    ok, info, natural = run_with_adaptive_monitoring(cmd, out_path, timeout, "yt-dlp")
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
        print(f"   [ffmpeg] timeout={FFMPEG_TIMEOUT}s...", flush=True)
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


def collect_iframes(ep, series_name):
    base = f"https://u.3seq.com/video/modablaj-{series_name}-episode-{ep:02d}"
    result = []
    watch_url_final = None
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
            watch_url_final = wu
            print(f"📺 {wu}")
            sb.open(wu)
            time.sleep(4)
            try:
                sb.wait_for_element("ul.serversList", timeout=25)
                print("✅ السيرفرات")
            except Exception:
                print("⚠️ لا سيرفرات")
                return result, watch_url_final
            html = sb.get_page_source()
            servers = extract_servers(html)
            if not servers:
                return result, watch_url_final
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
                    is_active = False
                    try:
                        cls = sb.find_element(f"#{srv['id']}").get_attribute("class") or ""
                        is_active = "active" in cls.split()
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
                    new = None
                    for _ in range(10):
                        time.sleep(1)
                        try:
                            new = sb.find_element(".watch iframe").get_attribute("src")
                            if new and new != old:
                                break
                        except Exception:
                            pass
                    if not new:
                        new = old
                    if not new or "about:blank" in new:
                        if is_active and not clicked:
                            print(f"   ⚠️ تعذّر قراءة iframe")
                            continue
                        print(f"   ⚠️ iframe فارغ")
                        continue
                    new = new.replace("&amp;", "&")
                    if new == old:
                        if is_active or len(servers) == 1:
                            print(f"   ✅ (نشط مسبقاً) {new[:90]}")
                            result.append({"server": srv["name"], "url": new})
                        else:
                            print(f"   ⚠️ iframe لم يتغير — تخطي")
                        continue
                    print(f"   ✅ {new[:90]}")
                    result.append({"server": srv["name"], "url": new})
                except Exception as e:
                    print(f"   ❌ {str(e)[:80]}")
            return result, watch_url_final
        except Exception as e:
            print(f"❌ {e}")
            return result, watch_url_final


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
        print(f"🧪 SKIP_UPLOAD: {fp}")
        return True
    if app is None or not os.path.exists(fp):
        return False
    w, h, real_d = meta(fp)
    if override_duration and override_duration > 0:
        d = int(override_duration)
    else:
        d = real_d
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
        res = await asyncio.to_thread(collect_iframes, ep, sn)
        iframes, watch_url = res
        if not iframes:
            return False, "لا iframes"
        print(f"\n📋 {len(iframes)} iframe | watch_url={watch_url[:80] if watch_url else 'None'}")

        success_if = None
        dloaded = 0
        method = None
        partials = []

        for i, it in enumerate(iframes):
            if exceeded():
                break
            print(f"\n{'='*60}\n🎬 [{i+1}/{len(iframes)}] {it['server']}\n{'='*60}")

            iframes_url = it["url"]
            print(f"   [1/1] Browser HLS attempt...")

            result = await asyncio.to_thread(
                extract_and_download_via_browser, iframes_url, tmp_ts, 0, watch_url
            )
            m3u8_urls, dur, ck_dict, ck_full, dl_result = result
            ck = {"dict": ck_dict, "list": ck_full}

            if dl_result and dl_result[1]:
                size = dl_result[0]
                size_mb = size / (1024*1024)
                print(f"   📦 (Browser/cffi) {size_mb:.2f} MB")

                actual_dur = 0
                if os.path.exists(tmp_ts):
                    actual_dur = await asyncio.to_thread(get_real_duration, tmp_ts)
                print(f"   🎞️ المدة الحقيقية: {actual_dur}s ({actual_dur//60}m{actual_dur%60}s)")

                expected_dur = 0
                if m3u8_urls and m3u8_urls[0] != iframes_url:
                    ck_dict_only = ck.get("dict", {}) if isinstance(ck, dict) else {}
                    expected_dur = await asyncio.to_thread(
                        get_expected_duration, m3u8_urls[0], watch_url or iframes_url, ck_dict_only
                    )
                    if expected_dur > 0:
                        print(f"   📏 المدة المتوقعة: {expected_dur}s")

                is_complete = False
                reason = ""
                if expected_dur > 0:
                    if actual_dur >= int(expected_dur * DURATION_ACCEPT_RATIO):
                        is_complete = True
                        reason = f"وصلنا {actual_dur}/{expected_dur}s"
                    else:
                        reason = f"فقط {actual_dur}/{expected_dur}s"
                elif actual_dur >= MIN_EPISODE_DURATION:
                    is_complete = True
                    reason = f"المدة {actual_dur}s كافية"

                if is_complete:
                    success_if = iframes_url
                    dloaded = size
                    method = "cffi-session"
                    expected_dur_final = expected_dur
                    print(f"   ✅ نجاح كامل ({reason})!")
                else:
                    partial_path = os.path.join(ddir, f"partial_{ep:02d}_browser.ts")
                    try:
                        if os.path.exists(partial_path):
                            os.remove(partial_path)
                        shutil.move(tmp_ts, partial_path)
                        partials.append(("cffi", size, iframes_url, partial_path, actual_dur, expected_dur))
                        print(f"   ♻️ partial: {size_mb:.1f} MB / {actual_dur}s — {reason}")
                    except Exception as e:
                        print(f"   ⚠️ نقل: {e}")
            else:
                print(f"   ❌ cffi/Browser فشل — fallback")
                fallback_urls = list(m3u8_urls) if m3u8_urls else []
                if not fallback_urls:
                    fallback_urls = [iframes_url]

                for url_idx, url in enumerate(fallback_urls[:3]):
                    if exceeded() or success_if:
                        break
                    is_iframe_fallback = (url == iframes_url)
                    expected_dur = 0
                    if ".m3u8" in url:
                        ck_dict_only = ck.get("dict", {}) if isinstance(ck, dict) else {}
                        expected_dur = await asyncio.to_thread(
                            get_expected_duration, url, watch_url or iframes_url, ck_dict_only
                        )

                    print(f"\n   ⬇️ (CDP-fb) attempt 1...")
                    t0 = time.time()
                    ok, info, natural = await asyncio.to_thread(
                        download_video, url, tmp_ts, watch_url or iframes_url, ck, expected_dur,
                        is_iframe_fallback
                    )
                    dt = time.time() - t0

                    if ok and isinstance(info, (int, float)):
                        size = int(info)
                        size_mb = size / (1024*1024)
                        print(f"   📦 (CDP-fb) {size_mb:.2f} MB في {dt:.1f}s")

                        actual_dur = 0
                        if os.path.exists(tmp_ts):
                            actual_dur = await asyncio.to_thread(get_real_duration, tmp_ts)
                        print(f"   🎞️ المدة الحقيقية: {actual_dur}s")

                        is_complete = False
                        reason = ""
                        if expected_dur > 0:
                            if actual_dur >= int(expected_dur * DURATION_ACCEPT_RATIO):
                                is_complete = True
                                reason = f"وصلنا {actual_dur}/{expected_dur}s"
                            else:
                                reason = f"فقط {actual_dur}/{expected_dur}s"
                        elif natural and actual_dur >= NATURAL_EXIT_MIN_DURATION:
                            is_complete = True
                            reason = "انتهى طبيعياً"
                        elif actual_dur >= MIN_EPISODE_DURATION:
                            is_complete = True
                            reason = "المدة كافية"

                        if is_complete:
                            success_if = iframes_url
                            dloaded = size
                            method = "CDP-fallback"
                            expected_dur_final = expected_dur
                            print(f"   ✅ نجاح كامل ({reason})!")
                            break
                        else:
                            partial_path = os.path.join(ddir, f"partial_{ep:02d}_cdp_{url_idx}.ts")
                            try:
                                if os.path.exists(partial_path):
                                    os.remove(partial_path)
                                shutil.move(tmp_ts, partial_path)
                                partials.append(("CDP-fb", size, iframes_url, partial_path, actual_dur, expected_dur))
                            except Exception as e:
                                print(f"   ⚠️ نقل: {e}")
                    else:
                        print(f"   ❌ ({info}) في {dt:.1f}s")
                        if os.path.exists(tmp_ts):
                            try: os.remove(tmp_ts)
                            except: pass

            if success_if:
                break

        if not success_if and partials:
            print(f"\n🔍 تحليل partials ({len(partials)}):")
            scored = []
            for p in partials:
                src, size, url, path, real_dur, exp = p
                ratio = (real_dur / exp) if exp > 0 else 0
                scored.append((src, size, url, path, real_dur, exp, ratio))
                print(f"   - {src}: {real_dur}s / {exp}s | {ratio:.0%}")

            with_exp = [p for p in scored if p[5] > 0]
            if with_exp:
                best = max(with_exp, key=lambda p: (p[6], p[1]))
                src, size, url, path, real_dur, exp, ratio = best
                print(f"\n🏆 أفضل partial: {src} | {real_dur}s/{exp}s ({ratio:.0%})")

                if real_dur < MIN_PARTIAL_REAL_DURATION:
                    for p in scored:
                        try:
                            if os.path.exists(p[3]): os.remove(p[3])
                        except: pass
                    return False, f"partials قصيرة"

                if ratio < MIN_REAL_RATIO_AFTER_COMPRESS:
                    for p in scored:
                        try:
                            if os.path.exists(p[3]): os.remove(p[3])
                        except: pass
                    return False, f"حلقة مقطوعة ({ratio:.0%})"

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
            else:
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
        print(f"   🎞️ المدة النهائية: {real_final_dur}s")

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
    print("🎬 Video Downloader v16.5")
    if TEST_MODE: print("🧪 TEST_MODE")
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS//60}m")
    print(f"🌐 cffi Session: HTML + m3u8 + segments in one session")
    print(f"📦 batch={BROWSER_FETCH_BATCH}")
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
