const cheerio = require('cheerio');
const fs = require('fs');
const puppeteer = require('puppeteer');

// ================================================================
// 1. قائمة احتياطية موسعة (ضمان عمل الواجهة دائمًا)
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
    { name: 'الآسيوي', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=الآسيوي' },
    { name: 'مسلسل تركي مدبلج 1', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Turkish+Series+1' },
    { name: 'مسلسل تركي مدبلج 2', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Turkish+Series+2' }
];

// ================================================================
// 2. تكوين المواقع
// ================================================================
const SITE_CONFIGS = [
    // --- مواقع تقدم sitemap (سهلة الجلب) ---
    {
        name: 'LodyNet (Sitemap)',
        type: 'sitemap',
        url: 'https://lodynet.watch/sitemap.xml',
        // محددات لاستخراج روابط المسلسلات من sitemap
        seriesPattern: /\/category\/.*-مدبلج/ // نمط للبحث في الروابط
    },
    {
        name: 'Eishq (Sitemap)',
        type: 'sitemap',
        url: 'https://new.eishq.net/sitemap.xml',
        seriesPattern: /\/video\/series\/.*-de-01/ // نمط للبحث في الروابط
    },
    // --- مواقع تعتمد على JavaScript (جلب عبر Puppeteer) ---
    {
        name: 'EgyWatch (Puppeteer)',
        type: 'puppeteer',
        url: 'https://egywatch.live/page/series/',
        // محددات لاستخراج البيانات من الصفحة بعد تحميلها
        selectors: {
            item: '.series-item, .movie-item, .post-item', // العنصر الذي يحيط بكل مسلسل
            title: '.title, .series-title, h3', // محدد اسم المسلسل
            link: 'a', // محدد الرابط
            image: 'img' // محدد الصورة
        }
    },
    // --- مواقع قديمة كمصدر احتياطي ---
    {
        name: 'LodyNet (HTML)',
        type: 'html',
        url: 'https://lodynet.watch/dubbed-turkish-series-g/',
        selectors: {
            item: 'li, .ItemNewly',
            title: 'a, .NewlyTitle',
            link: 'a',
            image: '.NewlyCover'
        }
    }
];

// ================================================================
// 3. دوال مساعدة أساسية
// ================================================================

/** جلب محتوى صفحة مع إعادة محاولة (للمواقع العادية) */
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

/** جلب محتوى صفحة باستخدام Puppeteer (للمواقع الديناميكية) */
async function fetchWithPuppeteer(url, waitForSelector = '.series-item, .movie-item, .post-item') {
    let browser;
    try {
        browser = await puppeteer.launch({
            headless: 'new',
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });
        const page = await browser.newPage();
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36');
        await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
        // انتظار ظهور العناصر
        await page.waitForSelector(waitForSelector, { timeout: 10000 });
        const html = await page.content();
        return html;
    } catch (e) {
        console.warn(`  ⚠️ فشل Puppeteer: ${e.message}`);
        return null;
    } finally {
        if (browser) await browser.close();
    }
}

/** استخراج روابط المسلسلات من Sitemap */
function extractSeriesFromSitemap(xmlText, pattern) {
    const $ = cheerio.load(xmlText, { xmlMode: true });
    const results = [];
    $('url > loc').each((i, el) => {
        const loc = $(el).text().trim();
        if (pattern.test(loc)) {
            // استخراج اسم المسلسل من الرابط
            let name = loc.split('/').pop().replace(/-/g, ' ');
            try { name = decodeURIComponent(name); } catch (e) {}
            results.push({
                name: name,
                link: loc,
                image: null // سيتم محاولة جلب الصورة لاحقاً
            });
        }
    });
    return results;
}

/** استخراج المسلسلات من HTML عادي */
function extractSeriesFromHTML(html, selectors) {
    const $ = cheerio.load(html);
    const results = [];
    const { item, title, link, image } = selectors;

    $(item).each((i, el) => {
        const $el = $(el);
        const name = $el.find(title).text().trim();
        const href = $el.find(link).attr('href');
        let img = $el.find(image).attr('src');
        // محاولة استخراج الصورة من style background-image
        if (!img) {
            const style = $el.find(image).attr('style') || '';
            const match = style.match(/url\(["']?([^"')]+)["']?\)/);
            if (match) img = match[1];
        }
        if (name && href) {
            results.push({
                name: name,
                link: href.startsWith('http') ? href : new URL(href, url).href,
                image: img || null
            });
        }
    });
    return results;
}

/** محاولة جلب صورة المسلسل من صفحته */
async function fetchSeriesImage(seriesUrl) {
    const html = await fetchPage(seriesUrl, 1);
    if (!html) return null;
    const $ = cheerio.load(html);
    let img = $('meta[property="og:image"]').attr('content');
    if (!img) img = $('meta[name="twitter:image"]').attr('content');
    if (!img) img = $('.poster img').attr('src');
    if (!img) img = $('.series-poster img').attr('src');
    if (!img) img = $('img.cover').attr('src');
    if (img && !img.startsWith('http')) {
        img = new URL(img, seriesUrl).href;
    }
    return img || null;
}

/** جلب الحلقات من صفحة المسلسل */
async function fetchEpisodes(seriesUrl) {
    const html = await fetchPage(seriesUrl, 2);
    if (!html) return null;
    const $ = cheerio.load(html);
    const episodes = [];

    // البحث عن روابط الحلقات
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
// 4. الدالة الرئيسية لجلب البيانات من جميع المصادر
// ================================================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري جلب المسلسلات التركية المدبلجة...\n');
    let allSeries = [];
    const processedLinks = new Set();

    // المرحلة 1: جلب من Sitemap
    for (const config of SITE_CONFIGS.filter(c => c.type === 'sitemap')) {
        console.log(`📡 جلب Sitemap: ${config.name} (${config.url})`);
        const xml = await fetchPage(config.url);
        if (!xml) {
            console.log(`  ❌ فشل جلب Sitemap.`);
            continue;
        }
        const seriesList = extractSeriesFromSitemap(xml, config.seriesPattern);
        console.log(`  ✅ تم العثور على ${seriesList.length} مسلسل.`);

        for (const item of seriesList) {
            if (processedLinks.has(item.link)) continue;
            processedLinks.add(item.link);

            // محاولة جلب الصورة والحلقات
            let image = item.image;
            if (!image) {
                try { image = await fetchSeriesImage(item.link); } catch (e) {}
            }
            let episodes = null;
            try { episodes = await fetchEpisodes(item.link); } catch (e) {}

            allSeries.push({
                name: item.name,
                image: image || fallbackImage(item.name),
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

    // المرحلة 2: جلب من المواقع الديناميكية (Puppeteer)
    if (allSeries.length < 50) {
        for (const config of SITE_CONFIGS.filter(c => c.type === 'puppeteer')) {
            console.log(`📡 جلب عبر Puppeteer: ${config.name} (${config.url})`);
            const html = await fetchWithPuppeteer(config.url);
            if (!html) {
                console.log(`  ❌ فشل جلب الصفحة.`);
                continue;
            }
            const seriesList = extractSeriesFromHTML(html, config.selectors);
            console.log(`  ✅ تم العثور على ${seriesList.length} مسلسل.`);

            for (const item of seriesList) {
                if (processedLinks.has(item.link)) continue;
                processedLinks.add(item.link);

                let image = item.image;
                if (!image) {
                    try { image = await fetchSeriesImage(item.link); } catch (e) {}
                }
                let episodes = null;
                try { episodes = await fetchEpisodes(item.link); } catch (e) {}

                allSeries.push({
                    name: item.name,
                    image: image || fallbackImage(item.name),
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
    }

    // المرحلة 3: جلب من HTML عادي (احتياطي)
    if (allSeries.length < 30) {
        for (const config of SITE_CONFIGS.filter(c => c.type === 'html')) {
            console.log(`📡 جلب HTML: ${config.name} (${config.url})`);
            const html = await fetchPage(config.url);
            if (!html) {
                console.log(`  ❌ فشل جلب الصفحة.`);
                continue;
            }
            const seriesList = extractSeriesFromHTML(html, config.selectors);
            console.log(`  ✅ تم العثور على ${seriesList.length} مسلسل.`);

            for (const item of seriesList) {
                if (processedLinks.has(item.link)) continue;
                processedLinks.add(item.link);

                let image = item.image;
                if (!image) {
                    try { image = await fetchSeriesImage(item.link); } catch (e) {}
                }
                let episodes = null;
                try { episodes = await fetchEpisodes(item.link); } catch (e) {}

                allSeries.push({
                    name: item.name,
                    image: image || fallbackImage(item.name),
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
    }

    // المرحلة 4: إذا لم يتم جلب أي بيانات، استخدم القائمة الاحتياطية
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
