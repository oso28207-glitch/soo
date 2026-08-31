const cheerio = require('cheerio');
const fs = require('fs');

// ================================================================
// إعدادات المواقع
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

function extractPostData(html) {
    const startMatch = html.match(/PostData\s*=\s*\{/);
    if (!startMatch) return null;

    let startIndex = startMatch.index;
    let braceCount = 0;
    let inString = false;
    let escape = false;
    let endIndex = startIndex;

    for (let i = startIndex; i < html.length; i++) {
        const char = html[i];
        if (escape) { escape = false; continue; }
        if (char === '\\' && inString) { escape = true; continue; }
        if (char === '"' && !escape) { inString = !inString; continue; }
        if (!inString) {
            if (char === '{') braceCount++;
            else if (char === '}') {
                braceCount--;
                if (braceCount === 0) { endIndex = i + 1; break; }
            }
        }
    }

    if (braceCount !== 0) return null;

    let postDataStr = html.substring(startIndex, endIndex);
    postDataStr = postDataStr.replace(/PostData\s*=\s*/, '').trim();
    if (postDataStr.endsWith(';')) postDataStr = postDataStr.slice(0, -1);

    try {
        const cleaned = postDataStr.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
        return JSON.parse(cleaned);
    } catch (e) {
        try {
            const fn = new Function(`return ${postDataStr}`);
            return fn();
        } catch (err) { return null; }
    }
}

function extractServerUrls(postData) {
    const servers = postData.ServersWatch || [];
    const urls = [];
    for (const server of servers) {
        const embed = server.Embed;
        if (embed) {
            try {
                const decoded = Buffer.from(embed, 'base64').toString('utf-8');
                if (decoded.startsWith('http')) {
                    urls.push({ name: server.Name, embed: decoded });
                }
            } catch (e) {}
        }
    }
    return urls;
}

/**
 * محاولة استخراج رابط فيديو مباشر من صفحة السيرفر (embed)
 * مع تجربة عدة سيرفرات وليس فقط الأول
 */
async function extractDirectVideoFromEmbed(embedUrl, retries = 2) {
    for (let attempt = 0; attempt < retries; attempt++) {
        try {
            const html = await fetchPage(embedUrl, 2);
            if (!html) continue;

            const $ = cheerio.load(html);
            let videoUrl = null;

            // 1. البحث عن video source
            $('video source').each((i, el) => {
                const src = $(el).attr('src');
                if (src && src.startsWith('http')) videoUrl = src;
            });
            if (videoUrl) return videoUrl;

            // 2. البحث عن iframe متداخل
            const iframeSrc = $('iframe').attr('src');
            if (iframeSrc && iframeSrc.startsWith('http')) {
                const nestedHtml = await fetchPage(iframeSrc, 1);
                if (nestedHtml) {
                    const nested$ = cheerio.load(nestedHtml);
                    nested$('video source').each((i, el) => {
                        const src = nested$(el).attr('src');
                        if (src && src.startsWith('http')) videoUrl = src;
                    });
                    if (videoUrl) return videoUrl;
                }
            }

            // 3. البحث عن روابط .mp4 في النص
            const text = html;
            const mp4Match = text.match(/https?:\/\/[^\s"']+\.mp4/);
            if (mp4Match) return mp4Match[0];

            // 4. البحث عن .m3u8
            const m3u8Match = text.match(/https?:\/\/[^\s"']+\.m3u8/);
            if (m3u8Match) return m3u8Match[0];

            // 5. البحث عن روابط في عناصر <a>
            $('a[href*=".mp4"], a[href*=".m3u8"]').each((i, el) => {
                const href = $(el).attr('href');
                if (href && href.startsWith('http')) videoUrl = href;
            });
            if (videoUrl) return videoUrl;

        } catch (e) {
            // تجاهل الأخطاء واستمر
        }
    }
    return null;
}

/**
 * جلب الحلقات مع السيرفرات ومحاولة استخراج روابط مباشرة من عدة سيرفرات
 */
async function fetchEpisodesWithServers(seriesUrl) {
    const html = await fetchPage(seriesUrl, 2);
    if (!html) return null;

    const $ = cheerio.load(html);
    const episodes = [];
    const seenUrls = new Set();

    // استخراج من #AreaNewly
    const areaNewly = $('#AreaNewly');
    if (areaNewly.length) {
        areaNewly.find('.ItemNewly a').each((i, el) => {
            let href = $(el).attr('href');
            if (!href) return;
            let name = $(el).find('.NewlyTitle').text().trim() || $(el).text().trim() || `الحلقة ${i+1}`;
            href = href.startsWith('http') ? href : new URL(href, seriesUrl).href;
            if (!seenUrls.has(href) && !href.includes('/category/') && !href.includes('/tag/')) {
                seenUrls.add(href);
                episodes.push({ name, url: href });
            }
        });
    } else {
        // محاولة عامة
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

    // لكل حلقة، جلب PostData واستخراج الروابط المباشرة
    for (let ep of episodes) {
        console.log(`    🔍 جلب بيانات: ${ep.name}`);
        const epHtml = await fetchPage(ep.url, 2);
        if (epHtml) {
            const postData = extractPostData(epHtml);
            if (postData) {
                const serverUrls = extractServerUrls(postData);
                if (serverUrls.length > 0) {
                    ep.servers = serverUrls;
                    ep.embed = serverUrls[0].embed;
                    // محاولة استخراج رابط مباشر من عدة سيرفرات
                    let directFound = false;
                    for (const server of serverUrls) {
                        console.log(`      🔍 محاولة استخراج رابط مباشر من ${server.name}...`);
                        const direct = await extractDirectVideoFromEmbed(server.embed);
                        if (direct) {
                            ep.directVideo = direct;
                            console.log(`      ✅ رابط مباشر من ${server.name}: ${direct.substring(0, 60)}...`);
                            directFound = true;
                            break;
                        } else {
                            console.log(`      ⚠️ لم نستطع استخراج رابط مباشر من ${server.name}.`);
                        }
                    }
                    if (!directFound) {
                        console.log(`      ⚠️ لم نستطع استخراج رابط مباشر من أي سيرفر.`);
                    }
                } else {
                    console.log(`      ⚠️ لا توجد سيرفرات`);
                }
            } else {
                console.log(`      ⚠️ لا يوجد PostData`);
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
                episodes = [];
                console.log(`    ⚠️ لم نجد أي حلقة.`);
            } else {
                console.log(`    ✅ جلب ${episodes.length} حلقة مع سيرفرات.`);
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
        console.warn('\n⚠️ لم يتم جلب أي بيانات. الخروج.');
        return [];
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
