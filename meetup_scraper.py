#!/usr/bin/env python3
"""
Meetup.com Group Past Events Scraper

A command line tool to access past events for a specific Meetup group.
Handles login detection and session persistence with comprehensive data extraction.
"""

import time
import json
import re
import logging
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
from pathlib import Path

import click
from playwright.sync_api import sync_playwright, Page, BrowserContext


# =============================================================================
# CONFIGURATION AND CONSTANTS
# =============================================================================

@dataclass
class ScraperConfig:
    """Configuration settings for the meetup scraper."""
    # Directories
    project_dir: Path = Path(__file__).parent
    browser_state_dir: Path = project_dir / "browser_state"
    events_dir: Path = project_dir / "events"
    
    # Timeouts (milliseconds)
    navigation_timeout: int = 30000
    element_timeout: int = 3000
    short_timeout: int = 1000
    
    # Scraping limits
    max_scroll_attempts: int = 20
    scroll_wait_time: int = 2
    page_load_wait: int = 3
    
    # Browser settings
    browser_args: List[str] = None
    
    def __post_init__(self):
        if self.browser_args is None:
            self.browser_args = [
                "--no-first-run",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-extensions",
                "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            ]


@dataclass
class EventData:
    """Data structure for meetup event information."""
    id: str
    url: str
    name: str
    date: str
    attendees: str
    location: str
    details: str
    cancelled: bool


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class MeetupScraperError(Exception):
    """Base exception for meetup scraper errors."""
    pass


class NavigationError(MeetupScraperError):
    """Raised when navigation fails."""
    pass


class LoginRequiredError(MeetupScraperError):
    """Raised when login is required but not completed."""
    pass


class ExtractionError(MeetupScraperError):
    """Raised when data extraction fails."""
    pass


# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging() -> logging.Logger:
    """Set up logging configuration."""
    logger = logging.getLogger('meetup_scraper')
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

class DirectoryManager:
    """Handles directory creation and management."""
    
    @staticmethod
    def setup_directories(config: ScraperConfig) -> None:
        """Create necessary directories for storing browser state and events data."""
        config.browser_state_dir.mkdir(exist_ok=True)
        config.events_dir.mkdir(exist_ok=True)


class DateParser:
    """Handles date parsing and formatting."""
    
    MONTH_MAP = {
        'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
        'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08', 
        'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'
    }
    
    @classmethod
    def parse_date_to_iso_format(cls, date_string: str) -> str:
        """
        Parse date string and convert to ISO format YYYY-MM-DD.
        
        Args:
            date_string: Date like "WED, JUL 16, 2025, 10:00 AM BST"
            
        Returns:
            Formatted date string like "2025-07-16"
        """
        try:
            # Extract date parts using regex
            match = re.search(r'([A-Z]{3})\s+(\d{1,2}),\s+(\d{4})', date_string.upper())
            if match:
                month_abbr, day, year = match.groups()
                month = cls.MONTH_MAP.get(month_abbr, '01')
                day = day.zfill(2)
                return f"{year}-{month}-{day}"
        except Exception:
            pass
        
        # Fallback to today's date
        today = datetime.now()
        return f"{today.year}-{today.month:02d}-{today.day:02d}"


class FilenameUtils:
    """Utilities for handling filenames."""
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Make filename filesystem-safe."""
        safe_name = re.sub(r'[^\w\s-]', '', filename).strip()
        return re.sub(r'[-\s]+', '-', safe_name)


# =============================================================================
# BROWSER MANAGEMENT
# =============================================================================

class BrowserManager:
    """Manages browser operations and navigation."""
    
    def __init__(self, config: ScraperConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
    
    def is_login_page(self, page: Page) -> bool:
        """
        Detect if we've been redirected to a login page.
        
        Args:
            page: Playwright page object
            
        Returns:
            bool: True if on a login page, False otherwise
        """
        title = page.title()
        url = page.url.lower()
        
        return (
            title.startswith("Login to Meetup") or
            "/login" in url or
            "sign-in" in url.lower()
        )
    
    def wait_for_login_completion(self, page: Page) -> bool:
        """Wait for user to complete login."""
        self.logger.info("\n🔐 Please log in using the browser window")
        self.logger.info("Press ENTER when you're logged in and ready to continue...")
        input()
        return True
    
    def navigate_to_group_events(self, page: Page, group_name: str) -> bool:
        """
        Navigate to the past events page for a specific meetup group.
        
        Args:
            page: Playwright page object
            group_name: Name of the meetup group
            
        Returns:
            bool: True if navigation successful, False otherwise
        """
        try:
            events_url = f"https://www.meetup.com/{group_name}/events/past/"
            self.logger.info(f"📍 Navigating to: {events_url}")
            
            response = page.goto(
                events_url, 
                wait_until="domcontentloaded", 
                timeout=self.config.navigation_timeout
            )
            
            if response and response.status >= 400:
                raise NavigationError(f"Group '{group_name}' may not exist (HTTP {response.status})")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error navigating to group events: {e}")
            return False


# =============================================================================
# EVENT LOADING AND DETECTION
# =============================================================================

class EventLoader:
    """Handles loading events from the page."""
    
    def __init__(self, config: ScraperConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
    
    def scroll_to_load_events(self, page: Page, max_events: int) -> int:
        """
        Scroll the page to load more events dynamically.
        
        Args:
            page: Playwright page object
            max_events: Maximum number of events to load
            
        Returns:
            int: Number of events loaded
        """
        self.logger.info(f"📜 Loading events (up to {max_events})...")
        time.sleep(self.config.page_load_wait)
        
        previous_count = 0
        scroll_attempts = 0
        
        while scroll_attempts < self.config.max_scroll_attempts:
            # Scroll to bottom
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(self.config.scroll_wait_time)
            
            # Count events
            event_cards = page.locator('[id^="past-event-card-ep-"]')
            current_count = event_cards.count()
            
            self.logger.info(f"   Found {current_count} event cards...")
            
            # Debug if no events found on first attempt
            if current_count == 0 and scroll_attempts == 0:
                if self._debug_empty_page(page):
                    return 0
            
            # Stop if enough events or no new events
            if current_count >= max_events or current_count == previous_count:
                break
                
            previous_count = current_count
            scroll_attempts += 1
        
        self.logger.info(f"✅ Loaded {current_count} events")
        return current_count
    
    def _debug_empty_page(self, page: Page) -> bool:
        """
        Debug why no events were found.
        
        Returns:
            bool: True if should stop scraping, False if should continue
        """
        page_text = page.inner_text('body').lower()
        self.logger.info(f"   🔍 Debugging 0 events - Page title: {page.title()}")
        self.logger.info(f"   🔍 Current URL: {page.url}")
        
        if 'login' in page_text or 'sign in' in page_text:
            self.logger.warning("   ⚠️  Page contains login content - authentication required!")
            return True
            
        if any(phrase in page_text for phrase in ['no events', 'no upcoming events', 'no past events']):
            self.logger.info("   ℹ️  Page indicates no events available")
            return True
            
        return False


# =============================================================================
# EVENT DETAILS EXTRACTION
# =============================================================================

class EventDetailsExtractor:
    """Handles extraction of event details and location."""
    
    def __init__(self, config: ScraperConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
    
    def extract_event_details(self, page: Page, event_url: str, return_url: str) -> Tuple[str, str, str, str, str]:
        """
        Visit an individual event page and extract name, date, location, details, and attendees.
        
        Args:
            page: Playwright page object
            event_url: URL of the individual event page
            return_url: URL to return to after extraction
            
        Returns:
            Tuple of (name, date, location, details, attendees)
        """
        try:
            self.logger.info("      🔍 Visiting event page...")
            page.goto(event_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout)
            time.sleep(2)
            
            name = self._extract_name(page)
            date = self._extract_date(page)
            location = self._extract_location(page)
            details = self._extract_details(page)
            attendees = self._extract_attendees(page)
            
            # Navigate back
            page.goto(return_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout)
            time.sleep(1)
            
            return name, date, location, details, attendees
            
        except Exception as e:
            self.logger.error(f"      ⚠️  Error extracting event details: {e}")
            try:
                page.goto(return_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout)
                time.sleep(1)
            except:
                pass
            return "Name not found", "Date unknown", "Location not found", "Details not found", "0"
    
    def _extract_name(self, page: Page) -> str:
        """Extract event name from individual event page."""
        try:
            name_selector = "#main > div.px-5.w-full.bg-white.border-b.border-shadowColor.py-2.lg\\:py-6 > div > h1"
            name_elem = page.locator(name_selector)
            
            if name_elem.count() > 0:
                name = name_elem.inner_text().strip()
                if name:
                    return name
                    
        except Exception:
            pass
        
        return "Name not found"
    
    def _extract_date(self, page: Page) -> str:
        """Extract event date from individual event page."""
        try:
            date_selector = "#event-info > div > div:nth-child(1) > div.flex.gap-x-4.md\\:gap-x-4\\.5.lg\\:gap-x-5 > div:nth-child(2) > div > time"
            date_elem = page.locator(date_selector)
            
            if date_elem.count() > 0:
                date = date_elem.inner_text().strip()
                if date:
                    return date
                    
        except Exception:
            pass
        
        return "Date unknown"
    
    def _extract_attendees(self, page: Page) -> str:
        """Extract attendees count from individual event page."""
        try:
            attendees_selector = "#attendees > div.flex.items-center.justify-between > h2"
            attendees_elem = page.locator(attendees_selector)
            
            if attendees_elem.count() > 0:
                attendees_text = attendees_elem.inner_text().strip()
                if attendees_text:
                    # Extract number from text like "24 attendees" or "Going (15)"
                    match = re.search(r'(\d+)', attendees_text)
                    if match:
                        count = int(match.group(1))
                        return f"{count} attendees"
                    return attendees_text
                    
        except Exception:
            pass
        
        return "0"  # Default for cancelled events or when element not found
    
    def _extract_location(self, page: Page) -> str:
        """Extract location from event page."""
        try:
            # Use CSS selector instead of brittle XPath
            location_selector = "#event-info > div > div:nth-child(1) > div.flex.flex-col > div > div.overflow-hidden.pl-4.md\\:pl-4\\.5.lg\\:pl-5"
            location_elem = page.locator(location_selector)
            
            if location_elem.count() > 0:
                location = location_elem.inner_text().strip()
                if location and len(location) > 5:
                    return location
            
            # Try fallback selectors with original logic
            fallback_selectors = [
                '[data-testid="event-location"]',
                '[data-testid="venue-info"]',
                '.venueDisplay',
                '.event-location',
                '.venue-info',
                '[class*="location"]',
                '[class*="venue"]'
            ]
            
            for selector in fallback_selectors:
                try:
                    location_elem = page.locator(selector)
                    if location_elem.count() > 0:
                        location = location_elem.first.inner_text().strip()
                        if location and len(location) > 5:
                            return location
                except:
                    continue
                    
        except Exception:
            pass
        
        return "Location not found"
    
    def _extract_details(self, page: Page) -> str:
        """Extract details from event page."""
        try:
            # Primary CSS selector
            details_elem = page.locator("#event-details > div.break-words")
            
            if details_elem.count() > 0 and details_elem.is_visible(timeout=self.config.element_timeout):
                details = details_elem.inner_text().strip()
                if details:
                    return details
            
            # Fallback selectors
            fallback_selectors = [
                "#event-details",
                '[data-testid="event-description"]',
                '.event-description',
                '.description',
                '[class*="description"]',
                '#details',
                '.event-details',
                "xpath=/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div[3]/div[1]/div/div[1]/div[1]/div[2]/div[2]"
            ]
            
            for selector in fallback_selectors:
                try:
                    details_elem = page.locator(selector)
                    if details_elem.count() > 0 and details_elem.is_visible(timeout=2000):
                        details = details_elem.inner_text().strip()
                        if details and len(details) > 50:
                            return details
                except:
                    continue
                    
        except Exception:
            pass
        
        return "Details not found"


# =============================================================================
# EVENT SCRAPING ORCHESTRATOR
# =============================================================================

class EventScraper:
    """Main event scraping orchestrator."""
    
    def __init__(self, config: ScraperConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.details_extractor = EventDetailsExtractor(config, logger)
    
    def scrape_events(self, page: Page, max_events: int) -> List[EventData]:
        """
        Scrape event data using two-phase approach:
        Phase 1: Extract URLs and cancelled status from main page
        Phase 2: Visit individual pages for detailed extraction
        
        Args:
            page: Playwright page object with events loaded
            max_events: Maximum number of events to scrape
            
        Returns:
            List of EventData objects
        """
        events = []
        events_list_url = page.url
        
        # Phase 1: Extract URLs and cancelled status from main page
        self.logger.info("📋 Phase 1: Caching event URLs and cancelled status...")
        cached_events = self._cache_event_urls_and_status(page, max_events)
        
        if not cached_events:
            self.logger.warning("No events found to process")
            return events
        
        # Phase 2: Visit individual pages for detailed extraction
        self.logger.info(f"🔍 Phase 2: Visiting {len(cached_events)} individual event pages...")
        
        for i, (event_url, is_cancelled) in enumerate(cached_events):
            try:
                # Extract event ID from URL
                event_id = ""
                try:
                    match = re.search(r'/events/(\d+)', event_url)
                    if match:
                        event_id = match.group(1)
                except Exception:
                    pass
                
                self.logger.info(f"   🔍 [{i+1}/{len(cached_events)}] Event ID: {event_id}, Cancelled: {is_cancelled}")
                
                # Extract detailed information from individual event page
                name, date, location, details, attendees = self.details_extractor.extract_event_details(
                    page, event_url, events_list_url
                )
                
                # For cancelled events, default attendees to 0
                if is_cancelled and (attendees == "0" or "not found" in attendees.lower()):
                    attendees = "0"
                
                # Create event data
                event_data = EventData(
                    id=event_id,
                    url=event_url,
                    name=name,
                    date=date,
                    attendees=attendees,
                    location=location,
                    details=details,
                    cancelled=is_cancelled
                )
                
                events.append(event_data)
                
                # Save immediately
                self._save_event_immediately(event_data, i + 1, len(cached_events))
                
            except Exception as e:
                self.logger.error(f"   ⚠️  Error processing event {i+1}: {e}")
                self.logger.info(f"   📊 Continuing to next event... (current progress: {len(events)}/{len(cached_events)})")
                continue
        
        self.logger.info(f"✅ Scraped {len(events)} events (including {sum(1 for e in events if e.cancelled)} cancelled)")
        return events
    
    def _cache_event_urls_and_status(self, page: Page, max_events: int) -> List[Tuple[str, bool]]:
        """
        Extract URLs and cancelled status from all event cards on the main page.
        
        Args:
            page: Playwright page object
            max_events: Maximum number of events to extract
            
        Returns:
            List of tuples: (event_url, is_cancelled)
        """
        cached_events = []
        
        try:
            # Find all event cards
            event_cards = page.locator('[id^="past-event-card-ep-"]')
            event_count = event_cards.count()
            self.logger.info(f"   Found {event_count} event cards to cache...")
            
            for i in range(min(event_count, max_events)):
                try:
                    event_card = event_cards.nth(i)
                    
                    # Extract URL
                    event_url = self._extract_url_from_card(event_card, i + 1)
                    if not event_url:
                        continue
                    
                    # Check if cancelled
                    is_cancelled = self._is_cancelled_event(event_card)
                    
                    cached_events.append((event_url, is_cancelled))
                    status = "CANCELLED" if is_cancelled else "ACTIVE"
                    self.logger.info(f"   ✅ Cached {i+1}: {status} - {event_url}")
                    
                except Exception as e:
                    self.logger.warning(f"   ⚠️  Error caching event card {i+1}: {e}")
                    continue
            
            self.logger.info(f"✅ Cached {len(cached_events)} events for processing")
            return cached_events
            
        except Exception as e:
            self.logger.error(f"❌ Error caching event URLs: {e}")
            return []
    
    def _extract_url_from_card(self, event_card, card_num: int) -> Optional[str]:
        """Extract URL from a single event card."""
        try:
            # Try to find a link within the card first
            card_link = event_card.locator('a').first
            if card_link.count() > 0:
                event_url = card_link.get_attribute('href')
                if event_url and not event_url.startswith('http'):
                    event_url = f"https://www.meetup.com{event_url}"
                return event_url
            else:
                # Try getting href from the card itself if it's a link
                href = event_card.get_attribute('href')
                if href:
                    event_url = href if href.startswith('http') else f"https://www.meetup.com{href}"
                    return event_url
        except Exception:
            pass
        
        # If standard methods fail, try alternative extraction
        try:
            # Look for any element with href containing 'events'
            event_links = event_card.locator('[href*="/events/"]')
            if event_links.count() > 0:
                href = event_links.first.get_attribute('href')
                if href:
                    return href if href.startswith('http') else f"https://www.meetup.com{href}"
        except Exception:
            pass
        
        self.logger.warning(f"   ⚠️  Could not extract URL from card {card_num}")
        return None
    
    def _is_cancelled_event(self, event_card) -> bool:
        """Check if event is cancelled."""
        try:
            container_text = event_card.inner_text().lower()
            return 'cancelled' in container_text
        except:
            return False
    
    def _save_event_immediately(self, event_data: EventData, event_num: int, total_events: int) -> None:
        """Save event data immediately after processing."""
        try:
            file_manager = FileManager(self.config, self.logger)
            file_manager.save_event_data(event_data)
            
            iso_date = DateParser.parse_date_to_iso_format(event_data.date)
            directory_name = f"{iso_date}"
            status = " (CANCELLED)" if event_data.cancelled else ""
            
            self.logger.info(f"      ✅ Event {event_num} complete and saved: {directory_name}/{event_data.id}.json{status}")
            self.logger.info(f"      📊 Progress: {event_num}/{total_events} events collected")
            
            if event_num >= total_events:
                self.logger.info(f"      🎯 Completed all {total_events} events")
                
        except Exception as e:
            self.logger.error(f"      ⚠️  Event {event_num} complete but save failed: {e}")
            self.logger.info(f"      📊 Progress: {event_num}/{total_events} events collected")


# =============================================================================
# FILE MANAGEMENT
# =============================================================================

class FileManager:
    """Handles file operations for saving event data."""
    
    def __init__(self, config: ScraperConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
    
    def save_event_data(self, event_data: EventData) -> None:
        """
        Save event data to the events directory structure.
        
        Args:
            event_data: EventData object containing event information
        """
        try:
            iso_date = DateParser.parse_date_to_iso_format(event_data.date)
            event_dir = self.config.events_dir / f"{iso_date}"
            event_dir.mkdir(exist_ok=True)
            
            data_file = event_dir / f"{event_data.id}.json"
            with open(data_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(event_data), f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            raise ExtractionError(f"Failed to save event data: {e}")


# =============================================================================
# MAIN APPLICATION
# =============================================================================

class MeetupScraper:
    """Main application class for the Meetup scraper."""
    
    def __init__(self, config: ScraperConfig = None):
        self.config = config or ScraperConfig()
        self.logger = setup_logging()
        self.browser_manager = BrowserManager(self.config, self.logger)
        self.event_loader = EventLoader(self.config, self.logger)
        self.event_scraper = EventScraper(self.config, self.logger)
        
    def run(self, group_name: str, max_events: int, headless: bool = False) -> None:
        """
        Main execution method.
        
        Args:
            group_name: The name of the meetup group
            max_events: Maximum number of events to scrape
            headless: Whether to run browser in headless mode
        """
        try:
            self.logger.info("🚀 Meetup Group Past Events Scraper")
            self.logger.info(f"📅 Accessing past events for group: {group_name}")
            self.logger.info("-" * 50)
            
            # Setup
            DirectoryManager.setup_directories(self.config)
            
            # Launch browser and scrape
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(self.config.browser_state_dir),
                    headless=headless,
                    args=self.config.browser_args
                )
                
                page = context.new_page()
                
                try:
                    self._execute_scraping(page, group_name, max_events)
                finally:
                    self._cleanup(context)
                    
        except KeyboardInterrupt:
            self.logger.info("\n⏹️  Operation cancelled by user")
        except Exception as e:
            self.logger.error(f"❌ Unexpected error: {e}")
            
    def _execute_scraping(self, page: Page, group_name: str, max_events: int) -> None:
        """Execute the main scraping logic."""
        self.logger.info("🌐 Starting browser...")
        
        # Navigate to group events
        if not self.browser_manager.navigate_to_group_events(page, group_name):
            return
        
        # Handle login if required
        if self.browser_manager.is_login_page(page):
            if not self.browser_manager.wait_for_login_completion(page):
                raise LoginRequiredError("Login verification failed")
            
            if not self.browser_manager.navigate_to_group_events(page, group_name):
                raise NavigationError("Failed to navigate to group events page after login")
        
        self.logger.info("✅ Successfully accessed the past events page!")
        self.logger.info(f"📊 Current URL: {page.url}")
        
        # Scrape events
        self.logger.info("\n🎯 Browser is ready!")
        self.logger.info("The past events page is now loaded. The browser will stay open.")
        
        self.event_loader.scroll_to_load_events(page, max_events)
        events = self.event_scraper.scrape_events(page, max_events)
        
        self.logger.info(f"\n✅ All {len(events)} events processed and saved to {self.config.events_dir}")
        self.logger.info("Press ENTER when you're done to close the browser...")
        input()
    
    def _cleanup(self, context: BrowserContext) -> None:
        """Clean up browser resources."""
        self.logger.info("👋 Closing browser...")
        context.close()


# =============================================================================
# CLI INTERFACE
# =============================================================================

@click.command()
@click.argument('group_name', required=True)
@click.option('--headless', is_flag=True, help='Run browser in headless mode')
@click.option('--max-events', default=10, help='Maximum number of events to scrape (default: 10)')
def main(group_name: str, headless: bool, max_events: int):
    """
    Access and scrape past events for a Meetup group.
    
    GROUP_NAME: The name of the meetup group (from the URL)
    
    Examples:
        meetup_scraper.py python-seattle
        meetup_scraper.py python-seattle --max-events 50
        meetup_scraper.py python-seattle --headless --max-events 5
    """
    config = ScraperConfig()
    scraper = MeetupScraper(config)
    scraper.run(group_name, max_events, headless)


if __name__ == "__main__":
    main() 