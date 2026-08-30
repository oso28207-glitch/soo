const cheerio = require('cheerio');
const fs = require('fs');

// ================================================================
// قائمة احتياطية
// ================================================================
const FALLBACK_SERIES = [
    { name: 'قيامة عثمان', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=قيامة+عثمان' },
    { name: 'السلطان عبد الحميد', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=السلطان+عبد+الحميد' },
    { name: 'حكاية حب', image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=حكاية+حب' }
];

// ================================================================
// تكوين المواقع
// ================================================================
const SITE_CONFIGS = [
    {
        name: 'LodyNet',
        listUrl: 'https://lodynet.watch/category/%d9%85%d8%b4%d8%a7%d9%87%d8%af%d8%a9-%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%aa%d8%b1%d9%83%d9%8a%d8%a9-%d9%85%d8%af%d8%a8%d9%84%d8%ac%d8%a9/',
        selectors: {
            item: '.ItemNewly',
            title: '.NewlyTitle',
            link: 'a',
            image: '.NewlyCover'
        }
    },
    {
        name: 'Eishq',
        listUrl: 'https://new.eishq.net/video/category/%D9%85%D8%B3%D9%84%D8%B3%D9%84%D8%A7%D8%AA-%D8%AA%D8%B1%D9%83%D9%8A%D8%A9-%D9%85%D8%AF%D8%A8%D9%84%D8%AC%D8%A9/',
        selectors: {
            item: 'article.post',
            title: '.title',
            link: 'a',
            image: '.imgBg'
        }
    }
];

// ================================================================
// دوال مساعدة
// ================================================================

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

function extractImage($el) {
    const style = $el.attr('style') || '';
    const match = style.match(/url\(["']?([^"')]+)["']?\)/);
    if (match) {
        let url = match[1];
        if (url.startsWith('//')) url = 'https:' + url;
        return url;
    }
    const dataSrc = $el.attr('data-src');
    if (dataSrc) return dataSrc;
    const src = $el.attr('src');
    if (src) return src;
    return null;
}

function extractSeriesList(html, config) {
    const $ = cheerio.load(html);
    const results = [];
    const { item, title, link, image } = config.selectors;

    $(item).each((i, el) => {
        const $el = $(el);
        const name = $el.find(title).text().trim();
        const href = $el.find(link).attr('href');
        const imgEl = $el.find(image);
        let img = extractImage(imgEl);
        if (!img) {
            img = `https://via.placeholder.com/200x280/1e1e1e/f5c518?text=${encodeURIComponent(name)}`;
        }
        if (name && href) {
            const absoluteUrl = href.startsWith('http') ? href : new URL(href, config.listUrl).href;
            results.push({ name, link: absoluteUrl, image: img });
        }
    });
    return results;
}

/**
 * استخراج الحلقات من بيانات TheRequesterData
 * مع تحويل روابط التصنيفات إلى روابط حلقات فعلية
 */
async function fetchEpisodes(seriesUrl) {
    const html = await fetchPage(seriesUrl, 2);
    if (!html) return null;

    const $ = cheerio.load(html);
    let episodes = [];
    const seenUrls = new Set();

    // ===== الطريقة الأولى: استخدام TheRequesterData =====
    try {
        const scripts = $('script').toArray();
        for (const script of scripts) {
            const content = $(script).html() || '';
            if (content.includes('TheRequesterData')) {
                const match = content.match(/TheRequesterData\s*=\s*({[^;]+});/);
                if (match) {
                    const data = JSON.parse(match[1]);
                    if (data && data.Items && Array.isArray(data.Items)) {
                        for (const item of data.Items) {
                            // نتأكد أن العنصر يحتوي على episode أو count أو ribbon
                            const isEpisode = item.episode !== undefined || 
                                             item.count !== undefined || 
                                             (item.ribbon && item.ribbon.includes('حلقة')) ||
                                             (item.name && item.name.includes('الحلقة'));
                            
                            if (isEpisode && item.url) {
                                // تحويل الرابط إلى رابط مطلق
                                const href = item.url.startsWith('http') ? item.url : new URL(item.url, seriesUrl).href;
                                
                                // نستبعد روابط التصنيفات، ونبقي فقط روابط الحلقات الفعلية
                                if (!href.includes('/category/') && 
                                    !href.includes('/tag/') && 
                                    !href.includes('/series/') &&
                                    !seenUrls.has(href)) {
                                    seenUrls.add(href);
                                    // تنظيف اسم الحلقة
                                    let name = item.name || `الحلقة`;
                                    // إزالة الأرقام الزائدة والمسافات
                                    name = name.replace(/\s+/g, ' ').trim();
                                    episodes.push({ name, url: href });
                                }
                            }
                        }
                    }
                }
            }
        }
    } catch (e) {
        console.warn(`  ⚠️ فشل استخراج JSON: ${e.message}`);
    }

    // ===== الطريقة الثانية: البحث المباشر عن روابط الحلقات =====
    if (episodes.length === 0) {
        // نبحث في #AreaNewly عن روابط الحلقات الفعلية
        const area = $('#AreaNewly');
        if (area.length) {
            area.find('.ItemNewly a').each((i, el) => {
                let href = $(el).attr('href');
                if (!href) return;
                let name = $(el).find('.NewlyTitle').text().trim() || $(el).text().trim() || `الحلقة ${i+1}`;
                href = href.startsWith('http') ? href : new URL(href, seriesUrl).href;
                // نتأكد أن الرابط يحتوي على "الحلقة" أو "episode" وليس تصنيفاً
                if (!href.includes('/category/') && 
                    !href.includes('/tag/') && 
                    !href.includes('/series/') &&
                    (href.includes('الحلقة') || href.includes('episode') || name.includes('الحلقة')) &&
                    !seenUrls.has(href)) {
                    seenUrls.add(href);
                    episodes.push({ name, url: href });
                }
            });
        }
    }

    // ===== الطريقة الثالثة: البحث العام عن روابط تحتوي على "الحلقة" =====
    if (episodes.length === 0) {
        $('a[href*="الحلقة"], a[href*="episode"]').each((i, el) => {
            let href = $(el).attr('href');
            if (!href) return;
            let name = $(el).text().trim() || `الحلقة ${i+1}`;
            href = href.startsWith('http') ? href : new URL(href, seriesUrl).href;
            if (!href.includes('/category/') && 
                !href.includes('/tag/') && 
                !href.includes('/series/') &&
                !seenUrls.has(href)) {
                seenUrls.add(href);
                episodes.push({ name, url: href });
            }
        });
    }

    // نرتب الحلقات حسب رقم الحلقة إن أمكن
    episodes.sort((a, b) => {
        const numA = parseInt(a.name.match(/\d+/)?.[0] || 0);
        const numB = parseInt(b.name.match(/\d+/)?.[0] || 0);
        return numA - numB;
    });

    // نأخذ أول 50 حلقة
    if (episodes.length > 50) episodes.length = 50;

    // إذا لم نجد حلقات، نعيد null
    return episodes.length > 0 ? episodes : null;
}

// ================================================================
// الدالة الرئيسية
// ================================================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري جلب المسلسلات التركية المدبلجة...\n');
    let allSeries = [];
    const processedLinks = new Set();

    for (const config of SITE_CONFIGS) {
        console.log(`📡 جلب من: ${config.name} (${config.listUrl})`);
        const html = await fetchPage(config.listUrl);
        if (!html) {
            console.log(`  ❌ فشل جلب الصفحة.`);
            continue;
        }

        const seriesList = extractSeriesList(html, config);
        console.log(`  ✅ تم العثور على ${seriesList.length} مسلسل.`);

        let count = 0;
        for (const item of seriesList) {
            if (processedLinks.has(item.link)) continue;
            processedLinks.add(item.link);
            count++;

            console.log(`  🔍 (${count}/${seriesList.length}) جلب حلقات: ${item.name}`);

            let episodes = null;
            try {
                episodes = await fetchEpisodes(item.link);
            } catch (e) {
                console.warn(`    ⚠️ فشل جلب الحلقات: ${e.message}`);
            }

            if (!episodes || episodes.length === 0) {
                episodes = [
                    { name: 'الحلقة 1 (تجريبي)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                    { name: 'الحلقة 2 (تجريبي)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
                ];
                console.log(`    ⚠️ استخدام حلقات تجريبية.`);
            } else {
                console.log(`    ✅ جلب ${episodes.length} حلقة.`);
                const sample = episodes.slice(0, 3).map(e => e.name).join(' | ');
                console.log(`    📝 مثال: ${sample}`);
            }

            allSeries.push({
                name: item.name,
                image: item.image,
                link: item.link,
                source: config.name,
                episodes: episodes
            });
        }

        if (allSeries.length >= 30) {
            console.log(`\n🎉 تم جمع ${allSeries.length} مسلسل، كافٍ.`);
            break;
        }
    }

    if (allSeries.length === 0) {
        console.warn('\n⚠️ لم يتم جلب أي بيانات. استخدم القائمة الاحتياطية.');
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
// التشغيل
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
