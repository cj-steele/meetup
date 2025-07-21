#!/usr/bin/env python3
"""
Meetup.com Group Past Events Scraper

A command line tool to access past events for a specific Meetup group.
Handles login detection and session persistence.
"""

import sys
import time
import json
import re
from datetime import datetime
import click
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

# Configuration
PROJECT_DIR = Path(__file__).parent
BROWSER_STATE_DIR = PROJECT_DIR / "browser_state"
EVENTS_DIR = PROJECT_DIR / "events"


def setup_directories():
    """Create necessary directories for storing browser state and events data."""
    BROWSER_STATE_DIR.mkdir(exist_ok=True)
    EVENTS_DIR.mkdir(exist_ok=True)


def is_login_page(page: Page) -> bool:
    """
    Detect if we've been redirected to a login page.
    
    Args:
        page: Playwright page object
        
    Returns:
        bool: True if on a login page, False otherwise
    """
    title = page.title()
    url = page.url.lower()
    
    # Check if we're on a login page
    return (
        title.startswith("Login to Meetup") or
        "/login" in url or
        "sign-in" in url.lower()
    )


def wait_for_login_completion(page: Page):
    """Wait for user to complete login."""
    print("\n🔐 Please log in using the browser window")
    print("Press ENTER when you're logged in and ready to continue...")
    input()
    return True


def navigate_to_group_events(page: Page, group_name: str) -> bool:
    """
    Navigate to the past events page for a specific meetup group.
    
    Args:
        page: Playwright page object
        group_name: Name of the meetup group
        
    Returns:
        bool: True if navigation successful, False otherwise
    """
    try:
        # Construct the URL for the group's past events
        events_url = f"https://www.meetup.com/{group_name}/events/past/"
        
        print(f"📍 Navigating to: {events_url}")
        response = page.goto(events_url, wait_until="domcontentloaded", timeout=30000)
        
        # Check if we got a 404 or other error
        if response and response.status >= 400:
            print(f"❌ Group '{group_name}' may not exist (HTTP {response.status})")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error navigating to group events: {e}")
        return False


def scroll_to_load_events(page: Page, max_events: int) -> None:
    """
    Scroll down the page to load all events up to max_events.
    
    Args:
        page: Playwright page object
        max_events: Maximum number of events to load
    """
    print(f"📜 Loading events (up to {max_events})...")
    
    # Wait for page to be fully loaded
    time.sleep(3)
    
    previous_count = 0
    scroll_attempts = 0
    max_scroll_attempts = 20  # Enough scrolls to load events
    
    while scroll_attempts < max_scroll_attempts:
        # Scroll to bottom of page
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)  # Wait for new content to load
        
        # Count events 
        events = page.locator('a[href*="/events/"]').all()
        current_count = len(events)
        
        print(f"   Found {current_count} event links...")
        
        # Stop if we have enough events or no new events loaded
        if current_count >= max_events or current_count == previous_count:
            break
            
        previous_count = current_count
        scroll_attempts += 1
    
    print(f"✅ Loaded {min(current_count, max_events)} events")



def scrape_events(page: Page, max_events: int) -> list:
    """
    Scrape event data from the loaded page, excluding cancelled events.
    
    Args:
        page: Playwright page object
        max_events: Maximum number of non-cancelled events to scrape
        
    Returns:
        List of event dictionaries matching the format: {id, url, name, date}
    """
    print(f"🔍 Scraping event data (excluding cancelled events)...")
    
    events = []
    
    # Find all event links  
    event_links = page.locator('a[href*="/events/"]').all()
    
    print(f"🔍 Found {len(event_links)} event links to process...")
    
    processed_count = 0
    for i, link in enumerate(event_links):
        try:
            processed_count += 1
            
            # Get event URL
            event_url = link.get_attribute('href')
            if event_url and not event_url.startswith('http'):
                event_url = f"https://www.meetup.com{event_url}"
            
            # Extract event ID from URL (the number after /events/)
            import re
            id_match = re.search(r'/events/(\d+)', event_url)
            if not id_match:
                continue  # Skip if no valid event ID
                
            event_id = id_match.group(1)
            
            # Check if event is cancelled - look in container for "Cancelled" text
            container = link.locator('xpath=../..').first
            try:
                container_text = container.inner_text()
                if 'cancelled' in container_text.lower():
                    print(f"   ⏭️  Skipping cancelled event {event_id}")
                    continue  # Skip cancelled events
            except Exception:
                pass
            
            # Get event name - need to extract just the title, not all the link text
            event_name = ""
            
            # Try to find the actual event title in the link or nearby elements
            try:
                # Strategy 1: Look for the event title in a heading within the link's container
                headings = container.locator('h1, h2, h3, h4, h5, h6').all()
                
                for heading in headings:
                    heading_text = heading.inner_text().strip()
                    # Skip if it's just a date or very short
                    if (heading_text and 
                        len(heading_text) > 10 and 
                        not heading_text.upper().startswith(('MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN')) and
                        ':' in heading_text):  # Event names often have colons
                        event_name = heading_text
                        break
                
                # Strategy 2: If no good heading found, try to extract from link text but clean it up
                if not event_name:
                    link_text = link.inner_text().strip()
                    if link_text:
                        # Split by newlines and look for the longest meaningful line
                        lines = [line.strip() for line in link_text.split('\n') if line.strip()]
                        for line in lines:
                            # Skip date lines, status lines, etc.
                            if (len(line) > 10 and 
                                not line.upper().startswith(('MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN')) and
                                'attendee' not in line.lower() and
                                'event has passed' not in line.lower() and
                                'cancelled' not in line.lower() and
                                ':' in line):
                                event_name = line
                                break
                        
                        # If still no good name found, take the longest line that's not a date
                        if not event_name:
                            longest_line = ""
                            for line in lines:
                                if (len(line) > len(longest_line) and 
                                    not line.upper().startswith(('MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN')) and
                                    'cancelled' not in line.lower()):
                                    longest_line = line
                            event_name = longest_line
                
            except Exception:
                pass
            
            if not event_name or len(event_name) < 3:
                continue  # Skip if no meaningful name
            
            # Find date - look in parent containers
            date_string = ""
            
            try:
                # Look for time elements
                time_elements = container.locator('time').all()
                for time_elem in time_elements:
                    date_text = time_elem.inner_text().strip()
                    if date_text and len(date_text) > 5:
                        date_string = date_text
                        break
                
                # If no time element found, look for date patterns in container text
                if not date_string:
                    container_text = container.inner_text()
                    date_patterns = [
                        r'[A-Z][a-z]{2},\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}[^0-9]*\d{1,2}:\d{2}\s+[AP]M\s+[A-Z]{3}',  # Full format
                        r'[A-Z][a-z]{2},\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}',  # Date only
                    ]
                    
                    for pattern in date_patterns:
                        match = re.search(pattern, container_text)
                        if match:
                            date_string = match.group()
                            break
            except:
                pass
            
            if not date_string:
                date_string = "Date not found"
            
            event_data = {
                "id": event_id,
                "url": event_url,
                "name": event_name,
                "date": date_string
            }
            
            events.append(event_data)
            print(f"   ✅ [{len(events)}/{max_events}] {event_name[:50]}...")
            
            # Stop if we have enough non-cancelled events
            if len(events) >= max_events:
                break
            
        except Exception as e:
            print(f"⚠️  Error scraping event {processed_count}: {e}")
            continue
    
    print(f"✅ Scraped {len(events)} valid events (processed {processed_count} total)")
    return events


def parse_date_to_folder_name(date_string: str) -> str:
    """
    Parse date string and convert to folder format YYYY_MM_DD.
    
    Args:
        date_string: Date like "WED, JUL 16, 2025, 10:00 AM BST"
        
    Returns:
        Formatted date string like "2025_07_16"
    """
    try:
        # Extract date parts using regex
        # Look for pattern like "JUL 16, 2025"
        match = re.search(r'([A-Z]{3})\s+(\d{1,2}),\s+(\d{4})', date_string.upper())
        if match:
            month_abbr, day, year = match.groups()
            
            # Convert month abbreviation to number
            months = {
                'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
                'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08', 
                'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'
            }
            
            month = months.get(month_abbr, '01')
            day = day.zfill(2)  # Pad with zero if needed
            
            return f"{year}_{month}_{day}"
    except Exception:
        pass
    
    # Fallback to today's date
    today = datetime.now()
    return f"{today.year}_{today.month:02d}_{today.day:02d}"


def save_event_data(event_data: dict) -> None:
    """
    Save event data to the events directory structure.
    
    Args:
        event_data: Dictionary containing event information {id, url, name, date}
    """
    try:
        # Create directory name from date
        date_folder = parse_date_to_folder_name(event_data['date'])
        event_dir = EVENTS_DIR / f"event_{date_folder}"
        event_dir.mkdir(exist_ok=True)
        
        # Save data.json
        data_file = event_dir / "data.json"
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(event_data, f, indent=2, ensure_ascii=False)
            
    except Exception as e:
        print(f"⚠️  Error saving event data: {e}")


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
    
    print(f"🚀 Meetup Group Past Events Scraper")
    print(f"📅 Accessing past events for group: {group_name}")
    print("-" * 50)
    
    # Setup directories
    setup_directories()
    
    try:
        with sync_playwright() as p:
            # Launch browser with persistent context
            print("🌐 Starting browser...")
            
            # Use persistent context to maintain session
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_STATE_DIR),
                headless=headless,
                args=[
                    "--no-first-run",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-extensions",
                    "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ]
            )
            
            # Get or create a page
            if context.pages:
                page = context.pages[0]
            else:
                page = context.new_page()
            
            # Navigate to the group's past events
            if not navigate_to_group_events(page, group_name):
                print("❌ Failed to navigate to group events page")
                return
            
            # Check if we hit a login page
            if is_login_page(page):
                if not wait_for_login_completion(page):
                    print("❌ Login verification failed. Exiting.")
                    return
                
                # Try navigating again after login
                if not navigate_to_group_events(page, group_name):
                    print("❌ Failed to navigate to group events page after login")
                    return
            
            print("✅ Successfully accessed the past events page!")
            print(f"📊 Current URL: {page.url}")
            
            # Scrape events
            print("\n🎯 Browser is ready!")
            print("The past events page is now loaded. The browser will stay open.")
            
            # Scroll to load events
            scroll_to_load_events(page, max_events)
            
            # Scrape event data
            events = scrape_events(page, max_events)
            
            # Save each event
            print(f"\n💾 Saving {len(events)} events...")
            for i, event in enumerate(events):
                save_event_data(event)
                date_folder = parse_date_to_folder_name(event['date'])
                print(f"   Saved event {i+1}/{len(events)}: event_{date_folder}")
            
            print(f"\n✅ All events saved to {EVENTS_DIR}")
            print("Press ENTER when you're done to close the browser...")
            
            input()
            
            print("👋 Closing browser...")
            context.close()
            
    except KeyboardInterrupt:
        print("\n⏹️  Operation cancelled by user")
    except Exception as e:
        print(f"❌ An error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 