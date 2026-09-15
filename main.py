#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - Universal Multi-Server
v18.2 — Fast + Resource-conscious (single browser session, cffi-first segments)
"""

import os, sys, time, json, base64, subprocess, shutil, asyncio, random, re, tempfile, threading
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
SKIP_UPLOAD = os.environ.get("SKIP_UPLOAD", "false").lower() in ("true", "1", "yes")
SKIP_COMPRESS = os.environ.get("SKIP_COMPRESS", "false").lower() in ("true", "1", "yes")

# ⏱️ الحد الزمني
MAX_RUNTIME_SECONDS = 350 * 60

MIN_VALID_SIZE = 100 * 1024
MIN_PARTIAL_ACCEPT = 30 * 1024 * 1024
MIN_EPISODE_DURATION = 900
WAIT_MIN, WAIT_MAX = 3, 6

YTDLP_TIMEOUT = 900
FFMPEG_TIMEOUT = 1800
STALL_TIMEOUT = 90

# ⚡ إعدادات سريعة ولكن آمنة للموارد
BROWSER_BATCH = 16               # معتدل
BROWSER_BATCH_TIMEOUT = 30
CURL_CFFI_WORKERS = 12           # محدود
SEGMENT_RETRY = 2
M3U8_CANDIDATE_LIMIT = 5

# أوقات انتظار قصيرة
JWPLAYER_WAIT = 25
M3U8_CAPTURE_WAIT = 15

# ⏱️ إدارة الحلقات
EPISODE_TIMEOUT_MAX = 22 * 60
MIN_EPISODE_TIME = 4 * 60

# 🗜️ الضغط — كما هو (لا تغيير في الجودة)
COMPRESS_PRESET = "veryfast"
COMPRESS_CRF = 28
COMPRESS_THREADS = 2            # محدود لتجنب spike
COMPRESS_SCALE = 144

KNOWN_SERVER_PATTERNS = {
    "vidsp":     r"v\.vidsp\.net|vidsp\.net",
    "vinovo":    r"vinovo\.to",
    "luluvdo":   r"luluvdo\.com|lulushort|luluvid",
    "vids":      r"cdn-vids\.xyz|vidaraa",
    "generic":   r".*",
}

SCRIPT_START = time.time()


# ═══════════════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════
#  Cookies
# ═══════════════════════════════════════════════════════════
def _normalize_cookie(c):
    if isinstance(c, dict):
        return c
    d = {}
    for attr in ("name", "value", "domain", "path", "secure",
                 "httpOnly", "expiry", "sameSite", "session"):
        try:
            v = getattr(c, attr, None)
            if v is not None:
                d[attr] = v
        except Exception:
            pass
    if d.get("name") and d.get("value"):
        return d
    try:
        if len(c) >= 2:
            return {"name": c[0], "value": c[1]}
    except Exception:
        pass
    try:
        if hasattr(c, "__dict__"):
            return dict(c.__dict__)
    except Exception:
        pass
    return {}


def _dedup_cookies(raw):
    out, seen = [], set()
    for c in raw:
        d = _normalize_cookie(c)
        n = str(d.get("name", "") or "").strip()
        v = str(d.get("value", "") or "").strip()
        if not n or not v:
            continue
        dom = str(d.get("domain", "") or "").strip()
        key = (n, dom)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "name": n, "value": v, "domain": dom,
            "path": str(d.get("path", "/") or "/"),
            "secure": bool(d.get("secure", False)),
            "httpOnly": bool(d.get("httpOnly", False)),
            "expiry": int(d.get("expiry", 0) or 0),
        })
    return out


def get_cookies_full(sb):
    try:
        r = sb.driver.execute_cdp_cmd("Network.getAllCookies", {})
        if r and r.get("cookies"):
            return _dedup_cookies(r["cookies"])
    except Exception:
        pass
    try:
        raw = sb.cdp.get_all_cookies()
        if raw:
            return _dedup_cookies(raw)
    except Exception:
        pass
    return []


def origin_of(url):
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════
#  Server detection
# ═══════════════════════════════════════════════════════════
def detect_server_type(iframe_url):
    url_lower = iframe_url.lower()
    for name, pattern in KNOWN_SERVER_PATTERNS.items():
        if name == "generic":
            continue
        if re.search(pattern, url_lower, re.I):
            return name
    return "generic"


def extract_file_code(iframe_url):
    patterns = [
        r'embed-([a-z0-9]{8,})\.html',
        r'/e/([a-z0-9]{8,})',
        r'/embed/([a-z0-9]{8,})',
        r'file[=/]([a-z0-9]{8,})',
    ]
    for p in patterns:
        m = re.search(p, iframe_url, re.I)
        if m:
            return m.group(1)
    return None


# ═══════════════════════════════════════════════════════════
#  HTML parsing
# ═══════════════════════════════════════════════════════════
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


def extract_m3u8_from_text(text):
    if not text:
        return []
    found, seen = [], set()
    for m in re.finditer(r'(https?:[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*)', text):
        u = m.group(1).replace('\\/', '/')
        if u not in seen:
            seen.add(u); found.append(u)
    for m in re.finditer(r'(https?:[^\s"\'<>\\]+\.mpd[^\s"\'<>\\]*)', text):
        u = m.group(1).replace('\\/', '/')
        if u not in seen:
            seen.add(u); found.append(u)
    return found


# ═══════════════════════════════════════════════════════════
#  m3u8 parsing
# ═══════════════════════════════════════════════════════════
def parse_m3u8_content(text, base_url):
    segs, variants = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '.m3u8' in line:
            variants.append(line if line.startswith('http') else urljoin(base_url + '/', line))
            continue
        if line.endswith('.ts') or '.ts?' in line or 'seg' in line.lower() or '.m4s' in line:
            segs.append(line if line.startswith('http') else urljoin(base_url + '/', line))
    return segs, variants


def build_m3u8_variants(original_url):
    variants = [original_url]
    if '?' in original_url:
        base = original_url.split('?')[0]
        q = original_url.split('?', 1)[1]
        qs = '?' + q
        tm = re.search(r'\bt=([^&]+)', qs)
        token = tm.group(1) if tm else ''
    else:
        base, token = original_url, ''
    d = base.rsplit('/', 1)[0] if '/' in base else ''
    if not d:
        return variants
    orig_fname = base.rsplit('/', 1)[-1]
    for fname in ['index-v1-a1.m3u8', 'master.m3u8', 'index.m3u8']:
        if fname == orig_fname:
            continue
        if token:
            variants.append(f"{d}/{fname}?t={token}")
    seen, out = set(), []
    for u in variants:
        if u and u not in seen:
            seen.add(u); out.append(u)
    return out


# ═══════════════════════════════════════════════════════════
#  Browser fetch (5 methods)
# ═══════════════════════════════════════════════════════════
def _poll_js(sb, done_var, result_var, timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        sb.cdp.sleep(0.15)
        try:
            if sb.cdp.execute_script(f"return window.{done_var} === true"):
                try:
                    return sb.cdp.execute_script(f"return window.{result_var}")
                except Exception:
                    return None
        except Exception:
            pass
    return None


def browser_fetch_text(sb, url, timeout=12):
    url_json = json.dumps(url)
    for idx, expr in enumerate([
        f"fetch({url_json}, {{mode:'cors'}})",
        f"fetch({url_json}, {{mode:'cors', credentials:'include'}})",
    ]):
        dv, rv = f"__d{idx+10}", f"__r{idx+10}"
        js = f"""
        (function(){{
            window.{dv}=false; window.{rv}=null;
            try {{
                {expr}
                    .then(function(r){{ r.text().then(function(t){{
                        window.{rv}={{ok:true,status:r.status,text:t}};
                        window.{dv}=true;
                    }}).catch(function(e){{
                        window.{rv}={{ok:false,error:String(e)}};
                        window.{dv}=true;
                    }});
                    }}).catch(function(e){{
                        window.{rv}={{ok:false,error:String(e)}};
                        window.{dv}=true;
                    }});
            }} catch(e) {{
                window.{rv}={{ok:false,error:String(e)}};
                window.{dv}=true;
            }}
        }})();
        """
        try:
            sb.cdp.execute_script(js)
        except Exception:
            continue
        r = _poll_js(sb, dv, rv, timeout)
        if r and r.get("ok") and r.get("status") == 200 and r.get("text"):
            return r.get("text"), "fetch-no-cred" if idx == 0 else "fetch-with-cred"
    return None, None


def browser_fetch_batch_b64(sb, urls, timeout=30):
    if not urls:
        return {}
    urls_json = json.dumps(urls)
    js = """
    (function(){
        window.__br = {}; window.__bd = false;
        var urls = %s;
        var results = {}; var pending = urls.length;
        if (pending === 0) { window.__br = results; window.__bd = true; return; }
        urls.forEach(function(u, idx){
            var done = function(val){
                results[String(idx)] = val;
                pending--;
                if (pending === 0) { window.__br = results; window.__bd = true; }
            };
            try {
                fetch(u, {mode:'cors'})
                    .then(function(r){
                        if (!r.ok) throw new Error('HTTP '+r.status);
                        return r.arrayBuffer();
                    })
                    .then(function(buf){
                        var bytes = new Uint8Array(buf);
                        var bin = ''; var chunk = 16384;
                        for (var j=0; j<bytes.length; j+=chunk) {
                            bin += String.fromCharCode.apply(null,
                                bytes.subarray(j, Math.min(j+chunk, bytes.length)));
                        }
                        try { done(btoa(bin)); } catch(e) { done(null); }
                    })
                    .catch(function(){ done(null); });
            } catch(e) { done(null); }
        });
    })();
    """ % urls_json
    try:
        sb.cdp.execute_script(js)
    except Exception:
        return {}
    r = _poll_js(sb, "__bd", "__br", timeout)
    if isinstance(r, dict):
        return r
    return {}


# ═══════════════════════════════════════════════════════════
#  ⚡ cffi segments (أسرع من المتصفح)
# ═══════════════════════════════════════════════════════════
def try_cffi_segments(segments, out_path, iframe_url, cookies_dict):
    """
    ⚡ محاولة تحميل segments عبر cffi (TLS fingerprint صحيح).
    يرجع (size, True) عند النجاح، أو None عند الفشل.
    """
    if not segments:
        return None

    ref_origin = origin_of(iframe_url) or ""
    headers = {
        "Referer": iframe_url,
        "Origin": ref_origin,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }

    # اختبار سريع على segment واحد
    test_url = segments[0]
    test_data = None
    for impersonate in ["chrome124", "chrome120", "chrome110"]:
        try:
            r = cffi_requests.get(test_url, headers=headers,
                                   impersonate=impersonate,
                                   timeout=15, verify=False)
            if r.status_code == 200 and len(r.content) > 100:
                test_data = r.content
                print(f"      ⚡ cffi[{impersonate}] segment test OK ({len(test_data)}b)", flush=True)
                break
        except Exception:
            continue

    if test_data is None:
        print(f"      ⚠️ cffi segment test فشل — استخدام المتصفح", flush=True)
        return None

    # تحميل الكل عبر cffi
    print(f"   ⚡ {len(segments)} segment عبر cffi parallel...", flush=True)
    seg_dir = tempfile.mkdtemp(prefix="hls_cffi_")
    seg_paths, failed, total_bytes = {}, 0, 0

    def _dl(idx_url):
        idx, url = idx_url
        try:
            for imp in ["chrome124", "chrome120"]:
                try:
                    r = cffi_requests.get(url, headers=headers,
                                           impersonate=imp,
                                           timeout=30, verify=False)
                    if r.status_code == 200 and len(r.content) > 100:
                        p = os.path.join(seg_dir, f"seg_{idx:06d}.ts")
                        with open(p, 'wb') as f:
                            f.write(r.content)
                        return (idx, p, len(r.content))
                except Exception:
                    continue
        except Exception:
            pass
        return (idx, None, 0)

    with ThreadPoolExecutor(max_workers=CURL_CFFI_WORKERS) as ex:
        futures = {ex.submit(_dl, (i, s)): i for i, s in enumerate(segments)}
        done = 0
        for fut in as_completed(futures):
            idx, p, size = fut.result()
            done += 1
            if p:
                seg_paths[idx] = p
                total_bytes += size
            else:
                failed += 1
            if done % 40 == 0 or done == len(segments):
                print(f"      📦 {done}/{len(segments)} | {total_bytes/(1024*1024):.1f} MB | فشل: {failed}", flush=True)

    if not seg_paths or failed > len(segments) * 0.15:
        try: shutil.rmtree(seg_dir, ignore_errors=True)
        except: pass
        print(f"      ❌ cffi: نسبة فشل عالية ({failed}/{len(segments)})", flush=True)
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
            try: shutil.rmtree(seg_dir, ignore_errors=True)
            except: pass
            return None
    except Exception:
        try: shutil.rmtree(seg_dir, ignore_errors=True)
        except: pass
        return None

    final_size = os.path.getsize(out_path)
    print(f"   ✅ cffi نجح: {final_size/(1024*1024):.1f} MB", flush=True)
    try: shutil.rmtree(seg_dir, ignore_errors=True)
    except: pass
    return (final_size, True)


# ═══════════════════════════════════════════════════════════
#  Browser segments (fallback)
# ═══════════════════════════════════════════════════════════
def download_segments_via_browser(sb, segments, out_path):
    total = len(segments)
    print(f"   🌐 المتصفح: {total} segment (batch={BROWSER_BATCH})...", flush=True)
    seg_dir = tempfile.mkdtemp(prefix="hls_br_")
    seg_paths, failed, total_bytes = {}, 0, 0

    for i in range(0, total, BROWSER_BATCH):
        if exceeded():
            break
        batch = segments[i:i + BROWSER_BATCH]
        result = browser_fetch_batch_b64(sb, batch, timeout=BROWSER_BATCH_TIMEOUT)

        retry = []
        for idx_str, b64 in result.items():
            try:
                li = int(idx_str)
            except Exception:
                continue
            si = i + li
            if b64:
                try:
                    data = base64.b64decode(b64)
                    p = os.path.join(seg_dir, f"seg_{si:06d}.ts")
                    with open(p, 'wb') as f:
                        f.write(data)
                    seg_paths[si] = p
                    total_bytes += len(data)
                except Exception:
                    retry.append((si, batch[li]))
            else:
                retry.append((si, batch[li]))

        if retry and SEGMENT_RETRY > 0:
            retry_urls = [u for _, u in retry]
            rr = browser_fetch_batch_b64(sb, retry_urls, timeout=BROWSER_BATCH_TIMEOUT)
            for idx_str, b64 in rr.items():
                try:
                    li = int(idx_str)
                except Exception:
                    continue
                si, _ = retry[li]
                if b64:
                    try:
                        data = base64.b64decode(b64)
                        p = os.path.join(seg_dir, f"seg_{si:06d}.ts")
                        with open(p, 'wb') as f:
                            f.write(data)
                        seg_paths[si] = p
                        total_bytes += len(data)
                    except Exception:
                        failed += 1
                else:
                    failed += 1
        elif retry:
            failed += len(retry)

        done = min(i + BROWSER_BATCH, total)
        if done % (BROWSER_BATCH * 2) == 0 or done == total:
            print(f"      📦 {done}/{total} | {total_bytes/(1024*1024):.1f} MB | فشل: {failed}", flush=True)

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
            try: shutil.rmtree(seg_dir, ignore_errors=True)
            except: pass
            return None
    except Exception:
        try: shutil.rmtree(seg_dir, ignore_errors=True)
        except: pass
        return None

    final_size = os.path.getsize(out_path)
    print(f"   ✅ ملف نهائي: {final_size/(1024*1024):.1f} MB", flush=True)
    try: shutil.rmtree(seg_dir, ignore_errors=True)
    except: pass
    return (final_size, True)


# ═══════════════════════════════════════════════════════════
#  Player detection & trigger
# ═══════════════════════════════════════════════════════════
def detect_player(sb):
    try:
        return sb.cdp.execute_script("""
            (function(){
                try {
                    var out = {player:'none', state:'unknown'};
                    if (typeof jwplayer !== 'undefined') {
                        var p = jwplayer();
                        if (p) {
                            out.player = 'jwplayer';
                            out.state = (p.getState && p.getState()) || 'unknown';
                        }
                    }
                    var v = document.querySelector('video');
                    if (v && out.player === 'none') {
                        out.player = 'html5';
                        out.state = v.paused ? 'paused' : 'playing';
                    }
                    return out;
                } catch(e) { return {player:'error', state:'err'}; }
            })();
        """)
    except Exception:
        return {"player": "none"}


def trigger_play(sb):
    for sel in ["video", ".jw-icon-playback", ".jw-icon-display",
                ".jw-display-icon-container", "[class*='play']",
                ".vjs-big-play-button", ".jwplayer"]:
        try:
            sb.cdp.click_if_visible(sel)
        except Exception:
            pass
    try:
        sb.cdp.execute_script("""
            (function(){
                try {
                    if (typeof jwplayer !== 'undefined') {
                        var p = jwplayer();
                        if (p && p.play) { p.play(true); return; }
                    }
                    var v = document.querySelector('video');
                    if (v) { v.muted = true; v.play && v.play().catch(function(){}); }
                } catch(e){}
            })();
        """)
    except Exception:
        pass


def click_center(sb):
    try:
        rect = sb.cdp.execute_script("""
            (function(){
                try {
                    var cs = [document.querySelector('video'),
                              document.querySelector('iframe'),
                              document.querySelector('.jwplayer')];
                    for (var i=0;i<cs.length;i++) {
                        var el = cs[i];
                        if (!el) continue;
                        var r = el.getBoundingClientRect();
                        if (r.width > 50 && r.height > 50)
                            return {x: Math.round(r.left+r.width/2),
                                    y: Math.round(r.top+r.height/2)};
                    }
                    return null;
                } catch(e){ return null; }
            })();
        """)
        if rect and rect.get("x", 0) > 0:
            for _ in range(2):
                try:
                    sb.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
                        "type": "mousePressed", "x": rect['x'], "y": rect['y'],
                        "button": "left", "clickCount": 1,
                    })
                    sb.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
                        "type": "mouseReleased", "x": rect['x'], "y": rect['y'],
                        "button": "left", "clickCount": 1,
                    })
                except Exception:
                    pass
                sb.cdp.sleep(0.8)
            return True
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════════
#  ⚡⚡ SINGLE SESSION — collect + extract + download
# ═══════════════════════════════════════════════════════════
def process_episode_all_in_one(ep, series_name, out_path):
    """
    ⚡ v18.2: جلسة متصفح واحدة لكل حلقة.
    Returns (iframe_url, cookies_full, download_result).
    """
    base_url = f"https://u.3seq.com/video/modablaj-{series_name}-episode-{ep:02d}"
    iframe_url = None
    watch_url = None
    cookies_full = []
    download_result = None
    m3u8_urls = []

    netlog = tempfile.mktemp(suffix=f"_ep{ep}_netlog.txt")
    with open(netlog, "w") as f:
        f.write("")

    def _log(u):
        try:
            with open(netlog, "a", encoding="utf-8") as fh:
                fh.write(u + "\n"); fh.flush()
        except Exception:
            pass

    def _read_log():
        try:
            with open(netlog, encoding="utf-8") as fh:
                return [l.strip() for l in fh if l.strip()]
        except Exception:
            return []

    try:
        with SB(uc=True, xvfb=True, headless=False, incognito=True,
                ad_block_on=False, disable_csp=True,
                page_load_strategy="eager", locale_code="en") as sb:
            try:
                sb.activate_cdp_mode()

                try:
                    import mycdp

                    async def on_req(e):
                        try:
                            u = e.request.url
                            _log(u)
                            if ".m3u8" in u or ".mpd" in u:
                                print(f"      ✅ [net] {u[:120]}", flush=True)
                        except Exception:
                            pass

                    sb.cdp.add_handler(mycdp.network.RequestWillBeSent, on_req)
                except Exception:
                    pass

                # ═══ الخطوة 1: اذهب إلى صفحة الحلقة ═══
                print(f"🖥️  فتح: {base_url}", flush=True)
                sb.cdp.open(base_url)
                sb.cdp.sleep(2)
                fu = sb.cdp.get_current_url()
                if not fu.endswith('/'):
                    fu += '/'
                watch_url = fu + '?do=watch'
                sb.cdp.open(watch_url)
                sb.cdp.sleep(2)

                # ═══ الخطوة 2: استخرج iframe من HTML ═══
                try:
                    sb.wait_for_element("ul.serversList", timeout=12)
                    print(f"   ✅ السيرفرات ظهرت", flush=True)
                except Exception:
                    print(f"   ⚠️ لا سيرفرات — استمر", flush=True)

                html = sb.get_page_source()
                servers = extract_servers(html)
                if not servers:
                    # جرّب iframe مباشرة
                    try:
                        ifr = sb.find_element(".watch iframe")
                        src = ifr.get_attribute("src")
                        if src and src.startswith("http"):
                            iframe_url = src.replace("&amp;", "&")
                    except Exception:
                        pass
                else:
                    # اختر الأول (نشط)
                    prio = {"luluvdo": 0, "vinovo": 1, "vidaraa": 2, "vids": 3, "v": 4}
                    servers.sort(key=lambda s: prio.get(s.get("name", "").lower(), 99))
                    srv = servers[0]

                    # اقرأ iframe الحالي
                    try:
                        ifr = sb.find_element(".watch iframe")
                        iframe_url = ifr.get_attribute("src")
                    except Exception:
                        pass

                    # إن لم يكن نشطاً، انقر
                    is_active = False
                    try:
                        cls = sb.find_element(f"#{srv['id']}").get_attribute("class") or ""
                        is_active = "active" in cls.split()
                    except Exception:
                        pass

                    if not is_active:
                        for m in ["uc_click", "js_click", "click"]:
                            try:
                                getattr(sb, m)(f"#{srv['id']}")
                                break
                            except Exception:
                                pass
                        sb.cdp.sleep(1.5)
                        try:
                            ifr = sb.find_element(".watch iframe")
                            iframe_url = ifr.get_attribute("src")
                        except Exception:
                            pass

                    if iframe_url:
                        iframe_url = iframe_url.replace("&amp;", "&")

                if not iframe_url:
                    print(f"   ❌ لا iframe URL", flush=True)
                    return None, [], None

                print(f"   📋 iframe: {iframe_url[:90]}", flush=True)

                # ═══ الخطوة 3: انتقل إلى iframe في نفس الجلسة ═══
                sb.driver.execute_cdp_cmd("Page.navigate", {
                    "url": iframe_url,
                    "referrer": watch_url,
                })
                sb.cdp.sleep(3)

                try:
                    cur = sb.cdp.get_current_url()
                    print(f"   🔍 {cur[:80]}", flush=True)
                except Exception:
                    pass

                # ═══ الخطوة 4: انتظر المشغل ═══
                player_seen = False
                for tick in range(JWPLAYER_WAIT):
                    sb.cdp.sleep(1)
                    info = detect_player(sb)
                    if info.get("player") not in ("none", "error"):
                        print(f"   ✅ {info['player']} بعد {tick+1}s", flush=True)
                        player_seen = True
                        break

                # ═══ الخطوة 5: تشغيل + التقاط m3u8 ═══
                m3u8_found = False
                for cycle in range(6):
                    click_center(sb)
                    trigger_play(sb)
                    sb.cdp.sleep(1)
                    if any(x in u for u in _read_log() for x in [".m3u8", ".mpd"]):
                        print(f"   ✨ m3u8 بعد دورة {cycle+1}", flush=True)
                        m3u8_found = True
                        break

                if not m3u8_found:
                    for i in range(M3U8_CAPTURE_WAIT):
                        sb.cdp.sleep(1)
                        if any(x in u for u in _read_log() for x in [".m3u8", ".mpd"]):
                            print(f"   ✨ m3u8 بعد {(i+1)+6}s", flush=True)
                            m3u8_found = True
                            break

                cookies_full = get_cookies_full(sb)

                # اجمع كل m3u8 من الشبكة + performance + HTML
                urls = _read_log()
                m3u8_now = [u for u in urls if any(x in u for x in [".m3u8", ".mpd"])]

                try:
                    perf = sb.cdp.execute_script("""
                        (function(){ try {
                            return performance.getEntriesByType('resource').map(e => e.name);
                        } catch(e){ return []; } })();
                    """)
                    if perf and isinstance(perf, list):
                        for u in perf:
                            if any(x in u for x in [".m3u8", ".mpd"]) and u not in m3u8_now:
                                m3u8_now.append(u)
                except Exception:
                    pass

                try:
                    html = sb.cdp.get_page_source() or ""
                    for u in extract_m3u8_from_text(html):
                        if u not in m3u8_now:
                            m3u8_now.append(u)
                except Exception:
                    pass

                # ترتيب
                idx_files = [u for u in m3u8_now if 'index-' in u.lower()]
                master = [u for u in m3u8_now if 'master' in u.lower()]
                mpd = [u for u in m3u8_now if '.mpd' in u.lower()]
                others = [u for u in m3u8_now if u not in idx_files and u not in master and u not in mpd]
                m3u8_urls = idx_files + master + mpd + others

                print(f"   🎯 {len(m3u8_urls)} مرشح m3u8", flush=True)
                for u in m3u8_urls[:3]:
                    print(f"      · {u[:120]}", flush=True)

                # ═══ الخطوة 6: احصل على محتوى m3u8 + segments ═══
                if m3u8_urls:
                    for m3u8_url in m3u8_urls[:M3U8_CANDIDATE_LIMIT]:
                        if download_result or exceeded():
                            break

                        print(f"   🎯 محاولة: {m3u8_url[:100]}", flush=True)
                        content, method = browser_fetch_text(sb, m3u8_url, timeout=12)
                        if not content:
                            print(f"      ❌ فشل", flush=True)
                            continue
                        print(f"      ✅ {method} → {len(content)}b", flush=True)

                        segments, variants = parse_m3u8_content(content, m3u8_url.rsplit('/', 1)[0])
                        if not segments and variants:
                            for v in variants[:2]:
                                vc, vm = browser_fetch_text(sb, v, timeout=12)
                                if vc:
                                    segs2, _ = parse_m3u8_content(vc, v.rsplit('/', 1)[0])
                                    if segs2:
                                        segments = segs2
                                        m3u8_url = v
                                        print(f"      ✅ variant: {len(segments)} seg", flush=True)
                                        break

                        if segments:
                            # ⚡ محاولة cffi أولاً
                            ck_dict = {}
                            for c in cookies_full:
                                ck_dict[c["name"]] = c["value"]
                            result_cffi = try_cffi_segments(
                                segments, out_path, iframe_url, ck_dict
                            )
                            if result_cffi:
                                download_result = result_cffi
                                break

                            # fallback: المتصفح
                            print(f"      🌐 المتصفح fallback", flush=True)
                            download_result = download_segments_via_browser(
                                sb, segments, out_path
                            )
                            if download_result:
                                break

            except Exception as e:
                print(f"   ❌ {str(e)[:150]}", flush=True)
    except Exception as e:
        print(f"   ❌ {str(e)[:150]}", flush=True)

    try:
        os.remove(netlog)
    except Exception:
        pass

    return iframe_url, cookies_full, download_result


# ═══════════════════════════════════════════════════════════
#  Compression (unchanged)
# ═══════════════════════════════════════════════════════════
def compress_144p(inp, out):
    if not os.path.exists(inp):
        return False
    im = os.path.getsize(inp) / (1024 * 1024)
    print(f"   🗜️ {im:.2f} MB → {COMPRESS_SCALE}p (preset={COMPRESS_PRESET})...")
    cmd = [
        'ffmpeg', '-err_detect', 'ignore_err',
        '-fflags', '+discardcorrupt+genpts',
        '-analyzeduration', '50M', '-probesize', '50M',
        '-i', inp,
        '-vf', f'scale=-2:{COMPRESS_SCALE}',
        '-c:v', 'libx264',
        '-crf', str(COMPRESS_CRF),
        '-preset', COMPRESS_PRESET,
        '-threads', str(COMPRESS_THREADS),
        '-c:a', 'aac', '-b:a', '64k',
        '-f', 'mp4', '-movflags', '+faststart',
        '-max_muxing_queue_size', '4096',
        '-y', out,
    ]
    try:
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 10 * 1024:
            print(f"   ❌ ffmpeg code={r.returncode}")
            return False
        om = os.path.getsize(out) / (1024 * 1024)
        dt = time.time() - t0
        print(f"   ✅ {im:.2f}→{om:.2f} MB في {dt:.1f}s")
        return True
    except Exception as e:
        print(f"   ❌ {e}")
        return False


def meta(vp, accurate=False):
    w, h, d = 0, 0, 0
    try:
        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
               '-show_entries', 'stream=width,height',
               '-show_entries', 'format=duration',
               '-of', 'default=noprint_wrappers=1:nokey=1']
        if accurate:
            cmd += ['-analyzeduration', '50M', '-probesize', '50M']
        cmd.append(vp)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            return 0, 0, 0
        lines = [l.strip() for l in p.stdout.strip().split('\n') if l.strip()]
        if len(lines) >= 2:
            try: w, h = int(float(lines[0])), int(float(lines[1]))
            except Exception: return 0, 0, 0
        if len(lines) >= 3:
            try: d = int(float(lines[2]))
            except Exception: d = 0
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
            capture_output=True, text=True, timeout=180,
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
                                if d > 0: return d
                        except Exception: pass
                    dur = s.get("duration")
                    if dur:
                        try:
                            d2 = int(float(dur))
                            if d2 > 0: return d2
                        except Exception: pass
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
            r = subprocess.run(cmd, capture_output=True, timeout=20)
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
    if w == 0 or h == 0: w, h = 640, 360
    if d == 0:
        try: d = int(os.path.getsize(fp) / (1024 * 1024) * 5)
        except Exception: d = 60
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


# ═══════════════════════════════════════════════════════════
#  Episode processing
# ═══════════════════════════════════════════════════════════
async def process_episode(ep, sn, sn_ar, season, ddir):
    print(f"\n🎬 Ep {ep:02d}  [{elapsed_str()}]  ⏳ {remaining()//60}m")
    tmp_ts = os.path.join(ddir, f"temp_{ep:02d}.ts")
    fin = os.path.join(ddir, f"final_{ep:02d}.mp4")
    thb = os.path.join(ddir, f"thumb_{ep:02d}.jpg")

    try:
        iframe_url, ck_full, dl_result = await asyncio.to_thread(
            process_episode_all_in_one, ep, sn, tmp_ts
        )

        if not dl_result or not dl_result[1]:
            return False, "فشل التحميل"

        size = dl_result[0]
        print(f"\n📦 {size/(1024*1024):.2f} MB")
        actual_dur = await asyncio.to_thread(get_real_duration, tmp_ts) if os.path.exists(tmp_ts) else 0
        print(f"🎞️ المدة: {actual_dur}s")

        if actual_dur < MIN_EPISODE_DURATION:
            return False, f"مدة قصيرة ({actual_dur}s)"

        print(f"\n🗜️ ضغط...")
        if SKIP_COMPRESS:
            shutil.copy2(tmp_ts, fin)
        else:
            if not compress_144p(tmp_ts, fin):
                shutil.copy2(tmp_ts, fin)

        if not os.path.exists(fin):
            return False, "لا ملف نهائي"

        real_final_dur = await asyncio.to_thread(get_real_duration, fin)
        print(f"   🎞️ المدة النهائية: {real_final_dur}s")

        print(f"\n🖼️ Thumbnail...")
        await asyncio.to_thread(thumb, fin, thb)

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


# ═══════════════════════════════════════════════════════════
#  Config + main
# ═══════════════════════════════════════════════════════════
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
    print("🎬 Video Downloader v18.2 — Fast + Resource-safe")
    if TEST_MODE: print("🧪 TEST_MODE")
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS//60}m")
    print(f"⚡ batch={BROWSER_BATCH} | workers={CURL_CFFI_WORKERS} | compress_threads={COMPRESS_THREADS}")
    print(f"🗜️ compression: {COMPRESS_PRESET}/CRF{COMPRESS_CRF}/{COMPRESS_SCALE}p")
    print(f"🌐 single browser session per episode")
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
    if e_ep - s_ep + 1 > 50:
        e_ep = s_ep + 49

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
        if remaining() < MIN_EPISODE_TIME:
            skipped = list(range(ep, e_ep + 1))
            print(f"\n⏰ لا وقت كافٍ للحلقة {ep}")
            break

        ep_timeout = min(EPISODE_TIMEOUT_MAX, max(240, remaining() - 60))
        try:
            ok, msg = await asyncio.wait_for(
                process_episode(ep, sn, snar, season, ddir),
                timeout=ep_timeout,
            )
        except asyncio.TimeoutError:
            print(f"⏰ timeout على الحلقة {ep}")
            ok, msg = False, "timeout"

        if ok:
            ok_n += 1
            print(f"✅ {ep}  [{elapsed_str()}]")
        else:
            failed.append(ep)
            print(f"❌ {ep}: {msg}  [{elapsed_str()}]")

        if ep < e_ep:
            if remaining() < MIN_EPISODE_TIME:
                skipped = list(range(ep + 1, e_ep + 1))
                break
            w = random.randint(WAIT_MIN, WAIT_MAX)
            print(f"⏳ {w}s...")
            await asyncio.sleep(w)

    print(f"\n{'='*60}")
    print(f"⏱️ {elapsed_str()} | متبقي: {remaining()//60}m")
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
