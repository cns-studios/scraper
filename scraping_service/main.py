#!/usr/bin/env python3

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
import logging
import argparse
from dotenv import load_dotenv
from scraper import WebScraper
from compressor import WebCompressor
from utils import ensure_directories, save_json
import database

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('web_archiver.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

with open('web_archiver.log', 'w') as log_file:
    log_file.write("")

async def scrape_and_compress(non_interactive=False):
    with open('web_archiver.log', 'a') as log_file:
        """Main workflow: scrape and compress"""
        
        # Load configuration from environment
        start_url = os.getenv('START_URL', 'https://example.com')
        max_workers = int(os.getenv('MAX_WORKERS', 10))
        max_depth = int(os.getenv('MAX_DEPTH', 3))
        max_pages = int(os.getenv('MAX_PAGES', 100))
        pages_per_domain = int(os.getenv('PAGES_PER_DOMAIN', 50))
        output_dir = os.getenv('OUTPUT_DIR', './scraped_data')
        archive_dir = os.getenv('ARCHIVE_DIR', './archives')
        image_quality = int(os.getenv('IMAGE_QUALITY', 85))
        max_image_width = int(os.getenv('MAX_IMAGE_WIDTH', 1920))
        compression_level = int(os.getenv('COMPRESSION_LEVEL', 19))
        skip_assets = os.getenv('SKIP_ASSETS', 'false').lower() == 'true'
        respect_robots = os.getenv('RESPECT_ROBOTS_TXT', 'true').lower() == 'true'
        request_delay = float(os.getenv('REQUEST_DELAY', 0.5))
        
        logger.info("=" * 60)
        log_file.write("=" * 60 + "\n")
        logger.info("Web Archiver - Scraper & Compressor")
        log_file.write("Web Archiver - Scraper & Compressor\n")
        logger.info("=" * 60)
        log_file.write("=" * 60 + "\n")
        logger.info(f"Start URL: {start_url}")
        log_file.write(f"Start URL: {start_url}\n")
        logger.info(f"Max Depth: {max_depth}")
        log_file.write(f"Max Depth: {max_depth}\n")
        logger.info(f"Max Pages: {max_pages}")
        log_file.write(f"Max Pages: {max_pages}\n")
        logger.info(f"Pages per Domain: {pages_per_domain}")
        log_file.write(f"Pages per Domain: {pages_per_domain}\n")
        logger.info(f"Max Workers: {max_workers}")
        log_file.write(f"Max Workers: {max_workers}\n")
        logger.info(f"Skip Assets: {skip_assets}")
        log_file.write(f"Skip Assets: {skip_assets}\n")
        logger.info(f"Respect Robots.txt: {respect_robots}")
        log_file.write(f"Respect Robots.txt: {respect_robots}\n")
        logger.info(f"Request Delay: {request_delay}s")
        log_file.write(f"Request Delay: {request_delay}s\n")
        logger.info(f"Output Directory: {output_dir}")
        log_file.write(f"Output Directory: {output_dir}\n")
        logger.info(f"Archive Directory: {archive_dir}")
        log_file.write(f"Archive Directory: {archive_dir}\n")
        logger.info("=" * 60)
        log_file.write("=" * 60 + "\n")
        
        # Create timestamp for this run
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        run_output_dir = f"{output_dir}/{timestamp}"
    with open('web_archiver.log', 'a') as log_file:    
        # Ensure directories exist
        ensure_directories(run_output_dir, archive_dir)
        
        try:
            # Create a new run in the database
            run_id = database.create_run(start_url=start_url)
            if not run_id:
                logger.error("Failed to create a new run in the database. Aborting.")
                return

            # Phase 1: Scraping
            logger.info("\n📥 PHASE 1: Web Scraping")
            logger.info("-" * 40)
            log_file.write("\n📥 PHASE 1: Web Scraping\n")
            log_file.write("-" * 40 + "\n")
            
            scraper = WebScraper(
                start_url=start_url,
                run_id=run_id,
                output_dir=run_output_dir,
                max_workers=max_workers,
                max_depth=max_depth,
                max_pages=max_pages,
                pages_per_domain=pages_per_domain,
                respect_robots=respect_robots,
                request_delay=request_delay,
                skip_assets=skip_assets
            )
            
            scraped_data = await scraper.run()
            
            if not scraped_data:
                logger.warning("No data scraped. Exiting.")
                log_file.write("No data scraped. Exiting.\n")
                return
            
            logger.info(f"✅ Scraping complete. {len(scraped_data)} pages saved")
            log_file.write(f"✅ Scraping complete. {len(scraped_data)} pages saved\n")
            
            # Ask user if they want to continue with compression
            if len(scraped_data) >= max_pages * 0.9:  # If we hit near the limit
                logger.info(f"\n⚠️  Page limit reached ({len(scraped_data)}/{max_pages})")
                log_file.write(f"\n⚠️  Page limit reached ({len(scraped_data)}/{max_pages})\n")
                if not non_interactive:
                    user_input = input("Continue with compression? (y/n): ").lower()
                    if user_input != 'y':
                        logger.info("Compression skipped by user")
                        log_file.write("Compression skipped by user\n")
                        return
            
            # Phase 2: Compression
            logger.info("\n🗜️ PHASE 2: Optimization & Compression")
            logger.info("-" * 40)
            log_file.write("\n🗜️ PHASE 2: Optimization & Compression\n")
            log_file.write("-" * 40 + "\n")
            
            compressor = WebCompressor(
                source_dir=run_output_dir,
                archive_dir=archive_dir,
                compression_level=compression_level
            )
            
            # Set optimizer parameters
            compressor.optimizer.image_quality = image_quality
            compressor.optimizer.max_image_width = max_image_width
            
            compression_report = await compressor.compress()
            
            logger.info("\n" + "=" * 60)
            logger.info("✅ ARCHIVING COMPLETE")
            logger.info("=" * 60)
            log_file.write("\n" + "=" * 60 + "\n")
            log_file.write("✅ ARCHIVING COMPLETE\n")
            log_file.write("=" * 60 + "\n")
            logger.info(f"📦 Archive: {compression_report['archive_path']}")
            logger.info(f"📊 Original Size: {compression_report['original_size']:,} bytes")
            logger.info(f"📊 Compressed Size: {compression_report['compressed_size']:,} bytes")
            logger.info(f"📊 Compression Ratio: {compression_report['compression_ratio']}")
            logger.info("=" * 60)
            log_file.write(f"📦 Archive: {compression_report['archive_path']}\n")
            log_file.write(f"📊 Original Size: {compression_report['original_size']:,} bytes\n")
            log_file.write(f"📊 Compressed Size: {compression_report['compressed_size']:,} bytes\n")
            log_file.write(f"📊 Compression Ratio: {compression_report['compression_ratio']}\n")
            log_file.write("=" * 60 + "\n")
            
        except KeyboardInterrupt:
            logger.info("\n⚠️ Process interrupted by user")
            log_file.write("\n⚠️ Process interrupted by user\n")
        except Exception as e:
            logger.error(f"❌ Error in main workflow: {e}", exc_info=True)
            log_file.write(f"❌ Error in main workflow: {e}\n")
            raise

def main():
    """Entry point"""
    parser = argparse.ArgumentParser(description="Web Archiver")
    parser.add_argument(
        '--non-interactive',
        action='store_true',
        help="Run in non-interactive mode, skipping user prompts"
    )
    args = parser.parse_args()

    try:
        # Check Python version
        if sys.version_info < (3, 7):
            print("Python 3.7+ required")
            sys.exit(1)
        
        # Run the async workflow
        asyncio.run(scrape_and_compress(non_interactive=args.non_interactive))
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()