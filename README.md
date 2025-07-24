# Meetup.com Group Past Events Scraper

A Python tool to scrape past events from any Meetup.com group page.

## Features

- 🚀 **Simple CLI**: Easy command-line interface
- 🔐 **Session Persistence**: Handles login automatically using persistent browser state
- 📊 **Comprehensive Data**: Extracts event details, dates, attendees, hosts, locations, and descriptions
- 📁 **Organized Storage**: Saves events in date-based directories with sanitized filenames
- ⚡ **Fast & Reliable**: Two-phase scraping approach for better reliability

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd meetup
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

### Basic Usage

```bash
python meetup_scraper.py <group-name>
```

### Examples

```bash
# Scrape 10 events (default)
python meetup_scraper.py python-seattle

# Scrape specific number of events
python meetup_scraper.py python-seattle --max-events 25
```

### Group Name Format

Extract the group name from the Meetup URL:
- URL: `https://www.meetup.com/python-seattle/` → Group name: `python-seattle`
- URL: `https://www.meetup.com/SF-JavaScript/` → Group name: `SF-JavaScript`

## CLI Options

- `--max-events`: Maximum number of events to scrape (default: 10)

## First-Time Setup

On first run, the browser will open for login:

1. Log in to your Meetup.com account
2. Press ENTER in the terminal when ready
3. The scraper will continue automatically

Your login session is saved for future runs.

## Output Structure

Events are saved in the `events/` directory:

```
events/
├── 2025-01-15/
│   ├── Python Workshop Introduction to Data Science.json
│   └── Advanced Flask Development Patterns.json
├── 2025-01-20/
│   └── Monthly Python Networking Social.json
```

### Event Data Format

Each JSON file contains:

```json
{
  "id": "123456789",
  "url": "https://www.meetup.com/group/events/123456789/",
  "name": "Event Title",
  "date": "WED, JAN 15, 2025, 7:00 PM PST",
  "attendees": 42,
  "host": "Host Name",
  "location": "Event Location",
  "details": "Event description...",
  "cancelled": false
}
```

## Requirements

- Python 3.9+
- Dependencies listed in `requirements.txt`
- Chromium browser (installed via Playwright)

## Dependencies

- `playwright` - Browser automation
- `click` - CLI interface
- `python-dateutil` - Date parsing
- `pathvalidate` - Filename sanitization 