const cheerio = require('cheerio');
const fs = require('fs');

// ============================================================
// تكوين المواقع مع المحددات الصحيحة
// ============================================================
const SITES = [
    {
        name: 'LodyNet',
        listUrl: 'https://lodynet.watch/category/%d9%85%d8%b4%d8%a7%d9%87%d8%af%d8%a9-%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%aa%d8%b1%d9%83%d9%8a%d8%a9-%d9%85%d8%af%d8%a8%d9%84%d8%ac%d8%a9/',
        selectors: {
            // كل مسلسل موجود داخل div.ItemNewly
            seriesContainer: '.ItemNewly',
            // رابط المسلسل داخل a
            link: 'a',
            // اسم المسلسل داخل div.NewlyTitle
            title: '.NewlyTitle',
            // الصورة موجودة في div.NewlyCover مع style background-image
            image: '.NewlyCover'
        },
        // دالة لاستخراج رابط الصورة من العنصر
        extractImage: (el, $) => {
            const cover = $(el).find('.NewlyCover');
            const style = cover.attr('style') || '';
            const match = style.match(/url\(["']?([^"')]+)["']?\)/);
            if (match) {
                let url = match[1];
                if (url.startsWith('//')) url = 'https:' + url;
                return url;
            }
            // محاولة من data-src
            const dataSrc = cover.attr('data-src');
            if (dataSrc) return dataSrc;
            return null;
        }
    },
    {
        name: 'Eishq (قصة عشق)',
        listUrl: 'https://new.eishq.net/video/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%aa%d8%b1%d9%83%d9%8a%d8%a9-%d9%85%d8%af%d8%a8%d9%84%d8%ac%d8%a9/',
        selectors: {
            // كل مسلسل داخل article.post
            seriesContainer: 'article.post',
            // رابط المسلسل داخل a
            link: 'a',
            // اسم المسلسل داخل div.title
            title: '.title',
            // الصورة في div.imgBg مع style background-image
            image: '.imgBg'
        },
        extractImage: (el, $) => {
            const imgBg = $(el).find('.imgBg');
            const style = imgBg.attr('style') || '';
            const match = style.match(/url\(["']?([^"')]+)["']?\)/);
            if (match) {
                let url = match[1];
                if (url.startsWith('//')) url = 'https:' + url;
                return url;
            }
            return null;
        }
    }
];

// ============================================================
// دوال مساعدة
// ============================================================
async function fetchContent(url, retries = 3) {
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
            await new Promise(r => setTimeout(r, 2000 * (i + 1)));
        }
    }
    return null;
}

/**
 * استخراج روابط المسلسلات من صفحة التصنيف
 */
function extractSeriesFromList(html, site) {
    const $ = cheerio.load(html);
    const results = [];
    const { seriesContainer, link: linkSelector, title: titleSelector } = site.selectors;
    const extractImage = site.extractImage;

    $(seriesContainer).each((i, el) => {
        const linkEl = $(el).find(linkSelector);
        const href = linkEl.attr('href');
        const name = $(el).find(titleSelector).text().trim();
        const image = extractImage(el, $);

        if (href && name) {
            // التأكد من الرابط مطلق
            let fullUrl = href;
            if (!href.startsWith('http')) {
                fullUrl = new URL(href, site.listUrl).href;
            }
            results.push({
                name: name,
                link: fullUrl,
                image: image || null
            });
        }
    });

    return results;
}

/**
 * جلب الحلقات من صفحة المسلسل
 */
async function fetchEpisodes(seriesUrl) {
    try {
        const html = await fetchContent(seriesUrl, 2);
        if (!html) return null;
        const $ = cheerio.load(html);
        const episodes = [];

        // محاولة استخراج الحلقات من الصفحة
        // البحث عن روابط تحتوي على "episode" أو "watch" أو "mp4"
        $('a[href*="episode"], a[href*="watch"], a[href*="mp4"], .episode-link, .episode-item a, .episode a').each((i, el) => {
            let link = $(el).attr('href');
            let name = $(el).text().trim() || `الحلقة ${i+1}`;
            if (link) {
                if (!link.startsWith('http')) {
                    link = new URL(link, seriesUrl).href;
                }
                // تجاهل الروابط التي لا تحتوي على episode أو watch أو mp4
                if (!link.includes('/episode/') && !link.includes('/watch/') && !link.includes('.mp4')) {
                    return;
                }
                episodes.push({ name: name, url: link });
            }
        });

        // إذا لم نجد، نحاول البحث عن أي روابط داخل .post-content أو .entry-content
        if (episodes.length === 0) {
            $('.post-content a, .entry-content a, .episodes-list a').each((i, el) => {
                let link = $(el).attr('href');
                let name = $(el).text().trim() || `الحلقة ${i+1}`;
                if (link && !link.includes('#') && !link.includes('mailto:')) {
                    if (!link.startsWith('http')) {
                        link = new URL(link, seriesUrl).href;
                    }
                    episodes.push({ name: name, url: link });
                }
            });
        }

        // نأخذ أول 30 حلقة فقط
        return episodes.length > 0 ? episodes.slice(0, 30) : null;
    } catch (error) {
        console.warn(`  ⚠️ فشل جلب الحلقات من ${seriesUrl}: ${error.message}`);
        return null;
    }
}

/**
 * الحصول على صورة احتياطية
 */
function getFallbackImage(name) {
    return `https://via.placeholder.com/200x280/1e1e1e/f5c518?text=${encodeURIComponent(name)}`;
}

// ============================================================
// الدالة الرئيسية
// ============================================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري جلب المسلسلات التركية المدبلجة...\n');
    const allSeries = [];
    const processedUrls = new Set();

    for (const site of SITES) {
        console.log(`📡 جلب من: ${site.name} (${site.listUrl})`);
        const html = await fetchContent(site.listUrl);

        if (!html) {
            console.log(`  ❌ فشل جلب الصفحة: ${site.name}`);
            continue;
        }

        const seriesList = extractSeriesFromList(html, site);
        console.log(`  ✅ تم العثور على ${seriesList.length} مسلسل في ${site.name}`);

        let count = 0;
        for (const item of seriesList) {
            // تجنب التكرار
            if (processedUrls.has(item.link)) continue;
            processedUrls.add(item.link);
            count++;

            console.log(`  🔍 (${count}/${seriesList.length}) جلب: ${item.name}`);

            // محاولة جلب الحلقات
            let episodes = null;
            try {
                episodes = await fetchEpisodes(item.link);
            } catch (e) {}

            // إذا لم نجد حلقات، نضع حلقتين تجريبيتين
            if (!episodes || episodes.length === 0) {
                episodes = [
                    { name: 'الحلقة 1 (تجريبي)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                    { name: 'الحلقة 2 (تجريبي)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
                ];
                console.log(`    ⚠️ لم نجد حلقات، نستخدم حلقات تجريبية`);
            } else {
                console.log(`    ✅ جلب ${episodes.length} حلقة`);
            }

            // الصورة
            const image = item.image || getFallbackImage(item.name);

            allSeries.push({
                name: item.name,
                image: image,
                link: item.link,
                source: site.name,
                episodes: episodes
            });
        }

        // إذا جمعنا عدداً كافياً، نتوقف
        if (allSeries.length >= 50) {
            console.log(`\n🎉 تم جمع ${allSeries.length} مسلسل، كافٍ للتوقف.`);
            break;
        }
    }

    // إذا لم نجد أي بيانات، استخدم البيانات التجريبية
    if (allSeries.length === 0) {
        console.warn('\n⚠️ لم يتم العثور على أي بيانات من المواقع.');
        return getMockData();
    }

    // إزالة التكرارات بناءً على الاسم
    const uniqueMap = new Map();
    allSeries.forEach(s => {
        const key = s.name.trim().toLowerCase();
        if (!uniqueMap.has(key)) {
            uniqueMap.set(key, s);
        }
    });
    const finalSeries = Array.from(uniqueMap.values());

    console.log(`\n✅ تم جمع ${finalSeries.length} مسلسل فريد.`);
    return finalSeries;
}

// ============================================================
// بيانات تجريبية
// ============================================================
function getMockData() {
    return [
        {
            name: 'مسلسل تركي مدبلج 1',
            image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Series+1',
            link: '#',
            source: 'تجريبي',
            episodes: [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ]
        },
        {
            name: 'مسلسل تركي مدبلج 2',
            image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Series+2',
            link: '#',
            source: 'تجريبي',
            episodes: [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ]
        }
    ];
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
