# Meetup Group Past Events Scraper

> **Note**: This is a vibe coding experiment to meet a personal need and is not intended for public consumption.

A command line tool that automates accessing past events for specific Meetup groups. The application handles login detection, session persistence, and provides a user-friendly interface for interacting with Meetup.com.

## Features

- 🚀 **Automated Navigation**: Directly navigates to any Meetup group's past events page
- 🔐 **Smart Login Detection**: Automatically detects when login is required
- 💾 **Session Persistence**: Saves browser session to reduce login frequency
- 🖥️ **Visual Browser**: Uses non-headless Chromium for easy login interaction
- ⚡ **Command Line Interface**: Simple CLI with clear feedback
- 🛡️ **Error Handling**: Comprehensive error handling and user guidance

## Prerequisites

- Python 3.7+
- pip (Python package manager)

## Installation

1. **Clone or download the project files**

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Playwright browsers:**
   ```bash
   playwright install chromium
   ```

## Usage

### Basic Usage

```bash
python meetup_scraper.py GROUP_NAME
```

Where `GROUP_NAME` is the group identifier from the Meetup URL.

### Examples

```bash
# For a group at https://www.meetup.com/python-seattle/
python meetup_scraper.py python-seattle

# For a group at https://www.meetup.com/SF-JavaScript/
python meetup_scraper.py SF-JavaScript
```

### Options

- `--headless`: Run browser in headless mode (not recommended for first-time login)

```bash
python meetup_scraper.py python-seattle --headless
```

## How It Works

1. **Launches Browser**: Opens a Chromium browser with persistent session storage
2. **Navigates to Group**: Goes directly to the specified group's past events page
3. **Login Detection**: If redirected to login, prompts user to log in manually
4. **Session Persistence**: Saves cookies and session data for future runs
5. **User Interaction**: Keeps browser open for you to browse the events

## Session Persistence

The application stores browser session data in the project directory:
- **Location**: `./browser_state/` (within the project folder)

This means you typically only need to log in once, and subsequent runs will use your saved session.

## Login Process

When login is required:

1. The app detects the login redirect
2. Displays a clear message about login being needed
3. Waits for you to complete login in the browser window
4. Prompts you to press ENTER when login is complete
5. Verifies login success and continues

## Troubleshooting

### "Login verification failed"
- Make sure you've completed the login process completely
- Check that you're not still on a login/signup page
- Try running the command again

### "Failed to navigate to group events page"
- Verify the group name is correct (check the Meetup URL)
- Ensure you have internet connectivity
- The group might not exist or might be private

### Browser issues
- If the browser doesn't open, try reinstalling Playwright:
  ```bash
  playwright install chromium
  ```

### Permission issues
- Make sure the script has permission to create directories in your home folder
- On some systems, you might need to run with appropriate permissions

## Security Notes

- Browser session data is stored locally on your machine
- No credentials are stored or transmitted by this application
- The app uses your manual login through the actual Meetup.com website

## Group Name Format

The group name should match the identifier in the Meetup URL:
- URL: `https://www.meetup.com/python-seattle/` → Group name: `python-seattle`
- URL: `https://www.meetup.com/SF-JavaScript/` → Group name: `SF-JavaScript`

## Requirements

See `requirements.txt` for the complete list of Python dependencies:
- `playwright`: Browser automation
- `click`: Command line interface

## Support

If you encounter issues:
1. Check that the group name matches the URL exactly
2. Ensure Playwright is properly installed
3. Verify your internet connection
4. Try clearing browser data by deleting the `./browser_state/` directory 