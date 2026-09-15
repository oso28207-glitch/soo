#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - u.3seq.com/.cam
v17.0 — Force browser to PLAY video + capture fresh m3u8 from network + dump embed HTML
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
SKIP_UPLOAD = os.environ.get("SKIP_UPLOAD", "false").lower() in ("true", "1", "yes")
SKIP_COMPRESS = os.environ.get("SKIP_COMPRESS", "false").lower() in ("true", "1", "yes")

MIN_VALID_SIZE = 100 * 1024
MIN_PARTIAL_ACCEPT = 30 * 1024 * 1024
MIN_EPISODE_DURATION = 900
MAX_RUNTIME_SECONDS = 165 * 60
WAIT_MIN, WAIT_MAX = 10, 20

YTDLP_TIMEOUT = 1800
YTDLP_TIMEOUT_IFRAME = 60
FFMPEG_TIMEOUT = 1800
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
#  Cookie utils
# ============================================================
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


def _dedup_cookies(raw_list):
    out, seen = [], set()
    for c in raw_list:
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
                print(f"      🍪 [CDP Network] {len(out)} كوكي", flush=True)
                return out
    except Exception:
        pass
    try:
        raw = sb.cdp.get_all_cookies()
        if raw:
            out = _dedup_cookies(raw)
            if out:
                print(f"      🍪 [sb.cdp] {len(out)} كوكي", flush=True)
                return out
    except Exception:
        pass
    try:
        raw = sb.driver.get_cookies()
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
    return "; ".join([f"{k}={v}" for k, v in clean.items()])[:8000]


def origin_of(url):
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return ""


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
#  cffi Session
# ============================================================
def create_cffi_session(cookies_full_list):
    session = cffi_requests.Session(impersonate="chrome120")
    added = 0
    for c in cookies_full_list or []:
        try:
            name = c.get("name", "")
            value = c.get("value", "")
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
    print(f"      🔑 cffi session: {added} كوكي", flush=True)
    return session


def parse_m3u8_content(text, base_url):
    segs, variants = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '.m3u8' in line:
            variants.append(line if line.startswith('http') else urljoin(base_url + '/', line))
            continue
        if line.endswith('.ts') or '.ts?' in line or 'seg' in line.lower():
            segs.append(line if line.startswith('http') else urljoin(base_url + '/', line))
    return segs, variants


def download_segments_with_session(session, segments, out_path, referer):
    print(f"   ⬇️ {len(segments)} segment...", flush=True)
    seg_dir = tempfile.mkdtemp(prefix="hls_curl_")
    seg_paths, failed, total_bytes = {}, 0, 0

    headers = {
        "Referer": referer,
        "Origin": origin_of(referer),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
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


# ============================================================
#  ✅ v17.0: Navigation helpers — Page.navigate with Referer
# ============================================================
def navigate_with_referrer(sb, url, referrer):
    """
    ✅ v17.0: استخدام Page.navigate مع referrer — يرسل Referer header
    بدون كسر التنقل مثل setExtraHTTPHeaders
    """
    try:
        sb.driver.execute_cdp_cmd("Page.navigate", {
            "url": url,
            "referrer": referrer,
        })
        return True
    except Exception as e:
        print(f"      ⚠️ Page.navigate: {str(e)[:80]}", flush=True)
        try:
            sb.cdp.open(url)
            return True
        except Exception as e2:
            print(f"      ⚠️ cdp.open: {str(e2)[:80]}", flush=True)
            return False


def wait_for_jwplayer_state(sb, timeout=60):
    """
    ✅ v17.0: انتظر حتى jwplayer يكون جاهز + يحاول getState
    """
    start = time.time()
    ready = False
    playing = False
    while time.time() - start < timeout:
        sb.cdp.sleep(2)
        try:
            state = sb.cdp.execute_script("""
                (function(){
                    try {
                        if (typeof jwplayer === 'undefined') return 'no_jwplayer';
                        var p = jwplayer();
                        if (!p) return 'no_instance';
                        var s = (p.getState && p.getState()) || 'unknown';
                        return s;
                    } catch(e) { return 'error:' + String(e).slice(0,30); }
                })();
            """)
            if state and state not in ('no_jwplayer', 'no_instance', 'unknown'):
                if not ready:
                    print(f"      📺 jwplayer state: {state}", flush=True)
                    ready = True
                if state == 'playing':
                    playing = True
                    return True
        except Exception:
            pass
    return playing


def trigger_play_comprehensive(sb):
    """
    ✅ v17.0: كل طرق التشغيل الممكنة
    """
    # 1) نقر على عناصر play
    for sel in ["video", "button.vjs-big-play-button",
                ".jw-icon-playback", ".jw-icon-display",
                ".jw-display-icon-container", ".jw-display-icon",
                "[class*='jw-display']", "[class*='play']",
                ".vjs-big-play-button", ".jwplayer"]:
        try:
            sb.cdp.click_if_visible(sel)
        except Exception:
            pass

    # 2) تشغيل برمجي
    try:
        sb.cdp.execute_script("""
            (function(){
                try {
                    if (typeof jwplayer !== 'undefined') {
                        var p = jwplayer();
                        if (p && p.play) { p.play(true); return; }
                    }
                    var v = document.querySelector('video');
                    if (v) {
                        v.muted = true;
                        v.play && v.play().catch(function(){});
                    }
                } catch(e){}
            })();
        """)
    except Exception:
        pass

    # 3) نقرات على مركز العناصر
    try:
        res = sb.cdp.execute_script("""
            (function(){
                try {
                    var v = document.querySelector('video');
                    if (v) {
                        var r = v.getBoundingClientRect();
                        return {x: Math.round(r.left + r.width/2),
                                y: Math.round(r.top + r.height/2)};
                    }
                    var w = document.querySelector('.jwplayer, .vjs-big-play-button, [class*="player"]');
                    if (w) {
                        var r2 = w.getBoundingClientRect();
                        return {x: Math.round(r2.left + r2.width/2),
                                y: Math.round(r2.top + r2.height/2)};
                    }
                    return null;
                } catch(e){ return null; }
            })();
        """)
        if res and res.get("x"):
            for _ in range(2):
                try:
                    sb.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
                        "type": "mousePressed", "x": res["x"], "y": res["y"],
                        "button": "left", "clickCount": 1,
                    })
                    sb.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
                        "type": "mouseReleased", "x": res["x"], "y": res["y"],
                        "button": "left", "clickCount": 1,
                    })
                except Exception:
                    pass
                sb.cdp.sleep(1)
    except Exception:
        pass

    # 4) keyboard space/enter
    try:
        sb.driver.execute_cdp_cmd("Input.dispatchKeyEvent", {
            "type": "keyDown", "key": " ", "code": "Space", "windowsVirtualKeyCode": 32,
        })
        sb.driver.execute_cdp_cmd("Input.dispatchKeyEvent", {
            "type": "keyUp", "key": " ", "code": "Space", "windowsVirtualKeyCode": 32,
        })
    except Exception:
        pass


def find_api_endpoints_in_html(html):
    """
    ✅ v17.0: ابحث عن مسارات API داخل HTML
    """
    endpoints = set()
    if not html:
        return list(endpoints)
    for m in re.finditer(r'["\'](/api/[^"\']+|/ajax/[^"\']+|/dl/[^"\']+|/player/[^"\']+\.(?:php|json))["\']', html):
        endpoints.add(m.group(1))
    for m in re.finditer(r'(https?://v\.vidsp\.net[^"\'\s<>]+)', html):
        endpoints.add(m.group(1))
    return list(endpoints)


def extract_script_srcs(html):
    """استخرج روابط JS من HTML"""
    srcs = []
    if not html:
        return srcs
    for m in re.finditer(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.I):
        u = m.group(1).strip()
        if u and not u.startswith('data:'):
            srcs.append(u)
    return list(dict.fromkeys(srcs))


def fetch_js_and_search_for_api(session, js_urls, base_url, referer):
    """✅ v17.0: اجلب ملفات JS وابحث فيها عن مسارات API"""
    found_apis = set()
    for js_url in js_urls[:10]:
        if not js_url.startswith('http'):
            js_url = urljoin(base_url + '/', js_url)
        try:
            r = session.get(js_url, headers={
                "Referer": referer,
                "User-Agent": "Mozilla/5.0",
            }, timeout=15, verify=False)
            if r.status_code == 200 and len(r.text) > 100:
                for m in re.finditer(r'["\'](/api/[a-zA-Z0-9_/\-]+)["\']', r.text):
                    found_apis.add(m.group(1))
                for m in re.finditer(r'["\'](https?://[^"\']*?/api/[a-zA-Z0-9_/\-]+)["\']', r.text):
                    found_apis.add(m.group(1))
                for m in re.finditer(r'url\s*[:=]\s*["\']([^"\']*/api/[^"\']+)["\']', r.text):
                    found_apis.add(m.group(1))
        except Exception:
            pass
    return list(found_apis)


def extract_m3u8_candidates_from_html(html):
    if not html:
        return []
    out, seen = [], set()
    for m in re.finditer(r'(https?:[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*)', html):
        u = m.group(1).replace('\\/', '/')
        if u not in seen:
            seen.add(u); out.append(u)
    for name in ['file', 'videoUrl', 'fileUrl', 'streamUrl', 'hlsUrl', 'm3u8', 'source', 'videoSrc']:
        for m in re.finditer(rf'["\']?{name}["\']?\s*[:=]\s*["\']([^"\']+\.m3u8[^"\']*)["\']', html):
            u = m.group(1).replace('\\/', '/')
            if u not in seen:
                seen.add(u); out.append(u)
    return out


# ============================================================
#  Main extraction
# ============================================================
def extract_and_download_via_browser(iframe_url, out_path, expected_dur=0,
                                      watch_url=None):
    print(f"   🌐 [Browser HLS v17.0] {iframe_url[:80]}", flush=True)
    if watch_url:
        print(f"      🌐 [Parent] {watch_url[:80]}", flush=True)

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

    cookies_dict = {}
    cookies_full = []
    m3u8_urls = []
    download_result = None
    out_dir = os.path.dirname(out_path)

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
                            if ".m3u8" in u:
                                print(f"      ✅ [net] {u[:130]}", flush=True)
                        except Exception:
                            pass

                    sb.cdp.add_handler(mycdp.network.RequestWillBeSent, on_req)
                except Exception as e:
                    print(f"      ⚠️ handler: {str(e)[:80]}", flush=True)

                # ═══ S1: parent page ═══
                if watch_url:
                    print(f"      🌐 [S1] فتح الصفحة الأم (get cookies)...", flush=True)
                    try:
                        sb.cdp.open(watch_url)
                        sb.cdp.sleep(10)
                        cookies_full = get_cookies_full(sb)
                        cookies_dict = get_cookies_safe(sb)
                        print(f"      🍪 S1: {len(cookies_dict)} كوكي", flush=True)

                        # انتظر تحميل iframe بالكامل
                        print(f"      ⏳ انتظار إضافي 20s...", flush=True)
                        sb.cdp.sleep(20)

                        # محاولة النقر داخل iframe
                        try:
                            rect = sb.cdp.execute_script("""
                                (function(){
                                    try {
                                        var cs = [
                                            document.querySelector('iframe[src*="vidsp"]'),
                                            document.querySelector('.watch iframe'),
                                            document.querySelector('iframe')
                                        ];
                                        for (var i=0;i<cs.length;i++) {
                                            var f = cs[i];
                                            if (!f) continue;
                                            var r = f.getBoundingClientRect();
                                            if (r.width > 50 && r.height > 50)
                                                return {x: Math.round(r.left+r.width/2),
                                                        y: Math.round(r.top+r.height/2),
                                                        w: Math.round(r.width),
                                                        h: Math.round(r.height)};
                                        }
                                        return null;
                                    } catch(e){ return null; }
                                })();
                            """)
                            if rect:
                                print(f"      🖱️ iframe @ ({rect['x']},{rect['y']}) {rect['w']}x{rect['h']}", flush=True)
                                # نقرات متعددة + حركة فأرة
                                for _ in range(3):
                                    try:
                                        sb.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
                                            "type": "mouseMoved",
                                            "x": rect['x'], "y": rect['y'],
                                        })
                                        sb.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
                                            "type": "mousePressed",
                                            "x": rect['x'], "y": rect['y'],
                                            "button": "left", "clickCount": 1,
                                        })
                                        sb.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
                                            "type": "mouseReleased",
                                            "x": rect['x'], "y": rect['y'],
                                            "button": "left", "clickCount": 1,
                                        })
                                    except Exception:
                                        pass
                                    sb.cdp.sleep(3)
                        except Exception as e:
                            print(f"      ⚠️ click: {str(e)[:80]}", flush=True)

                        # انتظر m3u8 من الشبكة
                        for i in range(20):
                            sb.cdp.sleep(2)
                            found = [u for u in _read_log() if '.m3u8' in u]
                            if found:
                                print(f"      ✨ m3u8 (S1) بعد {(i+1)*2}s", flush=True)
                                break
                    except Exception as e:
                        print(f"      ⚠️ S1: {str(e)[:100]}", flush=True)

                urls = _read_log()
                m3u8_now = [u for u in urls if '.m3u8' in u]
                print(f"      📊 S1: {len(m3u8_now)} m3u8 | إجمالي {len(urls)}", flush=True)
                if urls:
                    print(f"      📋 آخر 5 روابط:", flush=True)
                    for u in urls[-5:]:
                        print(f"         · {u[:120]}", flush=True)

                # ═══ S2: Page.navigate مع Referer صحيح ═══
                if not m3u8_now:
                    print(f"      🔀 [S2] Page.navigate إلى iframe مع Referer={watch_url[:60] if watch_url else 'None'}...", flush=True)
                    ok = navigate_with_referrer(sb, iframe_url, watch_url or "")
                    if ok:
                        sb.cdp.sleep(10)
                        try:
                            cur = sb.cdp.get_current_url()
                            html_len = len(sb.cdp.get_page_source() or "")
                            print(f"      🔍 URL: {cur[:100]}", flush=True)
                            print(f"      📄 HTML: {html_len} chars", flush=True)
                        except Exception:
                            pass

                        # انتظر jwplayer
                        print(f"      ⏳ انتظار jwplayer (60s)...", flush=True)
                        for tick in range(30):
                            sb.cdp.sleep(2)
                            try:
                                r = sb.cdp.execute_script(
                                    "return (typeof jwplayer !== 'undefined') ? 'yes' : 'no'"
                                )
                                if r == 'yes':
                                    print(f"      ✅ jwplayer ظهر بعد {(tick+1)*2}s", flush=True)
                                    break
                            except Exception:
                                pass

                        # تشغيل شامل
                        for cycle in range(6):
                            trigger_play_comprehensive(sb)
                            sb.cdp.sleep(3)

                        # انتظر أن يصبح playing
                        if wait_for_jwplayer_state(sb, timeout=30):
                            print(f"      ▶️ jwplayer في حالة playing!", flush=True)

                        # انتظر m3u8
                        for i in range(20):
                            sb.cdp.sleep(2)
                            found = [u for u in _read_log() if '.m3u8' in u]
                            if found:
                                print(f"      ✨ m3u8 (S2) بعد {(i+1)*2}s", flush=True)
                                break
                    else:
                        print(f"      ❌ فشل Page.navigate", flush=True)

                    cookies_full = get_cookies_full(sb) or cookies_full
                    cookies_dict = get_cookies_safe(sb) or cookies_dict

                urls = _read_log()
                m3u8_now = [u for u in urls if '.m3u8' in u]
                print(f"      📊 S2: {len(m3u8_now)} m3u8", flush=True)

                # performance API dump
                try:
                    perf = sb.cdp.execute_script("""
                        (function(){
                            try {
                                return performance.getEntriesByType('resource').map(e => e.name);
                            } catch(e){ return []; }
                        })();
                    """)
                    if perf and isinstance(perf, list):
                        perf_m3u8 = [u for u in perf if '.m3u8' in u]
                        print(f"      🔍 perf: {len(perf)} URLs | {len(perf_m3u8)} m3u8", flush=True)
                        for u in perf_m3u8[:3]:
                            if u not in m3u8_now:
                                m3u8_now.append(u)
                except Exception:
                    pass

                m3u8_urls = m3u8_now

                # ═══ Session ═══
                session = create_cffi_session(cookies_full)

                # ═══ إذا التقطنا m3u8 → حمّل ═══
                if m3u8_urls:
                    print(f"      🎯 محاولة تحميل m3u8 المُلتقط...", flush=True)
                    for m3u8_url in m3u8_urls[:3]:
                        if download_result:
                            break
                        print(f"         → {m3u8_url[:130]}", flush=True)
                        try:
                            r = session.get(m3u8_url, headers={
                                "Referer": iframe_url,
                                "Origin": "https://v.vidsp.net",
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                "Accept": "*/*",
                            }, timeout=25, verify=False)
                            print(f"            HTTP {r.status_code} | {len(r.text)}b", flush=True)
                            if r.status_code == 200:
                                segments, variants = parse_m3u8_content(r.text, m3u8_url.rsplit('/', 1)[0])
                                if not segments and variants:
                                    for v in variants[:3]:
                                        rv = session.get(v, headers={
                                            "Referer": iframe_url,
                                            "Origin": "https://v.vidsp.net",
                                            "User-Agent": "Mozilla/5.0",
                                        }, timeout=25, verify=False)
                                        if rv.status_code == 200:
                                            vb = v.rsplit('/', 1)[0]
                                            segs2, _ = parse_m3u8_content(rv.text, vb)
                                            if segs2:
                                                segments = segs2
                                                m3u8_url = v
                                                break
                                if segments:
                                    print(f"            ✅ {len(segments)} segment", flush=True)
                                    download_result = download_segments_with_session(
                                        session, segments, out_path, iframe_url
                                    )
                        except Exception as e:
                            print(f"            ❌ {str(e)[:100]}", flush=True)

                # ═══ Fallback: fetch embed HTML → ابحث عن API ═══
                if not download_result:
                    print(f"      🔎 [FALLBACK] جلب embed HTML + البحث عن API...", flush=True)
                    try:
                        ref_origin = origin_of(watch_url) or "https://u.3seq.cam"
                        r_html = session.get(iframe_url, headers={
                            "Referer": watch_url or "https://u.3seq.cam/",
                            "Origin": ref_origin,
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                            "Accept-Language": "en-US,en;q=0.9",
                            "Sec-Fetch-Site": "cross-site",
                            "Sec-Fetch-Mode": "navigate",
                            "Sec-Fetch-Dest": "iframe",
                        }, timeout=25, verify=False)
                        print(f"      📄 embed: HTTP {r_html.status_code} | {len(r_html.text)}b", flush=True)

                        if r_html.status_code == 200:
                            html = r_html.text
                            if out_dir:
                                try:
                                    with open(os.path.join(out_dir, "embed_debug.html"), 'w', encoding='utf-8') as fh:
                                        fh.write(html)
                                except Exception:
                                    pass

                            # اطبع مقتطف
                            print(f"      📝 أول 300 حرف من HTML:", flush=True)
                            print(f"         {html[:300]}", flush=True)

                            # script srcs
                            js_urls = extract_script_srcs(html)
                            print(f"      📜 سكربتات: {len(js_urls)}", flush=True)
                            for j in js_urls[:10]:
                                print(f"         · {j[:120]}", flush=True)

                            # APIs في HTML
                            apis = find_api_endpoints_in_html(html)
                            print(f"      🔗 APIs في HTML: {len(apis)}", flush=True)
                            for a in apis[:10]:
                                print(f"         · {a[:120]}", flush=True)

                            # جرّب كل API
                            for api in apis[:5]:
                                if download_result:
                                    break
                                api_full = api if api.startswith('http') else f"https://v.vidsp.net{api}"
                                # جرّب POST + GET
                                for method in ('GET', 'POST'):
                                    if download_result:
                                        break
                                    try:
                                        if method == 'GET':
                                            r = session.get(api_full, headers={
                                                "Referer": iframe_url,
                                                "Origin": "https://v.vidsp.net",
                                                "User-Agent": "Mozilla/5.0",
                                                "X-Requested-With": "XMLHttpRequest",
                                            }, timeout=15, verify=False)
                                        else:
                                            r = session.post(api_full, json={"filecode": "nsnddq6yxg8p", "device": "web"},
                                                             headers={
                                                                 "Referer": iframe_url,
                                                                 "Origin": "https://v.vidsp.net",
                                                                 "User-Agent": "Mozilla/5.0",
                                                                 "Content-Type": "application/json",
                                                                 "X-Requested-With": "XMLHttpRequest",
                                                             }, timeout=15, verify=False)
                                        print(f"      → {method} {api[:80]} → {r.status_code}", flush=True)
                                        if r.status_code == 200:
                                            text = r.text
                                            mm = re.search(r'(https?://[^"\'\s<>]+\.m3u8[^"\'\s<>]*)', text)
                                            if mm:
                                                found_url = mm.group(1)
                                                print(f"         🎯 m3u8! {found_url[:130]}", flush=True)
                                                rr2 = session.get(found_url, headers={
                                                    "Referer": iframe_url,
                                                    "Origin": "https://v.vidsp.net",
                                                    "User-Agent": "Mozilla/5.0",
                                                }, timeout=20, verify=False)
                                                if rr2.status_code == 200:
                                                    segments, variants = parse_m3u8_content(rr2.text, found_url.rsplit('/', 1)[0])
                                                    if segments:
                                                        download_result = download_segments_with_session(
                                                            session, segments, out_path, iframe_url
                                                        )
                                    except Exception as e:
                                        print(f"      ⚠️ {method} {api[:60]}: {str(e)[:80]}", flush=True)

                            # جرّب البحث في ملفات JS
                            if not download_result and js_urls:
                                print(f"      🔎 البحث في JS لـ APIs...", flush=True)
                                js_apis = fetch_js_and_search_for_api(session, js_urls,
                                                                       origin_of(iframe_url),
                                                                       iframe_url)
                                print(f"      🔗 APIs من JS: {len(js_apis)}", flush=True)
                                for a in js_apis[:10]:
                                    print(f"         · {a[:120]}", flush=True)

                                for api in js_apis[:10]:
                                    if download_result:
                                        break
                                    api_full = api if api.startswith('http') else f"https://v.vidsp.net{api}"
                                    try:
                                        r = session.get(api_full, headers={
                                            "Referer": iframe_url,
                                            "Origin": "https://v.vidsp.net",
                                            "User-Agent": "Mozilla/5.0",
                                        }, timeout=15, verify=False)
                                        print(f"      → GET {api[:80]} → {r.status_code}", flush=True)
                                        if r.status_code == 200:
                                            mm = re.search(r'(https?://[^"\'\s<>]+\.m3u8[^"\'\s<>]*)', r.text)
                                            if mm:
                                                found_url = mm.group(1)
                                                print(f"         🎯 m3u8! {found_url[:130]}", flush=True)
                                                rr2 = session.get(found_url, headers={
                                                    "Referer": iframe_url,
                                                    "Origin": "https://v.vidsp.net",
                                                    "User-Agent": "Mozilla/5.0",
                                                }, timeout=20, verify=False)
                                                if rr2.status_code == 200:
                                                    segments, _ = parse_m3u8_content(rr2.text, found_url.rsplit('/', 1)[0])
                                                    if segments:
                                                        download_result = download_segments_with_session(
                                                            session, segments, out_path, iframe_url
                                                        )
                                    except Exception:
                                        pass
                    except Exception as e:
                        print(f"      ❌ fallback: {str(e)[:120]}", flush=True)

                if not download_result:
                    print(f"      ⚠️ لا download_result", flush=True)
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

    return m3u8_urls, 0, cookies_dict, cookies_full, download_result


# ============================================================
#  Fallbacks (yt-dlp)
# ============================================================
def build_ytdlp_cmd(url, out_path, referer, cookies_info, cookies_file=None):
    origin = origin_of(referer) or "https://u.3seq.com"
    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '--no-warnings', '--no-playlist', '--no-part',
        '--retries', '20', '--fragment-retries', '50',
        '--socket-timeout', '60',
        '--concurrent-fragments', '8',
        '--no-check-certificate', '--continue',
        '--hls-use-mpegts', '--hls-prefer-native',
        '--no-abort-on-error',
        '--file-access-retries', '10', '--extractor-retries', '5',
        '--impersonate', 'chrome',
        '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        '--referer', referer,
        '--add-header', f'Origin:{origin}',
        '--add-header', 'Accept:*/*',
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
                el = now - start
                print(f"      ⏱️  {tag}: {size/(1024*1024):.1f} MB | {el:.0f}s", flush=True)
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


def download_video(url, out_path, referer, cookies_info=None, expected_dur=0,
                   is_iframe_fallback=False):
    if os.path.exists(out_path):
        try: os.remove(out_path)
        except Exception: pass

    if ".m3u8" not in url:
        return False, "not_m3u8", False

    cookies_file = None
    if cookies_info and isinstance(cookies_info, dict):
        cl = cookies_info.get("list", [])
        if cl:
            cookies_file = out_path + ".cookies.txt"
            try:
                with open(cookies_file, 'w', encoding='utf-8') as f:
                    f.write("# Netscape HTTP Cookie File\n")
                    for c in cl:
                        dom = c.get("domain", "") or ""
                        if not dom: continue
                        if not dom.startswith("."): dom = "." + dom
                        nm = str(c.get("name", ""))
                        vl = str(c.get("value", "")).replace("\n","").replace("\r","")
                        pc = c.get("path", "/") or "/"
                        sec = "TRUE" if c.get("secure", False) else "FALSE"
                        exp = int(c.get("expiry", 0) or 0)
                        f.write(f"{dom}\tTRUE\t{pc}\t{sec}\t{exp}\t{nm}\t{vl}\n")
            except Exception:
                cookies_file = None

    timeout = YTDLP_TIMEOUT_IFRAME if is_iframe_fallback else YTDLP_TIMEOUT
    print(f"   [yt-dlp] timeout={timeout}s...", flush=True)
    cmd = build_ytdlp_cmd(url, out_path, referer, cookies_info, cookies_file)
    ok, info, natural = run_with_adaptive_monitoring(cmd, out_path, timeout, "yt-dlp")
    try:
        if cookies_file and os.path.exists(cookies_file):
            os.remove(cookies_file)
    except: pass
    if ok and isinstance(info, (int, float)):
        return True, info, natural
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
    except Exception:
        return False


def meta(vp, accurate=False):
    w, h, d = 0, 0, 0
    try:
        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
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


async def process_episode(ep, sn, sn_ar, season, ddir):
    print(f"\n🎬 Ep {ep:02d}  [{elapsed_str()}]  ⏳ {remaining()//60}m")
    tmp_ts = os.path.join(ddir, f"temp_{ep:02d}.ts")
    fin = os.path.join(ddir, f"final_{ep:02d}.mp4")
    thb = os.path.join(ddir, f"thumb_{ep:02d}.jpg")

    try:
        print(f"\n{'='*60}\n📡 جمع iframes\n{'='*60}")
        res = await asyncio.to_thread(collect_iframes, ep, sn)
        iframes, watch_url = res
        if not iframes:
            return False, "لا iframes"
        print(f"\n📋 {len(iframes)} iframe")

        success_if = None
        dloaded = 0
        method = None

        for i, it in enumerate(iframes):
            if exceeded():
                break
            print(f"\n{'='*60}\n🎬 [{i+1}/{len(iframes)}] {it['server']}\n{'='*60}")

            iframes_url = it["url"]
            result = await asyncio.to_thread(
                extract_and_download_via_browser, iframes_url, tmp_ts, 0, watch_url
            )
            m3u8_urls, dur, ck_dict, ck_full, dl_result = result
            ck = {"dict": ck_dict, "list": ck_full}

            if dl_result and dl_result[1]:
                size = dl_result[0]
                print(f"   📦 {size/(1024*1024):.2f} MB")
                actual_dur = await asyncio.to_thread(get_real_duration, tmp_ts) if os.path.exists(tmp_ts) else 0
                print(f"   🎞️ المدة: {actual_dur}s")
                if actual_dur >= MIN_EPISODE_DURATION:
                    success_if = iframes_url
                    dloaded = size
                    method = "cffi"
                    print(f"   ✅ نجاح!")
            else:
                print(f"   ❌ fallback")
                fallback = list(m3u8_urls) if m3u8_urls else [iframes_url]
                for url_idx, url in enumerate(fallback[:3]):
                    if exceeded() or success_if:
                        break
                    is_iframe = (url == iframes_url)
                    print(f"\n   ⬇️ (fb#{url_idx+1}) {url[:100]}...")
                    t0 = time.time()
                    ok, info, natural = await asyncio.to_thread(
                        download_video, url, tmp_ts, watch_url or iframes_url, ck, 0, is_iframe
                    )
                    dt = time.time() - t0
                    if ok and isinstance(info, (int, float)):
                        size = int(info)
                        actual_dur = await asyncio.to_thread(get_real_duration, tmp_ts) if os.path.exists(tmp_ts) else 0
                        print(f"   📦 {size/(1024*1024):.1f} MB | {actual_dur}s في {dt:.1f}s")
                        if actual_dur >= MIN_EPISODE_DURATION:
                            success_if = iframes_url
                            dloaded = size
                            method = f"fb#{url_idx+1}"
                            break
                    else:
                        print(f"   ❌ ({info}) في {dt:.1f}s")
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
    print("🎬 Video Downloader v17.0")
    if TEST_MODE: print("🧪 TEST_MODE")
    print(f"⏱️ الحد: {MAX_RUNTIME_SECONDS//60}m")
    print(f"🌐 Force play + capture network + API discovery")
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
            print(f"⏳ {w}s...")
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
