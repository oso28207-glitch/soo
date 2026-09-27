#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_all.py — مُولّد الموقع الثابت لـ TelegramFlix
★ Autoplay + ترتيب حسب الأحدث + تصميم موبايل جميل ★
"""

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
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "docs"
DATA_FILE = ROOT / "data.json"
STATIC_SRC = ROOT / "static"
STREAM_SERVER = "https://soo-production.up.railway.app"
FALLBACK_PROXY = "https://tg-webapp-proxy-58b.pages.dev"
SITE_NAME = "TelegramFlix"
SITE_DESC = "مشاهدة المسلسلات والأفلام مباشرة"


# ═══════════════════════════════════════════════════════════════
# دوال مساعدة
# ═══════════════════════════════════════════════════════════════
def esc(s): return html.escape(str(s or ""), quote=True)
def enc(s): return quote(str(s or ""), safe="")


def safe_name(s):
    s = re.sub(r"[^\w\u0600-\u06FF\-]+", "_", str(s or "").strip())
    return re.sub(r"_+", "_", s).strip("_") or "untitled"


def write_file(p, c):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(c, encoding="utf-8")


def fmt_dur(sec):
    try: s = int(sec or 0)
    except: return ""
    if s <= 0: return ""
    h, r = divmod(s, 3600); m, sec = divmod(r, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def clean_tg_url(url):
    if not url: return ""
    url = url.split("?")[0].strip()
    url = re.sub(r"t\.me/@", "t.me/", url)
    url = re.sub(r"t\.me/c/@", "t.me/c/", url)
    return url


def format_date_ar(date_str):
    """يحوّل 2026-09-27 → '27 سبتمبر'"""
    if not date_str: return ""
    try:
        from datetime import datetime
        d = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        months = ["يناير","فبراير","مارس","أبريل","مايو","يونيو",
                  "يوليو","أغسطس","سبتمبر","أكتوبر","نوفمبر","ديسمبر"]
        return f"{d.day} {months[d.month-1]}"
    except:
        return ""


def get_series_latest_key(series):
    """
    يُعيد مفتاح الترتيب — الأحدث أولاً
    يستخدم max(date) أو max(message_id)
    """
    dates = []
    ids = []
    for ep in series.get("episodes", []):
        if ep.get("date"):
            dates.append(ep["date"])
        try:
            ids.append(int(ep.get("message_id", 0)))
        except:
            pass
    if dates:
        return max(dates)
    return str(max(ids)) if ids else "0"


# ═══════════════════════════════════════════════════════════════
# قالب HTML
# ═══════════════════════════════════════════════════════════════
def base(title, body, depth=0, head="", scripts=""):
    prefix = "../" * depth if depth else ""
    return f'''<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0b0f">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefix}static/style.css">
{head}
</head>
<body>
<header class="topbar">
  <a href="{prefix}index.html" class="logo">
    <span class="logo-icon">▶</span>
    <span class="logo-text">{SITE_NAME[:8]}<b>{SITE_NAME[8:]}</b></span>
  </a>
  <nav class="nav">
    <a href="{prefix}index.html" class="nav-link active">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
        <polyline points="9 22 9 12 15 12 15 22"/>
      </svg>
      <span>الرئيسية</span>
    </a>
  </nav>
</header>
<main class="container">{body}</main>
<footer class="footer">
  <p>© {SITE_NAME} — جميع الحقوق محفوظة</p>
</footer>
{scripts}
</body>
</html>'''


# ═══════════════════════════════════════════════════════════════
# تحميل البيانات
# ═══════════════════════════════════════════════════════════════
def load_data():
    if not DATA_FILE.exists():
        print(f"⚠️ لم يُعثر على {DATA_FILE}"); return []
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    series_raw = raw if isinstance(raw, list) else raw.get("series", [])
    series_list = []
    for s in series_raw:
        name = s.get("name") or "بدون اسم"
        poster = s.get("poster_url") or s.get("poster") or ""
        backdrop = s.get("poster_backdrop", "")
        rating = s.get("tmdb_rating", 0)
        year = s.get("tmdb_year", "")
        overview = s.get("tmdb_overview", "") or s.get("description", "")

        episodes = []
        seasons = s.get("seasons")
        if isinstance(seasons, dict):
            for sk, eps in seasons.items():
                try: sn = int(sk)
                except: sn = sk
                if isinstance(eps, list):
                    for ep in eps:
                        e = dict(ep); e.setdefault("season", sn); episodes.append(e)
        elif isinstance(seasons, list):
            for so in seasons:
                for ep in so.get("episodes", []):
                    e = dict(ep); e.setdefault("season", so.get("season", 1)); episodes.append(e)
        elif isinstance(s.get("episodes"), list):
            episodes = s["episodes"]

        episodes.sort(key=lambda e: (int(e.get("season", 1)), int(e.get("episode", 0))))

        series_list.append({
            "name": name,
            "poster": poster,
            "backdrop": backdrop,
            "rating": rating,
            "year": year,
            "description": overview,
            "episodes": episodes,
        })

    # ★ ترتيب حسب الأحدث ★
    series_list.sort(key=get_series_latest_key, reverse=True)
    return series_list


# ═══════════════════════════════════════════════════════════════
# الصفحة الرئيسية
# ═══════════════════════════════════════════════════════════════
def render_index(series_list):
    cards = []
    for i, s in enumerate(series_list):
        name = s["name"]
        poster = s["poster"]
        count = len(s["episodes"])
        url = "series/" + enc(safe_name(name)) + ".html"

        # شارة "جديد" لأول 3 مسلسلات
        badge = '<span class="badge-new">جديد</span>' if i < 3 else ""

        # تقييم
        rating_html = ""
        if s.get("rating"):
            rating_html = f'<span class="rating">★ {s["rating"]:.1f}</span>'

        ph = (
            f'<img src="{esc(poster)}" alt="{esc(name)}" loading="lazy" '
            f'onerror="this.src=\'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 200 300%22%3E%3Crect fill=%22%231c1c24%22 width=%22200%22 height=%22300%22/%3E%3Ctext x=%2250%25%22 y=%2250%25%22 fill=%22%234ea8de%22 font-size=%2260%22 text-anchor=%22middle%22 dy=%22.3em%22%3E📺%3C/text%3E%3C/svg%3E\'">'
            if poster else
            '<div class="poster-placeholder">📺</div>'
        )

        cards.append(
            f'<a class="series-card" href="{url}">'
            f'<div class="series-poster">{ph}'
            f'{badge}'
            f'<div class="series-overlay">'
            f'<div class="series-ep-count">{count} حلقة</div>'
            f'{rating_html}'
            f'</div></div>'
            f'<div class="series-info"><h3>{esc(name)}</h3></div>'
            f'</a>'
        )

    body = f'''
    <section class="hero">
      <h1>{SITE_NAME}</h1>
      <p>{SITE_DESC}</p>
    </section>
    <section class="section">
      <h2 class="section-title">
        <span class="title-dot"></span>
        الأحدث
      </h2>
      <div class="series-grid">{"".join(cards)}</div>
    </section>'''

    return base(f"{SITE_NAME} — الرئيسية", body)


# ═══════════════════════════════════════════════════════════════
# صفحة المسلسل
# ═══════════════════════════════════════════════════════════════
def render_series(series):
    name = series["name"]
    poster = series["poster"]
    backdrop = series.get("backdrop", "")
    eps = series["episodes"]

    ep_cards = []
    for ep in eps:
        dur = fmt_dur(ep.get("duration", 0))
        dur_html = f'<span class="ep-duration">{esc(dur)}</span>' if dur else ""
        date = format_date_ar(ep.get("date", ""))
        date_html = f'<span class="ep-date">{esc(date)}</span>' if date else ""
        ep_cards.append(
            f'<a class="episode-card" href="../watch/{ep.get("message_id", "")}.html">'
            f'<div class="episode-thumb"><span class="play-icon">▶</span></div>'
            f'<div class="episode-body">'
            f'<div class="episode-num">الحلقة {esc(ep.get("episode", "?"))}</div>'
            f'<div class="episode-meta">الموسم {esc(ep.get("season", 1))} {dur_html} {date_html}</div>'
            f'</div></a>'
        )

    ph = (
        f'<img src="{esc(poster)}" alt="{esc(name)}">'
        if poster else
        '<div class="poster-placeholder">📺</div>'
    )

    bg_html = ""
    if backdrop:
        bg_html = f'<div class="series-backdrop" style="background-image:url(\'{esc(backdrop)}\')"></div>'

    rating_html = ""
    if series.get("rating"):
        rating_html = f'<span class="rating">★ {series["rating"]:.1f}</span>'
    year_html = ""
    if series.get("year"):
        year_html = f'<span class="year">{esc(series["year"])}</span>'

    body = f'''
    {bg_html}
    <div class="series-hero">
      <div class="series-poster-large">{ph}</div>
      <div class="series-details">
        <h1>{esc(name)}</h1>
        <div class="series-badges">{year_html} {rating_html}</div>
        <p class="series-count">{len(eps)} حلقة</p>
        <p class="series-desc">{esc(series.get("description", ""))}</p>
      </div>
    </div>
    <h2 class="section-title"><span class="title-dot"></span>الحلقات</h2>
    <div class="episodes-grid">{"".join(ep_cards)}</div>'''

    return base(f"{name} — {SITE_NAME}", body, depth=1)


# ═══════════════════════════════════════════════════════════════
# صفحة المشاهدة — ★ Autoplay + تحسينات ★
# ═══════════════════════════════════════════════════════════════
def render_watch(name, season, episode, prev_ep, next_ep, ep):
    video_url = ep.get("video_url", "")
    tg_url = clean_tg_url(ep.get("telegram_url", "") or ep.get("embed_url", ""))
    file_id = ep.get("file_id", "")
    file_size = ep.get("file_size", 0) or 0
    message_id = ep.get("message_id", 0)
    thumb = ep.get("thumb_url", "")
    poster_attr = f' poster="{esc(thumb)}"' if thumb else ""

    if video_url and "/stream?fid=" in video_url:
        video_url = ""

    stream_url = ""
    use_iframe = False

    if file_id and file_size:
        stream_url = (
            f"{STREAM_SERVER}/stream"
            f"?fid={enc(file_id)}"
            f"&size={int(file_size)}"
            f"&mid={int(message_id)}"
        )
    elif video_url:
        stream_url = video_url
    elif tg_url:
        use_iframe = True
        iframe_url = f"{FALLBACK_PROXY}/?embed=1&url={enc(tg_url)}"

    # ★ المشغل مع Autoplay ★
    if use_iframe:
        player = (
            f'<div class="player-shell" id="playerShell">'
            f'<div class="loading-overlay" id="loadingOverlay">'
            f'<div class="spinner"></div><span>جاري التحضير...</span></div>'
            f'<iframe id="tgPlayer" src="{esc(iframe_url)}" '
            f'frameborder="0" width="100%" height="100%" '
            f'allow="autoplay; encrypted-media; fullscreen; picture-in-picture" '
            f'allowfullscreen></iframe></div>'
        )
        note_html = ""
        head = ""
        autoplay_html = ""
    elif stream_url:
        # ★★★ autoplay + muted + playsinline ★★★
        player = (
            f'<div class="player-shell">'
            f'<video id="mainPlayer" controls playsinline preload="auto" '
            f'autoplay muted{poster_attr} '
            f'style="width:100%;height:100%;display:block;background:#000;" '
            f'crossorigin="anonymous">'
            f'<source src="{esc(stream_url)}" type="video/mp4">'
            f'</video>'
            f'<button class="unmute-btn" id="unmuteBtn" aria-label="تشغيل الصوت">'
            f'<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">'
            f'<path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>'
            f'</svg><span>تشغيل الصوت</span></button>'
            f'</div>'
        )
        note_html = ""
        head = '<script src="../static/watch.js" defer></script>'
        autoplay_html = ""

    else:
        player = '<div class="no-player"><div>⚠️ لا يوجد رابط متاح لهذه الحلقة.</div></div>'
        note_html = ""; autoplay_html = ""; head = ""

    # ─── أزرار التنقل ───
    if prev_ep:
        prev_btn = f'<a class="btn" href="{prev_ep["message_id"]}.html">⏮ السابقة</a>'
    else:
        prev_btn = '<span class="btn disabled">⏮ السابقة</span>'

    if next_ep:
        next_btn = f'<a class="btn primary" href="{next_ep["message_id"]}.html">التالية ⏭</a>'
    else:
        next_btn = '<span class="btn disabled">التالية ⏭</span>'

    series_url = "../series/" + enc(safe_name(name)) + ".html"
    tg_btn = (
        f'<a class="btn" href="{esc(tg_url)}" target="_blank" rel="noopener">📱 تليجرام</a>'
        if tg_url else ""
    )
    next_json = json.dumps(f'{next_ep["message_id"]}.html' if next_ep else None)

    scripts = f'<script>window.__NEXT_URL__ = {next_json};</script>'

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
      </div>
    </div>'''

    return base(f"الحلقة {episode} — {name}", body, depth=1, head=head, scripts=scripts)


# ═══════════════════════════════════════════════════════════════
# CSS — تصميم عصري للموبايل
# ═══════════════════════════════════════════════════════════════
CSS = '''
:root{--bg:#0a0a0e;--surface:#14141c;--surface-2:#1c1c28;--border:#26263a;--text:#f0f0f5;--text-dim:#8a8aa0;--primary:#e50914;--accent:#4ea8de;--gold:#ffc107;--radius:14px;--radius-sm:10px;--shadow:0 8px 32px rgba(0,0,0,.45)}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:'Cairo',system-ui,-apple-system,sans-serif;line-height:1.6;min-height:100vh;overflow-x:hidden}
img{max-width:100%;display:block}
a{color:inherit;text-decoration:none}
button{font-family:inherit;cursor:pointer}

/* ═══ Topbar ═══ */
.topbar{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;background:rgba(10,10,14,.85);border-bottom:1px solid var(--border);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);position:sticky;top:0;z-index:100}
.logo{display:flex;align-items:center;gap:8px;font-weight:900;font-size:1.15rem;letter-spacing:-.3px}
.logo-icon{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;background:linear-gradient(135deg,var(--primary),#ff4444);color:#fff;border-radius:9px;font-size:.9rem;box-shadow:0 4px 12px rgba(229,9,20,.4)}
.logo-text{color:var(--text)}
.logo-text b{color:var(--primary)}
.nav{display:flex;gap:6px}
.nav-link{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;border-radius:10px;color:var(--text-dim);font-size:.9rem;font-weight:600;transition:all .2s}
.nav-link.active,.nav-link:hover{background:var(--surface);color:var(--text)}
.nav-link svg{flex-shrink:0}

/* ═══ Container ═══ */
.container{max-width:1200px;margin:0 auto;padding:24px 16px 80px}

/* ═══ Hero ═══ */
.hero{text-align:center;padding:32px 0 40px}
.hero h1{font-size:2.4rem;font-weight:900;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;letter-spacing:-.5px;margin-bottom:8px}
.hero p{color:var(--text-dim);font-size:1rem;max-width:480px;margin:0 auto}

/* ═══ Sections ═══ */
.section{margin-bottom:40px}
.section-title{display:flex;align-items:center;gap:10px;font-size:1.3rem;font-weight:800;margin-bottom:18px;letter-spacing:-.3px}
.title-dot{display:inline-block;width:5px;height:22px;background:linear-gradient(180deg,var(--primary),var(--accent));border-radius:3px}

/* ═══ Series Grid — تصميم متجاوب ═══ */
.series-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px}
@media(max-width:600px){.series-grid{grid-template-columns:repeat(2,1fr);gap:12px}}
@media(max-width:360px){.series-grid{grid-template-columns:repeat(2,1fr);gap:8px}}
@media(min-width:900px){.series-grid{grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:18px}}

.series-card{display:block;position:relative;background:var(--surface);border-radius:var(--radius);overflow:hidden;transition:transform .3s cubic-bezier(.2,.8,.2,1),box-shadow .3s}
.series-card:hover{transform:translateY(-6px);box-shadow:var(--shadow)}
.series-card:active{transform:scale(.98)}
.series-poster{position:relative;aspect-ratio:2/3;background:linear-gradient(135deg,var(--surface-2),#0f0f18);overflow:hidden}
.series-poster img{width:100%;height:100%;object-fit:cover;transition:transform .5s cubic-bezier(.2,.8,.2,1)}
.series-card:hover .series-poster img{transform:scale(1.08)}
.poster-placeholder{display:flex;align-items:center;justify-content:center;height:100%;font-size:3rem;color:var(--text-dim)}

/* شارة "جديد" */
.badge-new{position:absolute;top:10px;right:10px;background:linear-gradient(135deg,var(--primary),#ff4444);color:#fff;font-size:.7rem;font-weight:800;padding:4px 10px;border-radius:20px;box-shadow:0 4px 12px rgba(229,9,20,.5);letter-spacing:.3px}

/* Overlay سفلي */
.series-overlay{position:absolute;bottom:0;left:0;right:0;padding:12px 10px 10px;background:linear-gradient(to top,rgba(10,10,14,.95) 0%,rgba(10,10,14,.7) 60%,transparent 100%);display:flex;justify-content:space-between;align-items:center;gap:6px}
.series-ep-count{font-size:.75rem;color:#fff;font-weight:700;background:rgba(255,255,255,.15);padding:3px 8px;border-radius:12px;backdrop-filter:blur(8px)}
.rating{font-size:.75rem;color:var(--gold);font-weight:700}

.series-info{padding:10px 12px 12px}
.series-info h3{font-size:.9rem;font-weight:700;line-height:1.35;color:var(--text);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.4em}

/* ═══ Series Page ═══ */
.series-backdrop{position:fixed;top:0;left:0;right:0;height:340px;background-size:cover;background-position:center;opacity:.15;z-index:-1;mask-image:linear-gradient(to bottom,black 0%,transparent 100%);-webkit-mask-image:linear-gradient(to bottom,black 0%,transparent 100%)}

.series-hero{display:flex;gap:20px;margin-bottom:36px;background:linear-gradient(135deg,var(--surface),var(--surface-2));border:1px solid var(--border);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow)}
@media(max-width:600px){.series-hero{flex-direction:column;gap:16px;padding:16px;text-align:center}}

.series-poster-large{flex:0 0 160px;aspect-ratio:2/3;border-radius:var(--radius-sm);overflow:hidden;background:var(--surface-2);box-shadow:0 8px 24px rgba(0,0,0,.5)}
@media(max-width:600px){.series-poster-large{width:140px;flex:none;margin:0 auto}}
.series-poster-large img{width:100%;height:100%;object-fit:cover}

.series-details{flex:1;min-width:0}
.series-details h1{font-size:1.6rem;font-weight:900;margin-bottom:8px;line-height:1.2}
@media(max-width:600px){.series-details h1{font-size:1.3rem}}
.series-badges{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}
@media(max-width:600px){.series-badges{justify-content:center}}
.series-badges .year{font-size:.8rem;color:var(--text-dim);background:var(--surface-2);padding:3px 10px;border-radius:12px;font-weight:600}
.series-badges .rating{font-size:.8rem;color:var(--gold);background:rgba(255,193,7,.1);padding:3px 10px;border-radius:12px;font-weight:700}
.series-count{color:var(--accent);font-size:.9rem;font-weight:700;margin-bottom:10px}
.series-desc{color:var(--text-dim);font-size:.9rem;line-height:1.7;display:-webkit-box;-webkit-line-clamp:5;-webkit-box-orient:vertical;overflow:hidden}

/* ═══ Episodes Grid ═══ */
.episodes-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
@media(max-width:600px){.episodes-grid{grid-template-columns:1fr;gap:10px}}

.episode-card{display:flex;align-items:center;gap:12px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;transition:all .2s;overflow:hidden;position:relative}
.episode-card:hover{background:var(--surface-2);border-color:var(--accent);transform:translateX(-4px)}
.episode-card:active{transform:scale(.98)}

.episode-thumb{flex:0 0 48px;height:48px;border-radius:10px;background:linear-gradient(135deg,var(--primary),#ff4444);display:flex;align-items:center;justify-content:center;color:#fff;box-shadow:0 4px 12px rgba(229,9,20,.35)}
.play-icon{font-size:1rem;margin-right:2px}
.episode-body{flex:1;min-width:0}
.episode-num{font-weight:800;font-size:.95rem;margin-bottom:2px}
.episode-meta{font-size:.78rem;color:var(--text-dim);display:flex;gap:8px;flex-wrap:wrap}
.ep-duration{color:var(--accent)}
.ep-date{color:var(--text-dim)}

/* ═══ Watch Page ═══ */
.watch-wrap{max-width:100%}
.player-shell{position:relative;width:100%;aspect-ratio:16/9;background:#000;border-radius:var(--radius);overflow:hidden;margin-bottom:20px;box-shadow:0 12px 48px rgba(0,0,0,.6)}
.player-shell iframe,.player-shell video{width:100%;height:100%;border:0;display:block}

.unmute-btn{position:absolute;bottom:16px;right:16px;display:flex;align-items:center;gap:6px;padding:10px 16px;background:rgba(0,0,0,.75);color:#fff;border:1px solid rgba(255,255,255,.2);border-radius:25px;font-size:.85rem;font-weight:700;backdrop-filter:blur(12px);transition:all .2s;z-index:20;animation:pulse 2s infinite}
.unmute-btn:hover{background:var(--primary);border-color:var(--primary);transform:scale(1.05)}
.unmute-btn.hidden{display:none}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(229,9,20,.7)}50%{box-shadow:0 0 0 12px rgba(229,9,20,0)}}

.loading-overlay{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#0a0a0e;color:var(--accent);font-size:.95rem;gap:14px;z-index:10}
.spinner{width:42px;height:42px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

.no-player{aspect-ratio:16/9;background:var(--surface);border:1px dashed var(--border);border-radius:var(--radius);display:flex;align-items:center;justify-content:center;color:var(--text-dim);text-align:center;padding:20px;margin-bottom:20px}

.watch-info h1{font-size:1.5rem;font-weight:900;margin-bottom:6px;line-height:1.3}
.watch-info h2{font-size:.95rem;color:var(--text-dim);font-weight:400;margin-bottom:18px}
.watch-nav{display:flex;gap:8px;flex-wrap:wrap}
@media(max-width:600px){.watch-info h1{font-size:1.15rem}.watch-info h2{font-size:.85rem}}

/* ═══ Buttons ═══ */
.btn{display:inline-flex;align-items:center;gap:6px;padding:10px 18px;border-radius:10px;background:var(--surface-2);color:var(--text);font-size:.87rem;font-weight:700;border:1px solid var(--border);transition:all .2s;cursor:pointer}
.btn:hover{background:var(--surface);border-color:var(--accent);color:var(--accent);transform:translateY(-2px)}
.btn.primary{background:linear-gradient(135deg,var(--primary),#ff4444);color:#fff;border-color:transparent;box-shadow:0 4px 12px rgba(229,9,20,.35)}
.btn.primary:hover{background:linear-gradient(135deg,#c40812,var(--primary));color:#fff;box-shadow:0 6px 20px rgba(229,9,20,.5)}
.btn.disabled{opacity:.35;pointer-events:none}

/* ═══ Footer ═══ */
.footer{text-align:center;padding:32px 16px;color:var(--text-dim);font-size:.8rem;border-top:1px solid var(--border);margin-top:60px}

/* ═══ Animations ═══ */
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
.series-card{animation:fadeInUp .5s ease backwards}
.series-card:nth-child(1){animation-delay:.02s}
.series-card:nth-child(2){animation-delay:.04s}
.series-card:nth-child(3){animation-delay:.06s}
.series-card:nth-child(4){animation-delay:.08s}
.series-card:nth-child(5){animation-delay:.10s}
.series-card:nth-child(6){animation-delay:.12s}
.series-card:nth-child(n+7){animation-delay:.14s}

/* ═══ iOS Safe Area ═══ */
@supports(padding:max(0px)){
  .topbar{padding-top:max(14px,env(safe-area-inset-top))}
  .container{padding-left:max(16px,env(safe-area-inset-left));padding-right:max(16px,env(safe-area-inset-right))}
}
'''

WATCH_JS = '''
(function(){
  var v = document.getElementById('mainPlayer');
  var unmuteBtn = document.getElementById('unmuteBtn');
  if (!v) return;

  // ★ محاولة تشغيل الفيديو تلقائياً ★
  var playPromise = v.play();
  if (playPromise !== undefined) {
    playPromise.then(function(){
      // نجح التشغيل التلقائي — حاول إلغاء الكتم
      v.muted = false;
      if (unmuteBtn) unmuteBtn.classList.add('hidden');
    }).catch(function(err){
      // فشل التشغيل التلقائي — أبقِ الفيديو مكتوماً واعرض الزر
      console.log('Autoplay blocked, muted:', err);
      v.muted = true;
    });
  }

  // ★ زر تشغيل الصوت ★
  if (unmuteBtn) {
    unmuteBtn.addEventListener('click', function(){
      v.muted = false;
      v.volume = 1;
      unmuteBtn.classList.add('hidden');
    });
  }

  // ★ إخفاء الزر عند أي نقرة على الفيديو ★
  v.addEventListener('click', function(){
    if (v.muted) {
      v.muted = false;
      if (unmuteBtn) unmuteBtn.classList.add('hidden');
    }
  });

  // ★ حفظ موضع التشغيل ★
  var k = 'tgflix_pos_' + location.pathname;
  var saved = parseFloat(localStorage.getItem(k) || '0');
  if (saved > 5) {
    v.addEventListener('loadedmetadata', function(){
      if (confirm('استئناف من ' + ft(saved) + '؟')) v.currentTime = saved;
    });
  }
  setInterval(function(){
    if (!v.paused && v.currentTime > 0) {
      localStorage.setItem(k, v.currentTime.toString());
    }
  }, 5000);

  // ★ التشغيل التالي تلقائياً ★
  v.addEventListener('ended', function(){
    localStorage.removeItem(k);
    if (window.__NEXT_URL__) location.href = window.__NEXT_URL__;
  });

  function ft(s){
    var m = Math.floor(s / 60), x = Math.floor(s % 60);
    return m + ':' + (x < 10 ? '0' : '') + x;
  }
})();
'''


# ═══════════════════════════════════════════════════════════════
# بناء الموقع
# ═══════════════════════════════════════════════════════════════
def build_static():
    d = OUT / "static"
    d.mkdir(parents=True, exist_ok=True)
    (d / "style.css").write_text(CSS, encoding="utf-8")
    (d / "watch.js").write_text(WATCH_JS, encoding="utf-8")
    print(f"✅ static/ → {d}")


def build_site():
    series_list = load_data()
    print(f"📚 تم تحميل {len(series_list)} مسلسل (مرتّبة حسب الأحدث)")

    total = 0
    for series in series_list:
        name = series["name"]
        episodes = series["episodes"]

        write_file(OUT / "series" / f"{safe_name(name)}.html", render_series(series))

        for i, ep in enumerate(episodes):
            prev_ep = episodes[i - 1] if i > 0 else None
            next_ep = episodes[i + 1] if i < len(episodes) - 1 else None
            html_ep = render_watch(
                name, ep.get("season", 1), ep.get("episode", i + 1),
                prev_ep, next_ep, ep,
            )
            write_file(OUT / "watch" / f"{ep.get('message_id', f'ep{i}')}.html", html_ep)
            total += 1

    write_file(OUT / "index.html", render_index(series_list))
    print(f"✅ تم بناء {len(series_list)} مسلسل و {total} حلقة")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--clean", action="store_true")
    a = p.parse_args()
    if a.clean and OUT.exists():
        shutil.rmtree(OUT); print(f"🧹 تنظيف {OUT}")
    OUT.mkdir(parents=True, exist_ok=True)
    build_static(); build_site()
    print(f"\n✨ اكتمل البناء → {OUT}")


if __name__ == "__main__":
    main()
