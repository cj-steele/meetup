#!/usr/bin/env python3
"""
Meetup.com Group Past Events Scraper

A command line tool to access past events for a specific Meetup group.
Handles login detection and session persistence.
"""

import sys
import time
import click
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

# Configuration
PROJECT_DIR = Path(__file__).parent
BROWSER_STATE_DIR = PROJECT_DIR / "browser_state"


def setup_directories():
    """Create necessary directories for storing browser state."""
    BROWSER_STATE_DIR.mkdir(exist_ok=True)


def is_login_page(page: Page, debug=False) -> bool:
    """
    Detect if we've been redirected to a login page.
    
    Args:
        page: Playwright page object
        debug: Whether to show debug output
        
    Returns:
        bool: True if on a login page, False otherwise
    """
    return page.title().startswith("Login to Meetup")


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


@click.command()
@click.argument('group_name', required=True)
@click.option('--headless', is_flag=True, help='Run browser in headless mode')
def main(group_name: str, headless: bool):
    """
    Access past events for a Meetup group.
    
    GROUP_NAME: The name of the meetup group (from the URL)
    
    Example: meetup_scraper.py python-seattle
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
            if is_login_page(page, debug=True):
                if not wait_for_login_completion(page):
                    print("❌ Login verification failed. Exiting.")
                    return
                
                # Try navigating again after login
                if not navigate_to_group_events(page, group_name):
                    print("❌ Failed to navigate to group events page after login")
                    return
            
            print("✅ Successfully accessed the past events page!")
            print(f"📊 Current URL: {page.url}")
            
            # Keep browser open for user to interact
            print("\n🎯 Browser is ready!")
            print("The past events page is now loaded. The browser will stay open.")
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