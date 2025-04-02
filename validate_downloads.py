import os
import csv
from datetime import datetime

# Configuration
LOG_FILE = "download_log.csv"
BASE_DIR = os.getenv('KAJABI_DOWNLOAD_DIR', os.path.join(os.path.expanduser('~'), 'Kajabi_Courses'))
OUTPUT_FILE = "validation_results.csv"

# Supported file extensions
DESCRIPTION_EXT = ".txt"
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".m4v", ".m4a", ".m4b", ".m4p", ".m4v", ".m4a", ".m4b", ".m4p"}
MATERIAL_EXTS = {".pdf", ".mp3", ".docx", ".zip", ".wav", ".jpg", ".png", ".jpeg", ".gif", ".svg", ".webp"}
THUMBNAIL_EXT = {".jpg", ".png", ".jpeg", ".gif", ".svg", ".webp"}

def normalize_name(name):
    """Normalize a name by replacing parentheses with underscores to match download script sanitization."""
    return "".join(c if c.isalnum() or c in " _-–" else "_" for c in name).strip()

def find_module_dir(base_path, module_name):
    """Find a module directory, ignoring numeric prefix and matching sanitized names."""
    if not os.path.exists(base_path):
        return None
    normalized_module = normalize_name(module_name)
    for dir_name in os.listdir(base_path):
        if os.path.isdir(os.path.join(base_path, dir_name)):
            clean_dir_name = dir_name.split(" - ", 1)[-1] if " - " in dir_name else dir_name
            normalized_dir = normalize_name(clean_dir_name)
            if normalized_dir == normalized_module:
                return dir_name
            if dir_name == module_name:
                return dir_name
    return None

def validate_log_entry(entry, base_dir):
    """Validate a single log entry against the filesystem, adjusting for flattened hierarchy."""
    discrepancies = []
    validated_status = {
        "Timestamp": entry["Timestamp"],
        "Course": entry["Course"],
        "Module": entry["Module"],
        "Lesson": entry["Lesson"],
        "Description": "Failed",
        "Thumbnail": "Failed",
        "Video": "Failed",
        "Material": "Failed"
    }
    
    course = normalize_name(entry["Course"])  # Normalize course name
    module = entry["Module"]
    lesson = entry["Lesson"]
    course_path = os.path.join(base_dir, course)
    
    if not os.path.exists(course_path):
        discrepancies.append(f"Course directory not found: {course_path}")
        return validated_status, discrepancies
    
    # Try finding the module directory first
    module_dir = find_module_dir(course_path, module)
    if module_dir:
        # Construct lesson path assuming standard hierarchy
        lesson_path = os.path.join(course_path, module_dir, lesson)
        if not os.path.exists(lesson_path):
            # Fallback: Check if module_dir itself is the target directory
            lesson_path = os.path.join(course_path, module_dir)
            if not os.path.exists(lesson_path):
                existing_dirs = [d for d in os.listdir(course_path) if os.path.isdir(os.path.join(course_path, d))]
                discrepancies.append(f"Lesson directory missing: {lesson_path}. Existing dirs in course: {', '.join(existing_dirs) or 'None'}")
                return validated_status, discrepancies
    else:
        # Fallback: Module might be prefixed directly in course
        prefixed_module = f"{lesson.split(' - ')[0]} - {module}"
        module_dir = find_module_dir(course_path, prefixed_module)
        if module_dir:
            lesson_path = os.path.join(course_path, module_dir)
        else:
            existing_dirs = [d for d in os.listdir(course_path) if os.path.isdir(os.path(course_path, d))]
            discrepancies.append(f"Module directory not found for '{module}' in {course_path}. Existing dirs: {', '.join(existing_dirs) or 'None'}")
            return validated_status, discrepancies
    
    # Get all files in the lesson directory
    all_files = [f for f in os.listdir(lesson_path) if os.path.isfile(os.path.join(lesson_path, f))]
    
    # Validate Description
    description_files = [f for f in all_files if f.endswith(DESCRIPTION_EXT)]
    if description_files:
        validated_status["Description"] = "Success"
    elif entry["Description"] == "Success":
        discrepancies.append(f"Description marked Success but no .txt file found in: {lesson_path}. Files: {', '.join(all_files) or 'None'}")
    
    # Validate Thumbnail
    thumbnail_file = f"{lesson}{THUMBNAIL_EXT}"
    thumbnail_found = any(f.lower() == thumbnail_file.lower() for f in all_files)
    if thumbnail_found:
        validated_status["Thumbnail"] = "Success"
    elif entry["Thumbnail"] == "Success":
        discrepancies.append(f"Thumbnail marked Success but no {thumbnail_file} found in: {lesson_path}. Files: {', '.join(all_files) or 'None'}")
    
    # Validate Video
    video_files = [f for f in all_files if os.path.splitext(f)[1].lower() in VIDEO_EXTS]
    if video_files:
        validated_status["Video"] = "Success"
    elif entry["Video"] == "Success":
        discrepancies.append(f"Video marked Success but no video files ({', '.join(VIDEO_EXTS)}) found in: {lesson_path}. Files: {', '.join(all_files) or 'None'}")
    
    # Validate Material
    exclude_files = {thumbnail_file} | {f for f in description_files} | {f for f in video_files}
    material_files = [f for f in all_files if os.path.splitext(f)[1].lower() in MATERIAL_EXTS and f not in exclude_files]
    if material_files:
        validated_status["Material"] = "Success"
    elif entry["Material"] == "Success":
        discrepancies.append(f"Material marked Success but no material files ({', '.join(MATERIAL_EXTS)}) found in: {lesson_path}. Files: {', '.join(all_files) or 'None'}")
    
    return validated_status, discrepancies

def validate_download_log(log_file, base_dir, output_file):
    """Validate the download log and write results to a new CSV."""
    print(f"Validating download log: {log_file}")
    print(f"Against directory: {base_dir}")
    print(f"Writing results to: {output_file}")
    print("-" * 50)
    
    if not os.path.exists(log_file):
        print(f"❌ Log file not found: {log_file}")
        return
    
    if not os.path.exists(base_dir):
        print(f"❌ Base directory not found: {base_dir}")
        return
    
    headers = ["Timestamp", "Course", "Module", "Lesson", "Description", "Thumbnail", "Video", "Material"]
    validated_entries = []
    
    with open(log_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        total_entries = 0
        discrepancies_found = 0
        
        for entry in reader:
            total_entries += 1
            validated_status, issues = validate_log_entry(entry, base_dir)
            validated_entries.append(validated_status)
            
            if issues:
                discrepancies_found += 1
                print(f"\nEntry: {entry['Timestamp']} - {entry['Course']} > {entry['Module']} > {entry['Lesson']}")
                for issue in issues:
                    print(f"  ⚠️ {issue}")
        
        with open(output_file, "w", newline='', encoding="utf-8") as out_f:
            writer = csv.DictWriter(out_f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(validated_entries)
        
        print("-" * 50)
        print(f"Validation complete!")
        print(f"Total entries checked: {total_entries}")
        print(f"Entries with discrepancies: {discrepancies_found}")
        print(f"Results saved to: {output_file}")
        if discrepancies_found == 0:
            print("✅ All entries match the filesystem!")

if __name__ == "__main__":
    validate_download_log(LOG_FILE, BASE_DIR, OUTPUT_FILE)