#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classify.py — وحدة التصنيف المشتركة في المشروع
المعيار الرسمي:
  - فيلم   : عدد الحلقات/الأجزاء ≤ 3
  - مسلسل  : عدد الحلقات ≥ 5
  - 4 حلقات: منطقة رمادية → يُحسم من الاسم (موسم/Sxx/مسلسل → series، وإلا → movie)
"""

import re

MOVIE_MAX_PARTS = 3
SERIES_MIN_EPS  = 5

# ═══════════════════════════════════════════════════════════════
# كلمات الأصل
# ═══════════════════════════════════════════════════════════════
ARABIC_KW = [
    "لام شمسية","الحلانجي","سيد الناس","جوما","إش إش","اش اش",
    "ولد وبنت وشايب","حالات نادرة","قهوة المحطة","خالد نور وولده نور خالد",
    "برغم القانون","ما تراه ليس كما يبدو","عهد أنيس","قابيل","لعبة نيوتن",
    "منورة بأهلها","منورة باهلها","الاخ الكبير","الأخ الكبير","النص",
    "النص التاني","النص الثاني","البيت بيتي","البيت بيتك","صحاب الارض",
    "صحاب الأرض","عين سحرية","الست موناليزا","مناعة","كارثة طبيعية",
    "مملكة الحرير","موعد مع الماضي","بـ 100 وش","ب 100 وش","ضربة معلم",
    "بدون سابق انذار","بدون سابق إنذار","فن الحرب","حد اقصى","حد أقصى",
    "الف ليله وليله","ألف ليلة وليلة","اتنين غيرنا","المصيدة","الاختيار",
    "الحشاشين","المداح","جعفر العمدة","بيت الرفاعي","العتاولة","نسل الأغراب",
    "الهيبة",
]

TURKISH_KW = [
    "مدبلج","تركي","تركية","قيامة أرطغرل","قيامة ارطغرل","المؤسس عثمان",
    "حريم السلطان","وادي الذئاب","قيامة عثمان","أرطغرل","ارطغرل",
    "حياتي الرائعة","أوراق النسيان","اوراق النسيان","كذبتي الحلوة",
    "لعبة حب","التفاح الحرام","حب للايجار","حب للإيجار","الحب ورطة",
    "احتمال حب","ورود وذنوب","الغرفة 309","كيزيلجيك","على مر الزمان",
    "سنوات الضياع","العشق الأسود","العشق المشبوه","عشق ودموع","جسور والجميلة",
    "أنت اطرق بابي","انت اطرق بابي","كان يا مكان","فتاة النافذة",
    "حب أعمى","حب اعمى","قلب الأسد","قلب الاسد","الحفرة","الطبيب المعجزة",
    "الأزهار الحزينة","الازهار الحزينة","زهرة الثالوث","طائر الرفراف",
    "ثلاثة أجساد","ثلاثة اجساد","سجين الحب","دموع الغجرية","فيلينتا",
    "الخياط","المحافظ",
]

FOREIGN_KW = [
    "افاتار","آفاتار","avatar","بريكينغ باد","breaking bad","the last of us",
    "inception","the batman","squid game","game of thrones","money heist",
    "لوكي","loki",
]

# ═══════════════════════════════════════════════════════════════
# مؤشرات الاسم
# ═══════════════════════════════════════════════════════════════
SERIES_HINTS = [
    re.compile(r"^(?:مسلسل|series)\b", re.I),
    re.compile(r"\b(?:موسم|season|S\d{1,2})\b", re.I),
]
MOVIE_HINTS = [
    re.compile(r"^(?:فيلم|فيلمو|movie|film)\b", re.I),
]

# ═══════════════════════════════════════════════════════════════
def detect_origin(name: str) -> str:
    """يحدد أصل العمل: arabic / turkish / foreign"""
    if not name:
        return "arabic"
    nl = name.lower()
    for kw in FOREIGN_KW:
        if kw in name or kw.lower() in nl:
            return "foreign"
    if "مدبلج" in name or "تركي" in name or "تركية" in name:
        return "turkish"
    for kw in ARABIC_KW:
        if kw in name:
            return "arabic"
    for kw in TURKISH_KW:
        if kw in name:
            return "turkish"
    arabic_chars = len(re.findall(r"[\u0600-\u06FF]", name))
    latin_chars  = len(re.findall(r"[A-Za-z]", name))
    if arabic_chars > 0 and latin_chars == 0:
        return "arabic"
    if arabic_chars > latin_chars:
        return "arabic"
    return "foreign"

def detect_type(name: str, episode_count: int) -> str:
    """
    يحدد النوع حسب المعيار:
      ≥ 5 → series
      ≤ 3 → movie
      = 4 → يُحسم من الاسم
    """
    n = int(episode_count or 0)
    if n >= SERIES_MIN_EPS:
        return "series"
    if n <= MOVIE_MAX_PARTS:
        return "movie"
    # n == 4 (منطقة رمادية)
    for pat in SERIES_HINTS:
        if pat.search(name or ""):
            return "series"
    for pat in MOVIE_HINTS:
        if pat.search(name or ""):
            return "movie"
    # 4 حلقات ليست كافية لتكون مسلسلًا
    return "movie"

def category_slug(name: str, episode_count: int) -> str:
    return f"{detect_type(name, episode_count)}-{detect_origin(name)}"