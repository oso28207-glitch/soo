#!/usr/bin/env python3
"""
Telegram Video Downloader & Uploader - shhaiid4u.net
v16.2 — Browser-native API fetch (bypass Cloudflare 403)
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
BROWSER_FETCH_BATCH = 6

# ✅ سيرفرات مدعومة بـ CDP extract (من v15.8)
LULUVDO_SITES = ['luluvdo.com', 'luluvdo.to']
VINOVO_SITES = ['vinovo.to']

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
#  بناء الرابط
# ============================================================
SEASON_AR_MAP = {
    1: "الاول", 2: "الثاني", 3: "الثالث", 4: "الرابع",
    5: "الخامس", 6: "السادس", 7: "السابع", 8: "الثامن",
    9: "التاسع", 10: "العاشر",
}


def build_episode_url(series_slug, episode_num, season_num=1):
    sn = series_slug.strip().strip('-')
    if "الموسم" not in sn:
        season_ar = SEASON_AR_MAP.get(season_num, "الاول")
        sn = f"{sn}-الموسم-{season_ar}"
    full_path = f"/watch/{sn}-الحلقة-{episode_num}-مدبلجة"
    return SITE_BASE + quote(full_path, safe='/-')


# ============================================================
#  ✅✅ v16.2: كل شيء داخل المتصفح
# ============================================================
def process_via_browser(page_url, out_path, debug_html_path=None):
    """
    1) افتح الصفحة
    2) استخرج playerBootstrap + servers list
    3) استدعِ API عبر fetch داخل المتصفح (same-origin مع CF clearance)
    4) احصل على stream URL
    5) إذا كان HLS على نفس النطاق → حمّل عبر المتصفح
    6) إذا فشل → استخدم servers list (luluvdo مثلاً) كـ fallback

    يرجع: (ok, info, method)
    """
    print(f"   🌐 [Browser] {page_url[:80]}", flush=True)
    result = {
        "ok": False,
        "info": "غير معروف",
        "method": None,
        "stream_url": None,
        "cookies_dict": {},
        "servers": [],
        "fallback_server_url": None,
    }

    try:
        with SB(uc=True, xvfb=True, headless=False, incognito=True,
                ad_block_on=True, disable_csp=True,
                page_load_strategy="eager", locale_code="ar") as sb:
            try:
                sb.activate_cdp_mode()
                sb.cdp.open(page_url)
                sb.cdp.sleep(8)

                # عنوان الصفحة
                try:
                    title = sb.cdp.execute_script("return document.title || ''")
                    print(f"   📄 {str(title)[:80]}", flush=True)
                except Exception:
                    pass

                html = sb.cdp.get_page_source()
                if debug_html_path:
                    try:
                        with open(debug_html_path, 'w', encoding='utf-8') as f:
                            f.write(html or "")
                    except Exception:
                        pass

                # استخرج playerBootstrap + servers
                player_api = None
                player_fallback = None
                servers = []

                # playerBootstrap JSON
                m = re.search(r'playerBootstrap\s*=\s*({[^;]+});', html)
                if m:
                    try:
                        pb = json.loads(m.group(1))
                        player_api = pb.get("api")
                        player_fallback = pb.get("fallback")
                        print(f"   ✅ playerBootstrap.api", flush=True)
                    except Exception:
                        pass

                # data-player-api fallback
                if not player_api:
                    m2 = re.search(r'data-player-api="([^"]+)"', html)
                    if m2:
                        player_api = m2.group(1)

                if not player_fallback:
                    m3 = re.search(r'data-player-fallback="([^"]+)"', html)
                    if m3:
                        player_fallback = m3.group(1)

                # servers array
                m4 = re.search(r'let servers = JSON\.parse\(\'([^\']+)\'\)', html)
                if m4:
                    try:
                        servers_json = m4.group(1).replace('\\"', '"').replace("\\/", "/")
                        servers = json.loads(servers_json)
                        # تجاهل canary
                        servers = [s for s in servers if not s.get("__canary")]
                        print(f"   📦 {len(servers)} سيرفر", flush=True)
                        result["servers"] = servers
                    except Exception as e:
                        print(f"   ⚠️ servers parse: {e}", flush=True)

                # جيب الكوكيز
                cookies_dict = {}
                try:
                    r = sb.driver.execute_cdp_cmd("Network.getAllCookies", {})
                    for c in r.get("cookies", []):
                        n, v = c.get("name", ""), c.get("value", "")
                        if n and v:
                            cookies_dict[n] = v
                except Exception:
                    pass
                result["cookies_dict"] = cookies_dict
                print(f"   🍪 {len(cookies_dict)} كوكي", flush=True)

                # ✅✅ استدعِ API عبر fetch داخل المتصفح
                stream_url = None
                if player_api:
                    print(f"   📡 API (browser fetch)...", flush=True)
                    stream_url = _browser_fetch_json(sb, player_api, timeout=30)

                if stream_url:
                    result["stream_url"] = stream_url
                    print(f"   ✅ stream: {stream_url[:120]}", flush=True)

                    # إذا كان HLS على نفس النطاق → حمّل عبر المتصفح
                    if ".m3u8" in stream_url or "/media-edge/" in stream_url or "/media/" in stream_url:
                        print(f"   🌐 تحميل عبر المتصفح (same-origin)...", flush=True)
                        ok = _browser_download_hls(sb, stream_url, out_path)
                        if ok:
                            result["ok"] = True
                            result["info"] = os.path.getsize(out_path) if os.path.exists(out_path) else 0
                            result["method"] = "Browser-HLS"
                            return result
                        else:
                            print(f"   ⚠️ فشل تحميل المتصفح — جرّب سيرفرات", flush=True)

                # ✅ fallback: ابحث عن luluvdo في servers
                for srv in servers:
                    url = srv.get("url", "")
                    if any(x in url for x in LULUVDO_SITES):
                        result["fallback_server_url"] = url
                        print(f"   🔄 fallback: luluvdo {url[:80]}", flush=True)
                        break

            except Exception as e:
                print(f"   ❌ {str(e)[:150]}", flush=True)
    except Exception as e:
        print(f"   ❌ {str(e)[:150]}", flush=True)

    return result


def _browser_fetch_json(sb, url, timeout=30):
    """يجيب JSON من API عبر fetch داخل المتصفح + polling"""
    url_json = json.dumps(url)
    js = """
    (function(){
        window.__apiResp = null;
        window.__apiRespDone = false;
        fetch(%s, {
            credentials: 'include',
            headers: {
                'Accept': 'application/json, text/plain, */*',
                'X-Requested-With': 'XMLHttpRequest',
            }
        })
            .then(r => r.text().then(t => {
                window.__apiResp = {status: r.status, text: t};
                window.__apiRespDone = true;
            }))
            .catch(e => {
                window.__apiResp = {status: -1, error: String(e)};
                window.__apiRespDone = true;
            });
    })();
    """ % url_json

    try:
        sb.cdp.execute_script(js)
    except Exception as e:
        print(f"      ❌ inject: {str(e)[:80]}", flush=True)
        return None

    start = time.time()
    while time.time() - start < timeout:
        time.sleep(0.3)
        try:
            done = sb.cdp.execute_script("return window.__apiRespDone === true")
        except Exception:
            done = False
        if done:
            try:
                res = sb.cdp.execute_script("return window.__apiResp")
            except Exception:
                return None
            if not res:
                return None
            status = res.get("status")
            text = res.get("text", "")
            print(f"      📡 API status={status}", flush=True)
            if status != 200:
                print(f"      📋 {text[:150]}", flush=True)
                return None
            try:
                data = json.loads(text)
                # ابحث عن stream في أي حقل
                for key in ["stream", "url", "file", "player", "embed"]:
                    if data.get(key):
                        return data[key]
                print(f"      📋 keys: {list(data.keys())}", flush=True)
                return None
            except Exception:
                print(f"      📋 ليست JSON: {text[:150]}", flush=True)
                return None
    return None


def _browser_download_hls(sb, m3u8_url, out_path):
    """
    يحمل HLS عبر المتصفح (fetch segments + base64).
    """
    print(f"      🌐 fetch m3u8...", flush=True)

    # 1) اجلب m3u8
    m3u8_text = _browser_fetch_text(sb, m3u8_url, timeout=30)
    if not m3u8_text:
        print(f"      ❌ فشل جلب m3u8", flush=True)
        return False

    base_url = m3u8_url.rsplit('/', 1)[0]

    def _parse(text, b_url):
        segs = []
        variants = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if '.m3u8' in line:
                variants.append(line if line.startswith('http') else urljoin(b_url + '/', line))
                continue
            if line.endswith('.ts') or '.ts?' in line or 'seg' in line.lower():
                segs.append(line if line.startswith('http') else urljoin(b_url + '/', line))
        return segs, variants

    segments, variants = _parse(m3u8_text, base_url)

    if not segments and variants:
        print(f"      📋 master → {len(variants)} variant", flush=True)
        for v in variants[:3]:
            vt = _browser_fetch_text(sb, v, timeout=30)
            if vt:
                v_base = v.rsplit('/', 1)[0]
                segments, _ = _parse(vt, v_base)
                if segments:
                    print(f"      ✅ variant: {len(segments)} segment", flush=True)
                    break

    if not segments:
        print(f"      ❌ no segments", flush=True)
        return False

    print(f"      ⬇️ {len(segments)} segment عبر المتصفح...", flush=True)

    seg_dir = tempfile.mkdtemp(prefix="hls_seg_")
    seg_paths = {}
    failed = 0
    total_bytes = 0

    for i in range(0, len(segments), BROWSER_FETCH_BATCH):
        if exceeded():
            break
        batch = segments[i:i+BROWSER_FETCH_BATCH]
        result = _browser_fetch_batch_b64(sb, batch, timeout=120)

        for idx_str, b64 in result.items():
            try:
                idx = int(idx_str)
            except Exception:
                continue
            seg_idx = i + idx
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

        done = min(i + BROWSER_FETCH_BATCH, len(segments))
        if done % 30 == 0 or done == len(segments):
            print(f"      📦 {done}/{len(segments)} | {total_bytes/(1024*1024):.1f} MB | فشل: {failed}", flush=True)

    if not seg_paths:
        try: shutil.rmtree(seg_dir, ignore_errors=True)
        except: pass
        return False

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
            return False
    except Exception:
        try: shutil.rmtree(seg_dir, ignore_errors=True)
        except: pass
        return False

    final_size = os.path.getsize(out_path)
    print(f"      ✅ ملف نهائي: {final_size/(1024*1024):.1f} MB", flush=True)
    try: shutil.rmtree(seg_dir, ignore_errors=True)
    except: pass
    return True


def _browser_fetch_text(sb, url, timeout=30):
    url_json = json.dumps(url)
    js = """
    (function(){
        window.__txt = null;
        window.__txtDone = false;
        fetch(%s, {credentials: 'include'})
            .then(r => r.text().then(t => {
                window.__txt = {status: r.status, text: t};
                window.__txtDone = true;
            }))
            .catch(e => {
                window.__txt = {status: -1, error: String(e)};
                window.__txtDone = true;
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
            done = sb.cdp.execute_script("return window.__txtDone === true")
        except Exception:
            done = False
        if done:
            try:
                res = sb.cdp.execute_script("return window.__txt")
            except Exception:
                return None
            if res and res.get("status") == 200:
                return res.get("text", "")
            return None
    return None


def _browser_fetch_batch_b64(sb, urls, timeout=120):
    if not urls:
        return {}
    urls_json = json.dumps(urls)
    js = """
    (function(){
        window.__b64 = {};
        window.__b64Done = false;
        var urls = %s;
        var results = {};
        var pending = urls.length;
        if (pending === 0) { window.__b64 = results; window.__b64Done = true; return; }
        urls.forEach(function(u, idx) {
            fetch(u, {credentials: 'include'})
                .then(r => {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.arrayBuffer();
                })
                .then(buf => {
                    var bytes = new Uint8Array(buf);
                    var binary = '';
                    var chunk = 8192;
                    for (var j = 0; j < bytes.length; j += chunk) {
                        binary += String.fromCharCode.apply(null, bytes.subarray(j, Math.min(j+chunk, bytes.length)));
                    }
                    results[String(idx)] = btoa(binary);
                    pending--;
                    if (pending === 0) { window.__b64 = results; window.__b64Done = true; }
                })
                .catch(e => {
                    results[String(idx)] = null;
                    pending--;
                    if (pending === 0) { window.__b64 = results; window.__b64Done = true; }
                });
        });
    })();
    """ % urls_json

    try:
        sb.cdp.execute_script(js)
    except Exception as e:
        print(f"      ❌ b64 inject: {str(e)[:80]}", flush=True)
        return {}

    start = time.time()
    while time.time() - start < timeout:
        time.sleep(0.3)
        try:
            done = sb.cdp.execute_script("return window.__b64Done === true")
        except Exception:
            done = False
        if done:
            try:
                res = sb.cdp.execute_script("return window.__b64")
            except Exception:
                return {}
            if isinstance(res, dict):
                return res
            return {}
    return {}


# ============================================================
#  ✅✅ v16.2: fallback عبر luluvdo (باستخدام v15.8 browser HLS)
# ============================================================
def try_luluvdo_fallback(luluvdo_url, out_path):
    """يفتح luluvdo، يستخرج m3u8، ويحمّل عبر المتصفح (same-origin)."""
    print(f"   🔄 [luluvdo fallback] {luluvdo_url[:80]}", flush=True)
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

                    sb.cdp.add_handler(mycdp.network.RequestWillBeSent, on_req)
                except Exception:
                    pass

                sb.cdp.open(luluvdo_url)
                sb.cdp.sleep(6)
                for _ in range(3):
                    for sel in ["video", "button.vjs-big-play-button", ".jw-icon-display"]:
                        try:
                            sb.cdp.click_if_visible(sel)
                        except Exception:
                            pass
                    sb.cdp.sleep(2)
                sb.cdp.sleep(8)

                try:
                    dom = sb.cdp.execute_script("""
                        return Array.from(document.querySelectorAll('video, source'))
                            .map(el => el.src || el.currentSrc).filter(s => s && s.includes('.m3u8'))[0] || null;
                    """)
                    if dom:
                        _log(dom)
                except Exception:
                    pass

                urls = []
                try:
                    with open(lf, encoding="utf-8") as fh:
                        urls = [u.strip() for u in fh.readlines() if u.strip()]
                except Exception:
                    pass

                all_m3u8 = [u for u in urls if ".m3u8" in u]
                master = [u for u in all_m3u8 if "master.m3u8" in u.lower()]
                index_files = [u for u in all_m3u8 if "index-" in u.lower()]
                others = [u for u in all_m3u8 if u not in master and u not in index_files]
                ordered = master + index_files + others

                if not ordered:
                    print(f"      ❌ لا m3u8", flush=True)
                    try: os.remove(lf)
                    except: pass
                    return False

                m3u8_url = ordered[0]
                print(f"      🎯 {m3u8_url[:100]}", flush=True)

                # انتقل إلى نفس النطاق (same-origin)
                try:
                    sb.cdp.open(m3u8_url)
                    sb.cdp.sleep(3)
                except Exception:
                    pass

                ok = _browser_download_hls(sb, m3u8_url, out_path)
                try: os.remove(lf)
                except: pass
                return ok
            except Exception as e:
                print(f"      ❌ {str(e)[:120]}", flush=True)
    except Exception as e:
        print(f"      ❌ {str(e)[:120]}", flush=True)

    try: os.remove(lf)
    except: pass
    return False


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

        result = await asyncio.to_thread(process_via_browser, page_url, tmp_ts, debug_html)

        success = False
        dloaded = 0

        if result["ok"]:
            success = True
            dloaded = result["info"]
            method = result["method"]
            print(f"   ✅ نجح عبر {method} | {dloaded/(1024*1024):.2f} MB")
        else:
            # ✅ fallback: luluvdo
            fb = result.get("fallback_server_url")
            if fb:
                print(f"   🔄 محاولة luluvdo fallback...", flush=True)
                ok = await asyncio.to_thread(try_luluvdo_fallback, fb, tmp_ts)
                if ok:
                    dloaded = os.path.getsize(tmp_ts) if os.path.exists(tmp_ts) else 0
                    success = True
                    method = "luluvdo-fallback"
                    print(f"   ✅ نجح عبر luluvdo | {dloaded/(1024*1024):.2f} MB")

        if not success:
            return False, f"فشل: {result['info']}"

        # تحقق من الملف
        if not os.path.exists(tmp_ts) or os.path.getsize(tmp_ts) < MIN_VALID_SIZE:
            return False, "ملف صغير"

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
    print("🎬 Video Downloader v16.2 — shhaiid4u.net")
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
