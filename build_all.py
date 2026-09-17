#!/usr/bin/env python3
"""
TelegramFlix — One-file static site builder
- يقرأ data.json
- يبني موقعاً ثابتاً كاملاً في docs/
- يدعم أسماء ملفات عربية + روابط مشفّرة
- يدعم Telegram Embed لتشغيل الفيديو داخل الموقع
"""
import sys
import json
import html
import shutil
import argparse
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).parent.resolve()
DOCS = ROOT / "docs"
STATIC = ROOT / "static"
DATA = ROOT / "data.json"


# ═══════════════════════════════════════════════════════════
#  CSS
# ═══════════════════════════════════════════════════════════
CSS = '''\
:root{--bg:#0b0b0f;--bg2:#141418;--card:#1a1a20;--hover:#23232c;--text:#f5f5f7;--muted:#9a9aa5;--accent:#e50914;--r:12px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:"Cairo","Segoe UI",sans-serif;direction:rtl;min-height:100%}
a{color:inherit;text-decoration:none}
.topbar{position:sticky;top:0;z-index:100;display:flex;align-items:center;gap:2rem;padding:1rem 2rem;background:linear-gradient(to bottom,rgba(0,0,0,.9),rgba(0,0,0,.6));backdrop-filter:blur(10px)}
.logo{font-weight:800;font-size:1.6rem;color:var(--accent)}
.logo span{color:var(--text)}
.nav a{color:var(--muted);font-weight:600;margin-left:1.5rem}
.nav a:hover{color:var(--text)}
.container{padding:2rem;max-width:1500px;margin:0 auto}
.hero{margin-bottom:2.5rem}
.hero h1{font-size:2.4rem;margin-bottom:.4rem}
.hero p{color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:1.2rem}
.card{background:var(--card);border-radius:var(--r);overflow:hidden;transition:transform .25s,background .25s}
.card:hover{transform:translateY(-6px);background:var(--hover)}
.card-thumb{position:relative;aspect-ratio:2/3;background:#222;overflow:hidden}
.card-thumb img{width:100%;height:100%;object-fit:cover;transition:transform .35s}
.card:hover .card-thumb img{transform:scale(1.06)}
.no-thumb{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:4rem;color:var(--muted);background:linear-gradient(135deg,#2a2a33,#1a1a20)}
.card-overlay{position:absolute;inset:auto 0 0 0;padding:.6rem;background:linear-gradient(to top,rgba(0,0,0,.9),transparent)}
.badge{background:var(--accent);color:#fff;font-size:.75rem;font-weight:700;padding:.2rem .55rem;border-radius:999px}
.card-body{padding:.8rem 1rem 1rem}
.card-body h3{font-size:1rem;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card-body p{color:var(--muted);font-size:.85rem;margin-top:.2rem}
.series-header{display:flex;gap:2rem;margin-bottom:3rem;align-items:flex-start}
.series-poster{width:220px;aspect-ratio:2/3;border-radius:var(--r);overflow:hidden;background:#222;flex-shrink:0}
.series-poster img{width:100%;height:100%;object-fit:cover}
.series-meta h1{font-size:2.2rem;margin-bottom:.5rem}
.series-meta p{color:var(--muted);margin-bottom:1.2rem}
.season{margin-bottom:2.5rem}
.season h2{font-size:1.4rem;margin-bottom:1rem}
.episodes{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:1rem}
.episode-card{background:var(--card);border-radius:var(--r);overflow:hidden;transition:transform .2s,background .2s}
.episode-card:hover{transform:translateY(-4px);background:var(--hover)}
.episode-thumb{position:relative;aspect-ratio:16/9;background:#222}
.episode-thumb img{width:100%;height:100%;object-fit:cover}
.play-icon{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.45);opacity:0;transition:opacity .25s;font-size:2rem;color:#fff}
.episode-card:hover .play-icon{opacity:1}
.episode-info{padding:.7rem .9rem 1rem}
.episode-info h4{font-size:.95rem}
.episode-info .duration{color:var(--muted);font-size:.8rem}
.watch-wrap{max-width:1200px;margin:0 auto}
.player-shell{background:#000;border-radius:var(--r);overflow:hidden;margin-bottom:1.5rem;aspect-ratio:16/9;position:relative}
.player-shell video{width:100%;height:100%;display:block}
.player-shell iframe{width:100%;height:100%;border:0;display:block;background:#000}
.no-player{display:flex;align-items:center;justify-content:center;height:100%;color:var(--muted);text-align:center;padding:2rem}
.no-player a{color:var(--accent);font-weight:700;text-decoration:underline}
.watch-info h1{font-size:1.6rem;margin-bottom:.3rem}
.watch-info h2{font-size:1.05rem;color:var(--muted);margin-bottom:1.2rem;font-weight:500}
.watch-nav{display:flex;gap:.8rem;flex-wrap:wrap;margin-bottom:1rem}
.btn{display:inline-flex;align-items:center;gap:.4rem;padding:.65rem 1.2rem;background:#2a2a33;color:var(--text);border:none;border-radius:8px;font-weight:700;font-size:.9rem;cursor:pointer;transition:background .2s;font-family:inherit;text-decoration:none}
.btn:hover{background:#3a3a45}
.btn.primary{background:var(--accent)}
.btn.primary:hover{background:#ff2b36}
.btn.disabled{background:#1a1a20;color:#555;cursor:not-allowed;pointer-events:none}
.autoplay-bar{display:flex;align-items:center;gap:1rem;padding:.8rem 1rem;background:var(--bg2);border-radius:8px;color:var(--muted);font-size:.9rem}
.autoplay-bar label{display:flex;align-items:center;gap:.5rem;cursor:pointer}
.autoplay-bar input{accent-color:var(--accent)}
#countdown{color:var(--accent);font-weight:700}
.empty{text-align:center;padding:5rem 2rem;color:var(--muted)}
.empty code{display:inline-block;margin:.6rem;padding:.5rem .9rem;background:var(--card);border-radius:6px;color:var(--text);font-family:monospace}
.embed-note{background:#1a1a20;padding:.8rem 1rem;border-radius:8px;color:var(--muted);font-size:.85rem;margin-bottom:1rem;border-right:3px solid var(--accent)}
@media(max-width:720px){.container{padding:1rem}.topbar{padding:.8rem 1rem}.series-header{flex-direction:column}.series-poster{width:160px}.hero h1{font-size:1.6rem}}
'''


# ═══════════════════════════════════════════════════════════
#  JavaScript
# ═══════════════════════════════════════════════════════════
JS = '''\
document.addEventListener("DOMContentLoaded",function(){
var v=document.getElementById("player");
var t=document.getElementById("autoplay-toggle");
var c=document.getElementById("countdown");
var n=window.__NEXT_URL__||null;
var x=false;
var p=null;

if(v&&v.tagName==="VIDEO"){
    p=v;
    if(typeof Plyr!=="undefined"){
        p=new Plyr(v,{controls:["play-large","play","progress","current-time","duration","mute","volume","captions","settings","pip","airplay","fullscreen"],seekTime:10,keyboard:{focused:true,global:true}});
    }
}

function go(){
    if(!n||(t&&!t.checked))return;
    var k=5;
    if(c)c.textContent="\\u23ed \\u0627\\u0644\\u062a\\u0627\\u0644\\u064a\\u0629 "+k+"s";
    var tm=setInterval(function(){
        if(x){clearInterval(tm);if(c)c.textContent="";return;}
        k--;
        if(k<=0){clearInterval(tm);window.location.href=n;}
        else{if(c)c.textContent="\\u23ed \\u0627\\u0644\\u062a\\u0627\\u0644\\u064a\\u0629 "+k+"s";}
    },1000);
}
function stop(){x=true;if(c)c.textContent="";}

if(p&&p.on){p.on("ended",go);p.on("play",stop);p.on("seeking",stop);}
else if(v){v.addEventListener("ended",go);v.addEventListener("play",stop);v.addEventListener("seeking",stop);}

if(t){t.addEventListener("change",function(){x=!t.checked;if(!t.checked&&c)c.textContent="";});}

if(v&&v.tagName==="VIDEO"){
    var key="tf_p_"+window.location.pathname;
    var s=parseFloat(localStorage.getItem(key)||"0");
    if(s>5){if(v.readyState>=1)v.currentTime=s;else v.addEventListener("loadedmetadata",function(){v.currentTime=s;});}
    setInterval(function(){if(v.currentTime>0&&!v.paused)localStorage.setItem(key,String(v.currentTime));},5000);
}
});
'''


# ═══════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════
def log(m):
    print(f"[build] {m}", flush=True)


def esc(s):
    return html.escape(str(s or ""), quote=True)


def enc(s):
    """URL-encode للاستخدام في href"""
    return quote(str(s), safe="")


def safe_name(name: str) -> str:
    """
    اسم ملف آمن على القرص.
    - يزيل الرموز الممنوعة
    - يستبدل المسافات بـ _
    - يحتفظ بالحروف العربية
    """
    bad = ['/', '\\', ':', '*', '?', '"', '<', '>', '|',
           '\n', '\r', '\t', ' ']
    out = str(name)
    for ch in bad:
        out = out.replace(ch, '_')
    # إزالة النقاط في البداية/النهاية
    out = out.strip('.')
    return out.strip() or "unnamed"


def dur(s):
    s = int(s or 0)
    if s <= 0:
        return "—"
    m, sec = divmod(s, 60)
    return f"{m}:{sec:02d}"


# ═══════════════════════════════════════════════════════════
#  Static files
# ═══════════════════════════════════════════════════════════
def write_static():
    STATIC.mkdir(exist_ok=True)
    (STATIC / "style.css").write_text(CSS, encoding="utf-8")
    (STATIC / "watch.js").write_text(JS, encoding="utf-8")
    log(f"static written → {STATIC}")


# ═══════════════════════════════════════════════════════════
#  Data loading
# ═══════════════════════════════════════════════════════════
def load_data():
    if not DATA.exists():
        log("⚠️ data.json missing — using empty")
        return {"series": [], "channel": {}}
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"❌ data.json parse error: {e}")
        return {"series": [], "channel": {}}


def normalize(data):
    out = []
    for s in data.get("series", []):
        name = str(s.get("name", "")).strip() or "بدون اسم"
        seasons = s.get("seasons", {}) or {}
        norm = {}
        for sk, eps in seasons.items():
            try:
                ik = int(sk)
            except Exception:
                ik = sk
            arr = sorted(eps, key=lambda e: int(e.get("episode", 0) or 0))
            for e in arr:
                e.setdefault("episode", 0)
                e.setdefault("message_id", 0)
                e.setdefault("duration", 0)
                e.setdefault("thumb_url", "")
                e.setdefault("video_url", "")
                e.setdefault("embed_url", "")
                e.setdefault("telegram_url", "")
            norm[str(ik)] = arr
        norm = dict(sorted(norm.items(), key=lambda kv: int(kv[0])))
        total = sum(len(v) for v in norm.values())
        out.append({
            "name": name,
            "poster_url": s.get("poster_url", ""),
            "seasons": norm,
            "total_episodes": total,
            "season_count": len(norm),
        })
    out.sort(key=lambda s: s["name"])
    return out


# ═══════════════════════════════════════════════════════════
#  HTML base
# ═══════════════════════════════════════════════════════════
def base(title, body, depth=0, head="", scripts=""):
    p = "../" * depth
    return (
        '<!DOCTYPE html>\n<html lang="ar" dir="rtl">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'<title>{esc(title)}</title>\n'
        f'<link rel="stylesheet" href="{p}static/style.css">\n'
        '<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;800&display=swap" rel="stylesheet">\n'
        + head + '\n</head>\n<body>\n'
        f'<header class="topbar">'
        f'<a href="{p}index.html" class="logo">Telegram<span>Flix</span></a>'
        f'<nav class="nav"><a href="{p}index.html">الرئيسية</a></nav>'
        f'</header>\n'
        '<main class="container">\n' + body + '\n</main>\n'
        + scripts + '\n</body>\n</html>'
    )


# ═══════════════════════════════════════════════════════════
#  Index page
# ═══════════════════════════════════════════════════════════
def render_index(series):
    if not series:
        body = (
            '<section class="hero"><h1>المكتبة فارغة</h1>'
            '<p>لم يتم العثور على مسلسلات في القناة.</p></section>'
            '<div class="empty">'
            '<p>تأكد من أن صيغة الـ caption:</p>'
            '<code>اسم المسلسل الموسم 1 الحلقة 1</code>'
            '</div>'
        )
        return base("TelegramFlix", body)

    cards = []
    for s in series:
        # الملف عربي على القرص، الرابط مشفّر
        url = "series/" + enc(safe_name(s["name"])) + ".html"

        # جلب صورة الغلاف
        poster = s.get("poster_url", "")
        if not poster:
            for eps in s["seasons"].values():
                for e in eps:
                    if e.get("thumb_url"):
                        poster = e["thumb_url"]
                        break
                if poster:
                    break

        thumb = (
            f'<img loading="lazy" src="{esc(poster)}" alt="{esc(s["name"])}">'
            if poster
            else f'<div class="no-thumb">{esc(s["name"][0])}</div>'
        )
        cards.append(
            f'<a class="card" href="{url}">'
            f'<div class="card-thumb">{thumb}'
            f'<div class="card-overlay">'
            f'<span class="badge">{s["total_episodes"]} حلقة</span>'
            f'</div></div>'
            f'<div class="card-body"><h3>{esc(s["name"])}</h3>'
            f'<p>{s["season_count"]} موسم</p></div>'
            f'</a>'
        )

    body = (
        f'<section class="hero"><h1>مكتبة المسلسلات</h1>'
        f'<p>{len(series)} مسلسل متاح للمشاهدة</p></section>'
        f'<div class="grid">{"".join(cards)}</div>'
    )
    return base("المسلسلات — TelegramFlix", body)


# ═══════════════════════════════════════════════════════════
#  Series page
# ═══════════════════════════════════════════════════════════
def render_series(s):
    # صورة الغلاف
    poster = s.get("poster_url", "")
    if not poster:
        for eps in s["seasons"].values():
            for e in eps:
                if e.get("thumb_url"):
                    poster = e["thumb_url"]
                    break
            if poster:
                break

    poster_html = (
        f'<img src="{esc(poster)}" alt="{esc(s["name"])}">'
        if poster else ""
    )

    # زر "ابدأ المشاهدة"
    start = ""
    keys = list(s["seasons"].keys())
    if keys and s["seasons"][keys[0]]:
        first = s["seasons"][keys[0]][0]
        start = (
            f'<a class="btn primary" '
            f'href="../watch/{first["message_id"]}.html">'
            f'▶ ابدأ المشاهدة</a>'
        )

    # بناء الحلقات لكل موسم
    sh = []
    for sk, eps in s["seasons"].items():
        ec = []
        for e in eps:
            thumb = (
                f'<img loading="lazy" src="{esc(e["thumb_url"])}" '
                f'alt="حلقة {e["episode"]}">'
                if e.get("thumb_url") else ""
            )
            ec.append(
                f'<a class="episode-card" '
                f'href="../watch/{e["message_id"]}.html">'
                f'<div class="episode-thumb">{thumb}'
                f'<span class="play-icon">▶</span></div>'
                f'<div class="episode-info">'
                f'<h4>الحلقة {e["episode"]}</h4>'
                f'<span class="duration">{dur(e.get("duration"))}</span>'
                f'</div></a>'
            )
        sh.append(
            f'<section class="season"><h2>الموسم {sk}</h2>'
            f'<div class="episodes">{"".join(ec)}</div></section>'
        )

    body = (
        f'<section class="series-header">'
        f'<div class="series-poster">{poster_html}</div>'
        f'<div class="series-meta">'
        f'<h1>{esc(s["name"])}</h1>'
        f'<p>{s["season_count"]} موسم · {s["total_episodes"]} حلقة</p>'
        f'{start}</div></section>'
        + "".join(sh)
    )
    return base(f"{s['name']} — TelegramFlix", body, depth=1)


# ═══════════════════════════════════════════════════════════
#  Watch page
# ═══════════════════════════════════════════════════════════
def render_watch(name, season, episode, prev_ep, next_ep, ep):
    video_url = ep.get("video_url", "")
    embed_url = ep.get("embed_url", "")
    thumb = ep.get("thumb_url", "")
    poster_attr = f' poster="{esc(thumb)}"' if thumb else ""
    tg_url = ep.get("telegram_url", "")

    # ─── الخيار 1: فيديو مباشر ───
    if video_url:
        player = (
            f'<video id="player" playsinline controls preload="metadata"'
            f'{poster_attr}>'
            f'<source src="{esc(video_url)}" type="video/mp4">'
            f'</video>'
        )
    # ─── الخيار 2: Telegram Embed ───
    elif embed_url:
        player = (
            f'<iframe id="player" src="{esc(embed_url)}" '
            f'frameborder="0" width="100%" height="100%" '
            f'allow="autoplay; encrypted-media; fullscreen" '
            f'allowfullscreen></iframe>'
        )
    # ─── الخيار 3: رابط تليجرام فقط ───
    else:
        fb = (
            f'<a href="{esc(tg_url)}" target="_blank" rel="noopener">'
            f'افتح في تطبيق تليجرام</a>'
            if tg_url else "لا يوجد رابط متاح."
        )
        player = (
            '<div class="no-player"><p>'
            '⚠️ هذه قناة خاصة — البث داخل الموقع غير ممكن.<br>'
            f'{fb}'
            '</p></div>'
        )

    # أزرار التنقل
    prev_btn = (
        f'<a class="btn" href="{prev_ep["message_id"]}.html">⏮ السابقة</a>'
        if prev_ep else '<span class="btn disabled">⏮ السابقة</span>'
    )
    next_btn = (
        f'<a class="btn primary" href="{next_ep["message_id"]}.html">'
        f'التالية ⏭</a>'
        if next_ep else '<span class="btn disabled">التالية ⏭</span>'
    )

    # رابط صفحة المسلسل (مشفّر)
    series_url = "../series/" + enc(safe_name(name)) + ".html"

    # زر فتح في تليجرام
    tg_btn = (
        f'<a class="btn" href="{esc(tg_url)}" target="_blank" rel="noopener">'
        f'📱 فتح في تليجرام</a>'
        if tg_url else ""
    )

    # معلومات إضافية
    note = ""
    if embed_url:
        note = (
            '<div class="embed-note">'
            '▶ الفيديو يعمل مباشرة من تليجرام. '
            'إذا لم يظهر، اضغط "فتح في تليجرام".'
            '</div>'
        )

    next_json = json.dumps(
        f'{next_ep["message_id"]}.html' if next_ep else None
    )

    body = (
        f'<div class="watch-wrap">'
        f'<div class="player-shell">{player}</div>'
        f'{note}'
        f'<div class="watch-info">'
        f'<h1>{esc(name)}</h1>'
        f'<h2>الموسم {season} · الحلقة {episode}</h2>'
        f'<div class="watch-nav">'
        f'{prev_btn}'
        f'<a class="btn" href="{series_url}">📺 كل الحلقات</a>'
        f'{next_btn}'
        f'{tg_btn}'
        f'</div>'
        f'<div class="autoplay-bar">'
        f'<label><input type="checkbox" id="autoplay-toggle" checked> '
        f'تشغيل الحلقة التالية تلقائياً</label>'
        f'<span id="countdown"></span>'
        f'</div></div></div>'
        f'<script>window.__NEXT_URL__ = {next_json};</script>'
    )

    head = '<link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css">'
    scripts = (
        '<script src="https://cdn.plyr.io/3.7.8/plyr.polyfilled.js"></script>'
        '<script src="../static/watch.js"></script>'
    )
    return base(
        f"الحلقة {episode} — {name}",
        body,
        depth=1,
        head=head,
        scripts=scripts,
    )


# ═══════════════════════════════════════════════════════════
#  Build
# ═══════════════════════════════════════════════════════════
def build(clean=False):
    # حذف القديم
    if clean and DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir(parents=True, exist_ok=True)

    # static
    write_static()
    shutil.copytree(STATIC, DOCS / "static", dirs_exist_ok=True)

    # data
    data = load_data()
    series = normalize(data)
    total = sum(s["total_episodes"] for s in series)
    channel_info = data.get("channel", {})
    log(f"{len(series)} series | {total} episodes")
    if channel_info:
        log(f"channel: {channel_info.get('title', '?')} "
            f"(@{channel_info.get('username', '')}) "
            f"public={channel_info.get('is_public')}")

    # index
    (DOCS / "index.html").write_text(render_index(series), encoding="utf-8")

    # 404
    (DOCS / "404.html").write_text(
        base(
            "404",
            '<section class="hero"><h1>404</h1>'
            '<p><a href="index.html">العودة للرئيسية</a></p></section>'
        ),
        encoding="utf-8",
    )

    # .nojekyll
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    # مجلدات
    (DOCS / "series").mkdir(exist_ok=True)
    (DOCS / "watch").mkdir(exist_ok=True)

    # الصفحات
    ns = nw = 0
    for s in series:
        # ✅ اكتب الملف باسم عربي حقيقي
        fname = safe_name(s["name"])
        (DOCS / "series" / f"{fname}.html").write_text(
            render_series(s), encoding="utf-8"
        )
        ns += 1

        for sk, eps in s["seasons"].items():
            for i, ep in enumerate(eps):
                prev_ep = eps[i - 1] if i > 0 else None
                next_ep = eps[i + 1] if i + 1 < len(eps) else None
                html_out = render_watch(
                    s["name"], int(sk), ep["episode"],
                    prev_ep, next_ep, ep
                )
                (DOCS / "watch" / f"{ep['message_id']}.html").write_text(
                    html_out, encoding="utf-8"
                )
                nw += 1

    log(f"{ns} series pages | {nw} watch pages")

    # معلومات تشخيصية
    for s in series[:3]:
        f_name = safe_name(s["name"])
        log(f"  file: series/{f_name}.html")
        log(f"  link: series/{enc(f_name)}.html")


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true",
                        help="حذف docs/ قبل البناء")
    args = parser.parse_args()

    log("=" * 40)
    log("TelegramFlix builder")
    log(f"ROOT: {ROOT}")
    log(f"data.json exists: {DATA.exists()}")

    build(clean=args.clean)

    log("✅ done")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
