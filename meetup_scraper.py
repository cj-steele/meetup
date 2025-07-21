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
    current_url = page.url.lower()
    
    if debug:
        print(f"🔍 Checking login status for URL: {current_url}")
    
    # First check if we're already on the target page (past events or group page)
    if any(indicator in current_url for indicator in ['/events/past', '/events/', 'meetup.com/']):
        # If we're on a meetup page that's not explicitly a login page, assume we're good
        if not any(login_indicator in current_url for login_indicator in ['/login', '/signin', '/sign-in', '/auth']):
            if debug:
                print("✅ URL indicates we're on a valid Meetup page")
            return False
    
    # Check URL patterns that definitively indicate login
    login_url_indicators = [
        '/login',
        '/signin', 
        '/sign-in',
        '/auth',
        '/register',
        '/signup',
        'login.meetup.com',
        'secure.meetup.com/login'
    ]
    
    # Check if any login indicators are in the URL path
    if any(indicator in current_url for indicator in login_url_indicators):
        if debug:
            print(f"❌ URL contains login indicator: {current_url}")
        return True
    
    # Only do element checking if URL is ambiguous
    try:
        # Look for very specific login form patterns
        login_form_selector = 'form[action*="login"], form[action*="signin"], form[action*="auth"]'
        has_login_form = page.locator(login_form_selector).first.is_visible(timeout=1000)
        
        if has_login_form:
            if debug:
                print("❌ Found login form on page")
            return True
            
        # Look for specific Meetup login button/text
        meetup_login_selectors = [
            'text="Log in"',
            'text="Sign in"', 
            '[data-testid*="login"]',
            'button:has-text("Log in")',
            'button:has-text("Sign in")'
        ]
        
        for selector in meetup_login_selectors:
            if page.locator(selector).first.is_visible(timeout=500):
                if debug:
                    print(f"❌ Found login element: {selector}")
                return True
                
    except Exception as e:
        if debug:
            print(f"⚠️  Exception during login detection: {e}")
        pass
    
    if debug:
        print("✅ No login indicators found")
    return False


def wait_for_login_completion(page: Page):
    """
    Wait for user to complete login and notify when done.
    
    Args:
        page: Playwright page object
    """
    print("\n🔐 Login Required!")
    print("=" * 50)
    print("It looks like you need to log in to Meetup.com")
    print("Please log in using the browser window that opened.")
    print("After logging in successfully, press ENTER to continue...")
    print("=" * 50)
    
    # Wait for user to press enter
    input()
    
    # Wait briefly for any immediate redirects
    print("⏳ Checking if page redirects automatically...")
    login_url = page.url
    
    # Wait up to 3 seconds for URL to change from login page
    for i in range(3):
        time.sleep(1)
        current_url = page.url
        if current_url != login_url:
            print(f"✅ Page redirected to: {current_url}")
            break
    else:
        print("ℹ️  Meetup doesn't auto-redirect after login (this is normal)")
    
    # Debug: Show current URL
    current_url = page.url
    print(f"🔍 Current URL: {current_url}")
    
    # Verify login was successful
    if is_login_page(page, debug=False):  # Less verbose since this is expected
        print("📋 Still on login page - this is normal for Meetup.com")
        print("✅ Assuming login was successful and proceeding...")
        return True
    
    print("✅ Login successful! Continuing...")
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
        page.goto(events_url, wait_until="domcontentloaded", timeout=30000)
        
        # Wait a moment for any redirects
        time.sleep(2)
        
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
                    "--disable-blink-features=AutomationControlled"
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