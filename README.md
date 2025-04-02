# Kajabi Course Downloader

A powerful Python-based tool for downloading courses from Kajabi platform. This tool allows you to download course content including videos and materials while maintaining the course structure.

## Features

- 🔄 Parallel downloading with configurable thread count
- 📊 Progress tracking with detailed logging
- ⏸️ Pause/Resume functionality
- 🔍 Automatic retry mechanism for failed downloads
- 📁 Organized course structure preservation
- 🔒 Secure credential management using environment variables
- 📝 Detailed download logs and error tracking

## Prerequisites

- Python 3.7 or higher
- Chrome browser installed
- Internet connection
- Kajabi account credentials

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/kajabi-course-downloader.git
cd kajabi-course-downloader
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On Unix or MacOS
source venv/bin/activate
```

3. Install required packages:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root with your Kajabi credentials:
```
KAJABI_EMAIL=your_email@example.com
KAJABI_PASSWORD=your_password
```

5. Configure the application by editing `config.ini`:
```ini
[Download]
max_retries = 3
timeout = 60

[Paths]
base_dir = Kajabi_Courses

[Threads]
max_lesson_threads = 3
```

## Usage

1. Run the main script:
```bash
python kajabi.py
```

2. The script will:
   - Log in to your Kajabi account
   - Fetch all available courses
   - Create a structured folder hierarchy
   - Download course content with progress tracking

3. Control options:
   - Press `Ctrl+C` once to pause the download
   - Press `Ctrl+C` again to resume
   - Press `Ctrl+C` twice quickly to exit

## Project Structure

```
├── kajabi.py              # Main script
├── config.ini            # Configuration file
├── .env                  # Credentials (not in repo)
├── requirements.txt      # Python dependencies
├── debug_log.txt        # Detailed debug logs
├── download_log.csv     # Download progress tracking
├── validation_results.csv # Download validation results
└── Kajabi_Courses/      # Downloaded course content
```

## Logging and Monitoring

- `debug_log.txt`: Contains detailed debug information
- `download_log.csv`: Tracks download progress and status
- `validation_results.csv`: Contains validation results for downloaded content
- `download_errors.txt`: Records any download failures

## Error Handling

The script includes robust error handling:
- Automatic retries for failed downloads
- Detailed error logging
- Download validation
- Graceful interruption handling

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This tool is for personal use only. Please ensure you have the right to download and store the course content. Respect the terms of service of the Kajabi platform and the course creators' rights.

## Support

If you encounter any issues or have questions, please open an issue in the GitHub repository. 