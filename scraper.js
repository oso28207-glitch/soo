const cheerio = require('cheerio');
const fs = require('fs');

// ============================================================
// قائمة المواقع المستهدفة (مرتبة حسب الأولوية)
// يحتوي كل موقع على:
//   - name: اسم الموقع
//   - sitemap: رابط ملف خريطة الموقع (إن وجد)
//   - mainUrl: الرابط الرئيسي (للاحتياط)
//   - selectors: محددات العناصر في حال احتجنا تحليل HTML مباشر
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
        sitemap: null, // قد لا يوجد
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

/**
 * جلب محتوى صفحة مع محاولة تجاوز الحظر
 */
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
            // انتظر قبل إعادة المحاولة
            await new Promise(r => setTimeout(r, 2000));
        }
    }
    return null;
}

/**
 * استخراج روابط المسلسلات من ملف Sitemap
 */
function extractSeriesUrlsFromSitemap(xmlText) {
    const $ = cheerio.load(xmlText, { xmlMode: true });
    const urls = new Set();

    // البحث عن جميع الروابط
    $('url > loc, sitemap > loc').each((i, el) => {
        let loc = $(el).text().trim();
        if (!loc) return;

        // فلترة الروابط التي تبدو كمسلسلات
        const keywords = ['/series/', '/show/', '/مسلسل/', '/drama/', '/episode/', '/season/'];
        if (keywords.some(k => loc.includes(k))) {
            // نستبعد روابط الحلقات الفردية ونأخذ روابط المسلسلات فقط
            if (!loc.includes('/episode/') && !loc.includes('/season/')) {
                urls.add(loc);
            }
        }
    });

    // إذا كانت النتيجة صفر، حاول استخراج كل الروابط التي تحوي تاريخ (بعض المواقع تضع المسلسلات في sitemap الرئيسي)
    if (urls.size === 0) {
        $('url > loc').each((i, el) => {
            let loc = $(el).text().trim();
            // أي رابط ليس صفحة رئيسية أو تصنيف، غالباً هو مسلسل
            if (loc && loc.split('/').length >= 4 && !loc.endsWith('/')) {
                urls.add(loc);
            }
        });
    }

    return Array.from(urls);
}

/**
 * استخراج اسم المسلسل من الرابط
 */
function extractSeriesNameFromUrl(url) {
    try {
        const path = new URL(url).pathname;
        const parts = path.split('/').filter(p => p && p !== 'series' && p !== 'show' && p !== 'drama');
        if (parts.length > 0) {
            let name = parts[parts.length - 1].replace(/-/g, ' ');
            // ترجمة بعض الكلمات الشائعة
            name = name.replace(/\bseason\b/gi, 'موسم').replace(/\bepisode\b/gi, 'حلقة');
            return name.charAt(0).toUpperCase() + name.slice(1);
        }
        return url;
    } catch {
        return url;
    }
}

/**
 * محاولة جلب صورة المسلسل من صفحته
 */
async function fetchSeriesImage(seriesUrl) {
    try {
        const html = await fetchContent(seriesUrl, 1);
        if (!html) return null;
        const $ = cheerio.load(html);
        // البحث عن الصورة في الـ OG tags أو في أي img رئيسي
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
 * محاولة جلب المسلسلات من HTML مباشر (احتياطي)
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

            if (name && link) {
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
// الدالة الرئيسية: جلب البيانات من جميع المصادر
// ============================================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري البحث عن المسلسلات التركية المدبلجة...');
    console.log(`📋 سيتم البحث في ${SITES.length} موقع.\n`);

    let allSeries = [];
    const processedUrls = new Set();

    // المرحلة 1: محاولة جلب من Sitemap لكل موقع
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
                console.log(`✅ تم العثور على ${seriesUrls.length} مسلسل في ${site.name}`);
                
                // نأخذ أول 50 مسلسلاً فقط لتوفير الوقت
                const limitedUrls = seriesUrls.slice(0, 50);
                let index = 0;

                for (const url of limitedUrls) {
                    // تجنب التكرار
                    if (processedUrls.has(url)) continue;
                    processedUrls.add(url);
                    index++;
                    
                    const name = extractSeriesNameFromUrl(url);
                    console.log(`  🔍 (${index}/${limitedUrls.length}) جلب بيانات: ${name}`);

                    // محاولة جلب الصورة
                    let image = null;
                    try {
                        image = await fetchSeriesImage(url);
                    } catch (e) {}

                    // إضافة المسلسل مع حلقات تجريبية
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

                // إذا وجدنا عدداً كافياً من المسلسلات، نوقف البحث
                if (allSeries.length >= 30) {
                    console.log(`🎉 تم جلب ${allSeries.length} مسلسل من ${site.name} (كافي)`);
                    break;
                }
            } else {
                console.log(`  ⚠️ لم يتم العثور على مسلسلات في ${site.name}`);
            }
        }
    }

    // المرحلة 2: إذا لم نحصل على نتائج كافية، حاول جلب HTML مباشر
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
                
                // محاولة جلب الصورة
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
                console.log(`✅ تم جلب ${allSeries.length} مسلسل إجمالاً`);
            }
        }
    }

    // المرحلة 3: إذا فشل الجميع، استخدم البيانات التجريبية
    if (allSeries.length === 0) {
        console.warn('\n⚠️ جميع محاولات الجلب فشلت. سيتم استخدام بيانات تجريبية.');
        console.warn('💡 نصيحة: قد تكون المواقع تحجب البوتات. جرب تشغيل السكربت على جهازك الشخصي.');
        console.warn('💡 أو استخدم خدمة Proxy مثل ScraperAPI لتجاوز الحظر.\n');
        return getMockData();
    }

    console.log(`\n✅ تم جلب ${allSeries.length} مسلسل بنجاح.`);
    return allSeries;
}

// ============================================================
// البيانات التجريبية (للاختبار)
// ============================================================
function getMockData() {
    return [
        {
            name: 'مسلسل تركي تجريبي 1',
            image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Series+1',
            link: '#',
            source: 'تجريبي',
            episodes: [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ]
        },
        {
            name: 'مسلسل تركي تجريبي 2',
            image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Series+2',
            link: '#',
            source: 'تجريبي',
            episodes: [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ]
        },
        {
            name: 'مسلسل تركي تجريبي 3',
            image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Series+3',
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

// تشغيل السكربت
main().catch(error => {
    console.error('❌ خطأ غير متوقع:', error.message);
    process.exit(1);
});
