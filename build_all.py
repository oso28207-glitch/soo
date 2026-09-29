#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_all.py — مُولّد الموقع (تصنيف موحّد + إصلاح مسارات الحلقات + كتابة ذرّية)"""

import re
import os
import json
import shutil
import html
import argparse
import tempfile
from pathlib import Path
from urllib.parse import quote
from collections import defaultdict

from classify import detect_type, detect_origin

# ═══════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "docs"
DATA_FILE = ROOT / "data.json"
STREAM_SERVER = "https://soo-production.up.railway.app"
SITE_NAME = "TelegramFlix"
SITE_DESC = "مشاهدة المسلسلات والأفلام مباشرة"


def esc(s):
    return html.escape(str(s or ""), quote=True)


def enc(s):
    return quote(str(s or ""), safe="")


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
    """كتابة ذرّية للملفات الناتجة"""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(c)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


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
        months = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
                  "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
        return f"{d.day} {months[d.month - 1]}"
    except Exception:
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
# قراءة آمنة لـ data.json مع محاولة التعافي من النسخ الاحتياطية
# ═══════════════════════════════════════════════════════════════
def read_data_safe():
    """يحاول قراءة data.json، وإن فشل يبحث عن أحدث نسخة احتياطية"""
    if not DATA_FILE.exists():
        return None

    # 1) محاولة قراءة الملف الأصلي
    try:
        content = DATA_FILE.read_text(encoding="utf-8")
        if content.strip():
            return json.loads(content)
    except Exception as e:
        print(f"[build] data.json تالف: {e}")

    # 2) محاولة استرجاع من نسخة احتياطية
    backups = sorted(DATA_FILE.parent.glob("data.backup_*.json"), reverse=True)
    for bk in backups[:5]:
        try:
            content = bk.read_text(encoding="utf-8")
            if content.strip():
                data = json.loads(content)
                print(f"[build] استرجاع من {bk.name}")
                return data
        except Exception:
            continue

    print("[build] لا توجد نسخة صالحة")
    return None


# ═══════════════════════════════════════════════════════════════
# ★★★ تحميل البيانات — تصنيف موحّد ★★★
# ═══════════════════════════════════════════════════════════════
def load_data():
    # تنظيف تلقائي إن أمكن
    try:
        import clean_data
        clean_data.run(verbose=False)
    except Exception as e:
        print(f"[build] تحذير التنظيف: {e}")

    raw = read_data_safe()
    if not raw:
        print(f"لا يمكن قراءة {DATA_FILE.name}")
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

        # جمع الحلقات
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

        # إزالة التكرار
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

        if not unique_eps:
            continue

        unique_eps.sort(key=lambda e: (
            safe_int(e.get("season"), 1),
            safe_int(e.get("episode"), 0),
            safe_int(e.get("message_id"), 0),
        ))

        ctype = detect_type(name, len(unique_eps))
        origin = detect_origin(name)

        name_key = f"{ctype}::{name}"
        if name_key in seen_series:
            continue
        seen_series.add(name_key)

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
# قالب HTML
# ═══════════════════════════════════════════════════════════════
def base(title, body, depth=0, head="", scripts=""):
    prefix = "../" * depth if depth else ""
    return f'''
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=5">
<title>{esc(title)}</title>
{head}
<style>{CSS}</style>
</head>
<body>
<header class="topbar">
  <a href="{prefix}index.html" class="logo">
    <span class="logo-icon">▶</span>
    <span class="logo-text">Telegram<b>Flix</b></span>
  </a>
  <nav class="nav">
    <a href="{prefix}index.html" class="nav-link">الرئيسية</a>
  </nav>
</header>
<main class="container">
{body}
</main>
<footer class="footer">
  <p>© {SITE_NAME}</p>
</footer>
{scripts}
</body>
</html>'''


def render_card(s, idx=0, prefix=""):
    name = s["name"]
    poster = s["poster"]
    count = len(s["episodes"])
    url = prefix + "series/" + enc(safe_name(name)) + ".html"
    badge = '<span class="new">جديد</span>' if idx < 4 else ""
    rating_html = ""
    if s.get("rating"):
        try:
            rating_html = f'★ {float(s["rating"]):.1f}'
        except Exception:
            pass
    ph = f'<img src="{esc(poster)}" alt="{esc(name)}" loading="lazy">' if poster else \
         '<div class="no-poster">🎬</div>'
    count_label = "فيلم" if s["type"] == "movie" else f"{count} حلقة"
    return (
        f'<a href="{url}" class="series-card">'
        f'<div class="series-poster">{ph}{badge}</div>'
        f'<div class="series-overlay">'
        f'<span class="series-ep-count">{count_label}</span>'
        f'<span class="rating">{rating_html}</span>'
        f'</div>'
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
            f'<button class="main-tab{active_cls}" data-tab="{tab_slug}">'
            f'{tab_icon} {tab_label} <span class="count-badge">{len(items)}</span>'
            f'</button>'
        )
        if tab_slug == "series":
            sub_groups = [
                ("arabic", "عربي", "🇪🇬", grouped.get("series-arabic", [])),
                ("turkish", "تركي مدبلج", "🇹🇷", grouped.get("series-turkish", [])),
                ("foreign", "أجنبي", "🌍", grouped.get("series-foreign", [])),
            ]
        else:
            sub_groups = [
                ("arabic", "عربي", "🇪🇬", grouped.get("movie-arabic", [])),
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
                    f'<button class="sub-tab{sub_cls}" data-subtab="{sub_slug}">'
                    f'{sub_icon} {sub_label} <span class="count-badge-sm">{len(sub_items)}</span>'
                    f'</button>'
                )
                sub_cards = "".join(render_card(s, i) for i, s in enumerate(sub_items))
                sub_panels.append(
                    f'<div class="sub-panel{sub_hidden}" data-subpanel="{sub_slug}">'
                    f'<div class="series-grid">{sub_cards}</div>'
                    f'</div>'
                )
            panel_content = (
                f'<div class="sub-tabs">{"".join(sub_tabs)}</div>'
                f'<div class="sub-panels">{"".join(sub_panels)}</div>'
            )
        main_panels.append(
            f'<div class="main-panel{hidden_cls}" data-panel="{tab_slug}">'
            f'{panel_content}'
            f'</div>'
        )

    body = f'''
    <section class="hero">
      <h1>{SITE_NAME}</h1>
      <p>{SITE_DESC}</p>
    </section>
    <div class="main-tabs">{"".join(main_tabs)}</div>
    {"".join(main_panels)}
    '''
    scripts = '''<script>
document.querySelectorAll('.main-tab').forEach(tab=>{tab.onclick=()=>{
  document.querySelectorAll('.main-tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.main-panel').forEach(p=>p.classList.add('hidden'));
  tab.classList.add('active');
  document.querySelector(`.main-panel[data-panel="${tab.dataset.tab}"]`).classList.remove('hidden');
}});
document.querySelectorAll('.sub-tab').forEach(tab=>{tab.onclick=()=>{
  const parent=tab.closest('.main-panel');
  parent.querySelectorAll('.sub-tab').forEach(t=>t.classList.remove('active'));
  parent.querySelectorAll('.sub-panel').forEach(p=>p.classList.add('hidden'));
  tab.classList.add('active');
  parent.querySelector(`.sub-panel[data-subpanel="${tab.dataset.subtab}"]`).classList.remove('hidden');
}});
</script>'''
    return base(f"{SITE_NAME} — الرئيسية", body, scripts=scripts)


def _render_episode_card(ep):
    """
    ★★★ الإصلاح: الرابط يجب أن يكون ../watch/ لأن هذه الصفحة داخل مجلد series/ ★★★
    """
    dur = fmt_dur(ep.get("duration", 0))
    dur_html = f'<span class="ep-duration">{esc(dur)}</span>' if dur else ""
    date = format_date_ar(ep.get("date", ""))
    date_html = f'<span>{esc(date)}</span>' if date else ""
    ep_num = safe_int(ep.get("episode"), 0)
    label = f"الحلقة {ep_num}" if ep_num > 0 else "مشاهدة"
    fname = watch_filename(ep)
    return (
        f'<a href="../watch/{esc(fname)}" class="episode-card">'
        f'<div class="episode-thumb"><span class="play-icon">▶</span></div>'
        f'<div class="episode-body">'
        f'<div class="episode-num">{esc(label)}</div>'
        f'<div class="episode-meta">{dur_html}{date_html}</div>'
        f'</div>'
        f'</a>'
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
                f'الموسم {sn} <span class="season-count">{len(seasons[sn])}</span>'
                f'</button>'
            )
            cards = "".join(_render_episode_card(ep) for ep in seasons[sn])
            season_panels.append(
                f'<div class="season-panel{hidden}" data-season-panel="{sn}">'
                f'<div class="episodes-grid">{cards}</div>'
                f'</div>'
            )
        seasons_content = (
            f'<div class="season-tabs">{"".join(season_tabs)}</div>'
            f'<div class="season-panels">{"".join(season_panels)}</div>'
        )

    ph = f'<img src="{esc(poster)}" alt="{esc(name)}">' if poster else \
         '<div class="no-poster">🎬</div>'
    bg_html = ""
    if backdrop:
        bg_html = f'<div class="series-backdrop" style="background-image:url({esc(backdrop)})"></div>'

    rating_html = ""
    if series.get("rating"):
        try:
            rating_html = f'<span class="rating">★ {float(series["rating"]):.1f}</span>'
        except Exception:
            pass

    year_html = f'<span class="year">{esc(series["year"])}</span>' if series.get("year") else ""
    type_label = "فيلم" if series["type"] == "movie" else "مسلسل"
    origin_labels = {"arabic": "عربي", "turkish": "تركي مدبلج", "foreign": "أجنبي"}
    origin_label = origin_labels.get(series["origin"], "")
    type_badge = f'<span class="category-badge">{type_label} {origin_label}</span>'

    seasons_count_html = ""
    if len(sorted_seasons) > 1:
        seasons_count_html = f'<div class="series-seasons-count">{len(sorted_seasons)} مواسم</div>'

    body = f'''{bg_html}
    <section class="series-hero">
      <div class="series-poster-large">{ph}</div>
      <div class="series-details">
        <h1>{esc(name)}</h1>
        <div class="series-badges">{type_badge}{year_html}{rating_html}</div>
        <div class="series-count">{len(eps)} حلقة</div>
        {seasons_count_html}
        <p class="series-desc">{esc(series.get("description", ""))}</p>
      </div>
    </section>
    <h2>الحلقات</h2>
    {seasons_content}'''

    scripts = '''<script>
document.querySelectorAll('.season-tab').forEach(tab=>{tab.onclick=()=>{
  document.querySelectorAll('.season-tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.season-panel').forEach(p=>p.classList.add('hidden'));
  tab.classList.add('active');
  document.querySelector(`.season-panel[data-season-panel="${tab.dataset.season}"]`).classList.remove('hidden');
}});
</script>'''
    return base(f"{name} — {SITE_NAME}", body, depth=1, scripts=scripts)


def render_watch(name, season, episode, prev_ep, next_ep, ep):
    file_id = ep.get("file_id") or ""
    file_size = safe_int(ep.get("file_size"), 0)
    message_id = safe_int(ep.get("message_id"), 0)
    thumb = ep.get("thumb_url", "")

    stream_url = ""
    if file_id and file_size:
        stream_url = (
            f"{STREAM_SERVER}/stream"
            f"?fid={enc(file_id)}&size={int(file_size)}&mid={int(message_id)}"
        )

    if stream_url:
        player = (
            f'<div class="player-shell">'
            f'<video controls playsinline preload="metadata" '
            f'poster="{esc(thumb or "")}" src="{esc(stream_url)}">'
            f'<source src="{esc(stream_url)}" type="video/mp4">'
            f'</video>'
            f'<button class="unmute-btn" id="unmuteBtn">🔊 تشغيل الصوت</button>'
            f'</div>'
        )
        head = '<link rel="preload" as="video" href="' + esc(stream_url) + '">'
    else:
        player = (
            '<div class="no-player">'
            '<p>هذا الفيديو غير متاح حاليًا.<br>'
            'استخدم زر "تليجرام" للمشاهدة المباشرة.</p>'
            '</div>'
        )
        head = ""

    # داخل مجلد watch/ — الروابط النسبية للملفات المجاورة صحيحة
    prev_btn = (
        f'<a href="{esc(watch_filename(prev_ep))}" class="nav-btn">السابقة</a>'
        if prev_ep else '<span class="nav-btn disabled">السابقة</span>'
    )
    next_btn = (
        f'<a href="{esc(watch_filename(next_ep))}" class="nav-btn">التالية</a>'
        if next_ep else '<span class="nav-btn disabled">التالية</span>'
    )

    series_url = "../series/" + enc(safe_name(name)) + ".html"
    tg_url = clean_tg_url(ep.get("telegram_url", ""))
    tg_btn = (
        f'<a href="{esc(tg_url)}" target="_blank" rel="noopener" class="tg-btn">تليجرام</a>'
        if tg_url else ""
    )

    next_json = json.dumps(watch_filename(next_ep) if next_ep else None)
    scripts = f'''<script>
var nextEp = {next_json};
var video = document.querySelector('video');
if (video && nextEp) {{ video.addEventListener('ended', function() {{ window.location.href = nextEp; }}); }}
var unmuteBtn = document.getElementById('unmuteBtn');
if (unmuteBtn && video) {{
  unmuteBtn.onclick = function() {{ video.muted = false; video.volume = 1; unmuteBtn.classList.add('hidden'); }};
  video.addEventListener('volumechange', function() {{ if (!video.muted) unmuteBtn.classList.add('hidden'); }});
}}
</script>'''

    body = f'''
    {player}
    <div class="watch-info">
      <h1>{esc(name)}</h1>
      <div class="watch-meta">
        <span>الموسم {esc(season)} · الحلقة {esc(episode)}</span>
      </div>
      <div class="watch-nav">
        {prev_btn}
        <a href="{series_url}" class="nav-btn all-eps">كل الحلقات</a>
        {next_btn}
        {tg_btn}
      </div>
    </div>
    '''
    return base(f"الحلقة {episode} — {name}", body, depth=1, head=head, scripts=scripts)


CSS = '''
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0a0e17;--bg2:#131823;--card:#1a1f2e;--border:#252b3d;
  --text:#e8ecf4;--text2:#8892a6;--accent:#4f7cff;--accent2:#7c4fff;
  --gold:#ffc107;--success:#22c55e;
}
body{
  font-family:'Segoe UI',Tahoma,Arial,sans-serif;background:var(--bg);
  color:var(--text);direction:rtl;min-height:100vh;line-height:1.6;
}
.topbar{
  position:sticky;top:0;z-index:100;display:flex;align-items:center;
  justify-content:space-between;padding:14px 20px;background:rgba(10,14,23,.95);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--border);
}
.logo{display:flex;align-items:center;gap:8px;text-decoration:none;color:var(--text);font-size:20px;font-weight:700}
.logo-icon{color:var(--accent);font-size:24px}
.logo-text b{color:var(--accent)}
.nav-link{color:var(--text2);text-decoration:none;padding:8px 14px;border-radius:8px;transition:.2s}
.nav-link:hover{background:var(--card);color:var(--text)}
.container{max-width:1400px;margin:0 auto;padding:20px}
.hero{text-align:center;padding:40px 20px;margin-bottom:24px}
.hero h1{font-size:42px;margin-bottom:8px;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero p{color:var(--text2);font-size:16px}
.main-tabs{display:flex;gap:10px;justify-content:center;margin-bottom:24px;flex-wrap:wrap}
.main-tab{
  padding:12px 24px;background:var(--card);border:1px solid var(--border);
  border-radius:12px;color:var(--text);font-size:16px;font-weight:600;
  cursor:pointer;transition:.2s;display:flex;align-items:center;gap:8px;
}
.main-tab:hover{background:var(--bg2);border-color:var(--accent)}
.main-tab.active{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent}
.count-badge,.count-badge-sm{background:rgba(255,255,255,.15);padding:2px 8px;border-radius:10px;font-size:12px;font-weight:500}
.sub-tabs{display:flex;gap:8px;justify-content:center;margin-bottom:20px;flex-wrap:wrap}
.sub-tab{
  padding:8px 16px;background:var(--bg2);border:1px solid var(--border);
  border-radius:10px;color:var(--text2);font-size:14px;cursor:pointer;transition:.2s;
  display:flex;align-items:center;gap:6px;
}
.sub-tab:hover{color:var(--text);border-color:var(--accent)}
.sub-tab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.series-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px}
.series-card{
  background:var(--card);border-radius:12px;overflow:hidden;text-decoration:none;
  color:var(--text);transition:.25s;border:1px solid var(--border);position:relative;
}
.series-card:hover{transform:translateY(-4px);border-color:var(--accent);box-shadow:0 8px 24px rgba(79,124,255,.25)}
.series-poster{position:relative;aspect-ratio:2/3;overflow:hidden;background:var(--bg2)}
.series-poster img{width:100%;height:100%;object-fit:cover;transition:.3s}
.series-card:hover .series-poster img{transform:scale(1.05)}
.no-poster{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:48px;background:linear-gradient(135deg,var(--bg2),var(--card))}
.new{position:absolute;top:8px;right:8px;background:var(--success);color:#fff;padding:3px 8px;border-radius:6px;font-size:11px;font-weight:600;z-index:2}
.series-overlay{position:absolute;bottom:0;left:0;right:0;padding:8px;background:linear-gradient(to top,rgba(0,0,0,.9),transparent);display:flex;justify-content:space-between;align-items:center;font-size:12px}
.series-ep-count{color:#fff;background:rgba(0,0,0,.6);padding:2px 8px;border-radius:6px}
.rating{color:var(--gold);font-weight:600}
.series-info{padding:10px}
.series-info h3{font-size:14px;font-weight:600;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.series-backdrop{position:absolute;top:0;left:0;right:0;height:300px;background-size:cover;background-position:center;filter:blur(40px);opacity:.3;z-index:-1}
.series-hero{display:flex;gap:24px;margin-bottom:32px;position:relative;padding:20px;background:rgba(26,31,46,.5);border-radius:16px;border:1px solid var(--border)}
.series-poster-large{width:220px;flex-shrink:0;aspect-ratio:2/3;border-radius:12px;overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,.5)}
.series-poster-large img{width:100%;height:100%;object-fit:cover}
.series-details{flex:1}
.series-details h1{font-size:28px;margin-bottom:12px}
.series-badges{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.category-badge,.year,.rating{background:var(--bg2);padding:4px 12px;border-radius:8px;font-size:13px;border:1px solid var(--border)}
.category-badge{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent;color:#fff}
.series-count,.series-seasons-count{color:var(--text2);font-size:14px;margin-bottom:8px}
.series-desc{color:var(--text2);font-size:14px;line-height:1.7;margin-top:12px}
h2{font-size:22px;margin:24px 0 16px;color:var(--text)}
.episodes-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
.episode-card{
  display:flex;gap:10px;padding:10px;background:var(--card);border:1px solid var(--border);
  border-radius:10px;text-decoration:none;color:var(--text);transition:.2s;align-items:center;
}
.episode-card:hover{background:var(--bg2);border-color:var(--accent);transform:translateX(-4px)}
.episode-thumb{width:60px;height:60px;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.play-icon{font-size:20px;color:#fff}
.episode-body{flex:1;min-width:0}
.episode-num{font-size:14px;font-weight:600;margin-bottom:4px}
.episode-meta{display:flex;gap:8px;font-size:12px;color:var(--text2)}
.season-tabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.season-tab{padding:10px 18px;background:var(--card);border:1px solid var(--border);border-radius:10px;color:var(--text);cursor:pointer;transition:.2s;display:flex;align-items:center;gap:8px;font-size:14px}
.season-tab:hover{border-color:var(--accent)}
.season-tab.active{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent}
.season-count{background:rgba(255,255,255,.2);padding:1px 6px;border-radius:8px;font-size:11px}
.player-shell{position:relative;width:100%;max-width:900px;margin:0 auto 20px;background:#000;border-radius:12px;overflow:hidden;aspect-ratio:16/9}
.player-shell video{width:100%;height:100%;display:block;background:#000}
.unmute-btn{
  position:absolute;bottom:60px;right:20px;padding:10px 16px;background:var(--accent);
  color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;
  display:flex;align-items:center;gap:6px;box-shadow:0 4px 12px rgba(0,0,0,.5);z-index:5;
}
.unmute-btn:hover{background:var(--accent2)}
.unmute-btn.hidden{display:none}
.no-player{aspect-ratio:16/9;background:var(--card);border-radius:12px;display:flex;align-items:center;justify-content:center;text-align:center;padding:40px;color:var(--text2);border:1px solid var(--border);margin-bottom:20px;max-width:900px;margin-left:auto;margin-right:auto}
.watch-info{max-width:900px;margin:0 auto;text-align:center}
.watch-info h1{font-size:24px;margin-bottom:8px}
.watch-meta{color:var(--text2);font-size:14px;margin-bottom:20px}
.watch-nav{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
.nav-btn{
  padding:10px 20px;background:var(--card);border:1px solid var(--border);
  border-radius:10px;color:var(--text);text-decoration:none;font-size:14px;
  font-weight:600;transition:.2s;
}
.nav-btn:hover{background:var(--bg2);border-color:var(--accent)}
.nav-btn.disabled{opacity:.4;cursor:not-allowed;pointer-events:none}
.nav-btn.all-eps{background:var(--accent);border-color:var(--accent)}
.tg-btn{padding:10px 20px;background:#0088cc;color:#fff;border-radius:10px;text-decoration:none;font-size:14px;font-weight:600;transition:.2s}
.tg-btn:hover{background:#0099dd}
.footer{text-align:center;padding:30px 20px;color:var(--text2);font-size:13px;margin-top:60px;border-top:1px solid var(--border)}
.hidden{display:none!important}
@media(max-width:768px){
  .series-hero{flex-direction:column;text-align:center}
  .series-poster-large{width:160px;margin:0 auto}
  .series-grid{grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px}
  .hero h1{font-size:28px}
  .episodes-grid{grid-template-columns:1fr}
}
'''


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true", help="حذف مجلد docs قبل البناء")
    args = parser.parse_args()

    if args.clean and OUT.exists():
        shutil.rmtree(OUT)
        print(f"حذف {OUT}")

    OUT.mkdir(parents=True, exist_ok=True)

    print("تحميل البيانات ...")
    series_list = load_data()
    print(f"عدد الأعمال: {len(series_list)}")

    if not series_list:
        print("⚠️ لا توجد بيانات لبناء الموقع — تحقق من data.json")
        # نكتب صفحة فارغة بدل ما يبقى الموقع معطلًا
        write_file(OUT / "index.html", base(
            f"{SITE_NAME} — الرئيسية",
            "<section class='hero'><h1>لا توجد بيانات</h1>"
            "<p>سيتم البناء تلقائيًا بعد جلب البيانات</p></section>",
        ))
        write_file(OUT / ".nojekyll", "")
        return

    series_count = sum(1 for s in series_list if s["type"] == "series")
    movies_count = sum(1 for s in series_list if s["type"] == "movie")
    print(f"  مسلسلات: {series_count}")
    print(f"  أفلام:   {movies_count}")

    # الصفحة الرئيسية
    print("بناء الصفحة الرئيسية ...")
    write_file(OUT / "index.html", render_index(series_list))

    # صفحات الأعمال + الحلقات
    print("بناء صفحات الأعمال ...")
    for s in series_list:
        fname = safe_name(s["name"]) + ".html"
        write_file(OUT / "series" / fname, render_series(s))

        eps = s["episodes"]
        for i, ep in enumerate(eps):
            prev_ep = eps[i - 1] if i > 0 else None
            next_ep = eps[i + 1] if i + 1 < len(eps) else None
            ep_num = safe_int(ep.get("episode"), i + 1)
            sn = safe_int(ep.get("season"), 1)
            write_file(
                OUT / "watch" / watch_filename(ep),
                render_watch(s["name"], sn, ep_num, prev_ep, next_ep, ep),
            )

    write_file(OUT / ".nojekyll", "")
    print(f"✅ تم البناء في {OUT}")


if __name__ == "__main__":
    main()
