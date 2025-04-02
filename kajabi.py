import os
import time
import requests
import threading
import signal
import configparser
import csv
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from tqdm import tqdm
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import traceback
from datetime import datetime

# Configuration
config = configparser.ConfigParser()
config.read('config.ini')
MAX_RETRIES = config.getint('Download', 'max_retries', fallback=3)
TIMEOUT = config.getint('Download', 'timeout', fallback=60)
BASE_DIR = config.get('Paths', 'base_dir', fallback='Kajabi_Courses')
MAX_LESSON_THREADS = config.getint('Threads', 'max_lesson_threads', fallback=3)

# Thread-safe logging lock
log_lock = threading.Lock()

# Global state
FAILED_DOWNLOADS = []
PAUSED = False
INTERRUPTED = False
DRIVER = None

def signal_handler(signum, frame):
    global PAUSED, INTERRUPTED
    if PAUSED:
        PAUSED = False
        print("▶️ Resumed")
    else:
        PAUSED = True
        print("⏸️ Paused (Press Ctrl+C again to resume, or Ctrl+C twice to exit)")
signal.signal(signal.SIGINT, signal_handler)

# Load credentials from .env
load_dotenv()
EMAIL = os.getenv('KAJABI_EMAIL')
PASSWORD = os.getenv('KAJABI_PASSWORD')
KAJABI_URL = os.getenv('KAJABI_URL')

log_file = "download_log.csv"

def init_csv():
    if not os.path.exists(log_file):
        with open(log_file, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Course", "Module", "Lesson", "Description", "Thumbnail", "Video", "Material"])

def get_lesson_status(course_title, module_title, lesson_title):
    init_csv()
    try:
        with open(log_file, "r", newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row['Course'] == course_title and 
                    row['Module'] == module_title and 
                    row['Lesson'] == lesson_title):
                    return (row.get('Description', 'Failed'),
                            row.get('Thumbnail', 'Failed'),
                            row.get('Video', 'Failed'),
                            row.get('Material', 'Failed'))
    except Exception as e:
        print(f"⚠️ Error reading CSV: {e}")
    return ('Failed', 'Failed', 'Failed', 'Failed')

def log_status(course_title, module_title, safe_lesson_base, status_dict):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    headers = ["Timestamp", "Course", "Module", "Lesson", "Description", "Thumbnail", "Video", "Material"]
    rows = []
    updated = False

    try:
        with open(log_file, "r", newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row['Course'] == course_title and 
                    row['Module'] == module_title and 
                    row['Lesson'] == safe_lesson_base):
                    row.update({
                        'Timestamp': timestamp,
                        'Description': status_dict.get("Description", "Failed"),
                        'Thumbnail': status_dict.get("Thumbnail", "Failed"),
                        'Video': status_dict.get("Video", "Failed"),
                        'Material': status_dict.get("Material", "Failed")
                    })
                    updated = True
                rows.append(row)
    except FileNotFoundError:
        init_csv()

    if not updated:
        rows.append({
            'Timestamp': timestamp,
            'Course': course_title,
            'Module': module_title,
            'Lesson': safe_lesson_base,
            'Description': status_dict.get("Description", "Failed"),
            'Thumbnail': status_dict.get("Thumbnail", "Failed"),
            'Video': status_dict.get("Video", "Failed"),
            'Material': status_dict.get("Material", "Failed")
        })

    with log_lock:
        with open(log_file, "w", newline='', encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

def get_completed_lessons():
    init_csv()
    completed = set()
    try:
        with open(log_file, "r", newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("Description", "Failed") in ["Success", "None"] and 
                    row.get("Thumbnail", "Failed") in ["Success", "None"] and
                    row.get("Video", "Failed") in ["Success", "None"] and
                    row.get("Material", "Failed") in ["Success", "None"]):
                    key = f"{row['Course']}|{row['Module']}|{row['Lesson']}"
                    completed.add(key)
    except Exception as e:
        print(f"⚠️ Error reading completed lessons: {e}")
    return completed

def get_unique_filename(base_path, filename):
    counter = 1
    new_path = os.path.join(base_path, filename)
    while os.path.exists(new_path):
        name, ext = os.path.splitext(filename)
        new_path = os.path.join(base_path, f"{name}_{counter}{ext}")
        counter += 1
    return new_path

def selenium_download_video(driver, lesson_url, video_path, video_filename, course_title, module_title, lesson_title):
    for attempt in range(MAX_RETRIES):
        try:
            print(f"    ℹ️ Attempt {attempt + 1}/{MAX_RETRIES} to download video: {video_filename}")
            driver.get(lesson_url)
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            
            # Check if on login page
            if "login" in driver.current_url:
                print("    ⚠️ Session expired, re-logging in...")
                driver.get(f"{KAJABI_URL}/login")
                WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "username"))).send_keys(EMAIL)
                driver.find_element(By.ID, "password").send_keys(PASSWORD)
                driver.find_element(By.XPATH, "//button[@type='submit']").click()
                time.sleep(5)
                driver.get(lesson_url)
                WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

            # Updated selector - more flexible
            video_btn = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, '//button[contains(., "Video Actions") or contains(., "video actions")]'))
            )
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", video_btn)
            time.sleep(1)
            video_btn.click()
            print("    🔽 Clicked 'Video Actions' button.")
            
            video_link_elem = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, '//a[contains(@href, ".mp4") and contains(@class, "sage-dropdown__item-control--icon-download")]'))
            )
            video_url = video_link_elem.get_attribute("href")

            download_dir = os.path.dirname(video_path)
            driver.execute("send_command", {
                'cmd': 'Page.setDownloadBehavior',
                'params': {'behavior': 'allow', 'downloadPath': download_dir}
            })

            driver.execute_script(f"window.open('{video_url}', '_blank');")
            time.sleep(2)
            driver.switch_to.window(driver.window_handles[-1])

            max_wait = 120
            waited = 0
            while not os.path.exists(video_path) and waited < max_wait:
                time.sleep(1)
                waited += 1
                partial_files = [f for f in os.listdir(download_dir) if f.endswith('.crdownload') or f.startswith(os.path.splitext(video_filename)[0])]
                if partial_files:
                    print(f"    ℹ️ Download in progress: {partial_files[0]}")

            if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
                print(f"    ✅ Downloaded video: {video_filename}")
                status = get_lesson_status(course_title, module_title, lesson_title)
                new_status = {"Description": status[0], "Thumbnail": status[1], "Video": "Success", "Material": status[3]}
                log_status(course_title, module_title, lesson_title, new_status)
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                return True
            else:
                print(f"    ❌ Download failed: File not found or empty at {video_path}")
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                raise Exception("Download incomplete")
        except TimeoutException as e:
            print(f"    ❌ Timeout error on attempt {attempt + 1}/{MAX_RETRIES}: {e}")
            with open("debug_log.txt", "a") as f:
                f.write(f"Timeout in selenium_download_video: {driver.page_source[:1000]}\n")
            if attempt < MAX_RETRIES - 1:
                time.sleep(5)
                driver.refresh()
        except Exception as e:
            print(f"    ❌ Error downloading video {video_filename}: {e}")
            with open("debug_log.txt", "a") as f:
                traceback.print_exc(file=f)
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
            if attempt < MAX_RETRIES - 1:
                time.sleep(5)
                driver.refresh()
    return False

def login_to_kajabi():
    global DRIVER
    options = Options()
    options.add_argument('--start-maximized')
    options.add_argument('--force-device-scale-factor=0.5')
    options.add_experimental_option("prefs", {
        "profile.default_content_setting_values.notifications": 2,
        "profile.managed_default_content_settings.images": 1,
        "download.default_directory": BASE_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    })
    DRIVER = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    print("Opening Kajabi login page...")
    DRIVER.get(f"{KAJABI_URL}/login")

    try:
        WebDriverWait(DRIVER, 30).until(EC.presence_of_element_located((By.ID, "username"))).send_keys(EMAIL)
        DRIVER.find_element(By.ID, "password").send_keys(PASSWORD)
        DRIVER.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(5)
        if "dashboard" in DRIVER.current_url or "admin" in DRIVER.current_url:
            print("✅ Logged into Kajabi successfully!")
            return DRIVER
        else:
            print("❌ Login failed. Check credentials or 2FA.")
            DRIVER.quit()
            return None
    except Exception as e:
        print(f"❌ Login error: {e}")
        DRIVER.quit()
        return None

def get_all_courses(driver):
    print("🔍 Navigating to courses page...")
    driver.get("https://app.kajabi.com/admin/sites/100181/courses")
    time.sleep(5)

    course_cards = driver.find_elements(By.CSS_SELECTOR, "li.sage-catalog-item")
    courses = []
    for card in course_cards:
        try:
            title_elem = card.find_element(By.CSS_SELECTOR, "span.t-sage--truncate")
            link_elem = card.find_element(By.CSS_SELECTOR, "a.sage-link")
            title = title_elem.text.strip()
            url = link_elem.get_attribute("href")

            print(f"🟢 Found course: {title}")
            courses.append({
                "title": title,
                "url": "https://app.kajabi.com" + url if url.startswith("/") else url
            })

            safe_title = "".join(c if c.isalnum() or c in " _-–" else "_" for c in title)[:200]
            course_path = os.path.join(BASE_DIR, safe_title)
            os.makedirs(course_path, exist_ok=True)

        except Exception as e:
            print(f"⚠️ Error reading course card: {e}")
            with open("debug_log.txt", "a") as f:
                traceback.print_exc(file=f)

    return courses

def download_file_safe(url, local_path, label=None):
    for attempt in range(MAX_RETRIES):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            with requests.get(url, stream=True, headers=headers, timeout=TIMEOUT) as r:
                r.raise_for_status()
                total_length = int(r.headers.get('content-length', 0))
                progress = tqdm(total=total_length, unit='B', unit_scale=True, desc=os.path.basename(local_path), leave=False)
                with open(local_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            progress.update(len(chunk))
                progress.close()
                print(f"    ✅ Downloaded: {os.path.basename(local_path)}")
                return True
        except requests.exceptions.Timeout:
            print(f"    ❌ Timeout downloading {label}. Attempt {attempt + 1}/{MAX_RETRIES}")
            time.sleep(3)
        except Exception as e:
            print(f"    ❌ Download error {label}: {e}. Attempt {attempt + 1}/{MAX_RETRIES}")
            with open("debug_log.txt", "a") as f:
                traceback.print_exc(file=f)
            time.sleep(3)
    FAILED_DOWNLOADS.append({"file": label, "url": url, "error": "Max retries exceeded"})
    return False

def process_lesson(driver, lesson_url, lesson_title, lesson_path, lesson_counter, safe_lesson_base, course_title, module_title):
    while PAUSED:
        time.sleep(1)
    if INTERRUPTED:
        return

    desc_status, thumb_status, video_status, mat_status = get_lesson_status(course_title, module_title, safe_lesson_base)
    print(f"    🔍 Checking lesson: {lesson_title} - Status: Desc={desc_status}, Thumb={thumb_status}, Video={video_status}, Mat={mat_status}")

    status = {"Description": desc_status, "Thumbnail": thumb_status, "Video": video_status, "Material": mat_status}
    threads = []

    force_video_redownload = video_status in ["Queued", "Failed"]

    if not force_video_redownload and all(s in ["Success", "None"] for s in [desc_status, thumb_status, video_status, mat_status]):
        print(f"    ⏭️ All components already downloaded successfully. Skipping lesson: {safe_lesson_base}")
        return

    print(f"    🔍 Opening lesson page: {lesson_title}")
    driver.get(lesson_url)
    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    # Description
    if desc_status == "Failed":
        for attempt in range(MAX_RETRIES):
            try:
                description_elem = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.kjb-rte')))
                description_text = description_elem.text.strip()
                if description_text:
                    with open(os.path.join(lesson_path, "description.txt"), "w", encoding="utf-8") as f:
                        f.write(description_text)
                    print("    📝 Description saved.")
                    status["Description"] = "Success"
                    break
            except:
                try:
                    iframe = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe')))
                    driver.switch_to.frame(iframe)
                    body_elem = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'body#tinymce')))
                    description_text = body_elem.text.strip()
                    driver.switch_to.default_content()
                    if description_text:
                        with open(os.path.join(lesson_path, "description.txt"), "w", encoding="utf-8") as f:
                            f.write(description_text)
                        print("    📝 Description saved from iframe.")
                        status["Description"] = "Success"
                        break
                except Exception as e:
                    print(f"    ⚠️ Description not found. Attempt {attempt + 1}/{MAX_RETRIES}: {e}")
                    if attempt < MAX_RETRIES - 1:
                        print("    🔄 Refreshing page...")
                        driver.refresh()
                        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                    time.sleep(3)

    # Thumbnail
    if thumb_status == "Failed":
        for attempt in range(MAX_RETRIES):
            try:
                thumb_elem = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'img.img-thumbnail')))
                thumb_url = thumb_elem.get_attribute("src")
                thumb_filename = f"{safe_lesson_base}.jpg"
                thumb_path = get_unique_filename(lesson_path, thumb_filename)
                t = threading.Thread(target=download_file_safe, args=(thumb_url, thumb_path, thumb_filename))
                threads.append(t)
                t.start()
                print("    🖼️ Thumbnail queued for download.")
                status["Thumbnail"] = "Success"
                break
            except Exception as e:
                print(f"    ⚠️ Thumbnail not found. Attempt {attempt + 1}/{MAX_RETRIES}: {e}")
                if attempt < MAX_RETRIES - 1:
                    print("    🔄 Refreshing page...")
                    driver.refresh()
                    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                time.sleep(3)

    # Video
    if force_video_redownload or video_status == "Failed":
        for attempt in range(MAX_RETRIES):
            try:
                none_btn = driver.find_element(By.XPATH, '//button[.//em[text()="None"] and contains(@class, "sage-choice--active")]')
                print("    ⛔ Video skipped (None selected).")
                status["Video"] = "None"
                break
            except NoSuchElementException:
                video_filename = f"{safe_lesson_base}.mp4"
                video_path = get_unique_filename(lesson_path, video_filename)
                if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
                    if selenium_download_video(driver, lesson_url, video_path, video_filename, course_title, module_title, safe_lesson_base):
                        status["Video"] = "Success"
                        break
                    else:
                        print(f"    ❌ Video download failed after Selenium attempt {attempt + 1}/{MAX_RETRIES}")
                        if attempt < MAX_RETRIES - 1:
                            time.sleep(5)
                            driver.refresh()
                            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                else:
                    print(f"    ⚠️ Video already exists and valid: {video_filename}")
                    status["Video"] = "Success"
                    break
            except Exception as e:
                print(f"    ⚠️ Video processing error. Attempt {attempt + 1}/{MAX_RETRIES}: {e}")
                if attempt < MAX_RETRIES - 1:
                    print("    🔄 Refreshing page...")
                    driver.refresh()
                    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                time.sleep(3)
        else:
            print("    📹 No video available or all attempts failed.")
            status["Video"] = "Failed"
            FAILED_DOWNLOADS.append({"file": video_filename, "url": lesson_url, "error": "Max retries exceeded"})

    # Material
    if mat_status == "Failed":
        for attempt in range(MAX_RETRIES):
            try:
                resource_sections = driver.find_elements(By.CSS_SELECTOR, 'section.sage-sortable__item--card')
                if not resource_sections:
                    print("    📎 No material sections found.")
                    status["Material"] = "None"
                    break
                else:
                    material_found = False
                    for section in resource_sections:
                        try:
                            title_elem = section.find_element(By.CSS_SELECTOR, 'h1.sage-sortable__item-title')
                            resource_name = title_elem.text.strip()
                            download_link = section.find_element(By.CSS_SELECTOR, 'a.sage-btn--icon-only-download')
                            file_url = download_link.get_attribute("href")
                            file_ext = os.path.splitext(file_url.split("?")[0])[1]
                            safe_filename = "".join(c if c.isalnum() or c in " ._-–" else "_" for c in resource_name)[:200] + file_ext
                            file_path = get_unique_filename(lesson_path, safe_filename)
                            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                                print(f"    📎 Downloading material: {safe_filename}")
                                t = threading.Thread(target=download_file_safe, args=(file_url, file_path, safe_filename))
                                threads.append(t)
                                t.start()
                                material_found = True
                            else:
                                print(f"    ⚠️ Material already exists: {safe_filename}")
                                material_found = True
                        except Exception as e:
                            print(f"    ⚠️ Error processing material resource: {e}")
                    if material_found:
                        status["Material"] = "Success"
                        break
                    else:
                        status["Material"] = "None"
                        break
            except Exception as e:
                print(f"    ⚠️ Material section check failed. Attempt {attempt + 1}/{MAX_RETRIES}: {e}")
                if attempt < MAX_RETRIES - 1:
                    print("    🔄 Refreshing page...")
                    driver.refresh()
                    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                time.sleep(3)
            else:
                print("    📎 No materials available after retries.")
                status["Material"] = "None"

    for t in threads:
        t.join()
    log_status(course_title, module_title, safe_lesson_base, status)

def get_modules_and_lessons(driver, course_url, course_folder, course_title):
    print(f"\n📘 Scraping modules + lessons from course: {course_url}")
    for attempt in range(MAX_RETRIES):
        try:
            driver.get(course_url)
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(4)

            try:
                expand_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//button[.//span[contains(text(), "Expand All")]]')))
                expand_btn.click()
                print("    🔼 Clicked 'Expand All' button.")
                time.sleep(2)
            except:
                print("    ℹ️ 'Expand All' button not found.")

            lessons = []
            current_module_title = None
            module_path = None
            module_counter = 1
            lesson_counter = 1

            completed_lessons = get_completed_lessons()

            outline_items = WebDriverWait(driver, 30).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'section.kjb-outlinelist-item'))
            )
            for index, item in enumerate(outline_items):
                class_name = item.get_attribute("class")

                if "kjb-outlinelist-item--category" in class_name:
                    current_module_title = item.find_element(By.CSS_SELECTOR, 'span.sage-btn__truncate-text').text.strip()
                    module_folder_name = f"{module_counter:02d} - {current_module_title}"
                    safe_module = "".join(c if c.isalnum() or c in " _-–" else "_" for c in module_folder_name)[:200]
                    module_path = os.path.join(course_folder, safe_module)
                    os.makedirs(module_path, exist_ok=True)
                    print(f"\n📂 Module: {module_folder_name}")
                    module_counter += 1
                    lesson_counter = 1

                elif "kjb-outlinelist-item--depth-1" in class_name and module_path:
                    lesson_title = item.find_element(By.CSS_SELECTOR, 'span.sage-btn__truncate-text').text.strip()
                    lesson_link = item.find_element(By.CSS_SELECTOR, 'a[href*="/admin/posts/"]').get_attribute("href")
                    safe_lesson_base = f"{lesson_counter:02d} - {lesson_title}"
                    safe_lesson_base = "".join(c if c.isalnum() or c in " _-–" else "_" for c in safe_lesson_base)[:200]
                    lesson_key = f"{course_title}|{current_module_title}|{safe_lesson_base}"

                    desc_status, thumb_status, video_status, mat_status = get_lesson_status(course_title, current_module_title, safe_lesson_base)
                    if lesson_key in completed_lessons and all(s in ["Success", "None"] for s in [desc_status, thumb_status, video_status, mat_status]):
                        print(f"    ⏭️ Already downloaded. Skipping lesson: {safe_lesson_base}")
                        lesson_counter += 1
                        continue

                    print(f"  🎓 Lesson: {safe_lesson_base}")
                    lesson_path = os.path.join(module_path, safe_lesson_base)
                    os.makedirs(lesson_path, exist_ok=True)
                    lessons.append((lesson_link, lesson_title, lesson_path, lesson_counter, safe_lesson_base, current_module_title))
                    lesson_counter += 1

            with ThreadPoolExecutor(max_workers=MAX_LESSON_THREADS) as executor:
                executor.map(lambda args: process_lesson(driver, args[0], args[1], args[2], args[3], args[4], course_title, args[5]), lessons)
            return

        except TimeoutException as e:
            print(f"    ❌ Timeout error on attempt {attempt + 1}/{MAX_RETRIES}: {e}")
            with open("debug_log.txt", "a") as f:
                f.write(f"Timeout in get_modules_and_lessons: {driver.page_source[:1000]}\n")
            if attempt < MAX_RETRIES - 1:
                time.sleep(5)
                driver.refresh()
        except Exception as e:
            print(f"    ⚠️ Error parsing course: {e}")
            with open("debug_log.txt", "a") as f:
                traceback.print_exc(file=f)
            if attempt < MAX_RETRIES - 1:
                time.sleep(5)
                driver.refresh()
    print(f"    ❌ Failed to scrape course after {MAX_RETRIES} attempts.")
    FAILED_DOWNLOADS.append({"file": course_title, "url": course_url, "error": "Failed to scrape modules"})

if __name__ == "__main__":
    start_time = time.time()

    driver = login_to_kajabi()
    if driver:
        courses = get_all_courses(driver)
        print(f"\n📘 Found {len(courses)} courses.")

        for course in courses:
            course_title = course["title"]
            course_url = course["url"]
            safe_course = "".join(c if c.isalnum() or c in " _-–" else "_" for c in course_title)[:200]
            course_folder = os.path.join(BASE_DIR, safe_course)
            os.makedirs(course_folder, exist_ok=True)

            print(f"\n🚀 Processing course: {course_title}")
            get_modules_and_lessons(driver, course_url, course_folder, course_title)

        driver.quit()

    end_time = time.time()
    print(f"\n⏱️ Total time: {round(end_time - start_time, 2)} seconds")

    if FAILED_DOWNLOADS:
        with open("download_errors.txt", "w", encoding="utf-8") as f:
            for fail in FAILED_DOWNLOADS:
                f.write(f"[FAILED] {fail.get('file', fail.get('title'))}\nURL: {fail['url']}\nError: {fail['error']}\n\n")
        print(f"\n⚠️ Some downloads failed. Logged in 'download_errors.txt'")
    else:
        print("\n✅ All downloads completed without errors.")