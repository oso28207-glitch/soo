// scraper.js - يعمل في بيئة Node.js (GitHub Actions)
const axios = require('axios');
const cheerio = require('cheerio');
const fs = require('fs');

// =============================================
// مثال لجلب البيانات من موقع "قصة عشق" (مثال توضيحي)
// يجب عليك تعديل الـ Selectors حسب الموقع الفعلي الذي تريده
// =============================================
async function fetchTurkishSeries() {
    console.log('🔄 جاري جلب بيانات المسلسلات...');
    
    // مثال: رابط موقع مسلسلات تركية مدبلجة (استخدم رابط الموقع الحقيقي)
    const targetUrl = 'https://example-turkish-drama-site.com/'; 
    
    try {
        const { data } = await axios.get(targetUrl, {
            headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' }
        });
        const $ = cheerio.load(data);
        const seriesList = [];

        // مثال على استخراج البيانات (عدل المحددات حسب الموقع)
        $('.series-item').each((i, el) => {
            const name = $(el).find('.series-title').text().trim();
            const image = $(el).find('img').attr('src');
            const link = $(el).find('a').attr('href');
            
            // للحلقات - نفترض أن كل مسلسل له صفحة حلقات
            // سنقوم بجلب الحلقات من الرابط الداخلي (اختياري)
            const episodes = [];
            // مثال: لو أردنا جلب الحلقات فوراً (قد يكون بطيئاً، الأفضل جلبها عند الطلب)
            // لكن نتركها فارغة حالياً، أو نملأها بروابط تجريبية
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

        // إذا لم يتم جلب أي بيانات، نضع بيانات تجريبية لتجربة الواجهة
        if (seriesList.length === 0) {
            console.warn('⚠️ لم يتم العثور على بيانات، سيتم استخدام بيانات تجريبية.');
            return getMockData();
        }

        console.log(`✅ تم جلب ${seriesList.length} مسلسل.`);
        return seriesList;
    } catch (error) {
        console.error('❌ خطأ في الجلب:', error.message);
        return getMockData(); // بيانات تجريبية لضمان عمل الواجهة
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
