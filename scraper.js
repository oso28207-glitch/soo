const cheerio = require('cheerio');
const fs = require('fs');

// قائمة المواقع المستهدفة (نضيف sitemap.xml)
const SITEMAP_SOURCES = [
    { name: 'قصة عشق', url: 'https://3isk.com/sitemap.xml' },
    { name: 'لودي نت', url: 'https://lody.net/sitemap.xml' },
    { name: 'إيجي واتش', url: 'https://egy.watch/sitemap.xml' }
];

// دالة مساعدة لجلب المحتوى مع محاولة تجاوز الحظر
async function fetchContent(url) {
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
        console.warn(`  ⚠️ فشل جلب ${url}: ${error.message}`);
        return null;
    }
}

// استخراج روابط المسلسلات من ملف Sitemap
function extractSeriesUrlsFromSitemap(xmlText) {
    const $ = cheerio.load(xmlText, { xmlMode: true });
    const urls = new Set();

    // البحث عن جميع الروابط التي تشبه مسلسل
    $('url > loc, sitemap > loc').each((i, el) => {
        let loc = $(el).text().trim();
        if (!loc) return;

        // فلترة الروابط (غالباً تحتوي على /series/ أو /show/ أو /مسلسل/)
        if (loc.includes('/series/') || loc.includes('/show/') || 
            loc.includes('/مسلسل/') || loc.includes('/episode/')) {
            // نستبعد روابط الحلقات الفردية ونأخذ روابط المسلسلات فقط (التي لا تحتوي على episode)
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

// استخراج اسم المسلسل من الرابط
function extractSeriesNameFromUrl(url) {
    try {
        const path = new URL(url).pathname;
        const parts = path.split('/').filter(p => p && p !== 'series' && p !== 'show');
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

// محاولة جلب صورة المسلسل (من صفحته)
async function fetchSeriesImage(seriesUrl) {
    try {
        const html = await fetchContent(seriesUrl);
        if (!html) return null;
        const $ = cheerio.load(html);
        // البحث عن الصورة في الـ OG tags أو في أي img رئيسي
        let img = $('meta[property="og:image"]').attr('content');
        if (!img) img = $('meta[name="twitter:image"]').attr('content');
        if (!img) img = $('.poster img').attr('src');
        if (!img) img = $('.series-poster img').attr('src');
        if (!img) img = $('img.cover').attr('src');
        if (img && !img.startsWith('http')) {
            img = new URL(img, seriesUrl).href;
        }
        return img || null;
    } catch {
        return null;
    }
}

// ======================================================
// الدالة الرئيسية: جلب البيانات من جميع المصادر
// ======================================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري البحث عن المسلسلات التركية المدبلجة...');

    let allSeries = [];

    // المرحلة 1: محاولة جلب بيانات المسلسلات من Sitemap
    for (const source of SITEMAP_SOURCES) {
        console.log(`📡 محاولة جلب خريطة الموقع: ${source.name} (${source.url})`);
        const xmlContent = await fetchContent(source.url);

        if (xmlContent) {
            const seriesUrls = extractSeriesUrlsFromSitemap(xmlContent);
            if (seriesUrls.length > 0) {
                console.log(`✅ تم العثور على ${seriesUrls.length} مسلسل في ${source.name}`);
                
                // نأخذ أول 30 مسلسلاً فقط لتوفير الوقت (يمكنك زيادة الرقم)
                const limitedUrls = seriesUrls.slice(0, 30);
                let index = 0;

                for (const url of limitedUrls) {
                    index++;
                    const name = extractSeriesNameFromUrl(url);
                    console.log(`  🔍 (${index}/${limitedUrls.length}) جلب بيانات: ${name}`);

                    // محاولة جلب الصورة (اختياري، قد يبطئ)
                    let image = null;
                    try {
                        image = await fetchSeriesImage(url);
                    } catch (e) {}

                    // نضيف المسلسل مع حلقات وهمية (يمكن تعديلها لاحقاً)
                    allSeries.push({
                        name: name,
                        image: image || `https://via.placeholder.com/200x280/1e1e1e/f5c518?text=${encodeURIComponent(name)}`,
                        link: url,
                        episodes: [
                            // نضع حلقتين مثاليتين لتجربة الواجهة
                            { name: 'الحلقة 1 (جودة عالية)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                            { name: 'الحلقة 2 (جودة عالية)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
                        ]
                    });
                }

                // إذا وجدنا بيانات، نوقف البحث ونخرج
                if (allSeries.length > 0) {
                    console.log(`🎉 تم جلب ${allSeries.length} مسلسل من ${source.name}`);
                    return allSeries;
                }
            } else {
                console.log(`  ⚠️ لم يتم العثور على مسلسلات في ${source.name}`);
            }
        }
    }

    // ======================================================
    // المرحلة 2: إذا فشلت جميع محاولات الـ Sitemap، نستخدم البيانات التجريبية
    // ======================================================
    console.warn('⚠️ جميع محاولات جلب الـ Sitemap فشلت. سيتم استخدام بيانات تجريبية.');
    console.warn('💡 نصيحة: قم بتشغيل هذا السكربت على جهازك الشخصي حيث لن يكون الحظر شديداً.');
    console.warn('💡 أو استخدم خدمة ScraperAPI (المفتاح المجاني محدود) لتجاوز الحظر.');
    
    return getMockData();
}

// ======================================================
// البيانات التجريبية (للاختبار)
// ======================================================
function getMockData() {
    return [
        {
            name: 'مسلسل تركي تجريبي 1',
            image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Series+1',
            link: '#',
            episodes: [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ]
        },
        {
            name: 'مسلسل تركي تجريبي 2',
            image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Series+2',
            link: '#',
            episodes: [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ]
        }
    ];
}

// ======================================================
// الحفظ
// ======================================================
async function main() {
    const series = await fetchTurkishSeries();
    fs.writeFileSync('data.json', JSON.stringify(series, null, 2));
    console.log(`💾 تم حفظ ${series.length} مسلسل في data.json`);
}

main();
