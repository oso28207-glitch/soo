#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_all.py — مُولّد الموقع التزايدي
★ يبني فقط الصفحات الجديدة/المعدّلة ★
"""

import re
import json
import shutil
import html
import argparse
import hashlib
import time
from pathlib import Path
from urllib.parse import quote
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "docs"
DATA_FILE = ROOT / "data.json"
MANIFEST_FILE = ROOT / ".build_manifest.json"
STREAM_SERVER = "https://soo-production.up.railway.app"
SITE_NAME = "TelegramFlix"
SITE_DESC = "مشاهدة المسلسلات والأفلام مباشرة"


# ═══════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════
def esc(s): return html.escape(str(s or ""), quote=True)
def enc(s): return quote(str(s or ""), safe="")


def safe_name(s):
    s = re.sub(r"[^\w\u0600-\u06FF\-]+", "_", str(s or "").strip())
    return re.sub(r"_+", "_", s).strip("_") or "untitled"


def safe_int(v, default=0):
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


def file_hash(content):
    """hash سريع للمحتوى"""
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]


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
# Manifest — لتتبع ما تم بناؤه
# ═══════════════════════════════════════════════════════════════
def load_manifest():
    if MANIFEST_FILE.exists():
        try:
            return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"pages": {}, "global_hash": ""}


def save_manifest(manifest):
    MANIFEST_FILE.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ═══════════════════════════════════════════════════════════════
# تحميل البيانات
# ═══════════════════════════════════════════════════════════════
def load_data():
    if not DATA_FILE.exists():
        print(f"⚠️ {DATA_FILE} غير موجود")
        return []

    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"❌ data.json تالف: {e}")
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

        unique_eps.sort(key=lambda e: (
            safe_int(e.get("season"), 1),
            safe_int(e.get("episode"), 0)
        ))

        ctype = s.get("type", "") or ""
        if ctype == "movie" and len(unique_eps) > 1:
            ctype = "series"
        if not ctype:
            ctype = "series" if len(unique_eps) > 1 else "movie"

        if ctype == "movie":
            name_key = f"M::{name}::{s.get('_source_channel', '')}"
        else:
            name_key = f"S::{name}"

        if name_key in seen_series:
            continue
        seen_series.add(name_key)

        origin = s.get("origin") or "foreign"
        slug = f"{ctype}-{origin}"

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
# القوالب (same as before, but compact)
# ═══════════════════════════════════════════════════════════════
HEAD = '''<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0b0f">
<title>{title}</title>
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
    <span class="logo-text">Telegram<b>Flix</b></span>
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
<footer class="footer"><p>© TelegramFlix</p></footer>
{scripts}
</body>
</html>'''


def base(title, body, depth=0, head="", scripts=""):
    prefix = "../" * depth if depth else ""
    return HEAD.format(
        title=esc(title), prefix=prefix, head=head,
        body=body, scripts=scripts,
    )


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
    ph = (f'<img src="{esc(poster)}" alt="{esc(name)}" loading="lazy">'
          if poster else '<div class="poster-placeholder">📺</div>')
    count_label = "فيلم" if s["type"] == "movie" else f"{count} حلقة"
    return (f'<a class="series-card" href="{url}">'
            f'<div class="series-poster">{ph}{badge}'
            f'<div class="series-overlay">'
            f'<div class="series-ep-count">{count_label}</div>'
            f'{rating_html}</div></div>'
            f'<div class="series-info"><h3>{esc(name)}</h3></div></a>')


def _render_episode_card(ep):
    dur = fmt_dur(ep.get("duration", 0))
    dur_html = f'<span class="ep-duration">{esc(dur)}</span>' if dur else ""
    date = format_date_ar(ep.get("date", ""))
    date_html = f'<span class="ep-date">{esc(date)}</span>' if date else ""
    ep_num = safe_int(ep.get("episode"), 0)
    label = f"الحلقة {ep_num}" if ep_num > 0 else "مشاهدة"
    fname = watch_filename(ep)
    return (f'<a class="episode-card" href="../watch/{fname}">'
            f'<div class="episode-thumb"><span class="play-icon">▶</span></div>'
            f'<div class="episode-body">'
            f'<div class="episode-num">{esc(label)}</div>'
            f'<div class="episode-meta">{dur_html} {date_html}</div>'
            f'</div></a>')


def render_series(series):
    name = series["name"]
    poster = series["poster"]
    backdrop = series.get("backdrop", "")
    eps = series["episodes"]
    seasons = defaultdict(list)
    for ep in eps:
        seasons[safe_int(ep.get("season"), 1)].append(ep)
    sorted_seasons = sorted(seasons.keys())

    if len(sorted_seasons) <= 1:
        ep_cards = [_render_episode_card(ep) for ep in eps]
        seasons_content = f'<div class="episodes-grid">{"".join(ep_cards)}</div>'
    else:
        st, sp = [], []
        for i, sn in enumerate(sorted_seasons):
            active = " active" if i == 0 else ""
            hidden = "" if i == 0 else " hidden"
            st.append(f'<button class="season-tab{active}" data-season="{sn}">'
                      f'الموسم {sn}<span class="season-count">{len(seasons[sn])}</span></button>')
            cards = "".join(_render_episode_card(ep) for ep in seasons[sn])
            sp.append(f'<div class="season-panel{hidden}" data-season="{sn}">'
                      f'<div class="episodes-grid">{cards}</div></div>')
        seasons_content = f'<div class="season-tabs">{"".join(st)}</div><div class="season-panels">{"".join(sp)}</div>'

    ph = f'<img src="{esc(poster)}" alt="{esc(name)}">' if poster else '<div class="poster-placeholder">📺</div>'
    bg = f'<div class="series-backdrop" style="background-image:url(\'{esc(backdrop)}\')"></div>' if backdrop else ""
    rating = f'<span class="rating">★ {float(series["rating"]):.1f}</span>' if series.get("rating") else ""
    year = f'<span class="year">{esc(series["year"])}</span>' if series.get("year") else ""
    type_label = "فيلم" if series["type"] == "movie" else "مسلسل"
    origins = {"arabic": "عربي", "turkish": "تركي مدبلج", "foreign": "أجنبي"}
    type_badge = f'<span class="category-badge">{type_label} {origins.get(series["origin"], "")}</span>'
    sc = f'<p class="series-seasons-count">{len(sorted_seasons)} مواسم</p>' if len(sorted_seasons) > 1 else ""

    body = (f'{bg}<div class="series-hero">'
            f'<div class="series-poster-large">{ph}</div>'
            f'<div class="series-details">'
            f'<h1>{esc(name)}</h1>'
            f'<div class="series-badges">{type_badge} {year} {rating}</div>'
            f'<p class="series-count">{len(eps)} حلقة</p>'
            f'{sc}<p class="series-desc">{esc(series.get("description", ""))}</p>'
            f'</div></div>'
            f'<h2 class="section-title"><span class="title-dot"></span>الحلقات</h2>'
            f'{seasons_content}')

    scripts = '''<script>
(function(){
  var t=document.querySelectorAll('.season-tab');
  var p=document.querySelectorAll('.season-panel');
  if(!t.length)return;
  t.forEach(function(tab){
    tab.addEventListener('click',function(){
      var x=tab.dataset.season;
      t.forEach(function(a){a.classList.remove('active')});
      tab.classList.add('active');
      p.forEach(function(s){
        if(s.dataset.season===x)s.classList.remove('hidden');
        else s.classList.add('hidden');
      });
    });
  });
})();
</script>'''
    return base(f"{name} — TelegramFlix", body, depth=1, scripts=scripts)


def render_watch(name, season, episode, prev_ep, next_ep, ep):
    fid = ep.get("file_id") or ""
    fsize = safe_int(ep.get("file_size"), 0)
    mid = safe_int(ep.get("message_id"), 0)
    thumb = ep.get("thumb_url", "")
    pa = f' poster="{esc(thumb)}"' if thumb else ""

    stream_url = ""
    if fid and fsize:
        stream_url = (f"{STREAM_SERVER}/stream"
                      f"?fid={enc(fid)}&size={int(fsize)}&mid={int(mid)}")

    if stream_url:
        player = (f'<div class="player-shell">'
                  f'<video id="mainPlayer" controls playsinline preload="auto" '
                  f'autoplay muted{pa} '
                  f'style="width:100%;height:100%;display:block;background:#000;" '
                  f'crossorigin="anonymous">'
                  f'<source src="{esc(stream_url)}" type="video/mp4"></video>'
                  f'<button class="unmute-btn" id="unmuteBtn">'
                  f'<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">'
                  f'<path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>'
                  f'</svg><span>تشغيل الصوت</span></button></div>')
        head = '<script src="../static/watch.js" defer></script>'
    else:
        player = '<div class="no-player"><div>الفيديو غير متاح حالياً</div></div>'
        head = ""

    pbtn = (f'<a class="btn" href="{watch_filename(prev_ep)}">السابقة</a>'
            if prev_ep else '<span class="btn disabled">السابقة</span>')
    nbtn = (f'<a class="btn primary" href="{watch_filename(next_ep)}">التالية</a>'
            if next_ep else '<span class="btn disabled">التالية</span>')
    series_url = "../series/" + enc(safe_name(name)) + ".html"
    tg_url = clean_tg_url(ep.get("telegram_url", ""))
    tg_btn = (f'<a class="btn" href="{esc(tg_url)}" target="_blank">تليجرام</a>'
              if tg_url else "")

    next_json = json.dumps(watch_filename(next_ep) if next_ep else None)
    scripts = f'<script>window.__NEXT_URL__ = {next_json};</script>'

    body = (f'<div class="watch-wrap">{player}'
            f'<div class="watch-info">'
            f'<h1>{esc(name)}</h1>'
            f'<h2>الموسم {esc(season)} · الحلقة {esc(episode)}</h2>'
            f'<div class="watch-nav">{pbtn}'
            f'<a class="btn" href="{series_url}">كل الحلقات</a>'
            f'{nbtn}{tg_btn}</div></div></div>')
    return base(f"الحلقة {episode} — {name}", body, depth=1, head=head, scripts=scripts)


def render_index(series_list):
    grouped = defaultdict(list)
    for s in series_list:
        grouped[s["slug"]].append(s)

    s_all = (grouped.get("series-arabic", []) + grouped.get("series-turkish", []) +
             grouped.get("series-foreign", []))
    m_all = (grouped.get("movie-arabic", []) + grouped.get("movie-turkish", []) +
             grouped.get("movie-foreign", []))
    s_all.sort(key=lambda x: x["latest"], reverse=True)
    m_all.sort(key=lambda x: x["latest"], reverse=True)

    mt, mp = [], []
    active_main = True

    for tslug, tlbl, ticon, items in [("series", "مسلسلات", "📺", s_all),
                                       ("movies", "أفلام", "🎬", m_all)]:
        if not items:
            continue
        is_active = active_main
        if is_active:
            active_main = False
        acls = " active" if is_active else ""
        hcls = "" if is_active else " hidden"
        mt.append(f'<button class="main-tab{acls}" data-main="{tslug}">'
                  f'<span>{ticon}</span><span>{tlbl}</span>'
                  f'<span class="count-badge">{len(items)}</span></button>')
        if tslug == "series":
            sg = [("arabic", "عربي", "🌙", grouped.get("series-arabic", [])),
                  ("turkish", "تركي مدبلج", "🇹🇷", grouped.get("series-turkish", [])),
                  ("foreign", "أجنبي", "🌍", grouped.get("series-foreign", []))]
        else:
            sg = [("arabic", "عربي", "🌙", grouped.get("movie-arabic", [])),
                  ("turkish", "تركي مدبلج", "🇹🇷", grouped.get("movie-turkish", [])),
                  ("foreign", "أجنبي", "🌍", grouped.get("movie-foreign", []))]
        sg = [g for g in sg if g[3]]

        if len(sg) <= 1:
            cards = "".join(render_card(s, i) for i, s in enumerate(items))
            pc = f'<div class="series-grid">{cards}</div>'
        else:
            st, sp = [], []
            sa = True
            for sslug, slbl, sicon, sitems in sg:
                is_sa = sa
                if is_sa:
                    sa = False
                scls = " active" if is_sa else ""
                shid = "" if is_sa else " hidden"
                st.append(f'<button class="sub-tab{scls}" data-sub="{tslug}-{sslug}">'
                          f'{sicon} {slbl}<span class="count-badge-sm">{len(sitems)}</span></button>')
                sc = "".join(render_card(s, i) for i, s in enumerate(sitems))
                sp.append(f'<div class="sub-panel{shid}" data-sub="{tslug}-{sslug}">'
                          f'<div class="series-grid">{sc}</div></div>')
            pc = f'<div class="sub-tabs">{"".join(st)}</div><div class="sub-panels">{"".join(sp)}</div>'

        mp.append(f'<div class="main-panel{hcls}" data-main="{tslug}">{pc}</div>')

    body = (f'<section class="hero"><h1>TelegramFlix</h1>'
            f'<p>مشاهدة المسلسلات والأفلام مباشرة</p></section>'
            f'<div class="main-tabs">{"".join(mt)}</div>'
            f'<div class="main-panels">{"".join(mp)}</div>')

    scripts = '''<script>
(function(){
  var mt=document.querySelectorAll('.main-tab');
  var mp=document.querySelectorAll('.main-panel');
  mt.forEach(function(t){t.addEventListener('click',function(){
    var x=t.dataset.main;
    mt.forEach(function(a){a.classList.remove('active')});
    t.classList.add('active');
    mp.forEach(function(p){
      if(p.dataset.main===x)p.classList.remove('hidden');
      else p.classList.add('hidden');
    });
    try{localStorage.setItem('tgflix_main',x)}catch(e){}
  })});
  document.querySelectorAll('.sub-tab').forEach(function(t){
    t.addEventListener('click',function(){
      var x=t.dataset.sub;
      var p=t.closest('.main-panel');
      if(!p)return;
      p.querySelectorAll('.sub-tab').forEach(function(a){a.classList.remove('active')});
      t.classList.add('active');
      p.querySelectorAll('.sub-panel').forEach(function(s){
        if(s.dataset.sub===x)s.classList.remove('hidden');
        else s.classList.add('hidden');
      });
    });
  });
  try{
    var s=localStorage.getItem('tgflix_main');
    if(s){
      var t=document.querySelector('.main-tab[data-main="'+s+'"]');
      if(t)t.click();
    }
  }catch(e){}
})();
</script>'''
    return base("TelegramFlix — الرئيسية", body, scripts=scripts)


# ═══════════════════════════════════════════════════════════════
# ★★★ Build Engine — تزايدي ★★★
# ═══════════════════════════════════════════════════════════════
class IncrementalBuilder:
    def __init__(self, clean=False):
        self.manifest = load_manifest() if not clean else {"pages": {}, "global_hash": ""}
        self.new_pages = {}
        self.stats = {"new": 0, "changed": 0, "unchanged": 0, "deleted": 0}
        self.old_paths = set(self.manifest.get("pages", {}).keys())

    def should_write(self, path_str, content):
        """يقرر إذا كان يجب كتابة الملف"""
        content_hash = file_hash(content)
        old_hash = self.manifest["pages"].get(path_str)
        if old_hash == content_hash:
            self.stats["unchanged"] += 1
            self.old_paths.discard(path_str)
            return False
        if old_hash:
            self.stats["changed"] += 1
        else:
            self.stats["new"] += 1
        self.manifest["pages"][path_str] = content_hash
        self.new_pages[path_str] = content
        self.old_paths.discard(path_str)
        return True

    def cleanup_deleted(self):
        """حذف الصفحات التي لم تعد موجودة"""
        for old_path in self.old_paths:
            p = Path(old_path)
            if p.exists():
                try:
                    p.unlink()
                    self.stats["deleted"] += 1
                except Exception:
                    pass
            self.manifest["pages"].pop(old_path, None)

    def flush(self):
        """كتابة الملفات الجديدة فقط"""
        for path_str, content in self.new_pages.items():
            write_file(Path(path_str), content)


def build_site(clean=False, force_full=False):
    start = time.time()
    series_list = load_data()
    print(f"📚 {len(series_list)} عمل محمّل")

    if force_full:
        clean = True
        if MANIFEST_FILE.exists():
            MANIFEST_FILE.unlink()

    builder = IncrementalBuilder(clean=clean)

    # بنية المجلدات
    OUT.mkdir(parents=True, exist_ok=True)

    # static (دائماً يُكتب لأن hash يُقارن)
    from_build_static = True  # نبني static دائماً إذا تغير

    # CSS + JS
    css_path = str(OUT / "static" / "style.css")
    js_path = str(OUT / "static" / "watch.js")

    if css_path not in builder.manifest["pages"] or \
       builder.manifest["pages"].get(css_path) != file_hash(CSS):
        write_file(css_path, CSS)
        builder.manifest["pages"][css_path] = file_hash(CSS)
        print("🎨 style.css محدّث")

    if js_path not in builder.manifest["pages"] or \
       builder.manifest["pages"].get(js_path) != file_hash(WATCH_JS):
        write_file(js_path, WATCH_JS)
        builder.manifest["pages"][js_path] = file_hash(WATCH_JS)
        print("⚡ watch.js محدّث")

    # Series pages
    for series in series_list:
        name = series["name"]
        html = render_series(series)
        path = OUT / "series" / f"{safe_name(name)}.html"
        builder.should_write(str(path), html)

    # Watch pages
    total_watch = 0
    for series in series_list:
        name = series["name"]
        eps = series["episodes"]
        for i, ep in enumerate(eps):
            prev_ep = eps[i - 1] if i > 0 else None
            next_ep = eps[i + 1] if i < len(eps) - 1 else None
            season = safe_int(ep.get("season"), 1)
            ep_num = safe_int(ep.get("episode"), i + 1)
            html = render_watch(name, season, ep_num, prev_ep, next_ep, ep)
            fname = watch_filename(ep)
            builder.should_write(str(OUT / "watch" / fname), html)
            total_watch += 1

    # Index
    index_html = render_index(series_list)
    builder.should_write(str(OUT / "index.html"), index_html)

    # حذف المحذوفات
    if not clean:
        builder.cleanup_deleted()
    else:
        builder.old_paths.clear()

    # كتابة الملفات الجديدة
    builder.flush()

    # حفظ manifest
    save_manifest(builder.manifest)

    elapsed = time.time() - start
    s = builder.stats
    print(f"\n{'='*50}")
    print(f"✨ البناء اكتمل في {elapsed:.2f}s")
    print(f"   🆕 جديد: {s['new']}")
    print(f"   🔄 معدّل: {s['changed']}")
    print(f"   ⏭️  بدون تغيير: {s['unchanged']}")
    print(f"   🗑️  محذوف: {s['deleted']}")
    print(f"{'='*50}")


# ═══════════════════════════════════════════════════════════════
# CSS/JS (مُختصرة)
# ═══════════════════════════════════════════════════════════════
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
  var v=document.getElementById('mainPlayer');
  var u=document.getElementById('unmuteBtn');
  if(!v)return;
  var p=v.play();
  if(p!==undefined){
    p.then(function(){v.muted=false;if(u)u.classList.add('hidden')}).catch(function(){v.muted=true});
  }
  if(u)u.addEventListener('click',function(){v.muted=false;v.volume=1;u.classList.add('hidden')});
  v.addEventListener('click',function(){if(v.muted){v.muted=false;if(u)u.classList.add('hidden')}});
  var k='tgflix_pos_'+location.pathname;
  var s=parseFloat(localStorage.getItem(k)||'0');
  if(s>5){v.addEventListener('loadedmetadata',function(){if(confirm('استئناف؟'))v.currentTime=s})}
  setInterval(function(){if(!v.paused&&v.currentTime>0)localStorage.setItem(k,v.currentTime.toString())},5000);
  v.addEventListener('ended',function(){localStorage.removeItem(k);if(window.__NEXT_URL__)location.href=window.__NEXT_URL__});
})();
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--clean", action="store_true", help="تنظيف كامل")
    p.add_argument("--force-full", action="store_true", help="إعادة بناء كل شيء")
    a = p.parse_args()
    build_site(clean=a.clean, force_full=a.force_full)


if __name__ == "__main__":
    main()