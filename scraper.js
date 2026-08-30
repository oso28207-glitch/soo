const cheerio = require('cheerio');
const fs = require('fs');

// ================================================================
// قائمة احتياطية من المسلسلات التركية المدبلجة (مضمونة)
// ================================================================
const FALLBACK_SERIES = [
    { name: 'قيامة عثمان', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=قيامة+عثمان' },
    { name: 'السلطان عبد الحميد', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=السلطان+عبد+الحميد' },
    { name: 'حكاية حب', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=حكاية+حب' },
    { name: 'العشق الممنوع', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=العشق+الممنوع' },
    { name: 'وادي الذئاب', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=وادي+الذئاب' },
    { name: 'حب للايجار', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=حب+للايجار' },
    { name: 'ندى العمر', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=ندى+العمر' },
    { name: 'الوردة السوداء', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=الوردة+السوداء' },
    { name: 'عودة مهند', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=عودة+مهند' },
    { name: 'الآسيوي', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=الآسيوي' }
];

// ================================================================
// تكوين المواقع مع محددات دقيقة
// ================================================================
const SITE_CONFIGS = [
    {
        name: 'LodyNet',
        listUrl: 'https://lodynet.watch/category/%d9%85%d8%b4%d8%a7%d9%87%d8%af%d8%a9-%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%aa%d8%b1%d9%83%d9%8a%d8%a9-%d9%85%d8%af%d8%a8%d9%84%d8%ac%d8%a9/',
        // محددات استخراج المسلسلات من صفحة التصنيف
        itemSelector: '.ItemNewly',
        titleSelector: '.NewlyTitle',
        linkSelector: 'a',
        imageSelector: '.NewlyCover',
        // صورة الخلفية من style أو data-src
        imageExtractor: ($el) => {
            const style = $el.attr('style') || '';
            const match = style.match(/url\(["']?([^"')]+)["']?\)/);
            if (match) return match[1];
            const dataSrc = $el.attr('data-src');
            if (dataSrc) return dataSrc;
            return null;
        }
    },
    {
        name: 'Eishq (قصة عشق)',
        listUrl: 'https://new.eishq.net/video/category/%D9%85%D8%B3%D9%84%D8%B3%D9%84%D8%A7%D8%AA-%D8%AA%D8%B1%D9%83%D9%8A%D8%A9-%D9%85%D8%AF%D8%A8%D9%84%D8%AC%D8%A9/',
        itemSelector: 'article.post',
        titleSelector: '.title',
        linkSelector: 'a',
        imageSelector: '.imgBg',
        imageExtractor: ($el) => {
            const style = $el.attr('style') || '';
            const match = style.match(/url\(["']?([^"')]+)["']?\)/);
            if (match) return match[1];
            return null;
        }
    }
];

// ================================================================
// دوال مساعدة أساسية
// ================================================================

/** جلب محتوى صفحة مع إعادة محاولة */
async function fetchPage(url, retries = 3) {
    for (let i = 0; i < retries; i++) {
        try {
            const res = await fetch(url, {
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'ar,en;q=0.9',
                },
                redirect: 'follow'
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return await res.text();
        } catch (e) {
            console.warn(`  ⚠️ محاولة ${i+1} فشلت: ${e.message}`);
            if (i === retries - 1) return null;
            await new Promise(r => setTimeout(r, 2000 * (i + 1)));
        }
    }
    return null;
}

/** استخراج النص من عنصر مع إزالة المسافات الزائدة */
function cleanText(text) {
    return text ? text.replace(/\s+/g, ' ').trim() : '';
}

/** تحويل الرابط النسبي إلى مطلق */
function toAbsoluteUrl(relative, base) {
    try {
        return new URL(relative, base).href;
    } catch {
        return relative;
    }
}

/** استخراج قائمة المسلسلات من صفحة التصنيف باستخدام المحددات */
function extractSeriesFromList(html, config) {
    const $ = cheerio.load(html);
    const results = [];
    const { itemSelector, titleSelector, linkSelector, imageSelector, imageExtractor } = config;

    $(itemSelector).each((i, el) => {
        const $el = $(el);
        const title = cleanText($el.find(titleSelector).text());
        const link = $el.find(linkSelector).attr('href');
        const imageEl = $el.find(imageSelector);
        let image = imageExtractor ? imageExtractor(imageEl) : null;
        // إذا كانت الصورة نسبية، حوّلها إلى مطلقة
        if (image && !image.startsWith('http')) {
            image = toAbsoluteUrl(image, config.listUrl);
        }
        if (title && link) {
            results.push({
                name: title,
                link: toAbsoluteUrl(link, config.listUrl),
                image: image || null
            });
        }
    });

    return results;
}

/** جلب الحلقات من صفحة المسلسل (محاولات متعددة) */
async function fetchEpisodes(seriesUrl) {
    const html = await fetchPage(seriesUrl, 2);
    if (!html) return null;

    const $ = cheerio.load(html);
    let episodes = [];

    // المحاولة 1: البحث عن روابط تحتوي على 'episode' أو 'watch' أو '.mp4'
    $('a[href*="episode"], a[href*="watch"], a[href*=".mp4"]').each((i, el) => {
        let href = $(el).attr('href');
        if (!href) return;
        let name = cleanText($(el).text()) || `الحلقة ${i+1}`;
        href = toAbsoluteUrl(href, seriesUrl);
        // نتجنب الروابط المكررة
        if (!episodes.some(e => e.url === href)) {
            episodes.push({ name, url: href });
        }
    });

    // المحاولة 2: البحث داخل عناصر الحلقات النموذجية
    if (episodes.length === 0) {
        $('.episode-item a, .episode-link a, .episodes-list a, .season-episodes a').each((i, el) => {
            let href = $(el).attr('href');
            if (!href) return;
            let name = cleanText($(el).text()) || `الحلقة ${i+1}`;
            href = toAbsoluteUrl(href, seriesUrl);
            if (!episodes.some(e => e.url === href)) {
                episodes.push({ name, url: href });
            }
        });
    }

    // المحاولة 3: البحث عن أي رابط داخل .post-content أو .entry-content
    if (episodes.length === 0) {
        $('.post-content a, .entry-content a, .content a').each((i, el) => {
            let href = $(el).attr('href');
            if (!href) return;
            // نتجنب الروابط التي تبدو للصفحات الرئيسية أو التصنيفات
            if (href.includes('/category/') || href.includes('/tag/') || href === '#') return;
            let name = cleanText($(el).text()) || `الحلقة ${i+1}`;
            href = toAbsoluteUrl(href, seriesUrl);
            if (!episodes.some(e => e.url === href)) {
                episodes.push({ name, url: href });
            }
        });
    }

    // إذا وجدنا أكثر من 50 حلقة، نأخذ أول 50
    if (episodes.length > 50) episodes = episodes.slice(0, 50);

    return episodes.length > 0 ? episodes : null;
}

/** إنشاء صورة احتياطية */
function fallbackImage(name) {
    return `https://via.placeholder.com/200x280/1e1e1e/f5c518?text=${encodeURIComponent(name)}`;
}

// ================================================================
// الدالة الرئيسية لجلب البيانات
// ================================================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري جلب المسلسلات التركية المدبلجة...\n');

    let allSeries = [];
    const processedLinks = new Set();

    // المرحلة 1: جلب من المواقع المحددة
    for (const config of SITE_CONFIGS) {
        console.log(`📡 جلب من: ${config.name} (${config.listUrl})`);
        const html = await fetchPage(config.listUrl);
        if (!html) {
            console.log(`  ❌ فشل جلب الصفحة.`);
            continue;
        }

        const seriesList = extractSeriesFromList(html, config);
        console.log(`  ✅ تم العثور على ${seriesList.length} مسلسل.`);

        let count = 0;
        for (const item of seriesList) {
            // تجنب التكرار
            if (processedLinks.has(item.link)) continue;
            processedLinks.add(item.link);
            count++;

            console.log(`  🔍 (${count}/${seriesList.length}) جلب: ${item.name}`);

            // محاولة جلب الحلقات
            let episodes = null;
            try {
                episodes = await fetchEpisodes(item.link);
            } catch (e) {
                console.warn(`    ⚠️ فشل جلب الحلقات: ${e.message}`);
            }

            // إذا لم نجد حلقات، نستخدم حلقات تجريبية
            if (!episodes) {
                episodes = [
                    { name: 'الحلقة 1 (تجريبي)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                    { name: 'الحلقة 2 (تجريبي)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
                ];
                console.log(`    ⚠️ استخدام حلقات تجريبية.`);
            } else {
                console.log(`    ✅ جلب ${episodes.length} حلقة.`);
            }

            // الصورة: إذا لم تكن موجودة، استخدم الاحتياطية
            const image = item.image || fallbackImage(item.name);

            allSeries.push({
                name: item.name,
                image: image,
                link: item.link,
                source: config.name,
                episodes: episodes
            });
        }

        // إذا جمعنا عدداً كافياً، نتوقف (50 مسلسلاً كافٍ)
        if (allSeries.length >= 50) {
            console.log(`\n🎉 تم جمع ${allSeries.length} مسلسل، كافٍ.`);
            break;
        }
    }

    // المرحلة 2: إذا لم نحصل على أي بيانات، استخدم القائمة الاحتياطية
    if (allSeries.length === 0) {
        console.warn('\n⚠️ لم يتم جلب أي بيانات من المواقع. استخدم القائمة الاحتياطية.');
        return FALLBACK_SERIES.map(s => ({
            ...s,
            link: '#',
            source: 'احتياطي',
            episodes: [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ]
        }));
    }

    // إزالة التكرارات حسب الاسم
    const unique = new Map();
    allSeries.forEach(s => {
        const key = s.name.trim().toLowerCase();
        if (!unique.has(key)) {
            unique.set(key, s);
        }
    });

    const final = Array.from(unique.values());
    console.log(`\n✅ تم جمع ${final.length} مسلسل فريد.`);
    return final;
}

// ================================================================
// التشغيل والحفظ
// ================================================================
async function main() {
    const series = await fetchTurkishSeries();
    fs.writeFileSync('data.json', JSON.stringify(series, null, 2));
    console.log(`💾 تم حفظ ${series.length} مسلسل في data.json`);
}

main().catch(err => {
    console.error('❌ خطأ فادح:', err.message);
    process.exit(1);
});
