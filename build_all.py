#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_all.py — مُولّد الموقع الثابت لـ TelegramFlix
★ يزيل التكرارات ويستخدم file_id الصحيح من Pyrogram
"""

import re, json, shutil, html, argparse
from pathlib import Path
from urllib.parse import quote

ROOT       = Path(__file__).resolve().parent
OUT        = ROOT / "docs"
DATA_FILE  = ROOT / "data.json"
STATIC_SRC = ROOT / "static"

# ★★★ عنوان خادم البث على Railway ★★★
STREAM_WORKER = "https://soo-production.up.railway.app"

SITE_NAME = "TelegramFlix"
SITE_DESC = "مشاهدة المسلسلات مباشرة"


def esc(s): return html.escape(str(s or ""), quote=True)
def enc(s): return quote(str(s or ""), safe="")


def safe_name(s):
    s = re.sub(r"[^\w\u0600-\u06FF\-]+", "_", str(s or "").strip())
    return re.sub(r"_+", "_", s).strip("_") or "untitled"


def write_file(p, c):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(c, encoding="utf-8")


def fmt_dur(sec):
    try:
        s = int(sec or 0)
    except:
        return ""
    if s <= 0:
        return ""
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def clean_tg_url(url: str) -> str:
    """ينظف رابط t.me من @ الزائدة والمعاملات"""
    if not url:
        return ""
    url = url.split("?")[0].strip()
    url = re.sub(r"t\.me/@", "t.me/", url)
    url = re.sub(r"t\.me/c/@", "t.me/c/", url)
    return url


def base(title, body, depth=0, head="", scripts=""):
    prefix = "../" * depth if depth else ""
    return f'''<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefix}static/style.css">
{head}
</head>
<body>
<header class="topbar">
  <a href="{prefix}index.html" class="logo">{SITE_NAME[:8]}<span>{SITE_NAME[8:]}</span></a>
  <nav class="nav"><a href="{prefix}index.html">الرئيسية</a></nav>
</header>
<main class="container">{body}</main>
<footer class="footer"><p>© {SITE_NAME}</p></footer>
{scripts}
</body>
</html>'''


# ═══════════════════════════════════════════════════════════════
# ★ load_data — يزيل التكرارات ويختار file_id الصحيح
# ═══════════════════════════════════════════════════════════════
def load_data():
    if not DATA_FILE.exists():
        print(f"⚠️ لم يُعثر على {DATA_FILE}")
        return []

    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    series_raw = raw if isinstance(raw, list) else raw.get("series", [])
    series_list = []

    for s in series_raw:
        name = s.get("name") or "بدون اسم"
        poster = s.get("poster_url") or s.get("poster") or ""
        episodes = []
        seasons = s.get("seasons")

        if isinstance(seasons, dict):
            for sk, eps in seasons.items():
                try:
                    sn = int(sk)
                except:
                    sn = sk
                if isinstance(eps, list):
                    for ep in eps:
                        e = dict(ep)
                        e.setdefault("season", sn)
                        episodes.append(e)
        elif isinstance(seasons, list):
            for so in seasons:
                for ep in so.get("episodes", []):
                    e = dict(ep)
                    e.setdefault("season", so.get("season", 1))
                    episodes.append(e)
        elif isinstance(s.get("episodes"), list):
            episodes = s["episodes"]

        # ★ ترتيب حسب الموسم ثم الحلقة
        episodes.sort(key=lambda e: (
            int(e.get("season", 1)),
            int(e.get("episode", 0))
        ))

        # ★★★ إزالة التكرارات: احتفظ بأول إدخال لكل message_id ★★★
        seen = set()
        unique_episodes = []
        for ep in episodes:
            msg_id = str(ep.get("message_id", ""))
            if msg_id and msg_id in seen:
                continue
            seen.add(msg_id)
            unique_episodes.append(ep)

        series_list.append({
            "name": name,
            "poster": poster,
            "description": s.get("description", ""),
            "episodes": unique_episodes,
        })

    return series_list


def render_index(series_list):
    cards = []
    for s in series_list:
        name = s["name"]
        poster = s["poster"]
        count = len(s["episodes"])
        url = "series/" + enc(safe_name(name)) + ".html"
        ph = f'<img src="{esc(poster)}" alt="{esc(name)}" loading="lazy">' if poster else '<div class="poster-placeholder">📺</div>'
        cards.append(f'<a class="series-card" href="{url}"><div class="series-poster">{ph}</div><div class="series-info"><h3>{esc(name)}</h3><span class="series-meta">{count} حلقة</span></div></a>')

    body = f'<section class="hero"><h1>{SITE_NAME}</h1><p>{SITE_DESC}</p></section><section class="series-grid">{"".join(cards) if cards else "<p class=empty>لا توجد مسلسلات</p>"}</section>'
    return base(f"{SITE_NAME} — الرئيسية", body)


def render_series(series):
    name = series["name"]
    poster = series["poster"]
    eps = series["episodes"]
    ep_cards = []
    for ep in eps:
        dur = fmt_dur(ep.get("duration", 0))
        dur_html = f'<span class="ep-duration">⏱ {esc(dur)}</span>' if dur else ""
        ep_cards.append(f'<a class="episode-card" href="../watch/{ep.get("message_id","")}.html"><div class="episode-num">الحلقة {esc(ep.get("episode","?"))}</div><div class="episode-meta">الموسم {esc(ep.get("season",1))} {dur_html}</div></a>')
    ph = f'<img src="{esc(poster)}" alt="{esc(name)}">' if poster else '<div class="poster-placeholder">📺</div>'
    body = f'<div class="series-hero"><div class="series-poster-large">{ph}</div><div class="series-details"><h1>{esc(name)}</h1><p class="series-count">{len(eps)} حلقة</p><p class="series-desc">{esc(series.get("description",""))}</p></div></div><h2 class="section-title">الحلقات</h2><div class="episodes-grid">{"".join(ep_cards)}</div>'
    return base(f"{name} — {SITE_NAME}", body, depth=1)


# ═══════════════════════════════════════════════════════════════
# render_watch — مع كل الإصلاحات
# ═══════════════════════════════════════════════════════════════
def render_watch(name, season, episode, prev_ep, next_ep, ep):
    video_url = ep.get("video_url", "")
    tg_url = clean_tg_url(ep.get("telegram_url", "") or ep.get("embed_url", ""))
    file_id = ep.get("file_id", "")
    thumb = ep.get("thumb_url", "")
    poster_attr = f' poster="{esc(thumb)}"' if thumb else ""

    # تجاهل Worker URLs القديمة
    if video_url and "/stream?fid=" in video_url:
        video_url = ""

    # ★★★ اختيار المشغل ★★★
    stream_url = ""
    use_iframe = False

    if file_id:
        fsize = ep.get("file_size", 0)
        stream_url = (
            f"{STREAM_WORKER}/stream"
            f"?fid={enc(file_id)}"
            f"&size={fsize}"
        )
    elif video_url:
        stream_url = video_url

    # ─── اختيار المشغل ───
    if stream_url:
        player = (
            f'<video id="mainPlayer" controls playsinline preload="metadata"{poster_attr} '
            f'style="width:100%;height:100%;display:block;background:#000;" '
            f'crossorigin="anonymous">'
            f'<source src="{esc(stream_url)}" type="video/mp4">'
            f'متصفحك لا يدعم تشغيل الفيديو.</video>'
        )
        note_html = ""
        head = '<script src="../static/watch.js" defer></script>'
        autoplay_html = (
            '<label class="autoplay-toggle">'
            '<input type="checkbox" id="autoplayNext" checked> تشغيل تلقائي للحلقة التالية'
            '</label>'
        )
    else:
        player = '<div class="no-player"><div>⚠️ لا يوجد رابط متاح لهذه الحلقة.</div></div>'
        note_html = ""
        head = ""
        autoplay_html = ""

    # ─── التنقل ───
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
        f'<a class="btn" href="{esc(tg_url)}" target="_blank" rel="noopener">📱 فتح في تليجرام</a>'
        if tg_url else ""
    )
    next_json = json.dumps(f'{next_ep["message_id"]}.html' if next_ep else None)

    scripts = f'<script>window.__NEXT_URL__ = {next_json};</script>'

    body = f'''
    <div class="watch-wrap">
      <div class="player-shell">{player}</div>
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
    </div>'''
    return base(f"الحلقة {episode} — {name}", body, depth=1, head=head, scripts=scripts)


# ═══════════════════════════════════════════════════════════════
# CSS + JS
# ═══════════════════════════════════════════════════════════════
CSS = '''
:root{--bg:#0b0b0f;--surface:#14141a;--surface-2:#1c1c24;--border:#2a2a33;--text:#e8e8ef;--text-dim:#8a8a95;--primary:#e50914;--accent:#4ea8de;--radius:12px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Cairo',system-ui,sans-serif;line-height:1.6;min-height:100vh}
.topbar{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;background:rgba(20,20,26,.95);border-bottom:1px solid var(--border);backdrop-filter:blur(10px);position:sticky;top:0;z-index:100}
.logo{font-size:1.3rem;font-weight:800;color:var(--primary);text-decoration:none}
.logo span{color:var(--text)}
.nav a{color:var(--text-dim);text-decoration:none;margin-inline-start:18px;font-size:.92rem}
.nav a:hover{color:var(--accent)}
.container{max-width:1100px;margin:0 auto;padding:20px 16px 60px}
.hero{text-align:center;padding:40px 0 30px}
.hero h1{font-size:2.4rem;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:8px}
.hero p{color:var(--text-dim)}
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
.no-player{aspect-ratio:16/9;background:var(--surface);border:1px dashed var(--border);border-radius:var(--radius);display:flex;align-items:center;justify-content:center;color:var(--text-dim);text-align:center;padding:20px;margin-bottom:18px}
.watch-info h1{font-size:1.5rem;margin-bottom:4px}
.watch-info h2{font-size:1rem;color:var(--text-dim);font-weight:400;margin-bottom:16px}
.watch-nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.btn{display:inline-flex;align-items:center;gap:6px;padding:9px 18px;border-radius:8px;background:var(--surface-2);color:var(--text);text-decoration:none;font-size:.87rem;border:1px solid var(--border);transition:all .2s;cursor:pointer;font-family:inherit}
.btn:hover{background:var(--surface);border-color:var(--accent);color:var(--accent)}
.btn.primary{background:var(--primary);color:#fff;border-color:var(--primary)}
.btn.primary:hover{background:#c40812;color:#fff}
.btn.disabled{opacity:.35;pointer-events:none}
.autoplay-toggle{display:inline-flex;align-items:center;gap:.5rem;color:var(--text-dim);font-size:.85rem;cursor:pointer;margin-top:.5rem}
.autoplay-toggle input{accent-color:var(--accent);width:auto}
.empty{text-align:center;color:var(--text-dim);padding:40px 20px}
.footer{text-align:center;padding:24px 16px;color:var(--text-dim);font-size:.8rem;border-top:1px solid var(--border);margin-top:40px}
@media(max-width:600px){.hero h1{font-size:1.8rem}.series-hero{flex-direction:column}.series-poster-large{flex:none;width:140px;margin:0 auto}.series-grid{grid-template-columns:repeat(2,1fr)}.watch-info h1{font-size:1.2rem}}
'''

WATCH_JS = '''
(function(){
  var v = document.querySelector('video'); if(!v) return;
  var k = 'tgflix_pos_'+location.pathname;
  var s = parseFloat(localStorage.getItem(k)||'0');
  if(s>5) v.addEventListener('loadedmetadata',function(){ if(confirm('استئناف من '+ft(s)+'؟')) v.currentTime=s; });
  setInterval(function(){ if(!v.paused && v.currentTime>0) localStorage.setItem(k,v.currentTime.toString()); },5000);
  var a = document.getElementById('autoplayNext');
  if(a){ a.checked = localStorage.getItem('tgflix_autoplay')!=='0'; a.addEventListener('change',function(){ localStorage.setItem('tgflix_autoplay',this.checked?'1':'0'); }); }
  v.addEventListener('ended',function(){ localStorage.removeItem(k); if(a&&a.checked&&window.__NEXT_URL__) location.href=window.__NEXT_URL__; });
  function ft(s){var m=Math.floor(s/60),x=Math.floor(s%60);return m+':'+(x<10?'0':'')+x;}
})();
'''


def build_static():
    d = OUT / "static"
    if STATIC_SRC.exists():
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(STATIC_SRC, d)
    else:
        d.mkdir(parents=True, exist_ok=True)
        (d / "style.css").write_text(CSS, encoding="utf-8")
        (d / "watch.js").write_text(WATCH_JS, encoding="utf-8")
    print(f"✅ static/ → {d}")


def build_site():
    series_list = load_data()
    print(f"📚 تم تحميل {len(series_list)} مسلسل")
    total = 0
    for series in series_list:
        name = series["name"]
        episodes = series["episodes"]

        write_file(OUT / "series" / f"{safe_name(name)}.html", render_series(series))

        for i, ep in enumerate(episodes):
            prev_ep = episodes[i - 1] if i > 0 else None
            next_ep = episodes[i + 1] if i < len(episodes) - 1 else None
            html_ep = render_watch(
                name,
                ep.get("season", 1),
                ep.get("episode", i + 1),
                prev_ep,
                next_ep,
                ep,
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
        shutil.rmtree(OUT)
        print(f"🧹 تنظيف {OUT}")
    OUT.mkdir(parents=True, exist_ok=True)
    build_static()
    build_site()
    print(f"\n✨ اكتمل البناء → {OUT}")


if __name__ == "__main__":
    main()
