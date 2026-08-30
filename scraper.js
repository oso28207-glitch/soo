const cheerio = require('cheerio');
const fs = require('fs');

// ============================================================
// قائمة يدوية للمسلسلات التركية المدبلجة (مضمونة 100%)
// ============================================================
const MANUAL_TURKISH_SERIES = [
    {
        name: 'قيامة عثمان',
        search: 'قيامة عثمان مدبلج',
        knownUrl: 'https://3isk.homes/series/قيامة-عثمان-مدبلج/'
    },
    {
        name: 'السلطان عبد الحميد',
        search: 'السلطان عبد الحميد مدبلج',
        knownUrl: 'https://3isk.homes/series/السلطان-عبد-الحميد-مدبلج/'
    },
    {
        name: 'حكاية حب',
        search: 'حكاية حب مدبلج',
        knownUrl: 'https://3isk.homes/series/حكاية-حب-مدبلج/'
    },
    {
        name: 'العشق الممنوع',
        search: 'العشق الممنوع مدبلج',
        knownUrl: 'https://3isk.homes/series/العشق-الممنوع-مدبلج/'
    },
    {
        name: 'وادي الذئاب',
        search: 'وادي الذئاب مدبلج',
        knownUrl: 'https://3isk.homes/series/وادي-الذئاب-مدبلج/'
    },
    {
        name: 'حب للايجار',
        search: 'حب للايجار مدبلج',
        knownUrl: 'https://3isk.homes/series/حب-للايجار-مدبلج/'
    },
    {
        name: 'ندى العمر',
        search: 'ندى العمر مدبلج',
        knownUrl: 'https://3isk.homes/series/ندى-العمر-مدبلج/'
    },
    {
        name: 'الوردة السوداء',
        search: 'الوردة السوداء مدبلج',
        knownUrl: 'https://3isk.homes/series/الوردة-السوداء-مدبلج/'
    },
    {
        name: 'عودة مهند',
        search: 'عودة مهند مدبلج',
        knownUrl: 'https://3isk.homes/series/عودة-مهند-مدبلج/'
    },
    {
        name: 'الآسيوي',
        search: 'الآسيوي مدبلج',
        knownUrl: 'https://3isk.homes/series/الآسيوي-مدبلج/'
    },
    {
        name: 'ابن الحلال',
        search: 'ابن الحلال مدبلج',
        knownUrl: 'https://3isk.homes/series/ابن-الحلال-مدبلج/'
    },
    {
        name: 'زهرة القصر',
        search: 'زهرة القصر مدبلج',
        knownUrl: 'https://3isk.homes/series/زهرة-القصر-مدبلج/'
    },
    {
        name: 'أميرة اسطنبول',
        search: 'أميرة اسطنبول مدبلج',
        knownUrl: 'https://3isk.homes/series/أميرة-اسطنبول-مدبلج/'
    },
    {
        name: 'اغتيال عثمان',
        search: 'اغتيال عثمان مدبلج',
        knownUrl: 'https://3isk.homes/series/اغتيال-عثمان-مدبلج/'
    },
    {
        name: 'مسلسل تركي 1',
        search: 'مسلسل تركي مدبلج',
        knownUrl: ''
    }
];

// ============================================================
// قائمة المواقع (للمحاولة)
// ============================================================
const SITES = [
    { name: 'قصة عشق', url: 'https://3isk.homes' },
    { name: 'قصة عشق بديل', url: 'https://aa.3ick.net' },
    { name: 'EgyWatch', url: 'https://egywatch.live' }
];

// ============================================================
// دوال مساعدة محسنة
// ============================================================
async function fetchContent(url, retries = 3) {
    for (let i = 0; i < retries; i++) {
        try {
            const response = await fetch(url, {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'ar,en;q=0.9'
                },
                redirect: 'follow'
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.text();
        } catch (error) {
            console.warn(`  ⚠️ محاولة ${i+1} فشلت: ${error.message}`);
            if (i === retries - 1) return null;
            await new Promise(r => setTimeout(r, 2000 * (i + 1)));
        }
    }
    return null;
}

/**
 * استخراج الحلقات من صفحة المسلسل
 */
async function fetchEpisodesFromPage(pageUrl) {
    try {
        const html = await fetchContent(pageUrl, 2);
        if (!html) return null;
        const $ = cheerio.load(html);
        const episodes = [];

        // محاولة استخراج روابط الحلقات (محددات شائعة)
        $('.episode-link, .episode-item, .episodes-list a, .season-episodes a, .episode a').each((i, el) => {
            let link = $(el).attr('href');
            let name = $(el).text().trim() || `الحلقة ${i+1}`;
            if (link) {
                if (!link.startsWith('http')) {
                    link = new URL(link, pageUrl).href;
                }
                // تجاهل روابط التحميل أو الصفحات الأخرى
                if (!link.includes('/episode/') && !link.includes('/watch/')) return;
                episodes.push({ name: name.trim(), url: link });
            }
        });

        // إذا لم نجد، نحاول البحث عن أي رابط يحتوي على episode
        if (episodes.length === 0) {
            $('a[href*="episode"], a[href*="watch"]').each((i, el) => {
                let link = $(el).attr('href');
                let name = $(el).text().trim() || `الحلقة ${i+1}`;
                if (link) {
                    if (!link.startsWith('http')) link = new URL(link, pageUrl).href;
                    episodes.push({ name: name, url: link });
                }
            });
        }

        // إذا وجدنا أكثر من 50 حلقة، نأخذ أول 50
        return episodes.length > 0 ? episodes.slice(0, 50) : null;
    } catch (error) {
        console.warn(`  ⚠️ فشل جلب الحلقات من ${pageUrl}: ${error.message}`);
        return null;
    }
}

/**
 * محاولة جلب صورة من صفحة المسلسل
 */
async function fetchImageFromPage(pageUrl) {
    try {
        const html = await fetchContent(pageUrl, 1);
        if (!html) return null;
        const $ = cheerio.load(html);
        let img = $('meta[property="og:image"]').attr('content');
        if (!img) img = $('meta[name="twitter:image"]').attr('content');
        if (!img) img = $('.poster img').attr('src');
        if (!img) img = $('.series-poster img').attr('src');
        if (!img) img = $('img.cover').attr('src');
        if (!img) img = $('.entry-image img').attr('src');
        if (img && !img.startsWith('http')) {
            img = new URL(img, pageUrl).href;
        }
        return img || null;
    } catch {
        return null;
    }
}

/**
 * البحث عن مسلسل في موقع معين
 */
async function searchSeriesOnSite(seriesName, siteUrl) {
    try {
        // محاولة البحث باستخدام الرابط المباشر إن وجد
        const searchUrl = `${siteUrl}/search?q=${encodeURIComponent(seriesName)}`;
        const html = await fetchContent(searchUrl, 1);
        if (!html) return null;

        const $ = cheerio.load(html);
        // البحث عن أول نتيجة
        const firstResult = $('.result-item a, .search-result a, .series-item a').first();
        if (firstResult.length > 0) {
            let link = firstResult.attr('href');
            if (link && !link.startsWith('http')) {
                link = new URL(link, siteUrl).href;
            }
            return link;
        }
        return null;
    } catch {
        return null;
    }
}

// ============================================================
// الدالة الرئيسية: بناء قائمة المسلسلات
// ============================================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري بناء قائمة المسلسلات التركية المدبلجة...\n');
    const finalSeries = [];

    // 1. استخدام القائمة اليدوية أولاً
    console.log('📌 المرحلة 1: بناء القاعدة من القائمة اليدوية...');
    for (const manual of MANUAL_TURKISH_SERIES) {
        console.log(`  🔍 معالجة: ${manual.name}`);
        
        // محاولة الحصول على رابط مباشر من القائمة
        let seriesPageUrl = manual.knownUrl || '';
        let image = null;
        let episodes = [];

        // إذا لم يكن هناك رابط معروف، نحاول البحث
        if (!seriesPageUrl) {
            for (const site of SITES) {
                const found = await searchSeriesOnSite(manual.name, site.url);
                if (found) {
                    seriesPageUrl = found;
                    break;
                }
            }
        }

        // جلب التفاصيل من الصفحة
        if (seriesPageUrl) {
            console.log(`    📄 جلب البيانات من: ${seriesPageUrl}`);
            // جلب الصورة
            image = await fetchImageFromPage(seriesPageUrl);
            // جلب الحلقات
            const epData = await fetchEpisodesFromPage(seriesPageUrl);
            if (epData && epData.length > 0) {
                episodes = epData;
                console.log(`    ✅ تم جلب ${episodes.length} حلقة`);
            } else {
                // حلقات تجريبية
                episodes = [
                    { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                    { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
                ];
                console.log(`    ⚠️ لم نجد حلقات، نستخدم حلقات تجريبية`);
            }
        } else {
            console.log(`    ⚠️ لم نجد رابط للمسلسل، نستخدم بيانات تجريبية`);
            image = `https://via.placeholder.com/200x280/1e1e1e/f5c518?text=${encodeURIComponent(manual.name)}`;
            episodes = [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ];
        }

        // إضافة المسلسل للقائمة النهائية
        finalSeries.push({
            name: manual.name,
            image: image || `https://via.placeholder.com/200x280/1e1e1e/f5c518?text=${encodeURIComponent(manual.name)}`,
            link: seriesPageUrl || '#',
            source: 'قائمة يدوية',
            episodes: episodes
        });
    }

    // 2. محاولة جلب المزيد من Sitemap (احتياطي) ولكن مع فلترة صارمة
    console.log('\n📌 المرحلة 2: محاولة جلب إضافية من Sitemap (فلترة صارمة)...');
    const additional = await fetchFromSitemaps();
    if (additional.length > 0) {
        // دمج مع تجنب التكرار
        const existingNames = new Set(finalSeries.map(s => s.name.toLowerCase().trim()));
        for (const s of additional) {
            const key = s.name.toLowerCase().trim();
            if (!existingNames.has(key) && s.name.includes('تركي')) {
                finalSeries.push(s);
                existingNames.add(key);
            }
        }
    }

    console.log(`\n✅ تم جمع ${finalSeries.length} مسلسل تركي مدبلج فريد.`);
    return finalSeries;
}

// ============================================================
// جلب إضافي من Sitemap (مع فلترة صارمة)
// ============================================================
async function fetchFromSitemaps() {
    const results = [];
    const sitesWithSitemap = [
        'https://3isk.homes/sitemap.xml',
        'https://aa.3ick.net/sitemap.xml',
        'https://egywatch.live/sitemap.xml'
    ];

    for (const sitemapUrl of sitesWithSitemap) {
        console.log(`  📡 محاولة جلب: ${sitemapUrl}`);
        const xml = await fetchContent(sitemapUrl, 1);
        if (!xml) continue;

        const $ = cheerio.load(xml, { xmlMode: true });
        const urls = new Set();

        $('url > loc').each((i, el) => {
            let loc = $(el).text().trim();
            if (!loc) return;
            // فلترة صارمة: يجب أن يحتوي على كلمات تركية مدبلجة
            const lower = loc.toLowerCase();
            if ((lower.includes('تركي') || lower.includes('turkish') || lower.includes('dubbed')) &&
                (lower.includes('مسلسل') || lower.includes('series') || lower.includes('drama'))) {
                urls.add(loc);
            }
        });

        // أخذ أول 10 نتائج
        let count = 0;
        for (const url of urls) {
            if (count >= 10) break;
            count++;
            const name = extractNameFromUrl(url);
            if (name && name.includes('تركي')) {
                const image = await fetchImageFromPage(url);
                const episodes = await fetchEpisodesFromPage(url) || [
                    { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
                ];
                results.push({
                    name: name,
                    image: image || `https://via.placeholder.com/200x280/1e1e1e/f5c518?text=${encodeURIComponent(name)}`,
                    link: url,
                    source: 'Sitemap',
                    episodes: episodes
                });
            }
        }
    }
    return results;
}

function extractNameFromUrl(url) {
    try {
        const path = new URL(url).pathname;
        const parts = path.split('/').filter(p => p && p !== 'series' && p !== 'show');
        if (parts.length > 0) {
            let name = parts[parts.length - 1].replace(/-/g, ' ');
            try { name = decodeURIComponent(name); } catch (e) {}
            name = name.replace(/^مشاهدة\s*/i, '').replace(/^المسلسل المترجم\s*/i, '');
            name = name.replace(/^مسلسل\s*/i, '');
            return name.charAt(0).toUpperCase() + name.slice(1);
        }
        return null;
    } catch {
        return null;
    }
}

// ============================================================
// حفظ البيانات
// ============================================================
async function main() {
    const series = await fetchTurkishSeries();
    fs.writeFileSync('data.json', JSON.stringify(series, null, 2));
    console.log(`💾 تم حفظ ${series.length} مسلسل في data.json`);
}

main().catch(error => {
    console.error('❌ خطأ غير متوقع:', error.message);
    process.exit(1);
});
