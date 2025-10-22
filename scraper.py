import asyncio
import aiohttp
import aiofiles
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import os
import json
import time
from datetime import datetime
from typing import Set, Dict, Optional, Tuple
from tqdm.asyncio import tqdm
import logging
from utils import URLFilter, RobotsChecker, ScraperStats, save_json, ensure_directories
import hashlib
import random

logger = logging.getLogger(__name__)

class WebScraper:
    def __init__(self, 
                 start_url: str, 
                 output_dir: str, 
                 max_workers: int = 10, 
                 max_depth: int = 3,
                 max_pages: int = 100,
                 pages_per_domain: int = 50,
                 respect_robots: bool = True,
                 request_delay: float = 0.5,
                 skip_assets: bool = False):
        
        self.start_url = start_url
        self.base_domain = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
        self.output_dir = output_dir
        self.max_workers = max_workers
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.pages_per_domain = pages_per_domain
        self.respect_robots = respect_robots
        self.request_delay = request_delay
        self.skip_assets = skip_assets
        
        self.visited_urls: Set[str] = set()
        self.scraped_data: Dict[str, dict] = {}
        self.asset_map: Dict[str, str] = {}  # Map original URLs to local paths
        self.failed_assets: Set[str] = set()  # Track failed assets to avoid retrying
        self.queue = asyncio.Queue()
        self.semaphore = asyncio.Semaphore(max_workers)
        self.robots_checker = RobotsChecker() if respect_robots else None
        self.stats = ScraperStats()
        self.domain_counts: Dict[str, int] = {}
        self.last_request_time: Dict[str, float] = {}
        
        # Store cookies per domain
        self.domain_cookies: Dict[str, Dict] = {}
        
        # Page limit tracking
        self.pages_scraped_count = 0
        self.should_stop = False
        self.stop_lock = asyncio.Lock()
        
        # User agents pool for rotation
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
        ]
        
        # Ensure output directories exist
        ensure_directories(
            output_dir, 
            f"{output_dir}/html", 
            f"{output_dir}/assets",
            f"{output_dir}/css",
            f"{output_dir}/js",
            f"{output_dir}/images",
            f"{output_dir}/fonts",
            f"{output_dir}/media"
        )
    
    def get_headers(self, referer: str = None, is_asset: bool = False) -> Dict:
        """Get headers that mimic a real browser"""
        headers = {
            'User-Agent': random.choice(self.user_agents),
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        if is_asset:
            # Asset-specific headers
            headers.update({
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Sec-Fetch-Dest': 'image',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'same-origin',
            })
        else:
            # Page headers
            headers.update({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
            })
        
        if referer:
            headers['Referer'] = referer
            
        return headers
    
    def get_asset_local_path(self, url: str, asset_type: str) -> str:
        """Generate local path for an asset"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        
        # Try to preserve file extension
        parsed_path = urlparse(url).path
        ext = os.path.splitext(parsed_path)[1] or '.bin'
        
        # Clean up extension
        if '?' in ext:
            ext = ext.split('?')[0]
        if not ext or len(ext) > 10:  # Sanity check
            if asset_type == 'image':
                ext = '.jpg'
            elif asset_type == 'css':
                ext = '.css'
            elif asset_type == 'js':
                ext = '.js'
            else:
                ext = '.bin'
        
        # Determine subdirectory based on asset type
        if asset_type in ['image', 'img']:
            subdir = 'images'
        elif asset_type == 'css':
            subdir = 'css'
        elif asset_type in ['js', 'javascript']:
            subdir = 'js'
        elif asset_type == 'font':
            subdir = 'fonts'
        elif asset_type in ['video', 'audio', 'media']:
            subdir = 'media'
        else:
            subdir = 'assets'
        
        return f"{subdir}/{url_hash}{ext}"
    
    async def download_asset(self, session: aiohttp.ClientSession, url: str, asset_type: str, referer: str = None) -> Optional[str]:
        with open('web_archiver.log', 'a') as log_file:
            """Download an asset and return its local path"""
            try:
                # Skip if already downloaded or failed before
                if url in self.asset_map:
                    return self.asset_map[url]
                
                if url in self.failed_assets:
                    return None
                
                # Clean URL (remove fragments)
                clean_url = url.split('#')[0]
                
                # Apply rate limiting
                domain = urlparse(clean_url).netloc
                await self.apply_rate_limit(domain)
                
                # Get appropriate headers
                headers = self.get_headers(referer=referer, is_asset=True)
                
                # Add cookies if we have them for this domain
                cookies = self.domain_cookies.get(domain, {})
                
                async with self.semaphore:
                    try:
                        async with session.get(
                            clean_url, 
                            timeout=30, 
                            ssl=False,
                            headers=headers,
                            cookies=cookies,
                            allow_redirects=True
                        ) as response:
                            
                            # Handle different response codes
                            if response.status == 200:
                                content = await response.read()
                                
                                # Generate local path
                                local_path = self.get_asset_local_path(clean_url, asset_type)
                                full_path = f"{self.output_dir}/{local_path}"
                                
                                # Save asset
                                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                                
                                if asset_type in ['css', 'js']:
                                    # Text assets
                                    try:
                                        text_content = content.decode('utf-8', errors='ignore')
                                        async with aiofiles.open(full_path, 'w', encoding='utf-8') as f:
                                            await f.write(text_content)
                                    except:
                                        # If decode fails, save as binary
                                        async with aiofiles.open(full_path, 'wb') as f:
                                            await f.write(content)
                                else:
                                    # Binary assets
                                    async with aiofiles.open(full_path, 'wb') as f:
                                        await f.write(content)
                                
                                # Store mapping
                                self.asset_map[url] = local_path
                                logger.debug(f"Downloaded asset: {url} -> {local_path}")
                                log_file.write(f"Downloaded asset: {url} -> {local_path}\n")
                                
                                return local_path
                                
                            elif response.status == 403:
                                # Try alternative approach for 403
                                logger.debug(f"403 for asset {url}, trying with different headers")
                                log_file.write(f"403 for asset {url}, trying with different headers\n")
                                
                                # Try with minimal headers
                                minimal_headers = {
                                    'User-Agent': headers['User-Agent']
                                }
                                
                                async with session.get(
                                    clean_url,
                                    timeout=30,
                                    ssl=False,
                                    headers=minimal_headers
                                ) as retry_response:
                                    if retry_response.status == 200:
                                        content = await retry_response.read()
                                        local_path = self.get_asset_local_path(clean_url, asset_type)
                                        full_path = f"{self.output_dir}/{local_path}"
                                        
                                        os.makedirs(os.path.dirname(full_path), exist_ok=True)
                                        async with aiofiles.open(full_path, 'wb') as f:
                                            await f.write(content)
                                        
                                        self.asset_map[url] = local_path
                                        return local_path
                                    else:
                                        logger.warning(f"Failed to download asset {url}: HTTP {retry_response.status}")
                                        log_file.write(f"Failed to download asset {url}: HTTP {retry_response.status}\n")
                                        self.failed_assets.add(url)
                                        return None
                            else:
                                logger.warning(f"Failed to download asset {url}: HTTP {response.status}")
                                log_file.write(f"Failed to download asset {url}: HTTP {response.status}\n")
                                self.failed_assets.add(url)
                                return None
                                
                    except asyncio.TimeoutError:
                        logger.warning(f"Timeout downloading asset {url}")
                        log_file.write(f"Timeout downloading asset {url}\n")
                        self.failed_assets.add(url)
                        return None
                        
            except Exception as e:
                logger.error(f"Error downloading asset {url}: {e}")
                log_file.write(f"Error downloading asset {url}: {e}\n")
                self.failed_assets.add(url)
                return None
    
    async def rewrite_html_urls(self, html: str, base_url: str, session: aiohttp.ClientSession) -> str:
        """Rewrite URLs in HTML to point to local assets"""
        soup = BeautifulSoup(html, 'lxml')
        
        # Process different types of assets
        asset_tasks = []
        
        # Images
        for img in soup.find_all(['img', 'source', 'picture']):
            for attr in ['src', 'srcset', 'data-src', 'data-srcset', 'data-lazy-src']:
                if img.get(attr):
                    urls = []
                    # Handle srcset which can have multiple URLs
                    if 'srcset' in attr:
                        srcset_parts = img[attr].split(',')
                        for part in srcset_parts:
                            url_part = part.strip().split(' ')[0]
                            if url_part:
                                urls.append(url_part)
                    else:
                        urls.append(img[attr])
                    
                    for url in urls:
                        if url and not url.startswith('data:'):
                            absolute_url = urljoin(base_url, url)
                            asset_tasks.append((img, attr, url, absolute_url, 'image'))
        
        # CSS files
        for link in soup.find_all('link'):
            if link.get('rel') and 'stylesheet' in link.get('rel') and link.get('href'):
                url = link['href']
                if not url.startswith('data:'):
                    absolute_url = urljoin(base_url, url)
                    asset_tasks.append((link, 'href', url, absolute_url, 'css'))
        
        # JavaScript files
        for script in soup.find_all('script'):
            if script.get('src'):
                url = script['src']
                if not url.startswith('data:'):
                    absolute_url = urljoin(base_url, url)
                    asset_tasks.append((script, 'src', url, absolute_url, 'js'))
        
        # Fonts in link tags
        for link in soup.find_all('link'):
            if link.get('rel') and 'font' in str(link.get('rel')) and link.get('href'):
                url = link['href']
                if not url.startswith('data:'):
                    absolute_url = urljoin(base_url, url)
                    asset_tasks.append((link, 'href', url, absolute_url, 'font'))
        
        # Video and audio
        for media in soup.find_all(['video', 'audio', 'source']):
            if media.get('src'):
                url = media['src']
                if not url.startswith('data:'):
                    absolute_url = urljoin(base_url, url)
                    asset_tasks.append((media, 'src', url, absolute_url, 'media'))
        
        # CSS in style tags (for url() references)
        for style in soup.find_all('style'):
            if style.string:
                style.string = await self.rewrite_css_urls(style.string, base_url, session)
        
        # Inline styles with url()
        for element in soup.find_all(style=True):
            element['style'] = await self.rewrite_css_urls(element['style'], base_url, session)
        
        # Download assets and update URLs
        if not self.skip_assets:
            # Process assets with referer header
            for element, attr, original_url, absolute_url, asset_type in asset_tasks:
                local_path = await self.download_asset(session, absolute_url, asset_type, referer=base_url)
                if local_path:
                    # Update the URL to point to local file
                    # Use relative path from html directory
                    relative_path = f"../{local_path}"
                    
                    if 'srcset' in attr:
                        # Handle srcset specially
                        srcset_parts = element[attr].split(',')
                        new_srcset = []
                        for part in srcset_parts:
                            part_items = part.strip().split(' ')
                            if part_items[0] == original_url:
                                part_items[0] = relative_path
                            new_srcset.append(' '.join(part_items))
                        element[attr] = ', '.join(new_srcset)
                    else:
                        element[attr] = relative_path
                else:
                    # If download failed, keep original URL but make it absolute
                    if not original_url.startswith(('http://', 'https://', '//')):
                        element[attr] = absolute_url
        
        # Process links to make them work locally
        for a in soup.find_all('a', href=True):
            href = a['href']
            if not href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                absolute_url = urljoin(base_url, href)
                # Check if we have this page
                if absolute_url in self.visited_urls:
                    # Link to local HTML file
                    url_hash = URLFilter.get_url_hash(absolute_url)
                    a['href'] = f"{url_hash}.html"
                else:
                    # Keep as external link but make it absolute
                    a['href'] = absolute_url
        
        return str(soup)
    
    async def rewrite_css_urls(self, css_content: str, base_url: str, session: aiohttp.ClientSession) -> str:
        """Rewrite URLs in CSS content"""
        import re
        
        # Find all url() references
        url_pattern = r'urlKATEX_INLINE_OPEN[\'"]?([^\'")]+)[\'"]?KATEX_INLINE_CLOSE'
        
        urls = re.findall(url_pattern, css_content)
        for url in urls:
            if not url.startswith('data:'):
                absolute_url = urljoin(base_url, url)
                
                # Determine asset type from URL
                asset_type = 'image'  # Default
                if '.woff' in url or '.ttf' in url or '.eot' in url or '.otf' in url:
                    asset_type = 'font'
                
                local_path = await self.download_asset(session, absolute_url, asset_type, referer=base_url)
                if local_path:
                    relative_path = f"../{local_path}"
                    # Replace all variations of the URL reference
                    css_content = css_content.replace(f'url({url})', f'url({relative_path})')
                    css_content = css_content.replace(f'url("{url}")', f'url("{relative_path}")')
                    css_content = css_content.replace(f"url('{url}')", f'url("{relative_path}")')
        
        return css_content
    
    async def fetch_page(self, session: aiohttp.ClientSession, url: str) -> Optional[Tuple[str, str, Dict]]:
        with open('web_archiver.log', 'a') as log_file:
            """Fetch a single page and return content, content-type, and cookies"""
            try:
                # Check robots.txt
                if self.robots_checker:
                    can_fetch = await self.robots_checker.can_fetch(url, 'WebArchiver/1.0')
                    if not can_fetch:
                        logger.info(f"Robots.txt disallows: {url}")
                        log_file.write(f"Robots.txt disallows: {url}\n")
                        return None
                
                # Apply rate limiting
                domain = urlparse(url).netloc
                await self.apply_rate_limit(domain)
                
                # Get headers for page request
                headers = self.get_headers()
                
                async with self.semaphore:
                    async with session.get(
                        url, 
                        timeout=30, 
                        ssl=False,
                        headers=headers,
                        allow_redirects=True
                    ) as response:
                        if response.status == 200:
                            content = await response.text()
                            content_type = response.headers.get('Content-Type', '')
                            
                            # Store cookies for this domain
                            if response.cookies:
                                self.domain_cookies[domain] = dict(response.cookies)
                            
                            return content, content_type, dict(response.cookies)
                        else:
                            logger.warning(f"HTTP {response.status} for {url}")
                            log_file.write(f"HTTP {response.status} for {url}\n")
                            return None
                            
            except asyncio.TimeoutError:
                logger.warning(f"Timeout fetching {url}")
                log_file.write(f"Timeout fetching {url}\n")
                self.stats.add_failed()
            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")
                log_file.write(f"Error fetching {url}: {e}\n")
                self.stats.add_failed()
            return None
    
    async def check_limits(self, url: str) -> bool:
        with open('web_archiver.log', 'a') as log_file:
            """Check if we should continue scraping based on limits"""
            async with self.stop_lock:
                # Check global page limit
                if self.pages_scraped_count >= self.max_pages:
                    if not self.should_stop:
                        logger.info(f"Reached maximum page limit: {self.max_pages}")
                        log_file.write(f"Reached maximum page limit: {self.max_pages}\n")
                        self.should_stop = True
                    return False

                # Check per-domain limit
                domain = urlparse(url).netloc
                domain_count = self.domain_counts.get(domain, 0)

                if domain_count >= self.pages_per_domain:
                    logger.warning(f"Reached limit for domain {domain}: {self.pages_per_domain} pages")
                    log_file.write(f"Reached limit for domain {domain}: {self.pages_per_domain} pages\n")
                    return False

                return True
    
    async def apply_rate_limit(self, domain: str):
        """Apply rate limiting per domain"""
        if self.request_delay > 0:
            last_time = self.last_request_time.get(domain, 0)
            elapsed = time.time() - last_time
            
            if elapsed < self.request_delay:
                await asyncio.sleep(self.request_delay - elapsed)
            
            self.last_request_time[domain] = time.time()
    
    def extract_urls(self, html: str, base_url: str) -> Set[str]:
        with open('web_archiver.log', 'a') as log_file:
            """Extract all URLs from HTML"""
            urls = set()
            try:
                soup = BeautifulSoup(html, 'lxml')
                
                # Extract from links
                for tag in soup.find_all(['a', 'area']):
                    url = tag.get('href')
                    if url:
                        absolute_url = urljoin(base_url, url)
                        if URLFilter.should_scrape(absolute_url, self.base_domain):
                            urls.add(absolute_url)
                            
            except Exception as e:
                logger.error(f"Error extracting URLs: {e}")
                
            return urls
    
    async def save_page_content(self, url: str, content: str, content_type: str) -> Optional[str]:
        """Save page content to disk"""
        try:
            url_hash = URLFilter.get_url_hash(url)
            
            # Always save HTML files in the html directory
            if 'html' in content_type or 'text' in content_type:
                filepath = f"{self.output_dir}/html/{url_hash}.html"
            else:
                # Other content types
                ext = '.txt'
                if 'json' in content_type:
                    ext = '.json'
                elif 'xml' in content_type:
                    ext = '.xml'
                filepath = f"{self.output_dir}/html/{url_hash}{ext}"
            
            async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
                await f.write(content)
            
            return filepath
            
        except Exception as e:
            with open('web_archiver.log', 'a') as log_file:
                logger.error(f"Error saving content for {url}: {e}")
                log_file.write(f"Error saving content for {url}: {e}\n")
            return None
    
    async def process_url(self, session: aiohttp.ClientSession, url: str, depth: int):
        """Process a single URL"""
        if self.should_stop:
            return
            
        if url in self.visited_urls or depth > self.max_depth:
            return
        
        # Check limits before processing
        if not await self.check_limits(url):
            return
        
        self.visited_urls.add(url)
        
        # Fetch page
        result = await self.fetch_page(session, url)
        if not result:
            return
        
        content, content_type, cookies = result
        
        # Update counters
        async with self.stop_lock:
            self.pages_scraped_count += 1
            if self.pages_scraped_count >= self.max_pages:
                self.should_stop = True

        domain = urlparse(url).netloc
        self.domain_counts[domain] = self.domain_counts.get(domain, 0) + 1
        
        # Store cookies for this domain
        if cookies:
            self.domain_cookies[domain] = cookies
        
        # Update stats
        self.stats.add_page(url, len(content))
        
        # Process HTML content
        if 'html' in content_type:
            # Rewrite URLs to point to local assets
            content = await self.rewrite_html_urls(content, url, session)
        
        # Save content
        filepath = await self.save_page_content(url, content, content_type)
        
        # Store metadata
        self.scraped_data[url] = {
            'url': url,
            'timestamp': datetime.now().isoformat(),
            'content_type': content_type,
            'filepath': filepath,
            'depth': depth,
            'size': len(content),
            'domain': domain
        }
        
        # Log progress
        logger.info(f"Progress: {self.pages_scraped_count}/{self.max_pages} pages scraped, {len(self.asset_map)} assets downloaded")
        
        # Extract and queue new URLs if HTML
        if 'html' in content_type and not self.should_stop:
            new_urls = self.extract_urls(content, url)
            for new_url in new_urls:
                if new_url not in self.visited_urls and not self.should_stop:
                    await self.queue.put((new_url, depth + 1))
    
    async def worker(self, session: aiohttp.ClientSession, pbar: tqdm):
        """Worker to process URLs from queue"""
        while not self.should_stop:
            try:
                url, depth = await asyncio.wait_for(self.queue.get(), timeout=5)
                
                if self.should_stop:
                    break
                    
                await self.process_url(session, url, depth)
                pbar.update(1)
                with open('web_archiver.log', 'a') as log_file:
                    log_file.write(f"#{self.pages_scraped_count}; {self.max_pages}; {len(self.asset_map)} \n")
                pbar.set_description(f"Pages: {self.pages_scraped_count}/{self.max_pages}, Assets: {len(self.asset_map)}")
                self.queue.task_done()
                
            except asyncio.TimeoutError:
                if self.queue.empty():
                    break
            except Exception as e:
                with open('web_archiver.log', 'a') as log_file:
                    logger.error(f"Worker error: {e}")
                    log_file.write(f"Worker error: {e}\n")
    
    async def run(self):
        with open('web_archiver.log', 'a') as log_file:
            """Run the scraper"""
            logger.info(f"Starting scraper for {self.start_url}")
            log_file.write(f"Starting scraper for {self.start_url}\n")
            logger.info(f"Limits: max_pages={self.max_pages}, pages_per_domain={self.pages_per_domain}")
            log_file.write(f"Limits: max_pages={self.max_pages}, pages_per_domain={self.pages_per_domain}\n")
            logger.info(f"Settings: max_depth={self.max_depth}, workers={self.max_workers}")
            log_file.write(f"Settings: max_depth={self.max_depth}, workers={self.max_workers}\n")
            
            # Initialize session with cookie jar
            timeout = aiohttp.ClientTimeout(total=60)
            connector = aiohttp.TCPConnector(
                limit=100, 
                limit_per_host=30,
                force_close=True
            )
            
            # Use cookie jar for session
            jar = aiohttp.CookieJar()
            
            async with aiohttp.ClientSession(
                timeout=timeout, 
                connector=connector,
                cookie_jar=jar
            ) as session:
                
                # Add start URL to queue
                await self.queue.put((self.start_url, 0))
                
                # Create progress bar
                with tqdm(
                    desc=f"Scraping (0/{self.max_pages})", 
                    unit="pages",
                    total=self.max_pages
                ) as pbar:
                    # Start workers
                    workers = [
                        asyncio.create_task(self.worker(session, pbar))
                        for _ in range(self.max_workers)
                    ]
                    
                    # Monitoring task to check for completion
                    async def monitor():
                        while not self.should_stop:
                            await asyncio.sleep(0.5)

                        # Once stop is signaled, empty the queue
                        while not self.queue.empty():
                            self.queue.get_nowait()
                            self.queue.task_done()

                    monitor_task = asyncio.create_task(monitor())
                    
                    # Wait for all initial tasks to complete
                    await self.queue.join()
                    self.should_stop = True # Ensure stop is signaled
                    
                    # Cancel monitor and workers
                    monitor_task.cancel()
                    for worker in workers:
                        worker.cancel()
                    
                    await asyncio.gather(*workers, return_exceptions=True)
            
            # Get final stats
            final_stats = self.stats.get_stats()
            
            # Save metadata
            metadata_path = f"{self.output_dir}/metadata.json"
            save_json({
                'start_url': self.start_url,
                'total_pages': len(self.scraped_data),
                'pages_scraped': self.pages_scraped_count,
                'max_pages_limit': self.max_pages,
                'pages_per_domain_limit': self.pages_per_domain,
                'timestamp': datetime.now().isoformat(),
                'stats': final_stats,
                'domain_counts': self.domain_counts,
                'pages': self.scraped_data,
                'asset_map': self.asset_map,
                'failed_assets': list(self.failed_assets)
            }, metadata_path)
            
            # Log summary
            logger.info("=" * 60)
            log_file.write("=" * 60 + "\n")
            logger.info("Scraping Summary:")
            log_file.write("Scraping Summary:\n")
            logger.info(f"  Pages scraped: {self.pages_scraped_count}/{self.max_pages}")
            log_file.write(f"  Pages scraped: {self.pages_scraped_count}/{self.max_pages}\n")
            logger.info(f"  Assets downloaded: {len(self.asset_map)}")
            log_file.write(f"  Assets downloaded: {len(self.asset_map)}\n")
            logger.info(f"  Failed assets: {len(self.failed_assets)}")
            log_file.write(f"  Failed assets: {len(self.failed_assets)}\n")
            logger.info(f"  Pages failed: {final_stats['pages_failed']}")
            log_file.write(f"  Pages failed: {final_stats['pages_failed']}\n")
            logger.info(f"  Data downloaded: {final_stats['bytes_downloaded']:,} bytes")
            log_file.write(f"  Data downloaded: {final_stats['bytes_downloaded']:,} bytes\n")
            logger.info(f"  Time elapsed: {final_stats['elapsed_seconds']:.2f} seconds")
            log_file.write(f"  Time elapsed: {final_stats['elapsed_seconds']:.2f} seconds\n")
            logger.info(f"  Pages/second: {final_stats['pages_per_second']:.2f}")
            log_file.write(f"  Pages/second: {final_stats['pages_per_second']:.2f}\n")
            logger.info(f"  Domains scraped: {final_stats['total_domains']}")
            log_file.write(f"  Domains scraped: {final_stats['total_domains']}\n")
            
            if self.domain_counts:
                logger.info("\nTop domains:")
                log_file.write("\nTop domains:\n")
                for domain, count in sorted(self.domain_counts.items(), 
                                        key=lambda x: x[1], reverse=True)[:5]:
                    logger.info(f"    {domain}: {count} pages")
                    log_file.write(f"    {domain}: {count} pages\n")
            
            logger.info("=" * 60)
            log_file.write("=" * 60 + "\n")
            
            return self.scraped_data