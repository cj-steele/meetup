#!/usr/bin/env python3
"""
Meetup.com Group Past Events Scraper
"""

import time
import json
import re
import csv
import logging
from datetime import datetime
from dateutil.parser import parse as dateutil_parse
from pathvalidate import sanitize_filename
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
from pathlib import Path

import click
from playwright.sync_api import sync_playwright, Page, BrowserContext


@dataclass
class ScraperConfig:
    """Configuration settings for the meetup scraper."""
    project_dir: Path = Path(__file__).parent
    browser_state_dir: Path = project_dir / "browser_state"
    events_dir: Path = project_dir / "events"
    
    navigation_timeout: int = 30000
    element_timeout: int = 3000
    max_scroll_attempts: int = 20
    scroll_wait_time: int = 2
    page_load_wait: int = 3
    
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
    time: str
    attendees: int
    host: str
    location: str
    details: str
    cancelled: bool


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


class MeetupScraper:
    """Main application class for the Meetup scraper."""
    
    def __init__(self, config: ScraperConfig = None):
        self.config = config or ScraperConfig()
        self.logger = setup_logging()
        self._setup_directories()
        self.save_csv = False
        self.csv_file_path = self.config.events_dir / "events.csv"
        
    def _setup_directories(self) -> None:
        """Create necessary directories."""
        self.config.browser_state_dir.mkdir(exist_ok=True)
        self.config.events_dir.mkdir(exist_ok=True)
    
    def run(self, group_name: str, max_events: int, save_csv: bool = False, scrape_all: bool = False) -> None:
        """Main execution method."""
        self.save_csv = save_csv
        
        try:
            if scrape_all:
                self.logger.info(f"🚀 Scraping ALL events for group: {group_name}")
            else:
                self.logger.info(f"🚀 Scraping events for group: {group_name} (max: {max_events})")
            if save_csv:
                self.logger.info(f"📄 CSV output enabled: {self.csv_file_path}")
            
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(self.config.browser_state_dir),
                    headless=False,
                    args=self.config.browser_args
                )
                
                page = context.new_page()
                
                try:
                    # Use unlimited events if --all flag is set
                    effective_max = float('inf') if scrape_all else max_events
                    events = self._scrape_events(page, group_name, effective_max)
                    self.logger.info(f"✅ Completed: {len(events)} events saved")
                    input("Press ENTER to close browser...")
                finally:
                    context.close()
                    
        except KeyboardInterrupt:
            self.logger.info("\n⏹️  Operation cancelled by user")
        except Exception as e:
            self.logger.error(f"❌ Error: {e}")
    
    def _scrape_events(self, page: Page, group_name: str, max_events: int) -> List[EventData]:
        """Execute the main scraping logic."""
        if not self._navigate_to_group_events(page, group_name):
            return []
        
        if self._is_login_page(page):
            if not self._wait_for_login(page):
                raise LoginRequiredError("Login verification failed")
            
            if not self._navigate_to_group_events(page, group_name):
                raise NavigationError("Failed to navigate after login")
        
        self.logger.info("✅ Events page loaded")
        
        self._load_events(page, max_events)
        return self._extract_events(page, max_events)
    
    def _navigate_to_group_events(self, page: Page, group_name: str) -> bool:
        """Navigate to the past events page."""
        try:
            events_url = f"https://www.meetup.com/{group_name}/events/past/"
            response = page.goto(events_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout)
            
            if response and response.status >= 400:
                raise NavigationError(f"Group '{group_name}' may not exist (HTTP {response.status})")
            
            return True
        except Exception as e:
            self.logger.error(f"❌ Navigation error: {e}")
            return False
    
    def _is_login_page(self, page: Page) -> bool:
        """Detect if we're on a login page."""
        title = page.title()
        url = page.url.lower()
        
        return (
            title.startswith("Login to Meetup") or
            "/login" in url or
            "sign-in" in url.lower()
        )
    
    def _wait_for_login(self, page: Page) -> bool:
        """Wait for user to complete login."""
        self.logger.info("\n🔐 Please log in using the browser window")
        input("Press ENTER when logged in...")
        return True
    
    def _load_events(self, page: Page, max_events: int) -> int:
        """Scroll to load more events."""
        time.sleep(self.config.page_load_wait)
        
        previous_count = 0
        current_count = 0
        scroll_attempts = 0
        consecutive_no_change = 0
        is_unlimited = max_events == float('inf')
        
        # For unlimited mode, use much higher scroll limit
        max_scroll_limit = 1000 if is_unlimited else self.config.max_scroll_attempts
        
        while scroll_attempts < max_scroll_limit:
            # Try multiple scroll strategies to trigger lazy loading
            if scroll_attempts % 3 == 0:
                # Every 3rd scroll: scroll to end of events list
                page.evaluate("""
                    const eventCards = document.querySelectorAll('[id^="past-event-card-ep-"]');
                    if (eventCards.length > 0) {
                        eventCards[eventCards.length - 1].scrollIntoView({behavior: 'smooth', block: 'end'});
                    }
                """)
            else:
                # Regular scroll
                page.evaluate("window.scrollBy(0, window.innerHeight)")
            
            # Wait longer for lazy loading to happen
            time.sleep(2)
            
            event_cards = page.locator('[id^="past-event-card-ep-"]')
            current_count = event_cards.count()
            
            if current_count == 0 and scroll_attempts == 0:
                self.logger.warning("⚠️  No events found")
                return 0
            
            # Progress reporting
            if current_count != previous_count:
                if is_unlimited:
                    self.logger.info(f"📄 Loading events... {current_count} found so far")
                elif max_events > 10:
                    self.logger.info(f"📄 Loading events... {current_count}/{max_events}")
            
            # Check if we're getting new events
            if current_count == previous_count:
                consecutive_no_change += 1
                
                # Be MUCH more patient for lazy loading
                patience_limit = 20 if is_unlimited else 10
                
                if consecutive_no_change >= patience_limit:
                    self.logger.info(f"📄 No new events after {patience_limit} scroll attempts. Final count: {current_count}")
                    break
            else:
                consecutive_no_change = 0
            
            # For limited mode, stop when we have enough events  
            if not is_unlimited and current_count >= max_events:
                self.logger.info(f"📄 Reached target: {current_count} events loaded")
                break
                
            previous_count = current_count
            scroll_attempts += 1
        
        if scroll_attempts >= max_scroll_limit:
            self.logger.warning(f"⚠️  Reached scroll limit ({max_scroll_limit} attempts), {current_count} events loaded")
        
        return current_count
    
    def _extract_events(self, page: Page, max_events: int) -> List[EventData]:
        """Extract event data using two-phase approach."""
        events = []
        events_list_url = page.url
        
        # Phase 1: Cache URLs and status
        cached_events = self._cache_event_urls_and_status(page, max_events)
        if not cached_events:
            return events
        
        # Phase 2: Extract details
        for i, (event_url, is_cancelled) in enumerate(cached_events):
            try:
                # For unlimited mode, don't limit the number processed
                if max_events != float('inf') and len(events) >= max_events:
                    break
                    
                event_id = self._extract_event_id(event_url)
                
                name, raw_date, host, location, details, attendees = self._extract_event_details(
                    page, event_url, events_list_url
                )
                
                if is_cancelled:
                    attendees = 0
                
                # Split date and time for better CSV handling
                date_part, time_part = self._split_date_time(raw_date)
                
                event_data = EventData(
                    id=event_id,
                    url=self._clean_event_url(event_url),
                    name=name,
                    date=date_part,
                    time=time_part,
                    attendees=attendees,
                    host=host,
                    location=location,
                    details=details,
                    cancelled=is_cancelled
                )
                
                events.append(event_data)
                self._save_event_data(event_data)
                
                if self.save_csv:
                    self._save_to_csv(event_data)
                
                status = " (CANCELLED)" if is_cancelled else ""
                if max_events == float('inf'):
                    self.logger.info(f"✅ [{i+1}/{len(cached_events)}] {event_data.name[:50]}{status}")
                else:
                    self.logger.info(f"✅ [{i+1}/{len(cached_events)}] {event_data.name[:50]}{status}")
                
            except Exception as e:
                self.logger.error(f"⚠️  Error processing event {i+1}: {e}")
                continue
        
        return events
    
    def _cache_event_urls_and_status(self, page: Page, max_events: int) -> List[Tuple[str, bool]]:
        """Extract URLs and cancelled status from event cards."""
        cached_events = []
        
        try:
            event_cards = page.locator('[id^="past-event-card-ep-"]')
            event_count = event_cards.count()
            
            # For unlimited mode, process all events found
            events_to_process = event_count if max_events == float('inf') else min(event_count, max_events)
            
            for i in range(events_to_process):
                try:
                    event_card = event_cards.nth(i)
                    
                    event_url = self._extract_url_from_card(event_card)
                    if not event_url:
                        continue
                    
                    is_cancelled = self._is_cancelled_event(event_card)
                    cached_events.append((event_url, is_cancelled))
                    
                except Exception as e:
                    self.logger.warning(f"⚠️  Error caching event {i+1}: {e}")
                    continue
            
            if max_events == float('inf'):
                self.logger.info(f"📋 Cached {len(cached_events)} events (all available)")
            else:
                self.logger.info(f"📋 Cached {len(cached_events)} events (max: {max_events})")
            
            return cached_events
            
        except Exception as e:
            self.logger.error(f"❌ Error caching events: {e}")
            return []
    
    def _extract_url_from_card(self, event_card) -> Optional[str]:
        """Extract URL from event card."""
        try:
            card_link = event_card.locator('a').first
            if card_link.count() > 0:
                event_url = card_link.get_attribute('href')
                if event_url and not event_url.startswith('http'):
                    event_url = f"https://www.meetup.com{event_url}"
                return event_url
            
            href = event_card.get_attribute('href')
            if href:
                return href if href.startswith('http') else f"https://www.meetup.com{href}"
        except Exception:
            pass
        
        try:
            event_links = event_card.locator('[href*="/events/"]')
            if event_links.count() > 0:
                href = event_links.first.get_attribute('href')
                if href:
                    return href if href.startswith('http') else f"https://www.meetup.com{href}"
        except Exception:
            pass
        
        return None
    
    def _is_cancelled_event(self, event_card) -> bool:
        """Check if event is cancelled."""
        try:
            container_text = event_card.inner_text().lower()
            return 'cancelled' in container_text
        except:
            return False
    
    def _extract_event_id(self, event_url: str) -> str:
        """Extract event ID from URL."""
        try:
            match = re.search(r'/events/(\d+)', event_url)
            return match.group(1) if match else ""
        except Exception:
            return ""
    
    def _clean_event_url(self, url: str) -> str:
        """Clean event URL by removing query parameters."""
        try:
            clean_url = url.split('?')[0]
            if not clean_url.endswith('/'):
                clean_url += '/'
            return clean_url
        except Exception:
            return url
    
    def _extract_event_details(self, page: Page, event_url: str, return_url: str) -> Tuple[str, str, str, str, str, int]:
        """Visit event page and extract details."""
        try:
            page.goto(event_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout)
            time.sleep(2)
            
            name = self._extract_text(page, "#main > div.px-5.w-full.bg-white.border-b.border-shadowColor.py-2.lg\\:py-6 > div > h1") or "Name not found"
            date = self._extract_text(page, "#event-info > div > div:nth-child(1) > div.flex.gap-x-4.md\\:gap-x-4\\.5.lg\\:gap-x-5 > div:nth-child(2) > div > time") or "Date unknown"
            host = self._extract_text(page, "#main > div.px-5.w-full.bg-white.border-b.border-shadowColor.py-2.lg\\:py-6 > div > a > div > div.ml-6 > div:nth-child(2) > span") or "Host not found"
            location = self._extract_location(page)
            details = self._extract_details(page)
            attendees = self._extract_attendees(page)
            
            page.goto(return_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout)
            time.sleep(1)
            
            return name, date, host, location, details, attendees
            
        except Exception as e:
            try:
                page.goto(return_url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout)
            except:
                pass
            return "Name not found", "Date unknown", "Host not found", "Location not found", "Details not found", 0
    
    def _extract_text(self, page: Page, selector: str) -> Optional[str]:
        """Extract text from a CSS selector."""
        try:
            elem = page.locator(selector)
            if elem.count() > 0:
                text = elem.inner_text().strip()
                return text if text else None
        except Exception:
            pass
        return None
    
    def _extract_location(self, page: Page) -> str:
        """Extract location from event page."""
        location_selector = "#event-info > div > div:nth-child(1) > div.flex.flex-col > div > div.overflow-hidden.pl-4.md\\:pl-4\\.5.lg\\:pl-5"
        location = self._extract_text(page, location_selector)
        
        if location and len(location) > 5:
            return location
        
        fallback_selectors = [
            '[data-testid="event-location"]',
            '[data-testid="venue-info"]',
            '.venueDisplay',
            '.event-location',
            '.venue-info'
        ]
        
        for selector in fallback_selectors:
            try:
                location = self._extract_text(page, selector)
                if location and len(location) > 5:
                    return location
            except:
                continue
        
        return "Location not found"
    
    def _extract_details(self, page: Page) -> str:
        """Extract details from event page."""
        details_elem = page.locator("#event-details > div.break-words")
        
        try:
            if details_elem.count() > 0 and details_elem.is_visible(timeout=self.config.element_timeout):
                details = details_elem.inner_text().strip()
                if details:
                    return details
        except Exception:
            pass
        
        fallback_selectors = [
            "#event-details",
            '[data-testid="event-description"]',
            '.event-description',
            '.description'
        ]
        
        for selector in fallback_selectors:
            try:
                details = self._extract_text(page, selector)
                if details and len(details) > 50:
                    return details
            except:
                continue
        
        return "Details not found"
    
    def _extract_attendees(self, page: Page) -> int:
        """Extract attendees count from event page."""
        try:
            attendees_text = self._extract_text(page, "#attendees > div.flex.items-center.justify-between > h2")
            if attendees_text:
                match = re.search(r'(\d+)', attendees_text)
                if match:
                    return int(match.group(1))
        except Exception:
            pass
        
        return 0
    
    def _save_event_data(self, event_data: EventData) -> None:
        """Save event data to file."""
        try:
            try:
                # Parse the date field (which is now just the date part)
                parsed_date = dateutil_parse(event_data.date)
                iso_date = parsed_date.strftime('%Y-%m-%d')
            except Exception:
                today = datetime.now()
                iso_date = f"{today.year}-{today.month:02d}-{today.day:02d}"
            
            event_dir = self.config.events_dir / f"{iso_date}"
            event_dir.mkdir(exist_ok=True)
            
            safe_name = sanitize_filename(event_data.name)
            data_file = event_dir / f"{safe_name}.json"
            
            with open(data_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(event_data), f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            raise ExtractionError(f"Failed to save event data: {e}")
    
    def _save_to_csv(self, event_data: EventData) -> None:
        """Save event data to CSV file."""
        try:
            # Check if CSV file exists and has headers
            file_exists = self.csv_file_path.exists()
            
            with open(self.csv_file_path, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['id', 'url', 'name', 'date', 'time', 'attendees', 'host', 'location', 'details', 'cancelled']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                # Write headers if file is new
                if not file_exists:
                    writer.writeheader()
                
                # Write event data
                writer.writerow(asdict(event_data))
                
        except Exception as e:
            self.logger.warning(f"⚠️  Failed to save to CSV: {e}")
    
    def _split_date_time(self, raw_date_string: str) -> tuple[str, str]:
        """Split raw date string into separate date and time parts."""
        try:
            # Primary case: Handle newlines in date strings
            if '\n' in raw_date_string:
                # Format: "Wednesday, July 23, 2025\n10:00 AM to 4:00 PM BST"
                parts = raw_date_string.split('\n')
                date_part = parts[0].strip()
                time_part = parts[1].strip() if len(parts) > 1 else ""
                return date_part, time_part
            
            # Secondary case: Look for " at " pattern
            if ' at ' in raw_date_string:
                # Format: "Thursday, July 24, 2025 at 9:00 AM"
                parts = raw_date_string.split(' at ', 1)
                date_part = parts[0].strip()
                time_part = parts[1].strip()
                return date_part, time_part
            
            # Fallback: If no clear separator, treat whole string as date
            return raw_date_string.strip(), ""
            
        except Exception:
            return raw_date_string, ""


@click.command()
@click.argument('group_name', required=True)
@click.option('--max-events', default=10, help='Maximum number of events to scrape (default: 10)')
@click.option('--csv', is_flag=True, help='Save events to CSV file (events/events.csv)')
@click.option('--all', 'scrape_all', is_flag=True, help='Scrape ALL events (ignores --max-events)')
def main(group_name: str, max_events: int, csv: bool, scrape_all: bool):
    """Access and scrape past events for a Meetup group."""
    config = ScraperConfig()
    scraper = MeetupScraper(config)
    scraper.run(group_name, max_events, csv, scrape_all)


if __name__ == "__main__":
    main() 