const cheerio = require('cheerio');
const fs = require('fs');

// ================================================================
// 1. قائمة احتياطية (في حال فشل كل شيء)
// ================================================================
const FALLBACK_SERIES = [
    { name: 'قيامة عثمان', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=قيامة+عثمان' },
    { name: 'السلطان عبد الحميد', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=السلطان+عبد+الحميد' },
    { name: 'حكاية حب', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=حكاية+حب' },
    // ... يمكنك إضافة المزيد هنا
];

// ================================================================
// 2. تكوين المواقع (تم تحديث المحددات)
// ================================================================
const SITE_CONFIGS = [
    // --- لودي نت: جلب البيانات من صفحة التصنيف مباشرة ---
    {
        name: 'LodyNet (HTML)',
        type: 'html',
        url: 'https://lodynet.watch/dubbed-turkish-series-g/',
        selectors: {
            // المحددات الخاصة بصفحة لودي نت
            item: '.ItemNewly', // العنصر الذي يحتوي على كل مسلسل
            title: '.NewlyTitle', // مكان اسم المسلسل
            link: 'a', // مكان الرابط
            image: '.NewlyCover' // مكان الصورة (سيتم استخراجها من الخلفية)
        }
    },
    // --- قصة عشق: جلب البيانات من صفحة التصنيف مباشرة ---
    {
        name: 'Eishq (HTML)',
        type: 'html',
        url: 'https://new.eishq.net/video/category/%D9%85%D8%B3%D9%84%D8%B3%D9%84%D8%A7%D8%AA-%D8%AA%D8%B1%D9%83%D9%8A%D8%A9-%D9%85%D8%AF%D8%A8%D9%84%D8%AC%D8%A9/',
        selectors: {
            item: 'article.post', // العنصر الذي يحتوي على كل مسلسل
            title: '.title', // مكان اسم المسلسل
            link: 'a', // مكان الرابط
            image: '.imgBg' // مكان الصورة (سيتم استخراجها من الخلفية)
        }
    },
    // --- ماي سيما: مصدر إضافي ---
    {
        name: 'MyCima (HTML)',
        type: 'html',
        url: 'https://mycima.net/category/%D9%85%D8%B3%D9%84%D8%B3%D9%84%D8%A7%D8%AA-%D8%AA%D8%B1%D9%83%D9%8A%D8%A9/',
        selectors: {
            item: '.movie-item, .post-item',
            title: '.title, h3',
            link: 'a',
            image: 'img'
        }
    }
];

// ================================================================
// 3. دوال مساعدة أساسية (مع التصحيحات)
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

/** استخراج المسلسلات من HTML (تم إصلاح خطأ 'url') */
function extractSeriesFromHTML(html, config) {
    const $ = cheerio.load(html);
    const results = [];
    const { item, title, link, image } = config.selectors;

    $(item).each((i, el) => {
        const $el = $(el);
        const name = $el.find(title).text().trim();
        const href = $el.find(link).attr('href');
        
        // محاولة استخراج الصورة
        let img = $el.find(image).attr('src');
        if (!img) {
            // محاولة استخراج الصورة من خاصية style (مثل background-image)
            const style = $el.find(image).attr('style') || '';
            const match = style.match(/url\(["']?([^"')]+)["']?\)/);
            if (match) img = match[1];
        }

        if (name && href) {
            // **الإصلاح**: استخدام `config.url` لتحويل الرابط النسبي إلى مطلق
            const absoluteUrl = href.startsWith('http') ? href : new URL(href, config.url).href;
            results.push({
                name: name,
                link: absoluteUrl,
                image: img || null
            });
        }
    });
    return results;
}

/** جلب الحلقات من صفحة المسلسل */
async function fetchEpisodes(seriesUrl) {
    const html = await fetchPage(seriesUrl, 2);
    if (!html) return null;
    const $ = cheerio.load(html);
    const episodes = [];

    $('a[href*="episode"], a[href*="watch"], a[href*=".mp4"]').each((i, el) => {
        let href = $(el).attr('href');
        if (!href) return;
        let name = $(el).text().trim() || `الحلقة ${i+1}`;
        href = href.startsWith('http') ? href : new URL(href, seriesUrl).href;
        if (!episodes.some(e => e.url === href)) {
            episodes.push({ name, url: href });
        }
    });

    return episodes.length > 0 ? episodes.slice(0, 50) : null;
}

/** إنشاء صورة احتياطية */
function fallbackImage(name) {
    return `https://via.placeholder.com/200x280/1e1e1e/f5c518?text=${encodeURIComponent(name)}`;
}

// ================================================================
// 4. الدالة الرئيسية (تم تعديلها لاستخدام المصادر الجديدة)
// ================================================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري جلب المسلسلات التركية المدبلجة...\n');
    let allSeries = [];
    const processedLinks = new Set();

    // جلب من جميع المواقع (HTML)
    for (const config of SITE_CONFIGS) {
        if (config.type !== 'html') continue;
        console.log(`📡 جلب HTML: ${config.name} (${config.url})`);
        const html = await fetchPage(config.url);
        if (!html) {
            console.log(`  ❌ فشل جلب الصفحة.`);
            continue;
        }
        const seriesList = extractSeriesFromHTML(html, config);
        console.log(`  ✅ تم العثور على ${seriesList.length} مسلسل.`);

        for (const item of seriesList) {
            if (processedLinks.has(item.link)) continue;
            processedLinks.add(item.link);

            // محاولة جلب الحلقات (قد تكون بطيئة، يمكن تعطيلها مؤقتاً)
            let episodes = null;
            try { episodes = await fetchEpisodes(item.link); } catch (e) {}

            allSeries.push({
                name: item.name,
                image: item.image || fallbackImage(item.name),
                link: item.link,
                source: config.name,
                episodes: episodes || [
                    { name: 'الحلقة 1 (تجريبي)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                    { name: 'الحلقة 2 (تجريبي)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
                ]
            });
        }
        if (allSeries.length >= 100) break;
    }

    // إذا لم يتم جلب أي بيانات، استخدم القائمة الاحتياطية
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
// 5. التشغيل والحفظ
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
