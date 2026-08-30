const cheerio = require('cheerio');
const fs = require('fs');

// ============================================================
// قائمة أولية مضمونة من المسلسلات التركية المدبلجة
// (لضمان ظهور البيانات حتى لو فشل الجلب)
// ============================================================
const FALLBACK_SERIES = [
    {
        name: 'قيامة عثمان',
        image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=قيامة+عثمان',
        link: '#',
        source: 'قائمة مضمونة',
        episodes: [
            { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
            { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
        ]
    },
    {
        name: 'السلطان عبد الحميد',
        image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=السلطان+عبد+الحميد',
        link: '#',
        source: 'قائمة مضمونة',
        episodes: [
            { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
            { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
        ]
    },
    {
        name: 'حكاية حب',
        image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=حكاية+حب',
        link: '#',
        source: 'قائمة مضمونة',
        episodes: [
            { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
        ]
    },
    {
        name: 'العشق الممنوع',
        image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=العشق+الممنوع',
        link: '#',
        source: 'قائمة مضمونة',
        episodes: [
            { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
            { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
        ]
    },
    {
        name: 'وادي الذئاب',
        image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=وادي+الذئاب',
        link: '#',
        source: 'قائمة مضمونة',
        episodes: [
            { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
        ]
    },
    {
        name: 'حب للايجار',
        image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=حب+للايجار',
        link: '#',
        source: 'قائمة مضمونة',
        episodes: [
            { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
            { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
        ]
    },
    {
        name: 'ندى العمر',
        image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=ندى+العمر',
        link: '#',
        source: 'قائمة مضمونة',
        episodes: [
            { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
        ]
    },
    {
        name: 'الوردة السوداء',
        image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=الوردة+السوداء',
        link: '#',
        source: 'قائمة مضمونة',
        episodes: [
            { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
            { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
        ]
    },
    {
        name: 'عودة مهند',
        image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=عودة+مهند',
        link: '#',
        source: 'قائمة مضمونة',
        episodes: [
            { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
        ]
    },
    {
        name: 'الآسيوي',
        image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=الآسيوي',
        link: '#',
        source: 'قائمة مضمونة',
        episodes: [
            { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
            { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
        ]
    }
];

// ============================================================
// قائمة المواقع (مع Sitemap)
// ============================================================
const SITES = [
    {
        name: 'EgyWatch',
        sitemap: 'https://egywatch.live/sitemap.xml',
        mainUrl: 'https://egywatch.live/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'LodyNet',
        sitemap: 'https://lodynet.watch/sitemap.xml',
        mainUrl: 'https://lodynet.watch/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: '3isk (قصة عشق)',
        sitemap: 'https://aa.3ick.net/sitemap.xml',
        mainUrl: 'https://aa.3ick.net/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'قصة عشق (بديل)',
        sitemap: 'https://3isk.homes/sitemap.xml',
        mainUrl: 'https://3isk.homes/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'قصة عشق (3iskk)',
        sitemap: 'https://3iskk.xyz/sitemap.xml',
        mainUrl: 'https://3iskk.xyz/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'قصة عشق (3sk)',
        sitemap: 'https://we.3sk.media/sitemap.xml',
        mainUrl: 'https://we.3sk.media/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'قصة عشق (eishq)',
        sitemap: 'https://new.eishq.net/sitemap.xml',
        mainUrl: 'https://new.eishq.net/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'قصة عشق (qeseh)',
        sitemap: 'https://qeseh.net/sitemap.xml',
        mainUrl: 'https://qeseh.net/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'قرمزي',
        sitemap: 'https://www.qrmzi.tv/sitemap.xml',
        mainUrl: 'https://www.qrmzi.tv/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'سيما لينا',
        sitemap: 'https://cimalina.live/sitemap.xml',
        mainUrl: 'https://cimalina.live/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'دراما تركية (DramaTurk)',
        sitemap: null,
        mainUrl: 'https://dramaturk.com/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'لاروزا فيديو',
        sitemap: null,
        mainUrl: 'https://larozavideo.com/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'شاهد فور يو',
        sitemap: null,
        mainUrl: 'https://shahid4u.com/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'عرب سيد',
        sitemap: null,
        mainUrl: 'https://arabseed.com/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    },
    {
        name: 'ماي سيما',
        sitemap: null,
        mainUrl: 'https://mycima.net/',
        selectors: { series: '.series-item', title: '.series-title', image: 'img', link: 'a' }
    }
];

// ============================================================
// دوال مساعدة
// ============================================================
async function fetchContent(url, retries = 2) {
    for (let i = 0; i < retries; i++) {
        try {
            const response = await fetch(url, {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'ar,en;q=0.9',
                    'Cache-Control': 'no-cache'
                },
                redirect: 'follow'
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.text();
        } catch (error) {
            console.warn(`  ⚠️ محاولة ${i+1} فشلت: ${error.message}`);
            if (i === retries - 1) return null;
            await new Promise(r => setTimeout(r, 2000));
        }
    }
    return null;
}

/**
 * تحسين الفلترة: البحث عن كلمات مفتاحية للمسلسلات التركية المدبلجة
 */
function isTurkishDramaSeries(url, name = '') {
    const lowerUrl = url.toLowerCase();
    const lowerName = name.toLowerCase();

    // قائمة بأسماء مسلسلات تركية مدبلجة معروفة (للتأكيد)
    const knownSeries = [
        'قيامة عثمان', 'السلطان عبد الحميد', 'حكاية حب', 'العشق الممنوع',
        'وادي الذئاب', 'حب للايجار', 'ندى العمر', 'الوردة السوداء',
        'عودة مهند', 'الآسيوي', 'مسلسل تركي', 'drama turkish', 'turkish series'
    ];
    if (knownSeries.some(k => lowerName.includes(k) || lowerUrl.includes(k.replace(/ /g, '-')))) {
        return true;
    }

    // استبعاد الأفلام
    const exclude = ['فيلم', 'movie', 'film', 'black adam', 'avatar', 'john wick'];
    if (exclude.some(k => lowerUrl.includes(k) || lowerName.includes(k))) {
        return false;
    }

    // تضمين الكلمات الدالة
    const include = ['مسلسل', 'series', 'drama', 'episode', 'season', 'حلقات', 'موسم', 'تركي', 'turkish', 'مدبلج', 'dubbed'];
    if (include.some(k => lowerUrl.includes(k) || lowerName.includes(k))) {
        return true;
    }

    return false;
}

/**
 * استخراج روابط المسلسلات من Sitemap مع فلترة محسنة
 */
function extractSeriesUrlsFromSitemap(xmlText) {
    const $ = cheerio.load(xmlText, { xmlMode: true });
    const urls = new Set();

    $('url > loc, sitemap > loc').each((i, el) => {
        let loc = $(el).text().trim();
        if (!loc) return;

        let name = '';
        try {
            const path = new URL(loc).pathname;
            const parts = path.split('/').filter(p => p && p !== 'series' && p !== 'show' && p !== 'drama');
            if (parts.length > 0) {
                name = parts[parts.length - 1].replace(/-/g, ' ');
                try { name = decodeURIComponent(name); } catch (e) {}
            }
        } catch {}

        if (isTurkishDramaSeries(loc, name)) {
            urls.add(loc);
        }
    });

    console.log(`  📊 تم فلترة ${$('url > loc').length} رابط، بقي ${urls.size} مسلسل تركي مدبلج.`);
    return Array.from(urls);
}

/**
 * استخراج اسم المسلسل مع فك التشفير وتنظيف النص
 */
function extractSeriesNameFromUrl(url) {
    try {
        const path = new URL(url).pathname;
        const parts = path.split('/').filter(p => p && p !== 'series' && p !== 'show' && p !== 'drama');
        if (parts.length > 0) {
            let name = parts[parts.length - 1].replace(/-/g, ' ');
            try { name = decodeURIComponent(name); } catch (e) {}
            name = name.replace(/\bseason\b/gi, 'موسم').replace(/\bepisode\b/gi, 'حلقة');
            name = name.replace(/^مشاهدة\s*/i, '').replace(/^المسلسل المترجم\s*/i, '');
            name = name.replace(/^مسلسل\s*/i, '');
            if (name.toLowerCase().includes('فيلم') || name.toLowerCase().includes('film')) return null;
            return name.charAt(0).toUpperCase() + name.slice(1);
        }
        return url;
    } catch {
        return url;
    }
}

/**
 * محاولة جلب صورة المسلسل (مع تحسين)
 */
async function fetchSeriesImage(seriesUrl) {
    try {
        const html = await fetchContent(seriesUrl, 1);
        if (!html) return null;
        const $ = cheerio.load(html);
        let img = $('meta[property="og:image"]').attr('content');
        if (!img) img = $('meta[name="twitter:image"]').attr('content');
        if (!img) img = $('.poster img').attr('src') || $('.series-poster img').attr('src');
        if (!img) img = $('img.cover').attr('src') || $('.series-image img').attr('src');
        if (img && !img.startsWith('http')) {
            img = new URL(img, seriesUrl).href;
        }
        return img || null;
    } catch {
        return null;
    }
}

/**
 * محاولة جلب من HTML (احتياطي)
 */
async function fetchSeriesFromHtml(mainUrl, selectors) {
    try {
        const html = await fetchContent(mainUrl);
        if (!html) return [];
        const $ = cheerio.load(html);
        const seriesList = [];

        $(selectors.series).each((i, el) => {
            const name = $(el).find(selectors.title).text().trim();
            const image = $(el).find(selectors.image).attr('src');
            let link = $(el).find(selectors.link).attr('href');
            if (link && !link.startsWith('http')) link = new URL(link, mainUrl).href;
            if (name && link && isTurkishDramaSeries(link, name)) {
                seriesList.push({ name, image: image || '', link });
            }
        });

        return seriesList;
    } catch (error) {
        console.warn(`  ⚠️ فشل جلب HTML من ${mainUrl}: ${error.message}`);
        return [];
    }
}

// ============================================================
// الدالة الرئيسية: جلب البيانات + دمجها مع القائمة المضمونة
// ============================================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري البحث عن المسلسلات التركية المدبلجة...');
    console.log(`📋 سيتم البحث في ${SITES.length} موقع.\n`);

    let allSeries = [];
    const processedUrls = new Set();

    // 1. إضافة القائمة المضمونة أولاً (ضمان وجود بيانات)
    console.log('📌 إضافة القائمة المضمونة من المسلسلات التركية المدبلجة...');
    FALLBACK_SERIES.forEach(s => {
        allSeries.push({ ...s, source: 'قائمة مضمونة' });
    });

    // 2. محاولة جلب من Sitemap
    for (const site of SITES) {
        if (!site.sitemap) {
            console.log(`⏭️  تخطي ${site.name} (لا يوجد Sitemap)`);
            continue;
        }

        console.log(`📡 محاولة جلب Sitemap: ${site.name} (${site.sitemap})`);
        const xmlContent = await fetchContent(site.sitemap);

        if (xmlContent) {
            const seriesUrls = extractSeriesUrlsFromSitemap(xmlContent);
            if (seriesUrls.length > 0) {
                console.log(`✅ تم العثور على ${seriesUrls.length} مسلسل تركي مدبلج في ${site.name}`);

                const limitedUrls = seriesUrls.slice(0, 30);
                let index = 0;

                for (const url of limitedUrls) {
                    if (processedUrls.has(url)) continue;
                    processedUrls.add(url);
                    index++;

                    const name = extractSeriesNameFromUrl(url);
                    if (!name) continue;

                    console.log(`  🔍 (${index}/${limitedUrls.length}) جلب بيانات: ${name}`);

                    let image = null;
                    try { image = await fetchSeriesImage(url); } catch (e) {}

                    // البحث عن اسم مشابه في القائمة المضمونة للحفاظ على الحلقات
                    let episodes = [
                        { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                        { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
                    ];
                    const existing = allSeries.find(s => s.name.toLowerCase().includes(name.toLowerCase()) || name.toLowerCase().includes(s.name.toLowerCase()));
                    if (existing && existing.episodes && existing.episodes.length > 0) {
                        episodes = existing.episodes;
                    }

                    allSeries.push({
                        name: name,
                        image: image || `https://via.placeholder.com/200x280/1e1e1e/f5c518?text=${encodeURIComponent(name)}`,
                        link: url,
                        source: site.name,
                        episodes: episodes
                    });
                }

                if (allSeries.length >= 50) {
                    console.log(`🎉 تم جمع ${allSeries.length} مسلسل تركي مدبلج (كافي)`);
                    break;
                }
            } else {
                console.log(`  ⚠️ لم يتم العثور على مسلسلات تركية مدبلجة في ${site.name}`);
            }
        }
    }

    // 3. إذا كان العدد لا يزال قليلاً، حاول جلب HTML
    if (allSeries.length < 15) {
        console.log('\n🔄 محاولة جلب البيانات من HTML مباشر (احتياطي)...');
        for (const site of SITES) {
            if (allSeries.length >= 25) break;
            if (!site.mainUrl) continue;

            console.log(`📡 محاولة جلب HTML: ${site.name} (${site.mainUrl})`);
            const seriesFromHtml = await fetchSeriesFromHtml(site.mainUrl, site.selectors);

            for (const s of seriesFromHtml) {
                if (processedUrls.has(s.link)) continue;
                processedUrls.add(s.link);

                let image = s.image;
                if (!image || image === '') {
                    try { image = await fetchSeriesImage(s.link); } catch (e) {}
                }

                const existing = allSeries.find(ser => ser.name.toLowerCase().includes(s.name.toLowerCase()) || s.name.toLowerCase().includes(ser.name.toLowerCase()));
                const episodes = (existing && existing.episodes) ? existing.episodes : [
                    { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                    { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
                ];

                allSeries.push({
                    name: s.name,
                    image: image || `https://via.placeholder.com/200x280/1e1e1e/f5c518?text=${encodeURIComponent(s.name)}`,
                    link: s.link,
                    source: site.name,
                    episodes: episodes
                });
            }

            if (allSeries.length > 0) {
                console.log(`✅ تم جلب ${allSeries.length} مسلسل تركياً إجمالاً`);
            }
        }
    }

    // 4. إزالة التكرارات بناءً على الاسم
    const uniqueMap = new Map();
    allSeries.forEach(s => {
        const key = s.name.toLowerCase().trim();
        if (!uniqueMap.has(key) || s.source === 'قائمة مضمونة') {
            uniqueMap.set(key, s);
        }
    });
    allSeries = Array.from(uniqueMap.values());

    console.log(`\n✅ تم جمع ${allSeries.length} مسلسل تركي مدبلج فريد.`);
    return allSeries;
}

// ============================================================
// حفظ البيانات وتشغيل السكربت
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
