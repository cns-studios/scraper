# Web Archiver & Viewer

This project is a comprehensive solution for scraping, archiving, and viewing websites. It consists of a powerful Python-based web scraper and a modern web interface for viewing the archives.

## Features

### Scraper

- **Asynchronous Scraping**: High-performance crawling using `aiohttp` and `asyncio`.
- **Configurable**: Control crawl depth, max pages, pages per domain, and more via the web interface or a `.env` file.
- **Polite**: Respects `robots.txt` and has configurable request delays.
- **Asset Handling**: Scrapes HTML, CSS, JavaScript, and images.
- **Optimization**: Optimizes images and minifies text-based assets before archiving.
- **Compression**: Archives scraped sites into compressed `.tar.zst` or `.tar.gz` files for efficient storage.

### Viewer

- **Web-Based Interface**: A modern, single-page application for managing and viewing web archives.
- **Archive Browser**: Browse and view the contents of your web archives.
- **Real-time Progress**: A real-time progress bar shows the status of active scraping jobs.
- **Global Search**: Search for content across all of your archives.
- **Efficient Serving**: Serves content directly from the scraped data directories.
- **Security**: Includes security best practices to prevent common vulnerabilities.

## Tech Stack

- **Backend**:
  - `aiohttp`: Asynchronous HTTP client/server.
  - `beautifulsoup4`: For parsing HTML and XML.
  - `Pillow`: Image processing library.
  - `python-dotenv`: For managing environment variables.
  - `htmlmin`, `csscompressor`, `jsmin`: For minifying assets.

- **Frontend**:
  - Vanilla JavaScript, HTML, and CSS.
  - No frameworks, keeping it simple and fast.

## Project Structure

```
/
├───.env                # Environment variables for configuration
├───main.py             # Main entry point for the Python scraper
├───scraper.py          # Core web scraping logic
├───compressor.py       # Compresses scraped files into an archive
├───optimizer.py        # Optimizes assets (images, CSS, JS)
├───server.py           # Main entry point for the web viewer server
├───requirements.txt    # Python dependencies
├───public/             # Static assets for the viewer frontend
│   ├───index.html      # Main HTML file for the web interface
│   ├───app.js          # JavaScript for the web interface
│   └───styles.css      # CSS for the web interface
├───scraped_data/       # Directory to save scraped data
└───archives/           # Directory to save compressed archives
```

## Setup and Installation

### Prerequisites

- Python 3.8+
- `pip`

### Configuration

1.  Create a `.env` file in the root of the project.
2.  Add the following configuration variables:

    ```env
    # --- Scraper Configuration ---
    START_URL="https://example.com"  # The initial URL to start scraping from
    MAX_DEPTH=3                      # Maximum crawl depth
    MAX_PAGES=100                    # Maximum number of pages to scrape
    PAGES_PER_DOMAIN=50              # Maximum pages to scrape from a single domain
    MAX_WORKERS=10                   # Number of concurrent scraping workers
    REQUEST_DELAY=0.5                # Delay in seconds between requests to the same domain
    RESPECT_ROBOTS_TXT=true          # Whether to respect robots.txt rules
    SKIP_ASSETS=false                # If true, skips scraping of CSS, JS, and images

    # --- Optimizer & Compressor Configuration ---
    IMAGE_QUALITY=85                 # Image quality for optimization (1-100)
    MAX_IMAGE_WIDTH=1920             # Maximum width for resized images
    COMPRESSION_LEVEL=19             # Zstandard compression level for the final archive

    # --- Directory Configuration ---
    OUTPUT_DIR="./scraped_data"      # Directory to save scraped data
    ARCHIVE_DIR="./archives"         # Directory to save compressed archives

    # --- Server Configuration ---
    PORT=8080                        # Port for the web viewer server
    ```

### Installation

1.  **Create a virtual environment**:
    ```bash
    python -m venv .venv
    ```

2.  **Activate the virtual environment**:
    - **Windows**:
      ```bash
      .venv\Scripts\activate
      ```
    - **macOS/Linux**:
      ```bash
      source .venv/bin/activate
      ```

3.  **Install Python dependencies**:
    ```bash
    pip install -r requirements.txt
    ```


## Usage

### 1. Starting the Web Viewer

To start the web viewer, run `server.py`:

```bash
python server.py
```

You can then access the viewer in your browser at `http://localhost:8080`.

### 2. Scraping and Archiving

You can start a new scraping job from the web interface. Navigate to the "New Scrape" tab, configure the scraping parameters, and click "Start Scraping". The progress bar will show the status of the scraping job in real-time.

Alternatively, you can run the scraper from the command line:

```bash
python main.py
```

The script will use the configuration from your `.env` file, scrape the target website, and create a compressed archive in the `archives` directory.

## Contributing

Contributions are welcome! Please feel free to submit a pull request.

1.  Fork the repository.
2.  Create your feature branch (`git checkout -b feature/AmazingFeature`).
3.  Commit your changes (`git commit -m 'feat: Add some AmazingFeature'`).
4.  Push to the branch (`git push origin feature/AmazingFeature`).
5.  Open a pull request.

## License

This project is licensed under the MIT License.
