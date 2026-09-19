#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_all.py — مُولّد الموقع الثابت لـ TelegramFlix

يقرأ من:  data.json  (في جذر المستودع)
يبني:
  - docs/index.html               (الصفحة الرئيسية)
  - docs/series/<name>.html       (صفحات المسلسلات)
  - docs/watch/<message_id>.html  (صفحات المشاهدة)

الاستخدام:
  python build_all.py           # بناء عادي
  python build_all.py --clean   # تنظيف ثم بناء
"""

import os
import re
import json
import shutil
import html
import argparse
from pathlib import Path
from urllib.parse import quote

# ═══════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════
ROOT        = Path(__file__).resolve().parent
OUT         = ROOT / "docs"                 # مجلد الإخراج (GitHub Pages)
DATA_FILE   = ROOT / "data.json"            # ✅ ملف البيانات الفعلي في الجذر
STATIC_SRC  = ROOT / "static"               # ملفات CSS/JS المصدرية
PROXY_URL   = "https://tg-webapp-proxy-58b.pages.dev"
SITE_NAME   = "TelegramFlix"
SITE_DESC   = "مشاهدة المسلسلات والأفلام مباشرة عبر Telegram"


# ═══════════════════════════════════════════════════════════════
# دوال مساعدة
# ═══════════════════════════════════════════════════════════════
def esc(s):
    """تهريب HTML"""
    return html.escape(str(s or ""), quote=True)


def enc(s):
    """ترميز URL"""
    return quote(str(s or ""), safe="")


def safe_name(s):
    """اسم ملف آمن (يدعم العربية)"""
    s = str(s or "").strip()
    s = re.sub(r"[^\w\u0600-\u06FF\-]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_") or "untitled"


def write_file(path, content):
    """كتابة ملف مع إنشاء المجلدات"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def fmt_duration(seconds):
    """تنسيق المدة بصيغة mm:ss أو hh:mm:ss"""
    try:
        s = int(seconds or 0)
    except Exception:
        return ""
    if s <= 0:
        return ""
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


# ═══════════════════════════════════════════════════════════════
# قالب HTML الأساسي
# ═══════════════════════════════════════════════════════════════
def base(title, body, depth=0, head="", scripts="", lang="ar", dir_="rtl"):
    prefix = "../" * depth if depth else ""
    return f'''<!DOCTYPE html>
<html lang="{lang}" dir="{dir_}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefix}static/style.css">
{head}
</head>
<body>
<header class="topbar">
  <a href="{prefix}index.html" class="logo">{SITE_NAME[:8]}<span>{SITE_NAME[8:]}</span></a>
  <nav class="nav"><a href="{prefix}index.html">الرئيسية</a></nav>
</header>
<main class="container">
{body}
</main>
<footer class="footer">
  <p>© {SITE_NAME} — جميع الحقوق محفوظة</p>
</footer>
{scripts}
</body>
</html>'''


# ═══════════════════════════════════════════════════════════════
# تحميل البيانات — يتوافق مع بنية data.json الفعلية
# ═══════════════════════════════════════════════════════════════
def load_data():
    """
    يقرأ data.json ويُعيد قائمة موحّدة من المسلسلات،
    كل مسلسل يحتوي على episodes كقائمة مسطّحة (مع رقم الموسم).
    """
    if not DATA_FILE.exists():
        print(f"⚠️  لم يُعثر على {DATA_FILE}")
        return []

    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️  خطأ في قراءة {DATA_FILE}: {e}")
        return []

    # ─── استخراج قائمة المسلسلات من البنية المختلفة ───
    if isinstance(raw, list):
        series_raw = raw
    elif isinstance(raw, dict):
        series_raw = raw.get("series") or raw.get("items") or []
    else:
        return []

    stream_base = ""
    if isinstance(raw, dict):
        stream_base = raw.get("stream_base", "")

    series_list = []
    for s in series_raw:
        name = s.get("name") or "بدون اسم"
        poster = s.get("poster_url") or s.get("poster") or ""
        description = s.get("description") or ""

        # ✅ تحويل seasons (قاموس) → قائمة مسطّحة
        episodes = []
        seasons = s.get("seasons")

        if isinstance(seasons, dict):
            for season_key, eps in seasons.items():
                try:
                    season_num = int(season_key)
                except Exception:
                    season_num = season_key
                if not isinstance(eps, list):
                    continue
                for ep in eps:
                    ep_copy = dict(ep)
                    ep_copy.setdefault("season", season_num)
                    episodes.append(ep_copy)
        elif isinstance(seasons, list):
            for season_obj in seasons:
                season_num = season_obj.get("season", 1)
                for ep in season_obj.get("episodes", []):
                    ep_copy = dict(ep)
                    ep_copy.setdefault("season", season_num)
                    episodes.append(ep_copy)
        elif isinstance(s.get("episodes"), list):
            episodes = s["episodes"]

        # ترتيب الحلقات حسب الموسم ثم رقم الحلقة
        def _sort_key(ep):
            try:
                return (int(ep.get("season", 1)), int(ep.get("episode", 0)))
            except Exception:
                return (999, 999)
        episodes.sort(key=_sort_key)

        series_list.append({
            "name": name,
            "poster": poster,
            "description": description,
            "episodes": episodes,
            "stream_base": stream_base,
        })

    return series_list


# ═══════════════════════════════════════════════════════════════
# الصفحة الرئيسية
# ═══════════════════════════════════════════════════════════════
def render_index(series_list):
    cards = []
    for s in series_list:
        name = s.get("name", "بدون اسم")
        poster = s.get("poster", "")
        count = len(s.get("episodes", []))
        url = "series/" + enc(safe_name(name)) + ".html"
        poster_html = (
            f'<img src="{esc(poster)}" alt="{esc(name)}" loading="lazy">'
            if poster else
            '<div class="poster-placeholder">📺</div>'
        )
        cards.append(f'''
    <a class="series-card" href="{url}">
      <div class="series-poster">{poster_html}</div>
      <div class="series-info">
        <h3>{esc(name)}</h3>
        <span class="series-meta">{count} حلقة</span>
      </div>
    </a>''')

    body = f'''
    <section class="hero">
      <h1>{SITE_NAME}</h1>
      <p>{SITE_DESC}</p>
    </section>
    <section class="series-grid">
      {''.join(cards) if cards else '<p class="empty">لا توجد مسلسلات متاحة حالياً.</p>'}
    </section>
    '''
    return base(f"{SITE_NAME} — الرئيسية", body, depth=0)


# ═══════════════════════════════════════════════════════════════
# صفحة المسلسل
# ═══════════════════════════════════════════════════════════════
def render_series(series):
    name = series.get("name", "بدون اسم")
    poster = series.get("poster", "")
    episodes = series.get("episodes", [])

    ep_cards = []
    for ep in episodes:
        ep_num = ep.get("episode", "?")
        season = ep.get("season", 1)
        msg_id = ep.get("message_id", "")
        duration = fmt_duration(ep.get("duration", 0))
        dur_html = f'<span class="ep-duration">⏱ {esc(duration)}</span>' if duration else ""
        ep_cards.append(f'''
      <a class="episode-card" href="../watch/{msg_id}.html">
        <div class="episode-num">الحلقة {esc(ep_num)}</div>
        <div class="episode-meta">الموسم {esc(season)} {dur_html}</div>
      </a>''')

    poster_html = (
        f'<img src="{esc(poster)}" alt="{esc(name)}">'
        if poster else
        '<div class="poster-placeholder">📺</div>'
    )

    body = f'''
    <div class="series-hero">
      <div class="series-poster-large">{poster_html}</div>
      <div class="series-details">
        <h1>{esc(name)}</h1>
        <p class="series-count">{len(episodes)} حلقة</p>
        <p class="series-desc">{esc(series.get("description", ""))}</p>
      </div>
    </div>
    <h2 class="section-title">الحلقات</h2>
    <div class="episodes-grid">
      {''.join(ep_cards) if ep_cards else '<p class="empty">لا توجد حلقات.</p>'}
    </div>
    '''
    return base(f"{name} — {SITE_NAME}", body, depth=1)


# ═══════════════════════════════════════════════════════════════
# صفحة المشاهدة (watch) — مع postMessage
# ═══════════════════════════════════════════════════════════════
def render_watch(name, season, episode, prev_ep, next_ep, ep):
    video_url = ep.get("video_url", "")
    tg_url = ep.get("telegram_url", "") or ep.get("embed_url", "")
    thumb = ep.get("thumb_url", "")
    poster_attr = f' poster="{esc(thumb)}"' if thumb else ""

    # ✅ تجاهل Worker URLs — تفشل مع الملفات الكبيرة
    if video_url and "/stream?fid=" in video_url:
        video_url = ""

    # ─── اختيار المشغل ───
    if video_url:
        player = (
            f'<video controls preload="metadata"{poster_attr} '
            f'style="width:100%;height:100%;display:block;background:#000;">'
            f'<source src="{esc(video_url)}" type="video/mp4">'
            f'</video>'
        )
        note_html = ""
        autoplay_html = (
            '<label class="autoplay-toggle">'
            '<input type="checkbox" id="autoplayNext"> تشغيل الحلقة التالية تلقائياً'
            '</label>'
        )
        head = '<script src="../static/watch.js" defer></script>'

    elif tg_url:
        # ✅ استخراج الرابط الأصلي t.me (وليس embed)
        tg_clean = tg_url.split("?")[0] if "?" in tg_url else tg_url
        player_url = f"{PROXY_URL}/?embed=1&url={enc(tg_clean)}"
        iframe_id = f"tg-player-{ep.get('message_id', 'x')}"
        player = (
            f'<div class="player-shell" id="playerShell">'
            f'<div class="loading-overlay" id="loadingOverlay">'
            f'<div class="spinner"></div>'
            f'<span>جاري التحضير...</span>'
            f'</div>'
            f'<iframe id="{iframe_id}" src="{esc(player_url)}" '
            f'frameborder="0" width="100%" height="100%" '
            f'allow="autoplay; encrypted-media; fullscreen; picture-in-picture" '
            f'allowfullscreen></iframe>'
            f'</div>'
        )
        note_html = (
            '<div class="embed-note">'
            '💡 <strong>ملاحظة:</strong> إذا ظهرت رسالة "لا توجد جلسة مسجّلة"، '
            f'افتح <a href="{PROXY_URL}/" target="_blank">الصفحة الرئيسية للمشغل</a> '
            'وسجّل الدخول مرة واحدة، ثم أعد تحميل هذه الصفحة.'
            '</div>'
        )
        autoplay_html = ""
        head = ""
    else:
        player = (
            '<div class="no-player">'
            '<div>⚠️ لا يوجد رابط متاح لهذه الحلقة.<br>'
            'استخدم زر "فتح في تليجرام" أدناه.</div>'
            '</div>'
        )
        note_html = ""
        autoplay_html = ""
        head = ""

    # ─── أزرار التنقل ───
    prev_btn = (
        f'<a class="btn" href="{prev_ep["message_id"]}.html">⏮ السابقة</a>'
        if prev_ep else '<span class="btn disabled">⏮ السابقة</span>'
    )
    next_btn = (
        f'<a class="btn primary" href="{next_ep["message_id"]}.html">التالية ⏭</a>'
        if next_ep else '<span class="btn disabled">التالية ⏭</span>'
    )
    series_url = "../series/" + enc(safe_name(name)) + ".html"
    tg_btn = (
        f'<a class="btn" href="{esc(tg_url.split("?")[0] if "?" in tg_url else tg_url)}" '
        f'target="_blank" rel="noopener">📱 فتح في تليجرام</a>'
        if tg_url else ""
    )

    next_json = json.dumps(
        f'{next_ep["message_id"]}.html' if next_ep else None
    )

    # ─── سكريبت postMessage للـ embed mode ───
    if tg_url and not video_url:
        scripts = f'''<script>
(function() {{
  'use strict';
  var iframe = document.querySelector('.player-shell iframe');
  var overlay = document.getElementById('loadingOverlay');
  var PLAYER_ORIGIN = '{PROXY_URL}';
  var overlayHidden = false;

  function hideOverlay() {{
    if (!overlayHidden && overlay) {{
      overlayHidden = true;
      overlay.style.display = 'none';
    }}
  }}

  if (iframe) {{
    iframe.addEventListener('load', function() {{ setTimeout(hideOverlay, 600); }});
    setTimeout(hideOverlay, 12000);

    window.addEventListener('load', function() {{
      if (iframe.contentWindow) {{
        try {{ iframe.contentWindow.postMessage({{ type: 'tg-embed-ready' }}, PLAYER_ORIGIN); }} catch (e) {{}}
      }}
    }});

    window.addEventListener('message', function(event) {{
      if (event.origin !== PLAYER_ORIGIN) return;
      var data = event.data;
      if (!data || typeof data !== 'object') return;

      if (data.type === 'tg-embed-request-creds') {{
        var creds = null;
        try {{
          var raw = localStorage.getItem('tg_credentials');
          if (raw) creds = JSON.parse(raw);
        }} catch (e) {{}}
        try {{
          iframe.contentWindow.postMessage({{ type: 'tg-embed-creds', credentials: creds }}, PLAYER_ORIGIN);
        }} catch (e) {{}}
      }}

      if (data.type === 'tg-embed-error') {{
        console.warn('[Player] Error:', data.message);
        hideOverlay();
      }}

      if (data.type === 'tg-embed-progress') {{
        console.log('[Player] Progress:', data.text || data.percent || '');
        hideOverlay();
      }}

      if (data.type === 'tg-embed-success') {{ hideOverlay(); }}
    }});
  }}

  window.__NEXT_URL__ = {next_json};
}})();
</script>'''
    elif video_url:
        scripts = f'<script>window.__NEXT_URL__ = {next_json};</script>'
    else:
        scripts = ""

    body = f'''
    <div class="watch-wrap">
      {player}
      {note_html}
      <div class="watch-info">
        <h1>{esc(name)}</h1>
        <h2>الموسم {esc(season)} · الحلقة {esc(episode)}</h2>
        <div class="watch-nav">
          {prev_btn}
          <a class="btn" href="{series_url}">📺 كل الحلقات</a>
          {next_btn}
          {tg_btn}
        </div>
        {autoplay_html}
      </div>
    </div>
    '''
    return base(f"الحلقة {episode} — {name}", body, depth=1, head=head, scripts=scripts)


# ═══════════════════════════════════════════════════════════════
# بناء الموقع
# ═══════════════════════════════════════════════════════════════
def build_static():
    dst = OUT / "static"
    if STATIC_SRC.exists():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(STATIC_SRC, dst)
        print(f"✅ نسخ static/ → {dst}")
    else:
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "style.css").write_text(DEFAULT_CSS, encoding="utf-8")
        (dst / "watch.js").write_text(DEFAULT_WATCH_JS, encoding="utf-8")
        print(f"✅ إنشاء ملفات static الافتراضية → {dst}")


def build_site():
    series_list = load_data()
    print(f"📚 تم تحميل {len(series_list)} مسلسل")

    total_eps = 0
    for series in series_list:
        name = series.get("name", "بدون اسم")
        episodes = series.get("episodes", [])

        write_file(OUT / "series" / f"{safe_name(name)}.html", render_series(series))

        for i, ep in enumerate(episodes):
            prev_ep = episodes[i - 1] if i > 0 else None
            next_ep = episodes[i + 1] if i < len(episodes) - 1 else None
            ep_html = render_watch(
                name=name,
                season=ep.get("season", 1),
                episode=ep.get("episode", i + 1),
                prev_ep=prev_ep,
                next_ep=next_ep,
                ep=ep,
            )
            msg_id = ep.get("message_id", f"ep{i}")
            write_file(OUT / "watch" / f"{msg_id}.html", ep_html)
            total_eps += 1

    write_file(OUT / "index.html", render_index(series_list))
    print(f"✅ تم بناء {len(series_list)} مسلسل و {total_eps} حلقة")


# ═══════════════════════════════════════════════════════════════
# CSS الافتراضي
# ═══════════════════════════════════════════════════════════════
DEFAULT_CSS = '''
:root{--bg:#0b0b0f;--surface:#14141a;--surface-2:#1c1c24;--border:#2a2a33;--text:#e8e8ef;--text-dim:#8a8a95;--primary:#e50914;--accent:#4ea8de;--success:#22c55e;--warning:#f59e0b;--radius:12px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Cairo',system-ui,-apple-system,sans-serif;line-height:1.6;min-height:100vh}
.topbar{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;background:rgba(20,20,26,.95);border-bottom:1px solid var(--border);backdrop-filter:blur(10px);position:sticky;top:0;z-index:100}
.logo{font-size:1.3rem;font-weight:800;color:var(--primary);text-decoration:none}
.logo span{color:var(--text)}
.nav a{color:var(--text-dim);text-decoration:none;margin-inline-start:18px;font-size:.92rem;transition:color .2s}
.nav a:hover{color:var(--accent)}
.container{max-width:1100px;margin:0 auto;padding:20px 16px 60px}
.hero{text-align:center;padding:40px 0 30px}
.hero h1{font-size:2.4rem;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:8px}
.hero p{color:var(--text-dim);font-size:1rem}
.series-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:18px;margin-top:20px}
.series-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;text-decoration:none;color:inherit;transition:all .25s}
.series-card:hover{transform:translateY(-4px);border-color:var(--accent);box-shadow:0 8px 24px rgba(78,168,222,.15)}
.series-poster{aspect-ratio:2/3;background:var(--surface-2);display:flex;align-items:center;justify-content:center;overflow:hidden}
.series-poster img{width:100%;height:100%;object-fit:cover}
.poster-placeholder{font-size:3rem;color:var(--text-dim)}
.series-info{padding:12px}
.series-info h3{font-size:.95rem;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.series-meta{font-size:.8rem;color:var(--text-dim)}
.series-hero{display:flex;gap:24px;margin-bottom:32px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px}
.series-poster-large{flex:0 0 180px;aspect-ratio:2/3;border-radius:10px;overflow:hidden;background:var(--surface-2);display:flex;align-items:center;justify-content:center}
.series-poster-large img{width:100%;height:100%;object-fit:cover}
.series-details{flex:1}
.series-details h1{font-size:1.7rem;margin-bottom:6px}
.series-count{color:var(--accent);font-size:.9rem;margin-bottom:10px}
.series-desc{color:var(--text-dim);font-size:.92rem}
.section-title{font-size:1.2rem;margin-bottom:14px}
.episodes-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:12px}
.episode-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;text-decoration:none;color:inherit;text-align:center;transition:all .2s}
.episode-card:hover{background:var(--surface-2);border-color:var(--accent);transform:translateY(-2px)}
.episode-num{font-weight:700;font-size:.95rem;margin-bottom:4px}
.episode-meta{font-size:.78rem;color:var(--text-dim)}
.ep-duration{display:block;margin-top:2px;font-size:.72rem;color:var(--accent)}
.watch-wrap{max-width:100%}
.player-shell{position:relative;width:100%;aspect-ratio:16/9;background:#000;border-radius:var(--radius);overflow:hidden;margin-bottom:18px}
.player-shell iframe,.player-shell video{width:100%;height:100%;border:0;display:block}
.loading-overlay{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#0b0b0f;color:var(--accent);font-size:.95rem;gap:14px;z-index:10;transition:opacity .4s}
.loading-overlay.hidden{opacity:0;pointer-events:none}
.spinner{width:38px;height:38px;border:3px solid #222;border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.no-player{aspect-ratio:16/9;background:var(--surface);border:1px dashed var(--border);border-radius:var(--radius);display:flex;align-items:center;justify-content:center;color:var(--text-dim);text-align:center;padding:20px;margin-bottom:18px}
.embed-note{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #2a2a4a;border-radius:10px;padding:.9rem 1.2rem;margin-bottom:1.2rem;color:#c8c8d8;font-size:.88rem;line-height:1.7}
.embed-note a{color:var(--accent);font-weight:700}
.embed-note strong{color:#fff}
.watch-info h1{font-size:1.5rem;margin-bottom:4px}
.watch-info h2{font-size:1rem;color:var(--text-dim);font-weight:400;margin-bottom:16px}
.watch-nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.btn{display:inline-flex;align-items:center;gap:6px;padding:9px 18px;border-radius:8px;background:var(--surface-2);color:var(--text);text-decoration:none;font-size:.87rem;border:1px solid var(--border);transition:all .2s;cursor:pointer;font-family:inherit}
.btn:hover{background:var(--surface);border-color:var(--accent);color:var(--accent)}
.btn.primary{background:var(--primary);color:#fff;border-color:var(--primary)}
.btn.primary:hover{background:#c40812;border-color:#c40812;color:#fff}
.btn.disabled{opacity:.35;pointer-events:none}
.autoplay-toggle{display:inline-flex;align-items:center;gap:.5rem;color:var(--text-dim);font-size:.85rem;cursor:pointer;margin-top:.5rem}
.autoplay-toggle input{accent-color:var(--accent);width:auto}
.empty{text-align:center;color:var(--text-dim);padding:40px 20px}
.footer{text-align:center;padding:24px 16px;color:var(--text-dim);font-size:.8rem;border-top:1px solid var(--border);margin-top:40px}
@media (max-width:600px){.hero h1{font-size:1.8rem}.series-hero{flex-direction:column}.series-poster-large{flex:none;width:140px;margin:0 auto}.series-grid{grid-template-columns:repeat(2,1fr)}.watch-info h1{font-size:1.2rem}}
'''


# ═══════════════════════════════════════════════════════════════
# JS الافتراضي
# ═══════════════════════════════════════════════════════════════
DEFAULT_WATCH_JS = '''
(function(){
  'use strict';
  var video = document.querySelector('video');
  if (!video) return;

  var key = 'tgflix_pos_' + location.pathname;
  var saved = parseFloat(localStorage.getItem(key) || '0');
  if (saved > 5) {
    video.addEventListener('loadedmetadata', function(){
      if (confirm('استئناف من ' + formatTime(saved) + '؟')) video.currentTime = saved;
    });
  }

  setInterval(function(){
    if (!video.paused && video.currentTime > 0) localStorage.setItem(key, video.currentTime.toString());
  }, 5000);

  var autoplayToggle = document.getElementById('autoplayNext');
  if (autoplayToggle) {
    var autoKey = 'tgflix_autoplay';
    autoplayToggle.checked = localStorage.getItem(autoKey) === '1';
    autoplayToggle.addEventListener('change', function(){
      localStorage.setItem(autoKey, this.checked ? '1' : '0');
    });
  }

  video.addEventListener('ended', function(){
    localStorage.removeItem(key);
    if (autoplayToggle && autoplayToggle.checked && window.__NEXT_URL__) location.href = window.__NEXT_URL__;
  });

  function formatTime(s){
    var m = Math.floor(s / 60), sec = Math.floor(s % 60);
    return m + ':' + (sec < 10 ? '0' : '') + sec;
  }
})();
'''


# ═══════════════════════════════════════════════════════════════
# نقطة البداية
# ═══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="بناء موقع TelegramFlix")
    parser.add_argument("--clean", action="store_true", help="تنظيف مجلد docs قبل البناء")
    args = parser.parse_args()

    if args.clean and OUT.exists():
        shutil.rmtree(OUT)
        print(f"🧹 تم تنظيف {OUT}")

    OUT.mkdir(parents=True, exist_ok=True)
    build_static()
    build_site()
    print(f"\n✨ اكتمل البناء! الموقع في: {OUT}")


if __name__ == "__main__":
    main()
