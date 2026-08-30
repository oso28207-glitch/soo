const cheerio = require('cheerio');
const fs = require('fs');

// ================================================================
// 1. قائمة احتياطية (في حال فشل كل شيء)
// ================================================================
const FALLBACK_SERIES = [
    { name: 'قيامة عثمان', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=قيامة+عثمان' },
    { name: 'السلطان عبد الحميد', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=السلطان+عبد+الحميد' },
    { name: 'حكاية حب', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=حكاية+حب' },
    { name: 'العشق الممنوع', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=العشق+الممنوع' },
    { name: 'وادي الذئاب', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=وادي+الذئاب' },
    { name: 'حب للايجار', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=حب+للايجار' },
    { name: 'زهرة القصر', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=زهرة+القصر' },
    { name: 'أميرة اسطنبول', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=أميرة+اسطنبول' },
    { name: 'ابن الحلال', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=ابن+الحلال' },
    { name: 'الآسيوي', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=الآسيوي' }
];

// ================================================================
// 2. تكوين المواقع (محددات دقيقة)
// ================================================================
const SITE_CONFIGS = [
    {
        name: 'LodyNet (HTML)',
        type: 'html',
        url: 'https://lodynet.watch/dubbed-turkish-series-g/',
        selectors: {
            // كل مسلسل داخل div.ItemNewly
            item: '.ItemNewly',
            // اسم المسلسل داخل div.NewlyTitle
            title: '.NewlyTitle',
            // الرابط داخل a
            link: 'a',
            // الصورة داخل .NewlyCover
            image: '.NewlyCover'
        },
        // فلترة إضافية: فقط العناصر التي تحتوي على كلمة "مسلسل"
        filter: (name) => {
            return name && name.includes('مسلسل') && !name.includes('⌵') && !name.includes('مدبلجة');
        }
    },
    {
        name: 'Eishq (HTML)',
        type: 'html',
        url: 'https://new.eishq.net/video/category/%D9%85%D8%B3%D9%84%D8%B3%D9%84%D8%A7%D8%AA-%D8%AA%D8%B1%D9%83%D9%8A%D8%A9-%D9%85%D8%AF%D8%A8%D9%84%D8%AC%D8%A9/',
        selectors: {
            item: 'article.post',
            title: '.title',
            link: 'a',
            image: '.imgBg'
        },
        filter: (name) => {
            return name && name.includes('مسلسل') && name.includes('مدبلج');
        }
    }
];

// ================================================================
// 3. دوال مساعدة
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

/** استخراج المسلسلات من HTML مع فلترة */
function extractSeriesFromHTML(html, config) {
    const $ = cheerio.load(html);
    const results = [];
    const { item, title, link, image } = config.selectors;
    const filter = config.filter || (() => true);

    $(item).each((i, el) => {
        const $el = $(el);
        const name = $el.find(title).text().trim();
        const href = $el.find(link).attr('href');
        
        // تطبيق الفلترة
        if (!filter(name)) return;

        // استخراج الصورة
        let img = null;
        const imgEl = $el.find(image);
        if (imgEl) {
            img = imgEl.attr('src');
            if (!img) {
                const style = imgEl.attr('style') || '';
                const match = style.match(/url\(["']?([^"')]+)["']?\)/);
                if (match) img = match[1];
            }
            if (!img) {
                img = imgEl.attr('data-src');
            }
        }

        if (name && href) {
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

    // البحث عن روابط الحلقات
    const episodeSelectors = [
        'a[href*="episode"]',
        'a[href*="watch"]',
        'a[href*=".mp4"]',
        '.episode-item a',
        '.episode-link a',
        '.episodes-list a',
        '.season-episodes a'
    ];

    $(episodeSelectors.join(', ')).each((i, el) => {
        let href = $(el).attr('href');
        if (!href) return;
        let name = $(el).text().trim() || `الحلقة ${i+1}`;
        href = href.startsWith('http') ? href : new URL(href, seriesUrl).href;
        // تجاهل الروابط التي تحتوي على category أو tag
        if (href.includes('/category/') || href.includes('/tag/')) return;
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
// 4. الدالة الرئيسية
// ================================================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري جلب المسلسلات التركية المدبلجة...\n');
    let allSeries = [];
    const processedLinks = new Set();

    for (const config of SITE_CONFIGS) {
        console.log(`📡 جلب HTML: ${config.name} (${config.url})`);
        const html = await fetchPage(config.url);
        if (!html) {
            console.log(`  ❌ فشل جلب الصفحة.`);
            continue;
        }
        const seriesList = extractSeriesFromHTML(html, config);
        console.log(`  ✅ تم العثور على ${seriesList.length} مسلسل بعد الفلترة.`);

        let count = 0;
        for (const item of seriesList) {
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
