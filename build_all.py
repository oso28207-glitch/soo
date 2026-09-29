#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_all.py — مُولّد الموقع السريع
تصنيف صحيح + حماية ضد None
"""

import re
import json
import shutil
import html
import argparse
from pathlib import Path
from urllib.parse import quote
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "docs"
DATA_FILE = ROOT / "data.json"
STREAM_SERVER = "https://soo-production.up.railway.app"
SITE_NAME = "TelegramFlix"
SITE_DESC = "مشاهدة المسلسلات والأفلام مباشرة"


def esc(s): return html.escape(str(s or ""), quote=True)
def enc(s): return quote(str(s or ""), safe="")


def safe_name(s):
    s = re.sub(r"[^\w\u0600-\u06FF\-]+", "_", str(s or "").strip())
    return re.sub(r"_+", "_", s).strip("_") or "untitled"


def safe_int(v, default=0):
    """تحويل آمن للأعداد يتعامل مع None والقيم الفارغة"""
    try:
        if v is None:
            return default
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return default
        return int(v)
    except (ValueError, TypeError):
        return default


def write_file(p, c):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(c, encoding="utf-8")


def fmt_dur(sec):
    s = safe_int(sec, 0)
    if s <= 0:
        return ""
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def format_date_ar(date_str):
    if not date_str:
        return ""
    try:
        from datetime import datetime
        d = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        months = ["يناير","فبراير","مارس","أبريل","مايو","يونيو",
                  "يوليو","أغسطس","سبتمبر","أكتوبر","نوفمبر","ديسمبر"]
        return f"{d.day} {months[d.month-1]}"
    except:
        return ""


def clean_tg_url(url):
    if not url:
        return ""
    url = str(url).split("?")[0].strip()
    return re.sub(r"t\.me/@", "t.me/", url)


def watch_filename(ep):
    mid = str(ep.get("message_id") or "").strip() or "unknown"
    ch = str(ep.get("source_channel") or "").strip()
    if ch:
        ch_safe = re.sub(r"[^\w\-]+", "_", ch.lstrip("@"))
        return f"{ch_safe}_{mid}.html"
    fuid = str(ep.get("file_unique_id") or "").strip()
    if fuid:
        fuid_safe = re.sub(r"[^\w]+", "", fuid)[:16]
        return f"{mid}_{fuid_safe}.html"
    return f"{mid}.html"


# ═══════════════════════════════════════════════════════════════
# تحميل البيانات — ★★★ إعادة تصنيف الأعمال ★★★
# ═══════════════════════════════════════════════════════════════
def load_data():
    if not DATA_FILE.exists():
        print(f"لم يُعثر على {DATA_FILE}")
        return []

    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"data.json تالف: {e}")
        return []

    series_raw = raw if isinstance(raw, list) else raw.get("series", [])
    out = []
    seen_series = set()

    for s in series_raw:
        if not isinstance(s, dict):
            continue

        name = (s.get("name") or "").strip()
        if not name:
            continue

        # ─── جمع الحلقات ───
        all_eps = []
        seasons = s.get("seasons", {})
        if isinstance(seasons, dict):
            for sk, eps in seasons.items():
                sn = safe_int(sk, 1)
                if isinstance(eps, list):
                    for ep in eps:
                        if not isinstance(ep, dict):
                            continue
                        e = dict(ep)
                        e["season"] = safe_int(e.get("season"), sn)
                        e["episode"] = safe_int(e.get("episode"), 0)
                        all_eps.append(e)

        # ─── إزالة التكرار ───
        seen_keys = set()
        unique_eps = []
        for ep in all_eps:
            ch = str(ep.get("source_channel") or "").strip()
            mid = str(ep.get("message_id") or "").strip()
            key = f"{ch}|{mid}" if ch else mid
            if key and key in seen_keys:
                continue
            if key:
                seen_keys.add(key)
            unique_eps.append(ep)

        # ★★★ ترتيب آمن ضد None ★★★
        unique_eps.sort(key=lambda e: (
            safe_int(e.get("season"), 1),
            safe_int(e.get("episode"), 0)
        ))

        # ★★★ إعادة تصنيف النوع — الأولوية لعدد الحلقات ★★★
        ctype = s.get("type", "") or ""
        if ctype == "movie" and len(unique_eps) > 1:
            ctype = "series"
        if not ctype:
            ctype = "series" if len(unique_eps) > 1 else "movie"

        # مفتاح فريد
        if ctype == "movie":
            name_key = f"M::{name}::{s.get('_source_channel', '')}"
        else:
            name_key = f"S::{name}"

        if name_key in seen_series:
            continue
        seen_series.add(name_key)

        origin = s.get("origin") or "foreign"
        slug = f"{ctype}-{origin}"

        # أحدث تاريخ
        latest = ""
        for ep in unique_eps:
            d = ep.get("date")
            if d:
                d_str = str(d)
                if d_str > latest:
                    latest = d_str
        if not latest:
            ids = [safe_int(e.get("message_id"), 0) for e in unique_eps]
            latest = str(max(ids)) if ids else "0"

        out.append({
            "name": name,
            "poster": s.get("poster_url") or "",
            "backdrop": s.get("poster_backdrop", ""),
            "rating": s.get("tmdb_rating", 0),
            "year": s.get("tmdb_year", ""),
            "description": s.get("tmdb_overview", "") or s.get("description", ""),
            "episodes": unique_eps,
            "type": ctype,
            "origin": origin,
            "slug": slug,
            "latest": latest,
        })

    out.sort(key=lambda x: x["latest"], reverse=True)
    return out


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
    <a href="{prefix}index.html" class="nav-link">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
      </svg>
      <span>الرئيسية</span>
    </a>
  </nav>
</header>
<main class="container">{body}</main>
<footer class="footer"><p>© {SITE_NAME}</p></footer>
{scripts}
</body>
</html>'''


def render_card(s, idx=0, prefix=""):
    name = s["name"]
    poster = s["poster"]
    count = len(s["episodes"])
    url = prefix + "series/" + enc(safe_name(name)) + ".html"

    badge = '<span class="badge-new">جديد</span>' if idx < 4 else ""

    rating_html = ""
    if s.get("rating"):
        try:
            rating_html = f'<span class="rating">★ {float(s["rating"]):.1f}</span>'
        except:
            pass

    ph = f'<img src="{esc(poster)}" alt="{esc(name)}" loading="lazy">' if poster else \
         '<div class="poster-placeholder">📺</div>'

    count_label = "فيلم" if s["type"] == "movie" else f"{count} حلقة"

    return (
        f'<a class="series-card" href="{url}">'
        f'<div class="series-poster">{ph}{badge}'
        f'<div class="series-overlay">'
        f'<div class="series-ep-count">{count_label}</div>'
        f'{rating_html}'
        f'</div></div>'
        f'<div class="series-info"><h3>{esc(name)}</h3></div>'
        f'</a>'
    )


def render_index(series_list):
    grouped = defaultdict(list)
    for s in series_list:
        grouped[s["slug"]].append(s)

    main_tabs = []
    main_panels = []
    active_main = True

    series_all = (
        grouped.get("series-arabic", []) +
        grouped.get("series-turkish", []) +
        grouped.get("series-foreign", [])
    )
    movies_all = (
        grouped.get("movie-arabic", []) +
        grouped.get("movie-turkish", []) +
        grouped.get("movie-foreign", [])
    )

    series_all.sort(key=lambda x: x["latest"], reverse=True)
    movies_all.sort(key=lambda x: x["latest"], reverse=True)

    for tab_slug, tab_label, tab_icon, items in [
        ("series", "مسلسلات", "📺", series_all),
        ("movies", "أفلام", "🎬", movies_all),
    ]:
        if not items:
            continue

        is_active = active_main
        if is_active:
            active_main = False

        active_cls = " active" if is_active else ""
        hidden_cls = "" if is_active else " hidden"

        main_tabs.append(
            f'<button class="main-tab{active_cls}" data-main="{tab_slug}">'
            f'<span>{tab_icon}</span>'
            f'<span>{tab_label}</span>'
            f'<span class="count-badge">{len(items)}</span>'
            f'</button>'
        )

        if tab_slug == "series":
            sub_groups = [
                ("arabic", "عربي", "🌙", grouped.get("series-arabic", [])),
                ("turkish", "تركي مدبلج", "🇹🇷", grouped.get("series-turkish", [])),
                ("foreign", "أجنبي", "🌍", grouped.get("series-foreign", [])),
            ]
        else:
            sub_groups = [
                ("arabic", "عربي", "🌙", grouped.get("movie-arabic", [])),
                ("turkish", "تركي مدبلج", "🇹🇷", grouped.get("movie-turkish", [])),
                ("foreign", "أجنبي", "🌍", grouped.get("movie-foreign", [])),
            ]

        sub_groups = [g for g in sub_groups if g[3]]

        if len(sub_groups) <= 1:
            cards = "".join(render_card(s, i) for i, s in enumerate(items))
            panel_content = f'<div class="series-grid">{cards}</div>'
        else:
            sub_tabs = []
            sub_panels = []
            sub_active = True

            for sub_slug, sub_label, sub_icon, sub_items in sub_groups:
                is_sub_active = sub_active
                if is_sub_active:
                    sub_active = False

                sub_cls = " active" if is_sub_active else ""
                sub_hidden = "" if is_sub_active else " hidden"

                sub_tabs.append(
                    f'<button class="sub-tab{sub_cls}" data-sub="{tab_slug}-{sub_slug}">'
                    f'{sub_icon} {sub_label}'
                    f'<span class="count-badge-sm">{len(sub_items)}</span>'
                    f'</button>'
                )

                sub_cards = "".join(render_card(s, i) for i, s in enumerate(sub_items))
                sub_panels.append(
                    f'<div class="sub-panel{sub_hidden}" data-sub="{tab_slug}-{sub_slug}">'
                    f'<div class="series-grid">{sub_cards}</div>'
                    f'</div>'
                )

            panel_content = (
                f'<div class="sub-tabs">{"".join(sub_tabs)}</div>'
                f'<div class="sub-panels">{"".join(sub_panels)}</div>'
            )

        main_panels.append(
            f'<div class="main-panel{hidden_cls}" data-main="{tab_slug}">'
            f'{panel_content}</div>'
        )

    body = f'''
    <section class="hero">
      <h1>{SITE_NAME}</h1>
      <p>{SITE_DESC}</p>
    </section>
    <div class="main-tabs">{"".join(main_tabs)}</div>
    <div class="main-panels">{"".join(main_panels)}</div>'''

    scripts = '''<script>
(function(){
  var mt = document.querySelectorAll('.main-tab');
  var mp = document.querySelectorAll('.main-panel');
  mt.forEach(function(t){
    t.addEventListener('click', function(){
      var target = t.dataset.main;
      mt.forEach(function(x){ x.classList.remove('active'); });
      t.classList.add('active');
      mp.forEach(function(p){
        if (p.dataset.main === target) p.classList.remove('hidden');
        else p.classList.add('hidden');
      });
      try { localStorage.setItem('tgflix_main', target); } catch(e){}
    });
  });
  document.querySelectorAll('.sub-tab').forEach(function(t){
    t.addEventListener('click', function(){
      var target = t.dataset.sub;
      var parent = t.closest('.main-panel');
      if (!parent) return;
      parent.querySelectorAll('.sub-tab').forEach(function(x){ x.classList.remove('active'); });
      t.classList.add('active');
      parent.querySelectorAll('.sub-panel').forEach(function(p){
        if (p.dataset.sub === target) p.classList.remove('hidden');
        else p.classList.add('hidden');
      });
    });
  });
  try {
    var s = localStorage.getItem('tgflix_main');
    if (s) {
      var t = document.querySelector('.main-tab[data-main="' + s + '"]');
      if (t) t.click();
    }
  } catch(e){}
})();
</script>'''

    return base(f"{SITE_NAME} — الرئيسية", body, scripts=scripts)


def _render_episode_card(ep):
    dur = fmt_dur(ep.get("duration", 0))
    dur_html = f'<span class="ep-duration">{esc(dur)}</span>' if dur else ""
    date = format_date_ar(ep.get("date", ""))
    date_html = f'<span class="ep-date">{esc(date)}</span>' if date else ""

    ep_num = safe_int(ep.get("episode"), 0)
    label = f"الحلقة {ep_num}" if ep_num > 0 else "مشاهدة"

    fname = watch_filename(ep)

    return (
        f'<a class="episode-card" href="../watch/{fname}">'
        f'<div class="episode-thumb"><span class="play-icon">▶</span></div>'
        f'<div class="episode-body">'
        f'<div class="episode-num">{esc(label)}</div>'
        f'<div class="episode-meta">{dur_html} {date_html}</div>'
        f'</div></a>'
    )


def render_series(series):
    name = series["name"]
    poster = series["poster"]
    backdrop = series.get("backdrop", "")
    eps = series["episodes"]

    seasons = defaultdict(list)
    for ep in eps:
        sn = safe_int(ep.get("season"), 1)
        seasons[sn].append(ep)
    sorted_seasons = sorted(seasons.keys())

    if len(sorted_seasons) <= 1:
        ep_cards = [_render_episode_card(ep) for ep in eps]
        seasons_content = f'<div class="episodes-grid">{"".join(ep_cards)}</div>'
    else:
        season_tabs = []
        season_panels = []
        for i, sn in enumerate(sorted_seasons):
            active = " active" if i == 0 else ""
            hidden = "" if i == 0 else " hidden"
            season_tabs.append(
                f'<button class="season-tab{active}" data-season="{sn}">'
                f'الموسم {sn}<span class="season-count">{len(seasons[sn])}</span>'
                f'</button>'
            )
            cards = "".join(_render_episode_card(ep) for ep in seasons[sn])
            season_panels.append(
                f'<div class="season-panel{hidden}" data-season="{sn}">'
                f'<div class="episodes-grid">{cards}</div></div>'
            )
        seasons_content = (
            f'<div class="season-tabs">{"".join(season_tabs)}</div>'
            f'<div class="season-panels">{"".join(season_panels)}</div>'
        )

    ph = f'<img src="{esc(poster)}" alt="{esc(name)}">' if poster else \
         '<div class="poster-placeholder">📺</div>'

    bg_html = ""
    if backdrop:
        bg_html = f'<div class="series-backdrop" style="background-image:url(\'{esc(backdrop)}\')"></div>'

    rating_html = ""
    if series.get("rating"):
        try:
            rating_html = f'<span class="rating">★ {float(series["rating"]):.1f}</span>'
        except:
            pass

    year_html = f'<span class="year">{esc(series["year"])}</span>' if series.get("year") else ""

    type_label = "فيلم" if series["type"] == "movie" else "مسلسل"
    origin_labels = {"arabic": "عربي", "turkish": "تركي مدبلج", "foreign": "أجنبي"}
    origin_label = origin_labels.get(series["origin"], "")
    type_badge = f'<span class="category-badge">{type_label} {origin_label}</span>'

    seasons_count_html = ""
    if len(sorted_seasons) > 1:
        seasons_count_html = f'<p class="series-seasons-count">{len(sorted_seasons)} مواسم</p>'

    body = f'''
    {bg_html}
    <div class="series-hero">
      <div class="series-poster-large">{ph}</div>
      <div class="series-details">
        <h1>{esc(name)}</h1>
        <div class="series-badges">{type_badge} {year_html} {rating_html}</div>
        <p class="series-count">{len(eps)} حلقة</p>
        {seasons_count_html}
        <p class="series-desc">{esc(series.get("description", ""))}</p>
      </div>
    </div>
    <h2 class="section-title"><span class="title-dot"></span>الحلقات</h2>
    {seasons_content}'''

    scripts = '''<script>
(function(){
  var tabs = document.querySelectorAll('.season-tab');
  var panels = document.querySelectorAll('.season-panel');
  if (!tabs.length) return;
  tabs.forEach(function(tab){
    tab.addEventListener('click', function(){
      var sn = tab.dataset.season;
      tabs.forEach(function(t){ t.classList.remove('active'); });
      tab.classList.add('active');
      panels.forEach(function(p){
        if (p.dataset.season === sn) p.classList.remove('hidden');
        else p.classList.add('hidden');
      });
    });
  });
})();
</script>'''

    return base(f"{name} — {SITE_NAME}", body, depth=1, scripts=scripts)


def render_watch(name, season, episode, prev_ep, next_ep, ep):
    file_id = ep.get("file_id") or ""
    file_size = safe_int(ep.get("file_size"), 0)
    message_id = safe_int(ep.get("message_id"), 0)
    thumb = ep.get("thumb_url", "")
    poster_attr = f' poster="{esc(thumb)}"' if thumb else ""

    stream_url = ""
    if file_id and file_size:
        stream_url = (
            f"{STREAM_SERVER}/stream"
            f"?fid={enc(file_id)}&size={int(file_size)}&mid={int(message_id)}"
        )

    if stream_url:
        player = (
            f'<div class="player-shell">'
            f'<video id="mainPlayer" controls playsinline preload="auto" '
            f'autoplay muted{poster_attr} '
            f'style="width:100%;height:100%;display:block;background:#000;" '
            f'crossorigin="anonymous">'
            f'<source src="{esc(stream_url)}" type="video/mp4">'
            f'</video>'
            f'<button class="unmute-btn" id="unmuteBtn">'
            f'<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">'
            f'<path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>'
            f'</svg><span>تشغيل الصوت</span></button></div>'
        )
        head = '<script src="../static/watch.js" defer></script>'
    else:
        player = (
            '<div class="no-player">'
            '<div>هذا الفيديو غير متاح حاليًا.<br>'
            'استخدم زر "تليجرام" للمشاهدة المباشرة.</div>'
            '</div>'
        )
        head = ""

    prev_btn = (
        f'<a class="btn" href="{watch_filename(prev_ep)}">السابقة</a>'
        if prev_ep else
        '<span class="btn disabled">السابقة</span>'
    )
    next_btn = (
        f'<a class="btn primary" href="{watch_filename(next_ep)}">التالية</a>'
        if next_ep else
        '<span class="btn disabled">التالية</span>'
    )

    series_url = "../series/" + enc(safe_name(name)) + ".html"

    tg_url = clean_tg_url(ep.get("telegram_url", ""))
    tg_btn = (
        f'<a class="btn" href="{esc(tg_url)}" target="_blank" rel="noopener">تليجرام</a>'
        if tg_url else ""
    )

    next_json = json.dumps(watch_filename(next_ep) if next_ep else None)
    scripts = f'<script>window.__NEXT_URL__ = {next_json};</script>'

    body = f'''
    <div class="watch-wrap">
      {player}
      <div class="watch-info">
        <h1>{esc(name)}</h1>
        <h2>الموسم {esc(season)} · الحلقة {esc(episode)}</h2>
        <div class="watch-nav">
          {prev_btn}
          <a class="btn" href="{series_url}">كل الحلقات</a>
          {next_btn}
          {tg_btn}
        </div>
      </div>
    </div>'''

    return base(f"الحلقة {episode} — {name}", body, depth=1, head=head, scripts=scripts)


CSS = '''
:root{--bg:#0a0a0e;--surface:#14141c;--surface-2:#1c1c28;--border:#26263a;--text:#f0f0f5;--text-dim:#8a8aa0;--primary:#e50914;--accent:#4ea8de;--gold:#ffc107;--radius:14px;--radius-sm:10px;--shadow:0 8px 32px rgba(0,0,0,.45)}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:'Cairo',system-ui,sans-serif;line-height:1.6;min-height:100vh;overflow-x:hidden}
img{max-width:100%;display:block}
a{color:inherit;text-decoration:none}
button{font-family:inherit;cursor:pointer;border:0;background:none;color:inherit}
.topbar{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;background:rgba(10,10,14,.85);border-bottom:1px solid var(--border);backdrop-filter:blur(16px);position:sticky;top:0;z-index:100}
.logo{display:flex;align-items:center;gap:8px;font-weight:900;font-size:1.15rem}
.logo-icon{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;background:linear-gradient(135deg,var(--primary),#ff4444);color:#fff;border-radius:9px;box-shadow:0 4px 12px rgba(229,9,20,.4)}
.logo-text b{color:var(--primary)}
.nav{display:flex;gap:6px}
.nav-link{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;border-radius:10px;color:var(--text-dim);font-size:.9rem;font-weight:600}
.nav-link:hover{background:var(--surface);color:var(--text)}
.container{max-width:1200px;margin:0 auto;padding:24px 16px 80px}
.hero{text-align:center;padding:24px 0 20px}
.hero h1{font-size:2rem;font-weight:900;background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:8px}
.hero p{color:var(--text-dim);font-size:.95rem}
.main-tabs{display:flex;gap:8px;margin-bottom:20px;background:var(--surface);padding:6px;border-radius:14px;width:fit-content;border:1px solid var(--border)}
.main-tab{display:inline-flex;align-items:center;gap:8px;padding:10px 22px;border-radius:10px;color:var(--text-dim);font-size:.95rem;font-weight:800;transition:all .25s;white-space:nowrap}
.main-tab.active{background:linear-gradient(135deg,var(--primary),#ff4444);color:#fff;box-shadow:0 4px 12px rgba(229,9,20,.4)}
.count-badge{background:rgba(255,255,255,.15);font-size:.72rem;padding:2px 8px;border-radius:10px;font-weight:800;min-width:22px;text-align:center}
.main-tab.active .count-badge{background:rgba(255,255,255,.25)}
.sub-tabs{display:flex;gap:8px;margin-bottom:18px;overflow-x:auto;scrollbar-width:none;padding-bottom:4px}
.sub-tabs::-webkit-scrollbar{display:none}
.sub-tab{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:20px;background:var(--surface);border:1px solid var(--border);color:var(--text-dim);font-size:.85rem;font-weight:700;white-space:nowrap;transition:all .2s;flex-shrink:0}
.sub-tab:hover{color:var(--text);border-color:var(--accent)}
.sub-tab.active{background:linear-gradient(135deg,var(--accent),#3d8bc4);color:#fff;border-color:transparent;box-shadow:0 4px 12px rgba(78,168,222,.35)}
.count-badge-sm{background:rgba(255,255,255,.15);font-size:.68rem;padding:1px 7px;border-radius:9px;font-weight:800;min-width:18px;text-align:center}
.sub-tab.active .count-badge-sm{background:rgba(255,255,255,.25)}
.main-panel.hidden,.sub-panel.hidden{display:none}
.series-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px}
@media(max-width:600px){.series-grid{grid-template-columns:repeat(2,1fr);gap:12px}}
@media(min-width:900px){.series-grid{grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:18px}}
.series-card{display:block;position:relative;background:var(--surface);border-radius:var(--radius);overflow:hidden;transition:transform .3s,box-shadow .3s;animation:fadeInUp .4s ease backwards}
.series-card:hover{transform:translateY(-6px);box-shadow:var(--shadow)}
.series-card:active{transform:scale(.97)}
.series-poster{position:relative;aspect-ratio:2/3;background:linear-gradient(135deg,var(--surface-2),#0f0f18);overflow:hidden}
.series-poster img{width:100%;height:100%;object-fit:cover;transition:transform .4s}
.series-card:hover .series-poster img{transform:scale(1.06)}
.poster-placeholder{display:flex;align-items:center;justify-content:center;height:100%;font-size:3rem;color:var(--text-dim)}
.badge-new{position:absolute;top:10px;right:10px;background:linear-gradient(135deg,var(--primary),#ff4444);color:#fff;font-size:.7rem;font-weight:800;padding:4px 10px;border-radius:20px;box-shadow:0 4px 12px rgba(229,9,20,.5)}
.series-overlay{position:absolute;bottom:0;left:0;right:0;padding:12px 10px 10px;background:linear-gradient(to top,rgba(10,10,14,.95),transparent);display:flex;justify-content:space-between;align-items:center;gap:6px}
.series-ep-count{font-size:.72rem;color:#fff;font-weight:700;background:rgba(255,255,255,.15);padding:3px 8px;border-radius:12px;backdrop-filter:blur(8px)}
.rating{font-size:.72rem;color:var(--gold);font-weight:800}
.series-info{padding:10px 12px 12px}
.series-info h3{font-size:.88rem;font-weight:700;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.4em}
.series-backdrop{position:fixed;top:0;left:0;right:0;height:340px;background-size:cover;background-position:center;opacity:.15;z-index:-1;mask-image:linear-gradient(to bottom,black,transparent);-webkit-mask-image:linear-gradient(to bottom,black,transparent)}
.series-hero{display:flex;gap:20px;margin-bottom:32px;background:linear-gradient(135deg,var(--surface),var(--surface-2));border:1px solid var(--border);border-radius:var(--radius);padding:20px}
@media(max-width:600px){.series-hero{flex-direction:column;gap:16px;padding:16px;text-align:center}}
.series-poster-large{flex:0 0 160px;aspect-ratio:2/3;border-radius:var(--radius-sm);overflow:hidden;background:var(--surface-2);box-shadow:0 8px 24px rgba(0,0,0,.5)}
@media(max-width:600px){.series-poster-large{width:140px;flex:none;margin:0 auto}}
.series-poster-large img{width:100%;height:100%;object-fit:cover}
.series-details{flex:1;min-width:0}
.series-details h1{font-size:1.6rem;font-weight:900;margin-bottom:8px;line-height:1.2}
@media(max-width:600px){.series-details h1{font-size:1.3rem}}
.series-badges{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}
@media(max-width:600px){.series-badges{justify-content:center}}
.series-badges .year,.category-badge{font-size:.78rem;background:var(--surface-2);padding:3px 10px;border-radius:12px;font-weight:600;color:var(--text-dim)}
.series-badges .rating{font-size:.78rem;color:var(--gold);background:rgba(255,193,7,.1);padding:3px 10px;border-radius:12px;font-weight:700}
.category-badge{background:rgba(78,168,222,.15)!important;color:var(--accent)!important}
.series-count{color:var(--accent);font-size:.9rem;font-weight:700;margin-bottom:6px}
.series-seasons-count{color:var(--text-dim);font-size:.85rem;margin-bottom:10px}
.series-desc{color:var(--text-dim);font-size:.9rem;line-height:1.7;display:-webkit-box;-webkit-line-clamp:5;-webkit-box-orient:vertical;overflow:hidden}
.section-title{display:flex;align-items:center;gap:10px;font-size:1.25rem;font-weight:800;margin-bottom:16px}
.title-dot{display:inline-block;width:5px;height:22px;background:linear-gradient(180deg,var(--primary),var(--accent));border-radius:3px}
.season-tabs{display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;margin-bottom:16px;padding-bottom:4px}
.season-tabs::-webkit-scrollbar{display:none}
.season-tab{display:inline-flex;align-items:center;gap:6px;padding:10px 18px;border-radius:12px;background:var(--surface);border:1px solid var(--border);color:var(--text-dim);font-size:.88rem;font-weight:700;white-space:nowrap;transition:all .2s;flex-shrink:0}
.season-tab:hover{color:var(--text);border-color:var(--accent)}
.season-tab.active{background:linear-gradient(135deg,var(--accent),#3d8bc4);color:#fff;border-color:transparent;box-shadow:0 4px 12px rgba(78,168,222,.4)}
.season-count{background:rgba(255,255,255,.15);font-size:.7rem;padding:2px 7px;border-radius:10px;font-weight:800;min-width:20px;text-align:center}
.season-tab.active .season-count{background:rgba(255,255,255,.25)}
.season-panel.hidden{display:none}
.episodes-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
@media(max-width:600px){.episodes-grid{grid-template-columns:1fr;gap:10px}}
.episode-card{display:flex;align-items:center;gap:12px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;transition:all .2s}
.episode-card:hover{background:var(--surface-2);border-color:var(--accent);transform:translateX(-4px)}
.episode-thumb{flex:0 0 48px;height:48px;border-radius:10px;background:linear-gradient(135deg,var(--primary),#ff4444);display:flex;align-items:center;justify-content:center;color:#fff;box-shadow:0 4px 12px rgba(229,9,20,.35)}
.play-icon{font-size:1rem}
.episode-body{flex:1;min-width:0}
.episode-num{font-weight:800;font-size:.95rem;margin-bottom:2px}
.episode-meta{font-size:.78rem;color:var(--text-dim);display:flex;gap:8px;flex-wrap:wrap}
.ep-duration{color:var(--accent)}
.player-shell{position:relative;width:100%;aspect-ratio:16/9;background:#000;border-radius:var(--radius);overflow:hidden;margin-bottom:20px;box-shadow:0 12px 48px rgba(0,0,0,.6)}
.player-shell video{width:100%;height:100%;border:0;display:block}
.unmute-btn{position:absolute;bottom:16px;right:16px;display:flex;align-items:center;gap:6px;padding:10px 16px;background:rgba(0,0,0,.75);color:#fff;border:1px solid rgba(255,255,255,.2);border-radius:25px;font-size:.85rem;font-weight:700;backdrop-filter:blur(12px);transition:all .2s;z-index:20;animation:pulse 2s infinite}
.unmute-btn:hover{background:var(--primary);transform:scale(1.05)}
.unmute-btn.hidden{display:none}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(229,9,20,.7)}50%{box-shadow:0 0 0 12px rgba(229,9,20,0)}}
.no-player{aspect-ratio:16/9;background:var(--surface);border:1px dashed var(--border);border-radius:var(--radius);display:flex;align-items:center;justify-content:center;color:var(--text-dim);text-align:center;padding:20px;margin-bottom:20px}
.watch-info h1{font-size:1.5rem;font-weight:900;margin-bottom:6px}
.watch-info h2{font-size:.95rem;color:var(--text-dim);font-weight:400;margin-bottom:18px}
.watch-nav{display:flex;gap:8px;flex-wrap:wrap}
@media(max-width:600px){.watch-info h1{font-size:1.15rem}}
.btn{display:inline-flex;align-items:center;gap:6px;padding:10px 18px;border-radius:10px;background:var(--surface-2);color:var(--text);font-size:.87rem;font-weight:700;border:1px solid var(--border);transition:all .2s}
.btn:hover{background:var(--surface);border-color:var(--accent);color:var(--accent)}
.btn.primary{background:linear-gradient(135deg,var(--primary),#ff4444);color:#fff;border-color:transparent;box-shadow:0 4px 12px rgba(229,9,20,.35)}
.btn.disabled{opacity:.35;pointer-events:none}
.footer{text-align:center;padding:32px 16px;color:var(--text-dim);font-size:.8rem;border-top:1px solid var(--border);margin-top:60px}
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
.series-card:nth-child(1){animation-delay:.02s}
.series-card:nth-child(2){animation-delay:.04s}
.series-card:nth-child(3){animation-delay:.06s}
.series-card:nth-child(4){animation-delay:.08s}
.series-card:nth-child(n+5){animation-delay:.10s}
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
  var playPromise = v.play();
  if (playPromise !== undefined) {
    playPromise.then(function(){
      v.muted = false;
      if (unmuteBtn) unmuteBtn.classList.add('hidden');
    }).catch(function(){ v.muted = true; });
  }
  if (unmuteBtn) {
    unmuteBtn.addEventListener('click', function(){
      v.muted = false; v.volume = 1;
      unmuteBtn.classList.add('hidden');
    });
  }
  v.addEventListener('click', function(){
    if (v.muted) {
      v.muted = false;
      if (unmuteBtn) unmuteBtn.classList.add('hidden');
    }
  });
  var k = 'tgflix_pos_' + location.pathname;
  var saved = parseFloat(localStorage.getItem(k) || '0');
  if (saved > 5) {
    v.addEventListener('loadedmetadata', function(){
      if (confirm('استئناف؟')) v.currentTime = saved;
    });
  }
  setInterval(function(){
    if (!v.paused && v.currentTime > 0) localStorage.setItem(k, v.currentTime.toString());
  }, 5000);
  v.addEventListener('ended', function(){
    localStorage.removeItem(k);
    if (window.__NEXT_URL__) location.href = window.__NEXT_URL__;
  });
})();
'''


def build_static():
    d = OUT / "static"
    d.mkdir(parents=True, exist_ok=True)
    (d / "style.css").write_text(CSS, encoding="utf-8")
    (d / "watch.js").write_text(WATCH_JS, encoding="utf-8")


def build_site():
    series_list = load_data()
    print(f"{len(series_list)} عمل")

    total = 0
    written_files = set()
    movies = 0
    series_count = 0

    for series in series_list:
        name = series["name"]
        episodes = series["episodes"]

        if series["type"] == "movie":
            movies += 1
        else:
            series_count += 1

        write_file(OUT / "series" / f"{safe_name(name)}.html", render_series(series))

        for i, ep in enumerate(episodes):
            prev_ep = episodes[i - 1] if i > 0 else None
            next_ep = episodes[i + 1] if i < len(episodes) - 1 else None
            season = safe_int(ep.get("season"), 1)
            episode_num = safe_int(ep.get("episode"), i + 1)

            html_ep = render_watch(name, season, episode_num, prev_ep, next_ep, ep)
            fname = watch_filename(ep)
            if fname in written_files:
                print(f"تحذير: تعارض في {fname}")
            written_files.add(fname)
            write_file(OUT / "watch" / fname, html_ep)
            total += 1

    write_file(OUT / "index.html", render_index(series_list))
    print(f"   مسلسلات: {series_count}")
    print(f"   أفلام: {movies}")
    print(f"   حلقات: {total}")
    print(f"   ملفات watch فريدة: {len(written_files)}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--clean", action="store_true")
    a = p.parse_args()
    if a.clean and OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    build_static()
    build_site()
    print(f"\nتم البناء في {OUT}")


if __name__ == "__main__":
    main()