const cheerio = require('cheerio');
const fs = require('fs');

// ============================================================
// قائمة المواقع (كما هي مع بعض الإضافات)
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
// دوال مساعدة (نفسها مع تحسينات)
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
 * 🔍 فلترة الروابط: نقبل فقط الروابط التي تبدو كمسلسلات تركية مدبلجة
 */
function isTurkishDramaSeries(url, name = '') {
    const lowerUrl = url.toLowerCase();
    const lowerName = name.toLowerCase();

    // 🚫 استبعاد الأفلام بشكل قاطع
    const excludeKeywords = [
        'فيلم', 'movie', 'film', 'cinema', 'theater',
        'black adam', 'avatar', 'antman', 'john wick', 'shazam', 'scream',
        'creed', 'guardians', 'galaxy', 'spider', 'man', 'batman', 'superman',
        'wonder woman', 'aquaman', 'flash', 'green lantern', 'justice league',
        'avengers', 'thor', 'iron man', 'captain america', 'deadpool',
        'venom', 'morbius', 'uncharted', 'sonic', 'detective pikachu'
    ];
    if (excludeKeywords.some(k => lowerUrl.includes(k) || lowerName.includes(k))) {
        return false;
    }

    // ✅ كلمات تدل على مسلسل تركي مدبلج
    const includeKeywords = [
        'مسلسل', 'series', 'drama', 'episode', 'season', 'حلقات', 'موسم',
        'تركي', 'turkish', 'turkey', 'مدبلج', 'dubbed', 'عربي', 'arabic',
        'اسطنبول', 'istanbul', 'الحب', 'love', 'آخر', 'عشق', 'دمعة', 'فراق'
    ];
    // إذا احتوى الرابط أو الاسم على أي كلمة من القائمة، نعتبره مسلسل تركي
    if (includeKeywords.some(k => lowerUrl.includes(k) || lowerName.includes(k))) {
        return true;
    }

    // 🧠 فحص إضافي: إذا كان الرابط يحتوي على /episode/ أو /season/ فهو مسلسل
    if (lowerUrl.includes('/episode/') || lowerUrl.includes('/season/')) {
        return true;
    }

    // ❌ استبعاد الروابط التي تحتوي على كلمات تدل على أفلام
    return false;
}

/**
 * استخراج روابط المسلسلات من Sitemap مع فلترة قوية
 */
function extractSeriesUrlsFromSitemap(xmlText) {
    const $ = cheerio.load(xmlText, { xmlMode: true });
    const urls = new Set();

    // البحث عن جميع الروابط
    $('url > loc, sitemap > loc').each((i, el) => {
        let loc = $(el).text().trim();
        if (!loc) return;

        // نستخرج اسم المسلسل من الرابط لتقديم للفلترة
        let name = '';
        try {
            const path = new URL(loc).pathname;
            const parts = path.split('/').filter(p => p && p !== 'series' && p !== 'show' && p !== 'drama');
            if (parts.length > 0) {
                name = parts[parts.length - 1].replace(/-/g, ' ');
            }
        } catch {}

        // تطبيق الفلترة
        if (isTurkishDramaSeries(loc, name)) {
            urls.add(loc);
        }
    });

    // إحصائيات للمساعدة في التتبع
    console.log(`  📊 تم فلترة ${$('url > loc').length} رابط، بقي ${urls.size} مسلسل تركي مدبلج.`);
    return Array.from(urls);
}

/**
 * استخراج اسم المسلسل من الرابط (مع تنظيف)
 */
function extractSeriesNameFromUrl(url) {
    try {
        const path = new URL(url).pathname;
        const parts = path.split('/').filter(p => p && p !== 'series' && p !== 'show' && p !== 'drama');
        if (parts.length > 0) {
            let name = parts[parts.length - 1].replace(/-/g, ' ');
            // ترجمة بعض الكلمات الشائعة
            name = name.replace(/\bseason\b/gi, 'موسم').replace(/\bepisode\b/gi, 'حلقة');
            // إذا كان الاسم يحتوي على "فيلم" استبعده
            if (name.toLowerCase().includes('فيلم') || name.toLowerCase().includes('film')) {
                return null;
            }
            return name.charAt(0).toUpperCase() + name.slice(1);
        }
        return url;
    } catch {
        return url;
    }
}

/**
 * محاولة جلب صورة المسلسل (نفسها)
 */
async function fetchSeriesImage(seriesUrl) {
    try {
        const html = await fetchContent(seriesUrl, 1);
        if (!html) return null;
        const $ = cheerio.load(html);
        let img = $('meta[property="og:image"]').attr('content');
        if (!img) img = $('meta[name="twitter:image"]').attr('content');
        if (!img) img = $('.poster img').attr('src');
        if (!img) img = $('.series-poster img').attr('src');
        if (!img) img = $('img.cover').attr('src');
        if (!img) img = $('.series-image img').attr('src');
        if (!img) img = $('.entry-image img').attr('src');
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
            
            if (link && !link.startsWith('http')) {
                link = new URL(link, mainUrl).href;
            }

            if (name && link && isTurkishDramaSeries(link, name)) {
                seriesList.push({
                    name: name,
                    image: image || '',
                    link: link
                });
            }
        });

        return seriesList;
    } catch (error) {
        console.warn(`  ⚠️ فشل جلب HTML من ${mainUrl}: ${error.message}`);
        return [];
    }
}

// ============================================================
// الدالة الرئيسية
// ============================================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري البحث عن المسلسلات التركية المدبلجة...');
    console.log(`📋 سيتم البحث في ${SITES.length} موقع.\n`);

    let allSeries = [];
    const processedUrls = new Set();

    // المرحلة 1: Sitemap
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
                
                // نأخذ أول 50 مسلسلاً
                const limitedUrls = seriesUrls.slice(0, 50);
                let index = 0;

                for (const url of limitedUrls) {
                    if (processedUrls.has(url)) continue;
                    processedUrls.add(url);
                    index++;
                    
                    const name = extractSeriesNameFromUrl(url);
                    if (!name) continue; // استبعاد إذا كان الاسم null (يعني فيلم)
                    
                    console.log(`  🔍 (${index}/${limitedUrls.length}) جلب بيانات: ${name}`);

                    let image = null;
                    try {
                        image = await fetchSeriesImage(url);
                    } catch (e) {}

                    allSeries.push({
                        name: name,
                        image: image || `https://via.placeholder.com/200x280/1e1e1e/f5c518?text=${encodeURIComponent(name)}`,
                        link: url,
                        source: site.name,
                        episodes: [
                            { name: 'الحلقة 1 (جودة عالية)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                            { name: 'الحلقة 2 (جودة عالية)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
                        ]
                    });
                }

                if (allSeries.length >= 30) {
                    console.log(`🎉 تم جلب ${allSeries.length} مسلسل تركي مدبلج (كافي)`);
                    break;
                }
            } else {
                console.log(`  ⚠️ لم يتم العثور على مسلسلات تركية مدبلجة في ${site.name}`);
            }
        }
    }

    // المرحلة 2: HTML احتياطي
    if (allSeries.length < 10) {
        console.log('\n🔄 محاولة جلب البيانات من HTML مباشر (احتياطي)...');
        for (const site of SITES) {
            if (allSeries.length >= 20) break;
            if (!site.mainUrl) continue;
            
            console.log(`📡 محاولة جلب HTML: ${site.name} (${site.mainUrl})`);
            const seriesFromHtml = await fetchSeriesFromHtml(site.mainUrl, site.selectors);
            
            for (const s of seriesFromHtml) {
                if (processedUrls.has(s.link)) continue;
                processedUrls.add(s.link);
                
                let image = s.image;
                if (!image || image === '') {
                    try {
                        image = await fetchSeriesImage(s.link);
                    } catch (e) {}
                }
                
                allSeries.push({
                    name: s.name,
                    image: image || `https://via.placeholder.com/200x280/1e1e1e/f5c518?text=${encodeURIComponent(s.name)}`,
                    link: s.link,
                    source: site.name,
                    episodes: [
                        { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                        { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
                    ]
                });
            }
            
            if (allSeries.length > 0) {
                console.log(`✅ تم جلب ${allSeries.length} مسلسل تركياً إجمالاً`);
            }
        }
    }

    // المرحلة 3: بيانات تجريبية
    if (allSeries.length === 0) {
        console.warn('\n⚠️ جميع محاولات الجلب فشلت أو لم تجد مسلسلات تركية. سيتم استخدام بيانات تجريبية.');
        return getMockData();
    }

    console.log(`\n✅ تم جلب ${allSeries.length} مسلسل تركي مدبلج بنجاح.`);
    return allSeries;
}

// ============================================================
// البيانات التجريبية (مسلسلات تركية مدبلجة افتراضية)
// ============================================================
function getMockData() {
    return [
        {
            name: 'مسلسل تركي مدبلج 1',
            image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Turkish+Series+1',
            link: '#',
            source: 'تجريبي',
            episodes: [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ]
        },
        {
            name: 'مسلسل تركي مدبلج 2',
            image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Turkish+Series+2',
            link: '#',
            source: 'تجريبي',
            episodes: [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                { name: 'الحلقة 3', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ]
        }
    ];
}

// ============================================================
// الحفظ والتشغيل
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
