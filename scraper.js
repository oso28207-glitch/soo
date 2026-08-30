const cheerio = require('cheerio');
const fs = require('fs');

// =============================================
// دالة جلب المسلسلات باستخدام fetch المدمج
// =============================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري جلب بيانات المسلسلات...');
    
    // ⚠️ استبدل هذا الرابط بالموقع الفعلي للمسلسلات التركية المدبلجة
    const targetUrl = 'https://example-turkish-drama-site.com/'; 
    
    try {
        const response = await fetch(targetUrl, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        });
        if (!response.ok) throw new Error(`HTTP error ${response.status}`);
        
        const html = await response.text();
        const $ = cheerio.load(html);
        const seriesList = [];

        // مثال على استخراج البيانات – عدل المحددات حسب الموقع المستهدف
        $('.series-item').each((i, el) => {
            const name = $(el).find('.series-title').text().trim();
            const image = $(el).find('img').attr('src');
            const link = $(el).find('a').attr('href');
            
            // توليد حلقات وهمية (يمكنك تعديلها لجلب حلقات حقيقية من صفحة المسلسل)
            const episodes = [];
            for (let i = 0; i < 5; i++) {
                episodes.push({
                    name: `الحلقة ${i+1}`,
                    url: `${link}/episode-${i+1}` // رابط وهمي
                });
            }

            if (name && link) {
                seriesList.push({
                    name: name,
                    image: image || '',
                    link: link,
                    episodes: episodes
                });
            }
        });

        if (seriesList.length === 0) {
            console.warn('⚠️ لم يتم العثور على بيانات، سيتم استخدام بيانات تجريبية.');
            return getMockData();
        }

        console.log(`✅ تم جلب ${seriesList.length} مسلسل.`);
        return seriesList;
    } catch (error) {
        console.error('❌ خطأ في الجلب:', error.message);
        return getMockData(); // بيانات تجريبية
    }
}

// بيانات تجريبية (للتجربة)
function getMockData() {
    return [
        {
            name: 'مسلسل تركي 1 (تجريبي)',
            image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Series+1',
            link: '#',
            episodes: [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' },
                { name: 'الحلقة 2', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ]
        },
        {
            name: 'مسلسل تركي 2 (تجريبي)',
            image: 'https://via.placeholder.com/200x280/1e1e1e/f5c518?text=Series+2',
            link: '#',
            episodes: [
                { name: 'الحلقة 1', url: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
            ]
        }
    ];
}

// =============================================
// حفظ البيانات في ملف data.json
// =============================================
async function main() {
    const series = await fetchTurkishSeries();
    fs.writeFileSync('data.json', JSON.stringify(series, null, 2));
    console.log('💾 تم حفظ البيانات في data.json');
}

main();
