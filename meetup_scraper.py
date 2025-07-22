#!/usr/bin/env python3
"""
Meetup.com Group Past Events Scraper

A command line tool to access past events for a specific Meetup group.
Handles login detection and session persistence with comprehensive data extraction.
"""

import time
import json
import re
import requests
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
    attendees_dir: Path = project_dir / "events" / "attendees"
    
    # Timeouts (milliseconds)
    navigation_timeout: int = 30000
    element_timeout: int = 3000
    short_timeout: int = 1000
    
    # Scraping limits
    max_scroll_attempts: int = 20
    scroll_wait_time: int = 2
    page_load_wait: int = 3
    
    # Avatar settings
    avatar_timeout: int = 10
    avatar_format: str = "jpg"
    
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
    attendees_list: List[Dict]


@dataclass
class AttendeeData:
    """Data structure for attendee information."""
    name: str
    is_host: bool
    avatar_path: str
    guests: int


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
        config.attendees_dir.mkdir(exist_ok=True)


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
    
    @staticmethod
    def extract_member_id(avatar_url: str) -> str:
        """Extract member ID from avatar URL."""
        match = re.search(r'thumb_(\d+)', avatar_url)
        return match.group(1) if match else ""


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
# AVATAR MANAGEMENT
# =============================================================================

class AvatarManager:
    """Handles avatar downloading and management."""
    
    def __init__(self, config: ScraperConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
    
    def download_avatar(self, avatar_url: str, attendee_name: str) -> str:
        """
        Download an avatar image and save it to the attendees directory.
        
        Args:
            avatar_url: URL of the avatar image
            attendee_name: Attendee name to use in filename
            
        Returns:
            Relative path to the saved avatar or empty string if failed
        """
        try:
            member_id = FilenameUtils.extract_member_id(avatar_url)
            safe_name = FilenameUtils.sanitize_filename(attendee_name)
            
            # Create filename with format: [name]_[member_id].jpg
            filename = f"{safe_name}_{member_id}.{self.config.avatar_format}" if member_id else f"{safe_name}.{self.config.avatar_format}"
            avatar_path = self.config.attendees_dir / filename
            
            # Don't overwrite existing files
            if avatar_path.exists():
                return f"events/attendees/{filename}"
            
            # Download and save
            response = requests.get(avatar_url, timeout=self.config.avatar_timeout)
            response.raise_for_status()
            
            with open(avatar_path, 'wb') as f:
                f.write(response.content)
                
            return f"events/attendees/{filename}"
            
        except Exception as e:
            self.logger.warning(f"      ⚠️  Failed to download avatar for {attendee_name}: {e}")
            return ""


# =============================================================================
# ATTENDEE EXTRACTION
# =============================================================================

class AttendeeExtractor:
    """Handles extraction of attendee information."""
    
    def __init__(self, config: ScraperConfig, logger: logging.Logger, avatar_manager: AvatarManager):
        self.config = config
        self.logger = logger
        self.avatar_manager = avatar_manager
    
    def extract_attendees(self, page: Page, event_url: str) -> List[Dict]:
        """
        Extract attendee information including names, host status, avatars, and guest counts.
        
        Args:
            page: Playwright page object
            event_url: URL of the event page
            
        Returns:
            List of attendee dictionaries
        """
        attendees = []
        
        try:
            self.logger.info("      👥 Extracting attendees...")
            
            # Navigate to attendees page
            if not self._navigate_to_attendees_page(page):
                return attendees
            
            # Load all attendees
            self._load_all_attendees(page)
            
            # Extract attendee data
            attendees = self._extract_attendee_data(page)
            
        except Exception as e:
            self.logger.error(f"      ⚠️  Error extracting attendees: {e}")
        
        return attendees
    
    def _navigate_to_attendees_page(self, page: Page) -> bool:
        """Navigate to the attendees page."""
        try:
            # Click attendees button
            attendees_button = page.locator('#attendees-btn')
            if attendees_button.count() == 0:
                self.logger.warning("      ⚠️  Attendees button not found")
                return False
            
            attendees_button.click()
            time.sleep(2)
            
            # Handle potential paywall
            self._handle_paywall(page)
            
            return True
            
        except Exception as e:
            self.logger.error(f"      ⚠️  Failed to navigate to attendees page: {e}")
            return False
    
    def _handle_paywall(self, page: Page) -> None:
        """Handle paywall if present."""
        try:
            # Use CSS selector instead of brittle XPath
            paywall_selector = "#modal > div > div.fixed.inset-0.m-0.size-full.max-w-none.\\!rounded-none.border-0.md\\:m-0.md\\:size-auto.md\\:max-w-none.md\\:\\!rounded-lg.md\\:border-0.hidden.relative.sm\\:block.bg-white.rounded-lg.shadow-lg.z-50.max-h-screen.overflow-y-auto > div > div > div.relative.mx-6.mb-0.mt-14.flex.max-w-\\[368px\\].flex-col.space-y-8.md\\:mx-10.md\\:my-14 > div.flex.max-h-\\[calc\\(100vh-230px\\)\\].flex-col.space-y-8.overflow-y-auto.md\\:max-h-none.md\\:overflow-y-visible > div > button"
            paywall_button = page.locator(paywall_selector)
            if paywall_button.count() > 0 and paywall_button.is_visible(timeout=self.config.element_timeout):
                self.logger.info("      💰 Handling paywall...")
                paywall_button.click()
                time.sleep(2)
        except Exception:
            pass  # No paywall or couldn't handle it
    
    def _load_all_attendees(self, page: Page) -> None:
        """Scroll to load all attendees."""
        try:
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1)
        except Exception:
            pass
    
    def _extract_attendee_data(self, page: Page) -> List[Dict]:
        """Extract attendee data from the page."""
        attendees = []
        seen_attendees = set()
        
        # Find attendee containers
        base_selector = "#page > div.flex.flex-grow.flex-col > main > div.md\\:max-w-screen.z-10.mb-5.w-full.sm\\:my-4.sm\\:px-5.md\\:w-\\[750px\\].md\\:w-\\[600px\\] > div > div:nth-child(6) > div"
        attendees_container = page.locator(base_selector)
        
        if attendees_container.count() == 0:
            self.logger.info("      👥 Found 0 attendee containers")
            return attendees
        
        attendee_containers = attendees_container.locator("> div")
        attendee_count = attendee_containers.count()
        self.logger.info(f"      👥 Found {attendee_count} attendee containers using CSS selector")
        
        # Process each attendee
        for i in range(attendee_count):
            try:
                container = attendee_containers.nth(i)
                attendee_data = self._extract_single_attendee(container, seen_attendees)
                
                if attendee_data:
                    attendees.append(asdict(attendee_data))
                    guest_info = f" (+{attendee_data.guests} guest{'s' if attendee_data.guests != 1 else ''})" if attendee_data.guests > 0 else ""
                    host_info = " (Host)" if attendee_data.is_host else ""
                    self.logger.info(f"      ✅ Attendee {len(attendees)}: {attendee_data.name}{host_info}{guest_info}")
                    
            except Exception as e:
                self.logger.warning(f"      ⚠️  Error extracting attendee {i+1}: {e}")
                continue
        
        return attendees
    
    def _extract_single_attendee(self, container, seen_attendees: set) -> Optional[AttendeeData]:
        """Extract data for a single attendee."""
        # Extract name
        name_element = container.locator("div > div > div > div > button > div > div > p")
        attendee_name = name_element.inner_text().strip() if name_element.count() > 0 else "Unknown"
        
        # Extract host status
        host_element = container.locator("div > div > div > div > button > div > div > div > div:first-child")
        is_host = False
        if host_element.count() > 0:
            host_text = host_element.inner_text().strip()
            is_host = "Event host" in host_text
        
        # Extract guests
        guests = self._extract_guest_count(container.inner_text())
        
        # Check for duplicates
        attendee_key = f"{attendee_name}_{is_host}"
        if attendee_key in seen_attendees:
            return None
        
        # Validate name
        if not attendee_name or attendee_name == "Unknown" or len(attendee_name) <= 2:
            return None
        
        # Extract avatar
        avatar_path = self._extract_avatar(container, attendee_name)
        
        seen_attendees.add(attendee_key)
        return AttendeeData(
            name=attendee_name,
            is_host=is_host,
            avatar_path=avatar_path,
            guests=guests
        )
    
    def _extract_guest_count(self, container_text: str) -> int:
        """Extract guest count from container text."""
        guest_patterns = [
            r'\+(\d+)',  # "+1", "+2", etc.
            r'plus\s+(\d+)',  # "plus 1", "plus 2"
            r'(\d+)\s+guest',  # "1 guest", "2 guests"
            r'bringing\s+(\d+)',  # "bringing 1", "bringing 2"
        ]
        
        for pattern in guest_patterns:
            match = re.search(pattern, container_text, re.IGNORECASE)
            if match:
                return int(match.group(1))
        
        # If no number found but text contains guest-related words, assume 1
        if any(word in container_text.lower() for word in ['guest', 'plus', '+', 'bringing']):
            return 1
            
        return 0
    
    def _extract_avatar(self, container, attendee_name: str) -> str:
        """Extract avatar for an attendee."""
        try:
            avatar_img = container.locator("div > div > div > div > button > div > picture > img")
            if avatar_img.count() > 0:
                avatar_url = avatar_img.first.get_attribute('src')
                if avatar_url:
                    return self.avatar_manager.download_avatar(avatar_url, attendee_name)
        except Exception:
            pass
        return ""


# =============================================================================
# EVENT DETAILS EXTRACTION
# =============================================================================

class EventDetailsExtractor:
    """Handles extraction of event details and location."""
    
    def __init__(self, config: ScraperConfig, logger: logging.Logger, attendee_extractor: AttendeeExtractor):
        self.config = config
        self.logger = logger
        self.attendee_extractor = attendee_extractor
    
    def extract_event_details(self, page: Page, event_url: str, return_url: str) -> Tuple[str, str, List[Dict]]:
        """
        Visit an individual event page and extract location, details, and attendees.
        
        Args:
            page: Playwright page object
            event_url: URL of the individual event page
            return_url: URL to return to after extraction
            
        Returns:
            Tuple of (location, details, attendees)
        """
        try:
            self.logger.info("      🔍 Visiting event page...")
            page.goto(event_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout)
            time.sleep(2)
            
            location = self._extract_location(page)
            details = self._extract_details(page)
            attendees = self.attendee_extractor.extract_attendees(page, event_url)
            
            # Navigate back
            page.goto(return_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout)
            time.sleep(1)
            
            return location, details, attendees
            
        except Exception as e:
            self.logger.error(f"      ⚠️  Error extracting event details: {e}")
            try:
                page.goto(return_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout)
                time.sleep(1)
            except:
                pass
            return "Location not found", "Details not found", []
    
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
        self.avatar_manager = AvatarManager(config, logger)
        self.attendee_extractor = AttendeeExtractor(config, logger, self.avatar_manager)
        self.details_extractor = EventDetailsExtractor(config, logger, self.attendee_extractor)
    
    def scrape_events(self, page: Page, max_events: int) -> List[EventData]:
        """
        Scrape event data from the loaded page, excluding cancelled events.
        
        Args:
            page: Playwright page object with events loaded
            max_events: Maximum number of events to scrape
            
        Returns:
            List of EventData objects
        """
        events = []
        events_list_url = page.url
        
        self.logger.info("🔍 Scraping event data (excluding cancelled events)...")
        
        # Find all event cards
        event_cards = page.locator('[id^="past-event-card-ep-"]')
        event_count = event_cards.count()
        self.logger.info(f"🔍 Found {event_count} event cards to process...")
        
        processed_count = 0
        
        for i in range(event_count):
            if len(events) >= max_events:
                break
                
            try:
                processed_count += 1
                event_card = event_cards.nth(i)
                
                # Extract basic event info
                event_info = self._extract_basic_event_info(event_card, i + 1, max_events)
                if not event_info:
                    continue
                
                event_url, event_name, date_string, event_id = event_info
                
                # Skip cancelled events
                if self._is_cancelled_event(event_card):
                    self.logger.info(f"   ⚠️  Skipped cancelled event: {event_name[:50]}...")
                    continue
                
                # Extract detailed information
                self.logger.info(f"      🔍 Event ID: {event_id}, Date: {date_string}")
                self.logger.info(f"   🔍 [{len(events)+1}/{max_events}] {event_name[:50]}...")
                
                location, details, attendees_list = self.details_extractor.extract_event_details(
                    page, event_url, events_list_url
                )
                
                # Calculate attendees summary
                attendees_summary = self._calculate_attendees_summary(attendees_list)
                
                # Create event data
                event_data = EventData(
                    id=event_id,
                    url=event_url,
                    name=event_name,
                    date=date_string,
                    attendees=attendees_summary,
                    location=location,
                    details=details,
                    attendees_list=attendees_list
                )
                
                events.append(event_data)
                
                # Save immediately
                self._save_event_immediately(event_data, len(events), max_events)
                
            except Exception as e:
                self.logger.error(f"   ⚠️  Error processing event card {i+1}: {e}")
                self.logger.info(f"   📊 Continuing to next event... (current progress: {len(events)}/{max_events})")
                continue
        
        self.logger.info(f"✅ Scraped {len(events)} valid events (processed {processed_count} total)")
        return events
    
    def _extract_basic_event_info(self, event_card, card_num: int, max_events: int) -> Optional[Tuple[str, str, str, str]]:
        """Extract basic event information from event card."""
        try:
            # Extract URL with robust fallback logic
            event_url = ""
            try:
                # Try to find a link within the card first
                card_link = event_card.locator('a').first
                if card_link.count() > 0:
                    event_url = card_link.get_attribute('href')
                    if event_url and not event_url.startswith('http'):
                        event_url = f"https://www.meetup.com{event_url}"
                else:
                    # Try getting href from the card itself if it's a link
                    href = event_card.get_attribute('href')
                    if href:
                        event_url = href if href.startswith('http') else f"https://www.meetup.com{href}"
            except Exception:
                pass
            
            if not event_url:
                self.logger.warning(f"   ⚠️  Skipped card {card_num} - could not extract URL")
                return None
            
            # Extract name
            event_name = ""
            try:
                name_element = event_card.locator('div.flex.flex-col.space-y-5.overflow-hidden > div > div > span')
                if name_element.count() > 0:
                    event_name = name_element.first.inner_text().strip()
            except Exception:
                pass
            
            if not event_name:
                event_name = f"Event {card_num}"
            
            # Extract date
            date_string = ""
            try:
                date_element = event_card.locator('div.flex.flex-col.space-y-5.overflow-hidden > div > div > time')
                if date_element.count() > 0:
                    date_string = date_element.first.inner_text().strip()
            except Exception:
                pass
            
            if not date_string:
                date_string = "Date unknown"
            
            # Extract event ID
            event_id = ""
            try:
                match = re.search(r'/events/(\d+)', event_url)
                if match:
                    event_id = match.group(1)
            except Exception:
                pass
            
            # Validate we have minimum required info
            if not event_url or not event_name:
                self.logger.warning(f"   ⚠️  Skipped card {card_num} - missing basic info (name: {bool(event_name)}, url: {bool(event_url)})")
                return None
            
            return event_url, event_name, date_string, event_id
            
        except Exception as e:
            self.logger.error(f"   ⚠️  Error extracting basic info for card {card_num}: {e}")
            return None
    
    def _is_cancelled_event(self, event_card) -> bool:
        """Check if event is cancelled."""
        try:
            container_text = event_card.inner_text().lower()
            return 'cancelled' in container_text
        except:
            return False
    
    def _calculate_attendees_summary(self, attendees_list: List[Dict]) -> str:
        """Calculate attendees summary from attendees list."""
        total_members = len(attendees_list)
        total_guests = sum(attendee.get('guests', 0) for attendee in attendees_list)
        
        if total_guests > 0:
            return f"{total_members} members + {total_guests} guests = {total_members + total_guests} total"
        else:
            return f"{total_members} members"
    
    def _save_event_immediately(self, event_data: EventData, event_num: int, max_events: int) -> None:
        """Save event data immediately after processing."""
        try:
            file_manager = FileManager(self.config, self.logger)
            file_manager.save_event_data(event_data)
            
            iso_date = DateParser.parse_date_to_iso_format(event_data.date)
            directory_name = f"{iso_date}_{event_data.id}"
            
            self.logger.info(f"      ✅ Event {event_num} complete and saved: {directory_name}")
            self.logger.info(f"      📊 Progress: {event_num}/{max_events} events collected")
            
            if event_num >= max_events:
                self.logger.info(f"      🎯 Reached target of {max_events} events - stopping")
                
        except Exception as e:
            self.logger.error(f"      ⚠️  Event {event_num} complete but save failed: {e}")
            self.logger.info(f"      📊 Progress: {event_num}/{max_events} events collected")


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
            event_dir = self.config.events_dir / f"{iso_date}_{event_data.id}"
            event_dir.mkdir(exist_ok=True)
            
            data_file = event_dir / "data.json"
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