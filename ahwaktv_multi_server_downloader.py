#!/usr/bin/env python3
"""
Ahwaktv Multi-Server Video Downloader & Compressor
- يكتشف السيرفرات في صفحة المشاهدة، يجرب كل سيرفر حتى ينجح.
- يستخدم FFmpeg مباشرة لتحميل HLS (يتعامل مع fMP4 + AES-128 تلقائيًا).
- يضغط الفيديو إلى 360p.
"""

import os, sys, time, re, shutil, subprocess
from urllib.parse import urlparse

# ═══════════════════════════════════════════════════════════
#  إعدادات قابلة للتعديل
# ═══════════════════════════════════════════════════════════
TARGET_URL = "https://yam.ahwaktv.net/see.php?vid=5b5a090aa"
OUTPUT_DIR = "downloads"
COMPRESS_SCALE = 360
COMPRESS_CRF = 28
COMPRESS_PRESET = "veryfast"
KEEP_ORIGINAL = False
MAX_SERVERS_TO_TRY = 5

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")

# ═══════════════════════════════════════════════════════════
#  تثبيت المكتبات
# ═══════════════════════════════════════════════════════════
def install_requirements():
    print("📦 تثبيت المكتبات المطلوبة...")
    for r in ["seleniumbase>=4.30.0"]:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install",
                                   "--upgrade", r, "--quiet"])
            print(f"  ✅ {r}")
        except Exception:
            print(f"  ⚠️ فشل تثبيت {r}")

install_requirements()

from seleniumbase import SB


# ═══════════════════════════════════════════════════════════
#  ضغط الفيديو
# ═══════════════════════════════════════════════════════════
def compress_video(input_path, output_path, scale=360):
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
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0:
            print(f"❌ فشل الضغط: {r.stderr[-500:]}")
            return False
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"✅ تم الضغط: {mb:.2f} MB في {time.time() - t0:.1f}s")
            return True
        return False
    except Exception as e:
        print(f"❌ خطأ في الضغط: {e}")
        return False


# ═══════════════════════════════════════════════════════════
#  استخراج السيرفرات من الصفحة
# ═══════════════════════════════════════════════════════════
def extract_servers_from_page(sb):
    servers = []
    try:
        js = """
        (function(){
            var out = [];
            var els = document.querySelectorAll(
                '[onclick*="erver"], [onclick*="vid"], .server-item, .server-btn, ' +
                'li[id^="s_"], ul.serversList li, .serversList li, .server a, .tab-server'
            );
            els.forEach(function(el, idx){
                var txt = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                if (txt.length > 0 && txt.length < 120) {
                    out.push({
                        index: idx, text: txt,
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
                    selector = f".{item['className'].split()[0]}"
                if selector:
                    servers.append({
                        "id": item.get('id', f"srv_{item['index']}"),
                        "name": item.get('text', f"Server {item['index']+1}"),
                        "selector": selector
                    })
    except Exception as e:
        print(f"⚠️ خطأ في استخراج السيرفرات: {e}")

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
        except Exception:
            pass

    print(f"   🔍 تم العثور على {len(servers)} سيرفر")
    for s in servers[:5]:
        print(f"      · {s['name'][:50]}")
    return servers


# ═══════════════════════════════════════════════════════════
#  التقاط m3u8 من الشبكة
# ═══════════════════════════════════════════════════════════
def capture_m3u8_from_page(sb, wait_seconds=25):
    """يجمع روابط m3u8 الحقيقية (يتجاهل ping.gif من JWPlayer)."""
    m3u8_urls = []
    print(f"   ⏳ انتظار ظهور m3u8 (حتى {wait_seconds}s)...")

    def is_valid(u):
        ul = u.lower()
        if '.m3u8' not in ul and '.mpd' not in ul:
            return False
        bad = ['ping.gif', 'jwpltx', 'analytics', '.gif',
               'beacon', 'track', 'player.js']
        return not any(b in ul for b in bad)

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
                    if is_valid(u) and u not in m3u8_urls:
                        m3u8_urls.append(u)
                        print(f"      ✅ m3u8: {u[:110]}")
        except Exception:
            pass

        if i % 5 == 0:
            try:
                sb.cdp.execute_script("""
                    (function(){
                        try {
                            var v = document.querySelector('video');
                            if (v && v.src && v.src.indexOf('.m3u8') > -1) {
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
                        if is_valid(u) and u not in m3u8_urls:
                            m3u8_urls.append(u)
                            print(f"      ✅ m3u8 (video): {u[:110]}")
            except Exception:
                pass

        if m3u8_urls:
            break

    def priority(u):
        ul = u.lower()
        if 'master.m3u8' in ul: return 0
        if 'index-' in ul: return 1
        if 'index.m3u8' in ul: return 2
        if '.mpd' in ul: return 3
        return 4
    m3u8_urls.sort(key=priority)
    return m3u8_urls


# ═══════════════════════════════════════════════════════════
#  تحميل HLS عبر FFmpeg (بدون فلتر صوت غير مناسب)
# ═══════════════════════════════════════════════════════════
def download_with_ffmpeg(m3u8_url, output_dir, referer_url):
    """يستخدم FFmpeg لتحميل HLS مباشرة والإخراج بصيغة MP4 سليمة."""
    print(f"   📥 ffmpeg HLS: {m3u8_url[:110]}")
    output_mp4 = os.path.join(output_dir, "raw_video.mp4")

    origin = f"{urlparse(referer_url).scheme}://{urlparse(referer_url).netloc}"
    headers_str = (
        f"Referer: {referer_url}\r\n"
        f"Origin: {origin}\r\n"
    )

    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
        '-headers', headers_str,
        '-user_agent', UA,
        '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
        '-allowed_extensions', 'ALL',
        '-i', m3u8_url,
        '-c', 'copy',
        '-movflags', '+faststart',
        '-max_muxing_queue_size', '4096',
        output_mp4
    ]

    try:
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0 or not os.path.exists(output_mp4):
            print(f"   ❌ ffmpeg فشل: {r.stderr[-400:]}")
            return None
        size = os.path.getsize(output_mp4)
        if size < 1024 * 1024:
            print(f"   ❌ الملف صغير جدًا: {size} bytes")
            try: os.remove(output_mp4)
            except: pass
            return None
        mb = size / (1024 * 1024)
        print(f"   ✅ ffmpeg: {mb:.2f} MB في {time.time()-t0:.1f}s")

        # فحص سلامة الملف الخام
        probe = subprocess.run(
            ['ffprobe', '-v', 'error',
             '-show_entries', 'format=duration,size',
             '-of', 'default=noprint_wrappers=1', output_mp4],
            capture_output=True, text=True
        )
        if probe.returncode == 0:
            print(f"   🔍 فحص: {probe.stdout.strip().replace(chr(10), ' | ')}")
        else:
            print(f"   ⚠️ تحذير ffprobe: {probe.stderr[:200]}")

        return output_mp4
    except Exception as e:
        print(f"   ❌ {e}")
        return None


# ═══════════════════════════════════════════════════════════
#  تجربة السيرفرات
# ═══════════════════════════════════════════════════════════
def try_servers_and_download(url, output_dir):
    print(f"🌐 فتح الصفحة: {url}")

    with SB(uc=True, xvfb=True, headless=False,
            incognito=True, disable_csp=True,
            page_load_strategy="eager") as sb:
        try:
            sb.activate_cdp_mode()
            sb.cdp.open(url)
            sb.sleep(5)

            servers = extract_servers_from_page(sb)

            if not servers:
                print("⚠️ لا سيرفرات — محاولة التقاط m3u8 مباشرة...")
                m3u8_urls = capture_m3u8_from_page(sb, wait_seconds=30)
                for m3u8 in m3u8_urls[:3]:
                    result = download_with_ffmpeg(m3u8, output_dir, url)
                    if result:
                        return result
                return None

            for idx, srv in enumerate(servers[:MAX_SERVERS_TO_TRY]):
                print(f"\n🎯 السيرفر {idx+1}/"
                      f"{min(len(servers), MAX_SERVERS_TO_TRY)}: {srv['name'][:50]}")

                try:
                    if srv.get("iframe_src"):
                        sb.cdp.open(srv["iframe_src"])
                        sb.sleep(3)
                    elif srv.get("selector"):
                        try:
                            sb.cdp.click_if_visible(srv["selector"])
                        except Exception:
                            try:
                                sb.click(srv["selector"])
                            except Exception:
                                pass
                        sb.sleep(3)

                    for sel in ["video", ".jw-icon-playback", ".vjs-big-play-button",
                                "[class*='play']", ".jwplayer"]:
                        try:
                            sb.cdp.click_if_visible(sel)
                        except Exception:
                            pass

                    m3u8_urls = capture_m3u8_from_page(sb, wait_seconds=20)

                    if m3u8_urls:
                        print(f"   ✨ {len(m3u8_urls)} رابط m3u8 صالح")
                        for m3u8 in m3u8_urls[:3]:
                            result = download_with_ffmpeg(m3u8, output_dir, url)
                            if result:
                                return result
                    else:
                        print("   ❌ لا m3u8 من هذا السيرفر")

                except Exception as e:
                    print(f"   ⚠️ خطأ: {str(e)[:100]}")

            print("❌ فشلت جميع السيرفرات.")
            return None
        except Exception as e:
            print(f"❌ خطأ عام: {e}")
            import traceback
            traceback.print_exc()
            return None


# ═══════════════════════════════════════════════════════════
#  main
# ═══════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("🎬 Ahwaktv Downloader (ffmpeg HLS native)")
    print(f"🔗 {TARGET_URL}")
    print(f"🗜️ النهائي: {COMPRESS_SCALE}p")
    print("=" * 60)

    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ FFmpeg")
    except Exception:
        print("❌ FFmpeg غير مثبت.")
        return

    out_dir = os.path.join(os.getcwd(), OUTPUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    print(f"📁 {out_dir}")

    raw_file = try_servers_and_download(TARGET_URL, out_dir)
    if not raw_file:
        print("❌ فشل التحميل.")
        return

    final_path = os.path.join(out_dir, "final_360p.mp4")
    if compress_video(raw_file, final_path, COMPRESS_SCALE):
        print(f"\n✅ الملف النهائي: {final_path}")
        if not KEEP_ORIGINAL:
            try:
                os.remove(raw_file)
                print("🗑️ حذف الملف الخام.")
            except Exception:
                pass
    else:
        print("\n❌ فشل الضغط. الملف الخام محفوظ.")
        final_path = raw_file

    print(f"\n📁 {final_path}")


if __name__ == "__main__":
    main()
