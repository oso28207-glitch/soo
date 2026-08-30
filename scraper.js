const cheerio = require('cheerio');
const fs = require('fs');

// ================================================================
// قائمة مواقع المسلسلات التركية المدبلجة
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
 * استخراج روابط السيرفرات من صفحة الحلقة (PostData)
 */
function extractServersFromEpisode(html) {
    const $ = cheerio.load(html);
    let servers = [];

    $('script').each((i, el) => {
        const content = $(el).html() || '';
        // البحث عن const PostData = {...};
        const match = content.match(/const\s+PostData\s*=\s*({[^;]+});/);
        if (match) {
            try {
                const postData = JSON.parse(match[1]);
                if (postData.ServersWatch && Array.isArray(postData.ServersWatch)) {
                    servers = postData.ServersWatch.map(server => ({
                        name: server.Name,
                        embed: Buffer.from(server.Embed, 'base64').toString('utf-8'),
                        id: server.Id
                    }));
                }
            } catch (e) {
                // قد يكون JSON غير صحيح، نتجاهل
            }
        }
    });

    return servers;
}

/**
 * محاولة استخراج رابط فيديو مباشر من صفحة السيرفر (embed)
 */
async function extractDirectVideoFromEmbed(embedUrl) {
    try {
        const html = await fetchPage(embedUrl, 1);
        if (!html) return null;

        const $ = cheerio.load(html);
        // البحث عن عناصر الفيديو
        let videoUrl = null;
        // 1. البحث عن video source
        $('video source').each((i, el) => {
            const src = $(el).attr('src');
            if (src && src.startsWith('http')) videoUrl = src;
        });
        if (videoUrl) return videoUrl;

        // 2. البحث عن iframe داخل الصفحة (قد يكون هناك nested embed)
        const iframeSrc = $('iframe').attr('src');
        if (iframeSrc && iframeSrc.startsWith('http')) {
            // محاولة جلب الـ iframe المتداخل
            const nestedHtml = await fetchPage(iframeSrc, 1);
            if (nestedHtml) {
                const nested$ = cheerio.load(nestedHtml);
                nested$('video source').each((i, el) => {
                    const src = nested$(el).attr('src');
                    if (src && src.startsWith('http')) videoUrl = src;
                });
            }
        }

        // 3. البحث عن روابط .mp4 في النص
        if (!videoUrl) {
            const text = html;
            const mp4Match = text.match(/https?:\/\/[^\s"']+\.mp4/);
            if (mp4Match) videoUrl = mp4Match[0];
        }

        return videoUrl;
    } catch (e) {
        return null;
    }
}

/**
 * جلب الحلقات من صفحة المسلسل مع روابط السيرفرات
 */
async function fetchEpisodesWithServers(seriesUrl) {
    const html = await fetchPage(seriesUrl, 2);
    if (!html) return null;

    const $ = cheerio.load(html);
    const episodes = [];
    const seenUrls = new Set();

    // البحث عن روابط الحلقات في #AreaEpisodes أو .ItemNewly
    const areaEpisodes = $('#AreaEpisodes');
    if (areaEpisodes.length) {
        areaEpisodes.find('a.ItemEpisode, a.CurrentEpisode').each((i, el) => {
            let href = $(el).attr('href');
            if (!href) return;
            let name = $(el).text().trim() || `الحلقة ${i+1}`;
            href = href.startsWith('http') ? href : new URL(href, seriesUrl).href;
            if (!seenUrls.has(href)) {
                seenUrls.add(href);
                episodes.push({ name, url: href });
            }
        });
    } else {
        // محاولة البحث العام
        $('a[href*="الحلقة"], a[href*="episode"]').each((i, el) => {
            let href = $(el).attr('href');
            if (!href) return;
            let name = $(el).text().trim() || `الحلقة ${i+1}`;
            href = href.startsWith('http') ? href : new URL(href, seriesUrl).href;
            if (!seenUrls.has(href) && !href.includes('/category/') && !href.includes('/tag/')) {
                seenUrls.add(href);
                episodes.push({ name, url: href });
            }
        });
    }

    // الآن لكل حلقة، نجلب صفحتها لاستخراج السيرفرات
    for (let ep of episodes) {
        console.log(`    🔍 جلب سيرفرات الحلقة: ${ep.name}`);
        const epHtml = await fetchPage(ep.url, 2);
        if (epHtml) {
            const servers = extractServersFromEpisode(epHtml);
            if (servers.length > 0) {
                ep.servers = servers;
                // محاولة استخراج رابط فيديو مباشر من أول سيرفر
                const firstServer = servers[0];
                if (firstServer && firstServer.embed) {
                    const directVideo = await extractDirectVideoFromEmbed(firstServer.embed);
                    if (directVideo) {
                        ep.directVideo = directVideo;
                        console.log(`      ✅ تم العثور على رابط فيديو مباشر: ${directVideo.substring(0, 50)}...`);
                    } else {
                        console.log(`      ⚠️ لم نتمكن من استخراج رابط فيديو مباشر من السيرفر: ${firstServer.name}`);
                    }
                }
            } else {
                console.log(`      ⚠️ لم نجد سيرفرات لهذه الحلقة`);
            }
        }
    }

    return episodes;
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
                episodes = await fetchEpisodesWithServers(item.link);
            } catch (e) {
                console.warn(`    ⚠️ فشل جلب الحلقات: ${e.message}`);
            }

            if (!episodes || episodes.length === 0) {
                episodes = [
                    { name: 'الحلقة 1 (تجريبي)', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
                ];
                console.log(`    ⚠️ استخدام حلقات تجريبية.`);
            } else {
                console.log(`    ✅ جلب ${episodes.length} حلقة مع سيرفراتها.`);
                const sample = episodes.slice(0, 2).map(e => e.name).join(' | ');
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
        return getFallbackData();
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

function getFallbackData() {
    return [
        {
            name: 'مسلسل تركي تجريبي 1',
            image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Turkish+Series+1',
            link: '#',
            source: 'تجريبي',
            episodes: [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ]
        }
    ];
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
