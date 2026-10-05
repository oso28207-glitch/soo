#!/usr/bin/env python3
"""
Ahwaktv Multi-Server Video Downloader & Compressor (Local)
- يكتشف السيرفرات في صفحة المشاهدة، يجرب كل سيرفر حتى ينجح،
  ثم يحمّل الفيديو ويضغطه إلى 360p.
"""

import os, sys, time, re, json, shutil, subprocess, tempfile, asyncio
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# ═══════════════════════════════════════════════════════════
#  إعدادات قابلة للتعديل
# ═══════════════════════════════════════════════════════════
TARGET_URL = "https://yam.ahwaktv.net/see.php?vid=5b5a090aa"
OUTPUT_DIR = "downloads"
COMPRESS_SCALE = 360
COMPRESS_CRF = 28
COMPRESS_PRESET = "veryfast"
KEEP_ORIGINAL = False
MAX_SERVERS_TO_TRY = 5          # عدد السيرفرات التي سيتم تجربتها كحد أقصى

# ═══════════════════════════════════════════════════════════
#  تثبيت المكتبات
# ═══════════════════════════════════════════════════════════
def install_requirements():
    print("📦 تثبيت المكتبات المطلوبة...")
    reqs = ["seleniumbase>=4.30.0", "curl_cffi>=0.7.0"]
    for r in reqs:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", r, "--quiet"])
            print(f"  ✅ {r}")
        except Exception:
            print(f"  ⚠️ فشل تثبيت {r}")

install_requirements()

from seleniumbase import SB
from curl_cffi import requests as cffi_requests

# ═══════════════════════════════════════════════════════════
#  دوال مساعدة
# ═══════════════════════════════════════════════════════════
def compress_video(input_path, output_path, scale=360):
    """ضغط الفيديو إلى الدقة المطلوبة."""
    print(f"🗜️ ضغط الفيديو إلى {scale}p...")
    cmd = [
        'ffmpeg', '-y', '-err_detect', 'ignore_err',
        '-fflags', '+discardcorrupt+genpts',
        '-analyzeduration', '50M', '-probesize', '50M',
        '-i', input_path,
        '-vf', f'scale=-2:{scale}',
        '-c:v', 'libx264', '-crf', str(COMPRESS_CRF),
        '-preset', COMPRESS_PRESET,
        '-c:a', 'aac', '-b:a', '96k',
        '-movflags', '+faststart',
        '-max_muxing_queue_size', '4096',
        output_path
    ]
    try:
        t0 = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0:
            print(f"❌ فشل الضغط: {result.stderr[:300]}")
            return False
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            size_mb = os.path.getsize(output_path) / (1024*1024)
            print(f"✅ تم الضغط: {size_mb:.2f} MB في {time.time()-t0:.1f}s")
            return True
        return False
    except Exception as e:
        print(f"❌ خطأ في الضغط: {e}")
        return False

# ═══════════════════════════════════════════════════════════
#  اكتشاف السيرفرات من الصفحة
# ═══════════════════════════════════════════════════════════
def extract_servers_from_page(sb):
    """
    يحاول استخراج قائمة السيرفرات من الصفحة.
    يعيد قائمة من القواميس: [{"id": "...", "name": "...", "selector": "..."}]
    """
    servers = []

    # 1) البحث عن عناصر تحمل onclick يحتوي على getServer أو server
    try:
        js = """
        (function(){
            var out = [];
            var els = document.querySelectorAll('[onclick*="erver"], [onclick*="vid"], .server-item, .server-btn, li[id^="s_"], ul.serversList li');
            els.forEach(function(el, idx){
                var txt = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                if (txt.length > 0 && txt.length < 100) {
                    out.push({
                        index: idx,
                        text: txt,
                        id: el.id || '',
                        className: el.className || '',
                        tag: el.tagName
                    });
                }
            });
            return out;
        })();
        """
        result = sb.cdp.execute_script(js)
        if result and isinstance(result, list):
            for item in result:
                selector = None
                if item.get('id'):
                    selector = f"#{item['id']}"
                elif item.get('className'):
                    # خذ أول كلاس
                    cls = item['className'].split()[0]
                    selector = f".{cls}"
                if selector:
                    servers.append({
                        "id": item.get('id', f"srv_{item['index']}"),
                        "name": item.get('text', f"Server {item['index']+1}"),
                        "selector": selector
                    })
    except Exception as e:
        print(f"⚠️ خطأ في استخراج السيرفرات: {e}")

    # 2) إذا لم نجد شيئًا، جرب البحث عن روابط iframe مباشرة
    if not servers:
        try:
            iframes = sb.find_elements("iframe")
            for i, ifr in enumerate(iframes):
                src = ifr.get_attribute("src") or ""
                if src.startswith("http"):
                    servers.append({
                        "id": f"iframe_{i}",
                        "name": f"iframe_{i}",
                        "selector": None,
                        "iframe_src": src
                    })
        except:
            pass

    print(f"   🔍 تم العثور على {len(servers)} سيرفر")
    for s in servers[:5]:
        print(f"      · {s['name'][:40]}")
    return servers

# ═══════════════════════════════════════════════════════════
#  التقاط m3u8 من الشبكة
# ═══════════════════════════════════════════════════════════
def capture_m3u8_from_page(sb, wait_seconds=25):
    """ينتظر ويجمع كل روابط m3u8 من أداء الصفحة."""
    m3u8_urls = []
    print(f"   ⏳ انتظار ظهور m3u8 (حتى {wait_seconds}s)...")

    for i in range(wait_seconds):
        sb.sleep(1)
        try:
            perf = sb.cdp.execute_script("""
                (function(){
                    try {
                        return performance.getEntriesByType('resource')
                            .map(function(e){ return e.name; });
                    } catch(e){ return []; }
                })();
            """)
            if perf and isinstance(perf, list):
                for u in perf:
                    if ('.m3u8' in u or '.mpd' in u) and u not in m3u8_urls:
                        m3u8_urls.append(u)
                        print(f"      ✅ m3u8: {u[:110]}")
        except:
            pass

        # أيضًا حاول قراءة أي iframe أو فيديو
        if i % 5 == 0:
            try:
                sb.cdp.execute_script("""
                    (function(){
                        try {
                            var v = document.querySelector('video');
                            if (v && v.src && v.src.indexOf('.m3u8') > -1) {
                                // append to a global var
                                if (!window.__m3u8_list) window.__m3u8_list = [];
                                if (window.__m3u8_list.indexOf(v.src) === -1)
                                    window.__m3u8_list.push(v.src);
                            }
                        } catch(e){}
                    })();
                """)
                extra = sb.cdp.execute_script("return window.__m3u8_list || [];")
                if extra and isinstance(extra, list):
                    for u in extra:
                        if u not in m3u8_urls:
                            m3u8_urls.append(u)
                            print(f"      ✅ m3u8 (video): {u[:110]}")
            except:
                pass

        if m3u8_urls:
            break

    return m3u8_urls

# ═══════════════════════════════════════════════════════════
#  تحميل الفيديو من رابط m3u8
# ═══════════════════════════════════════════════════════════
def download_m3u8(m3u8_url, output_dir, referer_url):
    """ينزّل مقاطع m3u8 ويدمجها."""
    print(f"   📥 تحميل من: {m3u8_url[:100]}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": referer_url,
        "Origin": f"{urlparse(referer_url).scheme}://{urlparse(referer_url).netloc}",
        "Accept": "*/*",
    }

    # جلب محتوى m3u8
    try:
        resp = cffi_requests.get(m3u8_url, headers=headers, impersonate="chrome124", timeout=30, verify=False)
        resp.raise_for_status()
        m3u8_content = resp.text
    except Exception as e:
        print(f"   ❌ فشل جلب m3u8: {e}")
        return None

    # تحليل المقاطع
    base_url = m3u8_url.rsplit('/', 1)[0] + '/'
    segments = []
    for line in m3u8_content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.endswith('.ts') or '.ts?' in line or '.m4s' in line:
            if not line.startswith('http'):
                line = urljoin(base_url, line)
            segments.append(line)

    if not segments:
        print("   ❌ لا توجد مقاطع في m3u8.")
        return None

    print(f"   📦 {len(segments)} مقطع")

    # تنزيل المقاطع
    seg_dir = tempfile.mkdtemp(prefix="ahwaktv_segs_")
    downloaded = {}
    failed = 0

    def dl_seg(idx_url):
        idx, seg_url = idx_url
        for imp in ["chrome124", "chrome120", "chrome110"]:
            try:
                r = cffi_requests.get(seg_url, headers=headers, impersonate=imp, timeout=30, verify=False)
                if r.status_code == 200 and len(r.content) > 100:
                    p = os.path.join(seg_dir, f"seg_{idx:06d}.ts")
                    with open(p, 'wb') as f:
                        f.write(r.content)
                    return idx, p, len(r.content)
            except:
                continue
        return idx, None, 0

    print("   ⬇️ تنزيل المقاطع...")
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(dl_seg, (i, s)): i for i, s in enumerate(segments)}
        done = 0
        total_bytes = 0
        for fut in as_completed(futures):
            idx, path, size = fut.result()
            done += 1
            if path:
                downloaded[idx] = path
                total_bytes += size
            else:
                failed += 1
            if done % 30 == 0 or done == len(segments):
                print(f"      📥 {done}/{len(segments)} | {total_bytes/(1024*1024):.1f} MB | فشل: {failed}")

    if not downloaded or failed > len(segments) * 0.3:
        print(f"   ❌ فشل كبير: {failed}/{len(segments)}")
        shutil.rmtree(seg_dir, ignore_errors=True)
        return None

    # دمج
    print("   🔗 دمج المقاطع...")
    sorted_segs = [downloaded[k] for k in sorted(downloaded.keys())]
    concat_file = os.path.join(seg_dir, "concat.txt")
    with open(concat_file, 'w') as f:
        for p in sorted_segs:
            f.write(f"file '{p}'\n")

    output_ts = os.path.join(output_dir, "raw_video.ts")
    concat_cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'warning',
        '-f', 'concat', '-safe', '0', '-i', concat_file,
        '-c', 'copy', '-f', 'mpegts', '-y', output_ts
    ]
    result = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=600)
    shutil.rmtree(seg_dir, ignore_errors=True)

    if result.returncode != 0 or not os.path.exists(output_ts):
        print(f"   ❌ فشل الدمج: {result.stderr[:200]}")
        return None

    size_mb = os.path.getsize(output_ts) / (1024*1024)
    print(f"   ✅ ملف أولي: {size_mb:.2f} MB")
    return output_ts

# ═══════════════════════════════════════════════════════════
#  الدالة الرئيسية: تجربة السيرفرات
# ═══════════════════════════════════════════════════════════
def try_servers_and_download(url, output_dir):
    """يفتح الصفحة، يجرب السيرفرات، ويعيد مسار الملف الخام."""
    print(f"🌐 فتح الصفحة: {url}")

    with SB(uc=True, xvfb=True, headless=True, incognito=True,
            disable_csp=True, page_load_strategy="eager") as sb:
        sb.activate_cdp_mode(url)
        sb.sleep(5)

        # استخراج السيرفرات
        servers = extract_servers_from_page(sb)

        if not servers:
            print("⚠️ لم يتم العثور على سيرفرات. سأحاول التقاط m3u8 مباشرة...")
            m3u8_urls = capture_m3u8_from_page(sb, wait_seconds=30)
            if m3u8_urls:
                return download_m3u8(m3u8_urls[0], output_dir, url)
            return None

        # تجربة كل سيرفر
        for idx, srv in enumerate(servers[:MAX_SERVERS_TO_TRY]):
            print(f"\n🎯 تجربة السيرفر {idx+1}/{min(len(servers), MAX_SERVERS_TO_TRY)}: {srv['name'][:50]}")

            try:
                if srv.get("iframe_src"):
                    # إذا كان السيرفر عبارة عن iframe مباشر
                    sb.cdp.open(srv["iframe_src"])
                    sb.sleep(3)
                elif srv.get("selector"):
                    # النقر على السيرفر
                    try:
                        sb.cdp.click_if_visible(srv["selector"])
                    except:
                        try:
                            sb.click(srv["selector"])
                        except:
                            pass
                    sb.sleep(3)

                # محاولة تشغيل الفيديو
                for sel in ["video", ".jw-icon-playback", ".vjs-big-play-button",
                            "[class*='play']", ".jwplayer"]:
                    try:
                        sb.cdp.click_if_visible(sel)
                    except:
                        pass

                # التقاط m3u8
                m3u8_urls = capture_m3u8_from_page(sb, wait_seconds=20)

                if m3u8_urls:
                    print(f"   ✨ {len(m3u8_urls)} رابط m3u8")
                    # جرب كل رابط حتى ينجح أحدها
                    for m3u8 in m3u8_urls[:3]:
                        result = download_m3u8(m3u8, output_dir, url)
                        if result:
                            return result
                else:
                    print("   ❌ لا m3u8 من هذا السيرفر")

            except Exception as e:
                print(f"   ⚠️ خطأ: {str(e)[:100]}")

        print("❌ فشلت جميع السيرفرات.")
        return None

# ═══════════════════════════════════════════════════════════
#  main
# ═══════════════════════════════════════════════════════════
async def main():
    print("=" * 60)
    print("🎬 Ahwaktv Multi-Server Downloader")
    print(f"🔗 {TARGET_URL}")
    print(f"🗜️ النهائي: {COMPRESS_SCALE}p")
    print("=" * 60)

    # التحقق من FFmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ FFmpeg")
    except:
        print("❌ FFmpeg غير مثبت.")
        return

    out_dir = os.path.join(os.getcwd(), OUTPUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    print(f"📁 {out_dir}")

    # التحميل
    raw_file = try_servers_and_download(TARGET_URL, out_dir)
    if not raw_file:
        print("❌ فشل التحميل.")
        return

    # الضغط
    final_path = os.path.join(out_dir, "final_360p.mp4")
    if compress_video(raw_file, final_path, COMPRESS_SCALE):
        print(f"\n✅ الملف النهائي: {final_path}")
        if not KEEP_ORIGINAL:
            try:
                os.remove(raw_file)
                print("🗑️ حذف الملف الخام.")
            except:
                pass
    else:
        print("\n❌ فشل الضغط. الملف الخام محفوظ.")
        final_path = raw_file

    print(f"\n📁 {final_path}")

if __name__ == "__main__":
    asyncio.run(main())
