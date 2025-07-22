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
import requests
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
    ATTENDEES_DIR = EVENTS_DIR / "attendees"
    ATTENDEES_DIR.mkdir(exist_ok=True)


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


def scroll_to_load_events(page: Page, max_events: int):
    """
    Scroll the page to load more events dynamically.
    
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
        
        # Count events using CSS selector for event cards
        event_cards = page.locator('[id^="past-event-card-ep-"]')
        current_count = event_cards.count()
        
        print(f"   Found {current_count} event cards...")
        
        # If we find 0 events, debug what's on the page
        if current_count == 0 and scroll_attempts == 0:
            page_text = page.inner_text('body').lower()
            print(f"   🔍 Debugging 0 events - Page title: {page.title()}")
            print(f"   🔍 Current URL: {page.url}")
            if 'login' in page_text or 'sign in' in page_text:
                print("   ⚠️  Page contains login content - authentication required!")
                return 0
            if 'no events' in page_text or 'no upcoming events' in page_text or 'no past events' in page_text:
                print("   ℹ️  Page indicates no events available")
                return 0
        
        # Stop if we have enough events or no new events loaded
        if current_count >= max_events or current_count == previous_count:
            break
            
        previous_count = current_count
        scroll_attempts += 1
    
    print(f"✅ Loaded {current_count} events")
    return current_count



def download_avatar(avatar_url: str, filename: str, attendees_dir: Path) -> str:
    """
    Download an avatar image and save it to the attendees directory.
    
    Args:
        avatar_url: URL of the avatar image (e.g., contains thumb_323391730.jpeg)
        filename: Attendee name to use in filename
        attendees_dir: Directory to save avatars in
        
    Returns:
        Relative path to the saved avatar or empty string if failed
    """
    try:
        # Extract member ID from avatar URL (e.g., thumb_323391730.jpeg -> 323391730)
        member_id = ""
        id_match = re.search(r'thumb_(\d+)', avatar_url)
        if id_match:
            member_id = id_match.group(1)
        
        # Clean filename to be filesystem-safe
        safe_name = re.sub(r'[^\w\s-]', '', filename).strip()
        safe_name = re.sub(r'[-\s]+', '-', safe_name)
        
        # Create filename with format: [name]_[member_id].jpg
        if member_id:
            safe_filename = f"{safe_name}_{member_id}.jpg"
        else:
            safe_filename = f"{safe_name}.jpg"
            
        avatar_path = attendees_dir / safe_filename
        
        # Don't overwrite existing files
        if avatar_path.exists():
            return f"events/attendees/{safe_filename}"
            
        # Download the image
        response = requests.get(avatar_url, timeout=10)
        response.raise_for_status()
        
        # Save the image
        with open(avatar_path, 'wb') as f:
            f.write(response.content)
            
        return f"events/attendees/{safe_filename}"
        
    except Exception as e:
        print(f"      ⚠️  Failed to download avatar for {filename}: {e}")
        return ""


def extract_attendees(page: Page, event_url: str) -> list:
    """
    Extract attendee information including names, host status, avatars, and guest counts.
    
    Args:
        page: Playwright page object
        event_url: URL of the event page
        
    Returns:
        List of attendee dictionaries with name, is_host, avatar_path, and guests
    """
    attendees = []
    attendees_dir = EVENTS_DIR / "attendees"
    
    try:
        print(f"      👥 Extracting attendees...")
        
        # Click the attendees button using CSS selector (much more reliable)
        attendees_button = page.locator('#attendees-btn')
        
        if attendees_button.is_visible(timeout=3000):
            attendees_button.click()
            time.sleep(2)  # Wait for navigation
            
            # Handle paywall if present
            try:
                paywall_button_xpath = "/html/body/div[1]/div[3]/div/div[1]/div/div/div[1]/div[1]/div/button"
                paywall_button = page.locator(f"xpath={paywall_button_xpath}")
                if paywall_button.is_visible(timeout=3000):
                    print(f"      💰 Handling paywall...")
                    paywall_button.click()
                    time.sleep(2)
            except Exception:
                pass  # No paywall or couldn't handle it
            
            # Scroll to make sure all attendees are loaded
            try:
                for _ in range(3):  # Scroll a few times
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(1)
            except:
                pass
            
            # Extract attendee information using CSS selector structure
            attendee_containers = None
            attendee_count = 0
            
            # Use CSS selector to find all attendee button containers
            # Base selector path to the attendees list area
            attendees_base_selector = "#page > div.flex.flex-grow.flex-col > main > div.md\\:max-w-screen.z-10.mb-5.w-full.sm\\:my-4.sm\\:px-5.md\\:w-\\[750px\\].md\\:w-\\[600px\\] > div > div:nth-child(6) > div"
            attendees_container = page.locator(attendees_base_selector)
            
            if attendees_container.count() > 0:
                # Find all individual attendee containers 
                attendee_containers = attendees_container.locator("> div")
                attendee_count = attendee_containers.count()
                print(f"      👥 Found {attendee_count} attendee containers using CSS selector")
            
            if attendee_count == 0:
                print(f"      👥 Found {attendee_count} attendee containers")
            
            # Wait a bit longer for attendees to load after paywall
            time.sleep(3)
            
            # Track unique attendees to avoid duplicates
            seen_attendees = set()
            
            for i in range(attendee_count):
                try:
                    container = attendee_containers.nth(i)
                    
                    # Extract name using CSS selector within the container
                    attendee_name = "Unknown"
                    try:
                        # Look for the name within this container
                        name_element = container.locator("div > div > div > div > button > div > div > p")
                        if name_element.count() > 0:
                            attendee_name = name_element.first.inner_text().strip()
                    except Exception:
                        pass
                    
                    # Extract host status using CSS selector within the container
                    is_host = False
                    try:
                        # Look for host marker within this container
                        host_element = container.locator("div > div > div > div > button > div > div > div > div:first-child")
                        if host_element.count() > 0:
                            host_text = host_element.first.inner_text().strip()
                            is_host = "Event host" in host_text
                    except Exception:
                        pass
                    
                    # Extract guest information from container text
                    guests = 0
                    try:
                        # Get all text from this attendee container
                        container_text = container.inner_text()
                        
                        # Look for guest indicators like "+1", "plus 1", "guest", etc.
                        guest_patterns = [
                            r'\+(\d+)',  # "+1", "+2", etc.
                            r'plus\s+(\d+)',  # "plus 1", "plus 2"
                            r'(\d+)\s+guest',  # "1 guest", "2 guests"
                            r'bringing\s+(\d+)',  # "bringing 1", "bringing 2"
                        ]
                        
                        for pattern in guest_patterns:
                            match = re.search(pattern, container_text, re.IGNORECASE)
                            if match:
                                guests = int(match.group(1))
                                break
                        
                        # If no number found but text contains guest-related words, assume 1
                        if guests == 0 and any(word in container_text.lower() for word in ['guest', 'plus', '+', 'bringing']):
                                guests = 1
                    except Exception:
                        pass
                    
                    # Skip if we already have this attendee (deduplicate)
                    attendee_key = f"{attendee_name}_{is_host}"
                    if attendee_key in seen_attendees:
                        print(f"      ⚠️  Skipped duplicate: {attendee_name}")
                        continue
                    
                    # Extract avatar using CSS selector within the container
                    avatar_path = ""
                    try:
                        # Look for avatar image within this container
                        avatar_img = container.locator("div > div > div > div > button > div > picture > img")
                        if avatar_img.count() > 0:
                            avatar_url = avatar_img.first.get_attribute('src')
                            if avatar_url:
                                avatar_path = download_avatar(avatar_url, attendee_name, attendees_dir)
                    except Exception:
                        pass
                    
                    # Only add if we got a valid name
                    if attendee_name and attendee_name != "Unknown" and len(attendee_name) > 2:
                        attendee_data = {
                            "name": attendee_name,
                            "is_host": is_host,
                            "avatar_path": avatar_path,
                            "guests": guests
                        }
                        
                        attendees.append(attendee_data)
                        seen_attendees.add(attendee_key)
                        guest_info = f" (+{guests} guest{'s' if guests != 1 else ''})" if guests > 0 else ""
                        print(f"      ✅ Attendee {len(attendees)}: {attendee_name}" + (" (Host)" if is_host else "") + guest_info)
                    else:
                        print(f"      ⚠️  Skipped container {i+1} - invalid name: {attendee_name}")
                    
                except Exception as e:
                    print(f"      ⚠️  Error extracting attendee {i+1}: {e}")
                    continue
                    
        else:
            print(f"      ⚠️  Attendees button not found")
            
    except Exception as e:
        print(f"      ⚠️  Error extracting attendees: {e}")
    
    return attendees


def extract_event_details(page: Page, event_url: str, return_url: str) -> tuple:
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
        print(f"      🔍 Visiting event page...")
        page.goto(event_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)  # Wait for page to load
        
                # Extract location
        location = ""
        try:
            # Use the specific XPath provided by user for location
            location_xpath = "/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div[3]/div[1]/div/div[2]/div[2]/div[2]/div/div[1]/div[3]/div/div[2]"
            location_elem = page.locator(f"xpath={location_xpath}")
            
            if location_elem.is_visible(timeout=3000):
                location = location_elem.inner_text().strip()
            
            # Fallback to other selectors if XPath doesn't work
            if not location:
                location_selectors = [
                    '[data-testid="event-location"]',
                    '[data-testid="venue-info"]',
                    '.venueDisplay',
                    '.event-location',
                    '.venue-info',
                    '[class*="location"]',
                    '[class*="venue"]'
                ]
                
                for selector in location_selectors:
                    try:
                        location_elem = page.locator(selector).first
                        if location_elem.is_visible(timeout=1000):
                            location = location_elem.inner_text().strip()
                            if location and len(location) > 5 and len(location) < 200:
                                break
                    except:
                        continue
                        
        except Exception:
            pass
            
        if not location:
            location = "Location not found"
        
        # Extract details from the Details section
        details = ""
        try:
            # Use CSS selector for details (more reliable than XPath)
            details_elem = page.locator("#event-details > div.break-words")
            
            if details_elem.count() > 0 and details_elem.is_visible(timeout=3000):
                details = details_elem.inner_text().strip()
            
            # Fallback to other selectors if primary doesn't work
            if not details:
                details_selectors = [
                    "#event-details",
                    '[data-testid="event-description"]',
                    '.event-description',
                    '.description',
                    '[class*="description"]',
                    '#details',
                    '.event-details',
                    # XPath as last resort
                    "xpath=/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div[3]/div[1]/div/div[1]/div[1]/div[2]/div[2]"
                ]
                
                for selector in details_selectors:
                    try:
                        details_elem = page.locator(selector)
                        if details_elem.count() > 0 and details_elem.is_visible(timeout=2000):
                            details = details_elem.inner_text().strip()
                            if details and len(details) > 50:  # Make sure it's substantial content
                                break
                    except:
                        continue
                
        except Exception:
            pass
            
        if not details:
            details = "Details not found"
        
        # Extract attendees information
        attendees = extract_attendees(page, event_url)
        
        # Navigate back to the events list page
        page.goto(return_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(1)  # Brief wait for page to load
        
        return location, details, attendees
        
    except Exception as e:
        print(f"      ⚠️  Error extracting event details: {e}")
        # Try to return to events page even if extraction failed
        try:
            page.goto(return_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(1)
        except:
            pass
        return "Location not found", "Details not found", []


def scrape_events(page: Page, max_events: int) -> list:
    """
    Scrape event data from the loaded page, excluding cancelled events.
    Visits each individual event page to extract detailed information and attendees.
    
    Args:
        page: Playwright page object
        max_events: Maximum number of non-cancelled events to scrape
        
    Returns:
        List of event dictionaries: {id, url, name, date, attendees, location, details, attendees_list}
        Each attendee in attendees_list includes: {name, is_host, avatar_path, guests}
        The attendees field is calculated as "X members + Y guests = Z total" based on actual data
    """
    print(f"🔍 Scraping event data (excluding cancelled events)...")
    
    events = []
    
    # Save the current events list URL for returning to after visiting individual events
    events_list_url = page.url
    
    # Find all event cards using CSS selector
    event_cards = page.locator('[id^="past-event-card-ep-"]')
    event_count = event_cards.count()
    
    print(f"🔍 Found {event_count} event cards to process...")
    
    processed_count = 0
    
    for i in range(event_count):
        if len(events) >= max_events:
            break
            
        try:
            event_card = event_cards.nth(i)
            processed_count += 1
            
            # Extract event URL from the card (it should be clickable/have href)
            event_url = ""
            try:
                # The card itself might be a link, or contain a link
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
                print(f"   ⚠️  Skipped card {i+1} - could not extract URL")
                continue
            
            # Extract event title using CSS selector
            event_name = ""
            try:
                title_element = event_card.locator('div.flex.flex-col.space-y-5.overflow-hidden > div > div > span')
                if title_element.count() > 0:
                    event_name = title_element.first.inner_text().strip()
            except Exception:
                pass
            
            # Extract event date using CSS selector
            date_string = ""
            try:
                date_element = event_card.locator('div.flex.flex-col.space-y-5.overflow-hidden > div > div > time')
                if date_element.count() > 0:
                    date_string = date_element.first.inner_text().strip()
            except Exception:
                pass
            
            # Skip if we couldn't get basic info
            if not event_name or not event_url:
                print(f"   ⚠️  Skipped card {i+1} - missing basic info (name: {bool(event_name)}, url: {bool(event_url)})")
                continue
            
            # Check if event is cancelled by looking at the title or attendee text
            container_text = event_card.inner_text().lower()
            if 'cancelled' in container_text:
                print(f"   ⚠️  Skipped cancelled event: {event_name[:50]}...")
                continue
            
            # Extract event ID from URL
            event_id = ""
            try:
                match = re.search(r'/events/(\d+)', event_url)
                if match:
                    event_id = match.group(1)
            except Exception:
                pass
            
            print(f"      🔍 Event ID: {event_id}, Date: {date_string}")
            
            # Extract detailed information from the individual event page
            print(f"   🔍 [{len(events)+1}/{max_events}] {event_name[:50]}...")
            location, details, attendees_list = extract_event_details(page, event_url, events_list_url)
            
            # Calculate total attendees (members + guests) from actual data
            total_members = len(attendees_list)
            total_guests = sum(attendee.get('guests', 0) for attendee in attendees_list)
            total_attendees = total_members + total_guests
            
            # Format attendees summary
            if total_guests > 0:
                attendees_summary = f"{total_members} members + {total_guests} guests = {total_attendees} total"
            else:
                attendees_summary = f"{total_members} members"
            
            event_data = {
                "id": event_id,
                "url": event_url,
                "name": event_name,
                "date": date_string,
                "attendees": attendees_summary,
                "location": location,
                "details": details,
                "attendees_list": attendees_list
            }
            
            events.append(event_data)
            
            # Save immediately after processing each event
            try:
                save_event_data(event_data)
                iso_date = parse_date_to_iso_format(event_data['date'])
                event_id = event_data['id']
                directory_name = f"{iso_date}_{event_id}"
                print(f"      ✅ Event {len(events)} complete and saved: {directory_name}")
                print(f"      📊 Progress: {len(events)}/{max_events} events collected")
            except Exception as e:
                print(f"      ⚠️  Event {len(events)} complete but save failed: {e}")
                print(f"      📊 Progress: {len(events)}/{max_events} events collected")
            
            # Stop if we have enough non-cancelled events
            if len(events) >= max_events:
                print(f"      🎯 Reached target of {max_events} events - stopping")
                break
                
        except Exception as e:
            print(f"   ⚠️  Error processing event card {i+1}: {e}")
            print(f"   📊 Continuing to next event... (current progress: {len(events)}/{max_events})")
            continue
    
    print(f"✅ Scraped {len(events)} valid events (processed {processed_count} total)")
    return events


def parse_date_to_iso_format(date_string: str) -> str:
    """
    Parse date string and convert to ISO format YYYY-MM-DD.
    
    Args:
        date_string: Date like "WED, JUL 16, 2025, 10:00 AM BST"
        
    Returns:
        Formatted date string like "2025-07-16"
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
            
            return f"{year}-{month}-{day}"
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
        # Create directory name from ISO date and event ID
        iso_date = parse_date_to_iso_format(event_data['date'])
        event_id = event_data['id']
        event_dir = EVENTS_DIR / f"{iso_date}_{event_id}"
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
            
            print(f"\n✅ All {len(events)} events processed and saved to {EVENTS_DIR}")
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