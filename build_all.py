#!/usr/bin/env python3
"""
build_all.py — TelegramFlix One-File Builder
=============================================
ملف واحد يفعل كل شيء:
  1. ينشئ كل ملفات المشروع (templates, static, workflow, ...)
  2. يقرأ data.json ويبني موقعاً ثابتاً كاملاً في docs/
  3. يعمل مباشرة في GitHub Actions بدون ملفات مساعدة

الاستخدام:
    python build_all.py            # بناء عادي
    python build_all.py --init     # إنشاء ملفات المشروع فقط
    python build_all.py --clean    # حذف docs/ قبل البناء
"""
from __future__ import annotations

import os
import sys
import json
import html
import shutil
import argparse
from pathlib import Path
from datetime import datetime

# ═══════════════════════════════════════════════════════════
#  الإعدادات
# ═══════════════════════════════════════════════════════════
ROOT = Path(__file__).parent.resolve()
DOCS = ROOT / "docs"
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
WORKFLOW = ROOT / ".github" / "workflows"
DATA_FILE = ROOT / "data.json"

# رابط GitHub Pages — يمكن تجاوزه بمتغيّر بيئة
GH_OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "oso28207-glitch")
GH_REPO = os.environ.get("GITHUB_REPOSITORY", "oso28207-glitch/soo").split("/")[-1]
BASE_URL = os.environ.get(
    "BASE_URL", f"https://{GH_OWNER}.github.io/{GH_REPO}/"
)

# ═══════════════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════════════
def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)

def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)

def url_encode_arabic(name: str) -> str:
    """ترميز أسماء المسلسلات العربية لروابط URL"""
    from urllib.parse import quote
    return quote(name, safe="")

def human_duration(secs: int) -> str:
    if not secs:
        return "—"
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"

# ═══════════════════════════════════════════════════════════
#  1) إنشاء ملفات المشروع
# ═══════════════════════════════════════════════════════════
def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    log(f"  ✍️  {path.relative_to(ROOT)}")

def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    log(f"  ✍️  {path.relative_to(ROOT)}")

# ───────────── ملفات static ─────────────
STYLE_CSS = r"""
:root {
    --bg: #0b0b0f; --bg-2: #141418; --card: #1a1a20; --card-hover: #23232c;
    --text: #f5f5f7; --muted: #9a9aa5; --accent: #e50914; --accent-2: #ff2b36;
    --radius: 12px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: var(--bg); color: var(--text); font-family: "Cairo","Segoe UI",system-ui,sans-serif; min-height: 100%; }
a { color: inherit; text-decoration: none; }
.topbar { position: sticky; top: 0; z-index: 100; display: flex; align-items: center; gap: 2rem;
    padding: 1rem 2rem; background: linear-gradient(to bottom, rgba(0,0,0,.9), rgba(0,0,0,.6));
    backdrop-filter: blur(10px); }
.logo { font-weight: 800; font-size: 1.6rem; color: var(--accent); letter-spacing: -.5px; }
.logo span { color: var(--text); }
.nav { display: flex; gap: 1.5rem; }
.nav a { color: var(--muted); font-weight: 600; transition: color .2s; }
.nav a:hover { color: var(--text); }
.container { padding: 2rem; max-width: 1500px; margin: 0 auto; }
.hero { margin-bottom: 2.5rem; }
.hero h1 { font-size: 2.4rem; margin-bottom: .4rem; }
.hero p { color: var(--muted); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1.2rem; }
.card { background: var(--card); border-radius: var(--radius); overflow: hidden;
    transition: transform .25s ease, background .25s ease; display: block; }
.card:hover { transform: translateY(-6px); background: var(--card-hover); }
.card-thumb { position: relative; aspect-ratio: 2/3; background: #222; overflow: hidden; }
.card-thumb img { width: 100%; height: 100%; object-fit: cover; transition: transform .35s ease; }
.card:hover .card-thumb img { transform: scale(1.06); }
.no-thumb { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
    font-size: 4rem; color: var(--muted); background: linear-gradient(135deg, #2a2a33, #1a1a20); }
.card-overlay { position: absolute; inset: auto 0 0 0; padding: .6rem;
    background: linear-gradient(to top, rgba(0,0,0,.9), transparent); }
.badge { background: var(--accent); color: #fff; font-size: .75rem; font-weight: 700;
    padding: .2rem .55rem; border-radius: 999px; }
.card-body { padding: .8rem 1rem 1rem; }
.card-body h3 { font-size: 1rem; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-body p { color: var(--muted); font-size: .85rem; margin-top: .2rem; }
.series-header { display: flex; gap: 2rem; margin-bottom: 3rem; align-items: flex-start; }
.series-poster { width: 220px; aspect-ratio: 2/3; border-radius: var(--radius); overflow: hidden;
    background: #222; flex-shrink: 0; }
.series-poster img { width: 100%; height: 100%; object-fit: cover; }
.series-meta { flex: 1; }
.series-meta h1 { font-size: 2.2rem; margin-bottom: .5rem; }
.series-meta p { color: var(--muted); margin-bottom: 1.2rem; }
.season { margin-bottom: 2.5rem; }
.season h2 { font-size: 1.4rem; margin-bottom: 1rem; }
.episodes { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 1rem; }
.episode-card { background: var(--card); border-radius: var(--radius); overflow: hidden;
    transition: transform .2s, background .2s; }
.episode-card:hover { transform: translateY(-4px); background: var(--card-hover); }
.episode-thumb { position: relative; aspect-ratio: 16/9; background: #222; }
.episode-thumb img { width: 100%; height: 100%; object-fit: cover; }
.play-icon { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    background: rgba(0,0,0,.45); opacity: 0; transition: opacity .25s; font-size: 2rem; color: #fff; }
.episode-card:hover .play-icon { opacity: 1; }
.episode-info { padding: .7rem .9rem 1rem; }
.episode-info h4 { font-size: .95rem; }
.episode-info .duration { color: var(--muted); font-size: .8rem; }
.watch-wrap { max-width: 1200px; margin: 0 auto; }
.player-shell { background: #000; border-radius: var(--radius); overflow: hidden;
    margin-bottom: 1.5rem; aspect-ratio: 16/9; }
.player-shell video { width: 100%; height: 100%; display: block; }
.no-player { display: flex; align-items: center; justify-content: center; height: 100%;
    color: var(--muted); text-align: center; padding: 2rem; }
.no-player a { color: var(--accent); font-weight: 700; text-decoration: underline; }
.watch-info h1 { font-size: 1.6rem; margin-bottom: .3rem; }
.watch-info h2 { font-size: 1.05rem; color: var(--muted); margin-bottom: 1.2rem; font-weight: 500; }
.watch-nav { display: flex; gap: .8rem; flex-wrap: wrap; margin-bottom: 1rem; }
.btn { display: inline-flex; align-items: center; gap: .4rem; padding: .65rem 1.2rem;
    background: #2a2a33; color: var(--text); border: none; border-radius: 8px;
    font-weight: 700; font-size: .9rem; cursor: pointer; transition: background .2s;
    font-family: inherit; }
.btn:hover { background: #3a3a45; }
.btn.primary { background: var(--accent); }
.btn.primary:hover { background: var(--accent-2); }
.btn.disabled { background: #1a1a20; color: #555; cursor: not-allowed; pointer-events: none; }
.autoplay-bar { display: flex; align-items: center; gap: 1rem; padding: .8rem 1rem;
    background: var(--bg-2); border-radius: 8px; color: var(--muted); font-size: .9rem; }
.autoplay-bar label { display: flex; align-items: center; gap: .5rem; cursor: pointer; }
.autoplay-bar input { accent-color: var(--accent); }
#countdown { color: var(--accent); font-weight: 700; }
.empty { text-align: center; padding: 5rem 2rem; color: var(--muted); }
.empty code { display: inline-block; margin: .6rem; padding: .5rem .9rem;
    background: var(--card); border-radius: 6px; color: var(--text); font-family: monospace; }
@media (max-width: 720px) {
    .container { padding: 1rem; }
    .topbar { padding: .8rem 1rem; }
    .series-header { flex-direction: column; }
    .series-poster { width: 160px; }
    .hero h1 { font-size: 1.6rem; }
}
"""

WATCH_JS = r"""
document.addEventListener("DOMContentLoaded", function () {
    var video = document.getElementById("player");
    if (!video) return;

    var toggle = document.getElementById("autoplay-toggle");
    var countdown = document.getElementById("countdown");
    var nextUrl = window.__NEXT_URL__ || null;
    var cancelled = false;

    // Plyr إن توفّر
    var player = video;
    if (typeof Plyr !== "undefined") {
        player = new Plyr(video, {
            controls: ["play-large","play","progress","current-time","duration",
                       "mute","volume","captions","settings","pip","airplay","fullscreen"],
            seekTime: 10,
            keyboard: { focused: true, global: true }
        });
    }

    function startCountdown() {
        if (!nextUrl || (toggle && !toggle.checked)) return;
        var counter = 5;
        countdown.textContent = "⏭ الحلقة التالية بعد " + counter + " ثانية...";
        var timer = setInterval(function () {
            if (cancelled) { clearInterval(timer); countdown.textContent = ""; return; }
            counter -= 1;
            if (counter <= 0) { clearInterval(timer); window.location.href = nextUrl; }
            else { countdown.textContent = "⏭ الحلقة التالية بعد " + counter + " ثانية..."; }
        }, 1000);
    }

    function onEnded() { startCountdown(); }
    function onInteract() { cancelled = true; countdown.textContent = ""; }

    if (player.on) {
        player.on("ended", onEnded);
        player.on("play", onInteract);
        player.on("seeking", onInteract);
    } else {
        video.addEventListener("ended", onEnded);
        video.addEventListener("play", onInteract);
        video.addEventListener("seeking", onInteract);
    }

    if (toggle) {
        toggle.addEventListener("change", function () {
            cancelled = !toggle.checked;
            if (!toggle.checked) countdown.textContent = "";
        });
    }

    // حفظ موضع المشاهدة
    var key = "tf_progress_" + window.location.pathname;
    var saved = parseFloat(localStorage.getItem(key) || "0");
    if (saved > 5) {
        if (video.readyState >= 1) video.currentTime = saved;
        else video.addEventListener("loadedmetadata", function () { video.currentTime = saved; });
    }
    setInterval(function () {
        if (video.currentTime > 0 && !video.paused) {
            localStorage.setItem(key, String(video.currentTime));
        }
    }, 5000);
});
"""

WORKFLOW_YML = r"""name: 🎬 Build & Deploy TelegramFlix

on:
  push:
    branches: [main]
    paths:
      - 'build_all.py'
      - 'data.json'
  workflow_dispatch:
  schedule:
    - cron: '0 */6 * * *'

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: ⬇️ Checkout
        uses: actions/checkout@v4

      - name: 🐍 Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: 🔨 Build static site
        run: python build_all.py --clean
        env:
          BASE_URL: https://${{ github.repository_owner }}.github.io/${{ github.event.repository.name }}/

      - name: 📤 Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: docs/

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: 🚀 Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
"""

README_MD = r"""# 🎬 TelegramFlix

موقع نتفلكس-ستايل لعرض المسلسلات من قناة تليجرام، يُبنى تلقائياً على GitHub Pages.

## كيف يعمل؟

ملف واحد فقط: `build_all.py`
- يقرأ `data.json` الذي يحتوي بيانات المسلسلات.
- يبني موقعاً ثابتاً كاملاً في `docs/`.
- GitHub Actions تنشر `docs/` على GitHub Pages تلقائياً.

## التشغيل المحلي

```bash
python build_all.py --clean
# ثم افتح docs/index.html
