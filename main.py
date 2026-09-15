#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - Universal Multi-Server
v18.1 — Fast mode: ultrafast compression + huge batches + 350min runtime
"""

import os, sys, time, json, base64, subprocess, shutil, asyncio, random, re, tempfile, hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse, urlencode, parse_qs

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

# ⏱️ الحد الزمني — GitHub Actions يسمح بـ 360 دقيقة كحد أقصى
MAX_RUNTIME_SECONDS = 350 * 60

MIN_VALID_SIZE = 100 * 1024
MIN_PARTIAL_ACCEPT = 30 * 1024 * 1024
MIN_EPISODE_DURATION = 900
WAIT_MIN, WAIT_MAX = 3, 6

YTDLP_TIMEOUT = 1800
YTDLP_TIMEOUT_IFRAME = 90
FFMPEG_TIMEOUT = 1800
STALL_TIMEOUT = 90

# ⚡⚡ التسريع
BROWSER_BATCH = 24               # ← مرفوع من 12
BROWSER_BATCH_TIMEOUT = 45       # ← مخفّض من 90
CURL_CFFI_WORKERS = 16

# إعادة المحاولة
SEGMENT_RETRY = 1                # ← مخفّض من 2
M3U8_CANDIDATE_LIMIT = 6

# أوقات الانتظار — مخفّضة
PARENT_WAIT_FAST = 2
JWPLAYER_WAIT = 30
M3U8_CAPTURE_WAIT = 20

# ⏱️ إدارة أفضل للحلقات
EPISODE_TIMEOUT_MAX = 25 * 60
MIN_EPISODE_TIME = 4 * 60

# ضغط سريع
COMPRESS_PRESET = "ultrafast"
COMPRESS_CRF = 30
COMPRESS_THREADS = 0
COMPRESS_SCALE = 144

# أنماط كشف السيرفرات
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
            out = _dedup_cookies(r["cookies"])
            if out:
                return out
    except Exception:
        pass
    try:
        raw = sb.cdp.get_all_cookies()
        if raw:
            return _dedup_cookies(raw)
    except Exception:
        pass
    return []


def get_cookies_safe(sb):
    d = {}
    for c in get_cookies_full(sb):
        n, v = c.get("name", ""), c.get("value", "")
        if n and v:
            d[n] = v
    return d


def sanitize_cookies(d):
    if not d:
        return {}
    clean = {}
    for k, v in d.items():
        if not k or not v:
            continue
        k2 = str(k).strip().replace('\n', '').replace('\r', '')
        v2 = str(v).strip().replace('\n', '').replace('\r', '')
        if k2 and v2:
            clean[k2] = v2
    return clean


def get_all_cookies_string(d):
    clean = sanitize_cookies(d)
    if not clean:
        return ""
    return "; ".join([f"{k}={v}" for k, v in clean.items()])[:8000]


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
        r'/([a-z0-9]{12})\.html',
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
    for name in ['file', 'videoUrl', 'fileUrl', 'streamUrl', 'hlsUrl',
                 'm3u8', 'source', 'videoSrc', 'src', 'url', 'playlist']:
        for m in re.finditer(
            rf'["\']?{name}["\']?\s*[:=]\s*["\']([^"\']{{20,}})["\']', text):
            u = m.group(1).replace('\\/', '/')
            if ('.m3u8' in u or '.mpd' in u or '.mp4' in u) and u.startswith('http'):
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


def build_m3u8_variants(original_url, video_id=None):
    variants = [original_url]
    if '?' in original_url:
        base, q = original_url.split('?', 1)
        qs = '?' + q
        tm = re.search(r'\bt=([^&]+)', qs)
        token = tm.group(1) if tm else ''
    else:
        base, qs, token = original_url, '', ''
    d = base.rsplit('/', 1)[0] if '/' in base else ''
    if not d:
        return variants
    orig_fname = base.rsplit('/', 1)[-1]
    for fname in ['index-v1-a1.m3u8', 'master.m3u8', 'index.m3u8',
                  'playlist.m3u8', 'index-f1-v1-a1.m3u8']:
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
#  ⚡ Browser fetch (unchanged core)
# ═══════════════════════════════════════════════════════════
def _poll_js(sb, done_var, result_var, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        sb.cdp.sleep(0.2)
        try:
            if sb.cdp.execute_script(f"return window.{done_var} === true"):
                try:
                    return sb.cdp.execute_script(f"return window.{result_var}")
                except Exception:
                    return None
        except Exception:
            pass
    return None


def browser_fetch_text_multi(sb, url, timeout=15):
    url_json = json.dumps(url)
    methods = [
        ("fetch-no-cred",
         f"fetch({url_json}, {{mode:'cors'}})"),
        ("fetch-with-cred",
         f"fetch({url_json}, {{mode:'cors', credentials:'include'}})"),
    ]
    for idx, (name, fetch_expr) in enumerate(methods):
        done_var = f"__d{idx+10}"
        res_var = f"__r{idx+10}"
        js = f"""
        (function(){{
            window.{done_var}=false; window.{res_var}=null;
            try {{
                {fetch_expr}
                    .then(function(r){{ r.text().then(function(t){{
                        window.{res_var}={{ok:true,status:r.status,text:t}};
                        window.{done_var}=true;
                    }}).catch(function(e){{
                        window.{res_var}={{ok:false,error:'read:'+String(e)}};
                        window.{done_var}=true;
                    }});
                    }}).catch(function(e){{
                        window.{res_var}={{ok:false,error:'fetch:'+String(e)}};
                        window.{done_var}=true;
                    }});
            }} catch(e) {{
                window.{res_var}={{ok:false,error:'try:'+String(e)}};
                window.{done_var}=true;
            }}
        }})();
        """
        try:
            sb.cdp.execute_script(js)
        except Exception:
            continue
        r = _poll_js(sb, done_var, res_var, timeout)
        if r and r.get("ok") and r.get("status") == 200 and r.get("text"):
            return r.get("text"), name
    # XHR fallback
    for idx, (name, cred) in enumerate([("xhr-no-cred", "false"), ("xhr-with-cred", "true")]):
        done_var = f"__dx{idx}"
        res_var = f"__rx{idx}"
        js = f"""
        (function(){{
            window.{done_var}=false; window.{res_var}=null;
            try {{
                var x = new XMLHttpRequest();
                x.open('GET', {url_json}, true);
                x.withCredentials = {cred};
                x.onload = function(){{
                    window.{res_var}={{ok:true,status:x.status,text:x.responseText}};
                    window.{done_var}=true;
                }};
                x.onerror = function(){{
                    window.{res_var}={{ok:false,error:'xhr'}};
                    window.{done_var}=true;
                }};
                x.send();
            }} catch(e) {{
                window.{res_var}={{ok:false,error:'try'}};
                window.{done_var}=true;
            }}
        }})();
        """
        try:
            sb.cdp.execute_script(js)
        except Exception:
            continue
        r = _poll_js(sb, done_var, res_var, timeout)
        if r and r.get("ok") and r.get("status") == 200 and r.get("text"):
            return r.get("text"), name
    return None, None


def browser_fetch_batch_b64(sb, urls, timeout=45):
    if not urls:
        return {}
    urls_json = json.dumps(urls)
    js = """
    (function(){
        window.__br = {};
        window.__bd = false;
        var urls = %s;
        var results = {};
        var pending = urls.length;
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
                        var bin = '';
                        var chunk = 16384;
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


def download_segments_via_browser(sb, segments, out_path, tag="br"):
    total = len(segments)
    print(f"   🌐 {tag}: تحميل {total} segment (batch={BROWSER_BATCH})...", flush=True)
    seg_dir = tempfile.mkdtemp(prefix="hls_br_")
    seg_paths, failed = {}, 0
    total_bytes = 0

    for i in range(0, total, BROWSER_BATCH):
        if exceeded():
            break
        batch = segments[i:i + BROWSER_BATCH]
        result = browser_fetch_batch_b64(sb, batch, timeout=BROWSER_BATCH_TIMEOUT)

        retry_indices = []
        for idx_str, b64 in result.items():
            try:
                idx_local = int(idx_str)
            except Exception:
                continue
            seg_idx = i + idx_local
            if b64:
                try:
                    data = base64.b64decode(b64)
                    p = os.path.join(seg_dir, f"seg_{seg_idx:06d}.ts")
                    with open(p, 'wb') as f:
                        f.write(data)
                    seg_paths[seg_idx] = p
                    total_bytes += len(data)
                except Exception:
                    retry_indices.append((seg_idx, batch[idx_local]))
            else:
                retry_indices.append((seg_idx, batch[idx_local]))

        # إعادة محاولة سريعة
        if retry_indices and SEGMENT_RETRY > 0:
            retry_urls = [u for _, u in retry_indices]
            retry_res = browser_fetch_batch_b64(sb, retry_urls, timeout=BROWSER_BATCH_TIMEOUT)
            for idx_str, b64 in retry_res.items():
                try:
                    idx_local = int(idx_str)
                except Exception:
                    continue
                seg_idx, _ = retry_indices[idx_local]
                if b64:
                    try:
                        data = base64.b64decode(b64)
                        p = os.path.join(seg_dir, f"seg_{seg_idx:06d}.ts")
                        with open(p, 'wb') as f:
                            f.write(data)
                        seg_paths[seg_idx] = p
                        total_bytes += len(data)
                    except Exception:
                        failed += 1
                else:
                    failed += 1
        elif retry_indices:
            failed += len(retry_indices)

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
#  Player detection
# ═══════════════════════════════════════════════════════════
def detect_player_state(sb):
    try:
        r = sb.cdp.execute_script("""
            (function(){
                try {
                    var out = {player: 'none', state: 'unknown', duration: 0, src: ''};
                    if (typeof jwplayer !== 'undefined') {
                        var p = jwplayer();
                        if (p) {
                            out.player = 'jwplayer';
                            out.state = (p.getState && p.getState()) || 'unknown';
                            out.duration = (p.getDuration && p.getDuration()) || 0;
                        }
                    }
                    var v = document.querySelector('video');
                    if (v) {
                        if (out.player === 'none') out.player = 'html5';
                        if (out.state === 'unknown' || out.state === 'none') {
                            out.state = v.paused ? (v.readyState > 0 ? 'paused' : 'loading') : 'playing';
                        }
                        if (!out.duration && v.duration && isFinite(v.duration)) out.duration = v.duration;
                        out.src = v.src || v.currentSrc || '';
                    }
                    return out;
                } catch(e) { return {player:'error', state:String(e).slice(0,50), duration:0, src:''}; }
            })();
        """)
        if r and isinstance(r, dict):
            return r
    except Exception:
        pass
    return {"player": "none", "state": "unknown", "duration": 0, "src": ""}


def trigger_play_universal(sb):
    for sel in ["video", "button.vjs-big-play-button", ".jw-icon-playback",
                ".jw-icon-display", ".jw-display-icon-container",
                "[class*='jw-display']", "[class*='play']",
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
    try:
        for key in [' ']:
            sb.driver.execute_cdp_cmd("Input.dispatchKeyEvent", {
                "type": "keyDown", "key": key, "code": "Space", "windowsVirtualKeyCode": 32,
            })
            sb.driver.execute_cdp_cmd("Input.dispatchKeyEvent", {
                "type": "keyUp", "key": key, "code": "Space", "windowsVirtualKeyCode": 32,
            })
    except Exception:
        pass


def click_center_of_player(sb):
    try:
        rect = sb.cdp.execute_script("""
            (function(){
                try {
                    var cs = [document.querySelector('video'),
                              document.querySelector('iframe[src*="vidsp"]'),
                              document.querySelector('.watch iframe'),
                              document.querySelector('iframe')];
                    for (var i=0;i<cs.length;i++) {
                        var el = cs[i];
                        if (!el) continue;
                        var r = el.getBoundingClientRect();
                        if (r.width > 50 && r.height > 50) {
                            return {x: Math.round(r.left+r.width/2),
                                    y: Math.round(r.top+r.height/2)};
                        }
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
                sb.cdp.sleep(1)
            return rect
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
#  cffi session
# ═══════════════════════════════════════════════════════════
def create_cffi_session(cookies_full):
    for impersonate in ["chrome124", "chrome120", "chrome110"]:
        try:
            session = cffi_requests.Session(impersonate=impersonate)
            added = 0
            for c in cookies_full or []:
                try:
                    name = c.get("name", ""); value = c.get("value", "")
                    domain = c.get("domain", "") or ""
                    path = c.get("path", "/") or "/"
                    if not name or not value:
                        continue
                    try:
                        session.cookies.set(name, value, domain=domain, path=path)
                        added += 1
                    except Exception:
                        try:
                            session.cookies.set(name, value)
                            added += 1
                        except Exception:
                            pass
                except Exception:
                    pass
            print(f"      🔑 cffi[{impersonate}]: {added} كوكي", flush=True)
            return session
        except Exception:
            continue
    return cffi_requests.Session()


# ═══════════════════════════════════════════════════════════
#  Main extraction
# ═══════════════════════════════════════════════════════════
def extract_and_download_universal(iframe_url, out_path, watch_url=None):
    print(f"   🌐 [v18.1] {iframe_url[:90]}", flush=True)
    server_type = detect_server_type(iframe_url)
    file_code = extract_file_code(iframe_url)
    print(f"      🏷️ {server_type} | code: {file_code or 'N/A'}", flush=True)

    lf = tempfile.mktemp(suffix="_netlog.txt")
    with open(lf, "w") as f:
        f.write("")

    def _log(u):
        try:
            with open(lf, "a", encoding="utf-8") as fh:
                fh.write(u + "\n"); fh.flush()
        except Exception:
            pass

    def _read_log():
        try:
            with open(lf, encoding="utf-8") as fh:
                return [l.strip() for l in fh if l.strip()]
        except Exception:
            return []

    cookies_full, cookies_dict = [], {}
    m3u8_urls = []
    download_result = None

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
                                print(f"      ✅ [net] {u[:130]}", flush=True)
                        except Exception:
                            pass

                    sb.cdp.add_handler(mycdp.network.RequestWillBeSent, on_req)
                except Exception:
                    pass

                # ═══ S1: cookies سريع جداً (اختياري) ═══
                if watch_url:
                    print(f"      🌐 [S1] الصفحة الأم (سريع)...", flush=True)
                    try:
                        sb.cdp.open(watch_url)
                        sb.cdp.sleep(PARENT_WAIT_FAST)
                        cookies_full = get_cookies_full(sb)
                        cookies_dict = get_cookies_safe(sb)
                        print(f"      🍪 S1: {len(cookies_dict)}", flush=True)
                    except Exception:
                        pass

                # ═══ S2: Page.navigate مباشر ═══
                print(f"      🔀 [S2] Page.navigate...", flush=True)
                try:
                    sb.driver.execute_cdp_cmd("Page.navigate", {
                        "url": iframe_url,
                        "referrer": watch_url or "",
                    })
                except Exception:
                    try:
                        sb.cdp.open(iframe_url)
                    except Exception:
                        pass

                sb.cdp.sleep(4)

                try:
                    cur = sb.cdp.get_current_url()
                    html_len = len(sb.cdp.get_page_source() or "")
                    print(f"      🔍 URL: {cur[:80]}", flush=True)
                    print(f"      📄 HTML: {html_len} chars", flush=True)
                except Exception:
                    pass

                # ═══ انتظار مشغل ═══
                player_seen = False
                for tick in range(JWPLAYER_WAIT // 2):
                    sb.cdp.sleep(1)
                    info = detect_player_state(sb)
                    if info.get("player") not in ("none", "error"):
                        print(f"      ✅ {info['player']} بعد {(tick+1)*1}s", flush=True)
                        player_seen = True
                        break

                if not player_seen:
                    print(f"      ⚠️ لم يظهر مشغل معروف", flush=True)

                # ═══ تشغيل + التقاط ═══
                m3u8_found = False
                for cycle in range(6):
                    click_center_of_player(sb)
                    trigger_play_universal(sb)
                    sb.cdp.sleep(1)
                    if any(x in u for u in _read_log() for x in [".m3u8", ".mpd"]):
                        print(f"      ✨ m3u8 في الشبكة بعد دورة {cycle+1}", flush=True)
                        m3u8_found = True
                        break

                if not m3u8_found:
                    for i in range(M3U8_CAPTURE_WAIT):
                        sb.cdp.sleep(1)
                        if any(x in u for u in _read_log() for x in [".m3u8", ".mpd"]):
                            print(f"      ✨ m3u8 بعد {(i+1)}s", flush=True)
                            m3u8_found = True
                            break

                info = detect_player_state(sb)
                print(f"      📺 {info.get('player')} | {info.get('state')} | dur={info.get('duration')}", flush=True)

                cookies_full = get_cookies_full(sb) or cookies_full
                cookies_dict = get_cookies_safe(sb) or cookies_dict

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

                # أولويات
                idx_files = [u for u in m3u8_now if 'index-' in u.lower()]
                master = [u for u in m3u8_now if 'master' in u.lower()]
                mpd = [u for u in m3u8_now if '.mpd' in u.lower()]
                others = [u for u in m3u8_now if u not in idx_files and u not in master and u not in mpd]
                m3u8_urls = idx_files + master + mpd + others

                print(f"      🎯 {len(m3u8_urls)} مرشح", flush=True)
                for u in m3u8_urls[:4]:
                    print(f"         · {u[:120]}", flush=True)

                # ═══ تحميل ═══
                if m3u8_urls:
                    for m3u8_url in m3u8_urls[:M3U8_CANDIDATE_LIMIT]:
                        if download_result or exceeded():
                            break
                        print(f"      🎯 {m3u8_url[:100]}", flush=True)
                        content, method = browser_fetch_text_multi(sb, m3u8_url, timeout=15)
                        if not content:
                            print(f"         ❌ فشلت كل الطرق", flush=True)
                            continue
                        print(f"         ✅ {method} → {len(content)}b", flush=True)

                        if ".mpd" in m3u8_url.lower() or "<MPD" in content[:500]:
                            print(f"         📋 MPD → ffmpeg", flush=True)
                            ff_cmd = build_ffmpeg_cmd(m3u8_url, out_path, iframe_url,
                                                      {"dict": cookies_dict, "list": cookies_full})
                            ok2, info2, _ = run_with_adaptive_monitoring(
                                ff_cmd, out_path, FFMPEG_TIMEOUT, "ffmpeg-dash"
                            )
                            if ok2:
                                download_result = (info2, True)
                                m3u8_urls = [m3u8_url]
                            continue

                        segments, variants = parse_m3u8_content(content, m3u8_url.rsplit('/', 1)[0])
                        if not segments and variants:
                            print(f"         📋 master → {len(variants)} variant", flush=True)
                            for v in variants[:3]:
                                vc, vm = browser_fetch_text_multi(sb, v, timeout=15)
                                if vc:
                                    vb = v.rsplit('/', 1)[0]
                                    segs2, _ = parse_m3u8_content(vc, vb)
                                    if segs2:
                                        segments = segs2
                                        m3u8_url = v
                                        print(f"         ✅ variant {vm}: {len(segments)} seg", flush=True)
                                        break

                        if segments:
                            print(f"         ⬇️ {len(segments)} segment", flush=True)
                            download_result = download_segments_via_browser(
                                sb, segments, out_path, tag=method
                            )
                            if download_result:
                                m3u8_urls = [m3u8_url]
                                break

                if not download_result:
                    print(f"      ⚠️ لا نتيجة", flush=True)
                    if not m3u8_urls:
                        m3u8_urls = [iframe_url]

            except Exception as e:
                print(f"      ❌ {str(e)[:150]}", flush=True)
    except Exception as e:
        print(f"      ❌ {str(e)[:150]}", flush=True)

    try:
        os.remove(lf)
    except Exception:
        pass

    return m3u8_urls, cookies_dict, cookies_full, download_result


# ═══════════════════════════════════════════════════════════
#  ffmpeg / yt-dlp fallbacks
# ═══════════════════════════════════════════════════════════
def build_ytdlp_cmd(url, out_path, referer, cookies_info, cookies_file=None):
    origin = origin_of(referer) or ""
    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '--no-warnings', '--no-playlist', '--no-part',
        '--retries', '15', '--fragment-retries', '40',
        '--socket-timeout', '60',
        '--concurrent-fragments', '16',
        '--no-check-certificate', '--continue',
        '--hls-use-mpegts', '--hls-prefer-native',
        '--no-abort-on-error',
        '--file-access-retries', '10', '--extractor-retries', '5',
        '--impersonate', 'chrome',
        '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        '--referer', referer,
    ]
    if origin:
        cmd += ['--add-header', f'Origin:{origin}']
    cmd += ['--add-header', 'Accept:*/*']
    if cookies_file and os.path.exists(cookies_file):
        cmd += ['--cookies', cookies_file]
    cmd += ['-f', 'best[height<=720]/best', '-o', out_path, url]
    return cmd


def build_ffmpeg_cmd(input_url, out_path, referer, cookies_info):
    origin = origin_of(referer) or ""
    cookie_str = ""
    if isinstance(cookies_info, dict):
        cookie_str = get_all_cookies_string(cookies_info.get("dict", {}))
    header_lines = [
        f"Referer: {referer}",
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept: */*",
    ]
    if origin:
        header_lines.insert(1, f"Origin: {origin}")
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
        '-i', input_url, '-c', 'copy', '-f', 'mpegts', '-y', out_path,
    ]


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
                print(f"      ⏱️  {tag}: {size/(1024*1024):.1f} MB | {now-start:.0f}s", flush=True)
                last_report = now
            if now - start > total_timeout:
                try: proc.kill(); proc.wait(timeout=5)
                except Exception: pass
                log_file.close()
                if best_size >= MIN_PARTIAL_ACCEPT:
                    return True, best_size, False
                return False, f"timeout@{best_size}", False
            if now - last_change > STALL_TIMEOUT and size > 0:
                try: proc.kill(); proc.wait(timeout=5)
                except Exception: pass
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
    if size >= MIN_VALID_SIZE:
        return True, size, (exit_code == 0)
    return False, f"exited@{size}", (exit_code == 0)


# ═══════════════════════════════════════════════════════════
#  collect iframes
# ═══════════════════════════════════════════════════════════
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
            time.sleep(2)
            fu = sb.get_current_url()
            if not fu.endswith('/'):
                fu += '/'
            wu = fu + '?do=watch'
            watch_url_final = wu
            print(f"📺 {wu}")
            sb.open(wu)
            time.sleep(2)

            try:
                sb.wait_for_element("ul.serversList", timeout=15)
                print("✅ السيرفرات")
            except Exception:
                print("⚠️ لا سيرفرات")
                return result, watch_url_final

            html = sb.get_page_source()
            servers = extract_servers(html)

            if not servers:
                try:
                    iframes = sb.find_elements(".watch iframe, iframe[src]")
                    for idx, ifr in enumerate(iframes):
                        src = ifr.get_attribute("src")
                        if src and src.startswith("http"):
                            servers.append({"id": f"s_{idx}", "name": f"iframe_{idx}",
                                             "video": str(idx), "serverId": "0"})
                except Exception:
                    pass

            if not servers:
                return result, watch_url_final

            prio = {"luluvdo": 0, "vinovo": 1, "vidaraa": 2, "vids": 3, "v": 4,
                    "vidsonic": 5, "playmate": 6}
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
                    for _ in range(6):
                        time.sleep(0.5)
                        try:
                            new = sb.find_element(".watch iframe").get_attribute("src")
                            if new and new != old:
                                break
                        except Exception:
                            pass
                    if not new:
                        new = old
                    if not new or "about:blank" in new:
                        continue
                    new = new.replace("&amp;", "&")
                    if new == old:
                        if is_active or len(servers) == 1:
                            print(f"   ✅ (نشط) {new[:90]}")
                            result.append({"server": srv["name"], "url": new})
                        continue
                    print(f"   ✅ {new[:90]}")
                    result.append({"server": srv["name"], "url": new})
                except Exception as e:
                    print(f"   ❌ {str(e)[:80]}")
            return result, watch_url_final
        except Exception as e:
            print(f"❌ {e}")
            return result, watch_url_final


# ═══════════════════════════════════════════════════════════
#  ⚡⚡ Compression — سريع جداً
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
        '-c:a', 'aac', '-b:a', '48k', '-ac', '1',
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
        print(f"   ✅ {im:.2f}→{om:.2f} MB في {dt:.1f}s ({im/dt:.1f} MB/s)")
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
        res = await asyncio.to_thread(collect_iframes, ep, sn)
        iframes, watch_url = res
        if not iframes:
            return False, "لا iframes"
        print(f"📋 {len(iframes)} iframe")

        success_if = None
        dloaded = 0
        method = None

        for i, it in enumerate(iframes):
            if exceeded():
                break
            print(f"\n{'='*60}\n🎬 [{i+1}/{len(iframes)}] {it['server']}\n{'='*60}")
            iframes_url = it["url"]
            m3u8_urls, ck_dict, ck_full, dl_result = await asyncio.to_thread(
                extract_and_download_universal, iframes_url, tmp_ts, watch_url
            )

            if dl_result and dl_result[1]:
                size = dl_result[0]
                print(f"   📦 {size/(1024*1024):.2f} MB")
                actual_dur = await asyncio.to_thread(get_real_duration, tmp_ts) if os.path.exists(tmp_ts) else 0
                print(f"   🎞️ المدة: {actual_dur}s")
                if actual_dur >= MIN_EPISODE_DURATION:
                    success_if = iframes_url
                    dloaded = size
                    method = "browser"
                    print(f"   ✅ نجاح!")
            if success_if:
                break

        if not success_if:
            return False, "فشل"

        print(f"\n🎥 نجح: {method} | {dloaded/(1024*1024):.2f} MB")
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
    print("🎬 Video Downloader v18.1 — FAST MODE")
    if TEST_MODE: print("🧪 TEST_MODE")
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS//60}m")
    print(f"⚡ batch={BROWSER_BATCH} | retry={SEGMENT_RETRY} | workers={CURL_CFFI_WORKERS}")
    print(f"⚡ compression: preset={COMPRESS_PRESET}, crf={COMPRESS_CRF}, threads=all")
    print(f"⏱️ min/episode: {MIN_EPISODE_TIME//60}m | max/episode: {EPISODE_TIMEOUT_MAX//60}m")
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
        # فحص هل الوقت يكفي لبدء حلقة جديدة؟
        if remaining() < MIN_EPISODE_TIME:
            skipped = list(range(ep, e_ep + 1))
            print(f"\n⏰ لا وقت كافٍ لبدء الحلقة {ep}")
            print(f"   متبقي: {remaining()//60}m | المطلوب: {MIN_EPISODE_TIME//60}m")
            break

        ep_timeout = min(EPISODE_TIMEOUT_MAX, max(240, remaining() - 60))
        try:
            ok, msg = await asyncio.wait_for(
                process_episode(ep, sn, snar, season, ddir),
                timeout=ep_timeout,
            )
        except asyncio.TimeoutError:
            print(f"⏰ timeout على الحلقة {ep} بعد {ep_timeout//60}m")
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
