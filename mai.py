def extract_video_from_laroza_page(driver, page_url):
    """معالج خاص بصفحات لاروزا (larozaa.xyz)"""
    driver.get(page_url)
    time.sleep(5)

    # البحث عن قائمة السيرفرات
    try:
        servers = driver.find_elements(By.CSS_SELECTOR, "#pm-servers li")
        active_server = None
        for server in servers:
            if "active" in server.get_attribute("class"):
                active_server = server
                break
        if not active_server and servers:
            active_server = servers[0]  # أول سيرفر إذا لم يوجد نشط

        if active_server:
            embed_url = active_server.get_attribute("data-embed-url")
            if embed_url:
                print(f"🔗 استخراج رابط embed النشط: {embed_url}")

                # فتح صفحة embed
                driver.get(embed_url)
                time.sleep(5)

                # البحث عن iframe داخل #Playerholder (مثلما في الصفحة الأصلية)
                try:
                    iframe = driver.find_element(By.CSS_SELECTOR, "#Playerholder iframe")
                    iframe_src = iframe.get_attribute("src")
                    if iframe_src:
                        print(f"📦 تم العثور على iframe داخل embed: {iframe_src}")
                        # معالجة iframe بنفس الطرق السابقة
                        return extract_video_from_page(driver, iframe_src)
                except:
                    pass

                # إذا لم نجد iframe، نحاول استخراج الفيديو مباشرة من صفحة embed
                return extract_video_from_page(driver, embed_url)

    except Exception as e:
        print(f"⚠️ فشل استخراج السيرفرات من صفحة لاروزا: {e}")

    # إذا فشل، نعود للطريقة العامة
    return extract_video_from_page(driver, page_url)

def extract_video_from_page(driver, page_url):
    """
    محاولة استخراج رابط فيديو من أي صفحة.
    تعيد (video_url, referer)
    """
    # معالجة خاصة لمواقع لاروزا
    if "larozaa.xyz" in page_url:
        return extract_video_from_laroza_page(driver, page_url)

    driver.get(page_url)
    time.sleep(5)

    # 1. البحث عن iframe (مثل AlbaPlayer)
    try:
        iframe = driver.find_element(By.CSS_SELECTOR, ".aplr-player-content iframe")
        iframe_src = iframe.get_attribute("src")
        if iframe_src:
            print(f"📦 تم العثور على iframe: {iframe_src}")
            # معالجة iframe
            if 'uqload' in iframe_src:
                video_url = extract_video_from_uqload_page(driver, iframe_src)
                if video_url:
                    return video_url, iframe_src
            else:
                # فتح iframe
                driver.get(iframe_src)
                time.sleep(5)
                video_url = extract_video_from_current_page(driver)
                if video_url:
                    return video_url, iframe_src
    except:
        pass

    # 2. البحث عن عنصر video مباشرة
    video_url = extract_video_from_current_page(driver)
    if video_url:
        return video_url, page_url

    # 3. البحث عن روابط mp4 في الصفحة
    page_source = driver.page_source
    match = re.search(r'(https?://[^"\']+\.mp4[^"\']*)', page_source)
    if match:
        video_url = match.group(1)
        print(f"✅ تم العثور على رابط mp4 في الصفحة: {video_url[:100]}...")
        return video_url, page_url

    # 4. استخدام yt-dlp
    if test_video_url(page_url):
        print("✅ الرابط قابل للتنزيل عبر yt-dlp.")
        return page_url, page_url

    return None, None

def get_video_from_rmd(driver, base_url):
    """
    استخراج رابط الفيديو من صفحة الحلقة (أي رابط).
    """
    return extract_video_from_page(driver, base_url)
