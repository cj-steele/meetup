# Meetup Event Scraper

A Python tool to scrape past event data from Meetup groups using Playwright automation.

## Features

- ✅ **Smart lazy loading** - Handles groups with 400+ events
- ✅ **Two-phase scraping** - Fast URL caching then detailed extraction
- ✅ **Smart browser switching** - Non-headless only when login needed, then headless for scraping
- ✅ **Session persistence** - Remembers login between runs using `session.json`
- ✅ **Multiple output formats** - CSV and JSON (both enabled by default)
- ✅ **Flexible output control** - Use `--no-csv` or `--no-json` to customize
- ✅ **Cross-platform** - Works on Windows, macOS, and Linux
- ✅ **Robust error handling** - Graceful handling of missing data
- ✅ **Progress tracking** - Real-time progress updates

## Installation

### Prerequisites
- Python 3.8 or higher
- Git

### Setup

**Windows:**
```cmd
git clone https://github.com/your-username/meetup.git
cd meetup
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

**macOS/Linux:**
```bash
git clone https://github.com/your-username/meetup.git
cd meetup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Usage

### Basic Commands

**Default - saves both CSV and JSON:**
```bash
python meetup_scraper.py group-name --max-events 50
```

**Scrape all available events:**
```bash
python meetup_scraper.py group-name --all
```

**Only CSV output:**
```bash
python meetup_scraper.py group-name --max-events 100 --no-json
```

**Only JSON output:**
```bash
python meetup_scraper.py group-name --max-events 100 --no-csv
```

### CLI Options

| Option | Description |
|--------|-------------|
| `--max-events N` | Maximum number of events to scrape (default: 10) |
| `--all` | Scrape ALL available events (overrides --max-events) |
| `--no-csv` | Disable CSV output (CSV enabled by default) |
| `--no-json` | Disable JSON output (JSON enabled by default) |

**Note:** Using both `--no-csv` and `--no-json` will exit early with a warning, as there would be no output saved.

### First Run

On the first run, you'll be prompted to log in to Meetup:
1. A browser window will open for authentication
2. Log in with your Meetup credentials 
3. Press ENTER in the terminal when done
4. Your session will be saved to `session.json` for future runs

### Subsequent Runs

After the first login:
- Session automatically restored from `session.json`
- **Goes straight to headless mode** - no browser window opens
- Much faster startup and execution

### Output

Events are saved to:
- **CSV file**: `events/events.csv` (all events in one file, **enabled by default**)
- **JSON files**: `events/YYYY-MM-DD/event-name.json` (one per event, **enabled by default**)

## Smart Browser Mode

The scraper intelligently manages browser visibility:

1. **Login needed**: Opens visible browser for authentication → saves session → switches to headless
2. **Already logged in**: Restores session → goes straight to headless mode
3. **Session expires**: (after 7 days) Prompts for fresh login

**Benefits:**
- **Efficient**: Headless mode for all scraping operations
- **User-friendly**: Visible browser only when human interaction needed  
- **Fast**: Session persistence eliminates repeated logins

## Session Management

- **Session file**: `session.json` (lightweight, ~20KB)
- **Contains**: Cookies and localStorage data
- **Expires**: After 7 days (automatic cleanup)
- **Cross-platform**: Works identically on Windows/macOS/Linux
- **Debuggable**: Plain JSON format for troubleshooting

## Examples

```bash
# Scrape 25 recent events (CSV + JSON)
python meetup_scraper.py python-glasgow --max-events 25

# Scrape all events, save only CSV
python meetup_scraper.py london-tech-meetups --all --no-json

# Scrape 100 events, save only JSON
python meetup_scraper.py react-london --max-events 100 --no-csv

# Get 50 events from Perth Outdoors Scotland Group  
python meetup_scraper.py p-o-s-g --max-events 50
```

## Troubleshooting

**Login issues:**
- Delete `session.json` to force fresh login
- Ensure you have valid Meetup account

**Slow loading:**
- Large groups (400+ events) may take several minutes
- Progress is shown in real-time

**Platform issues:**
- Ensure Playwright browsers are installed: `playwright install chromium`
- On Linux, you may need additional dependencies: `playwright install-deps`

**Session problems:**
- Session expires after 7 days automatically
- Delete `session.json` if experiencing login loops

**Output format errors:**
- Using both `--no-csv` and `--no-json` will exit early with a helpful message
- At least one output format must be enabled for scraping to proceed

## Output Format Details

### CSV Format
All events in one file with columns:
- `id`, `url`, `name`, `date`, `time`, `attendees`, `host`, `location`, `details`, `cancelled`

### JSON Format  
Individual files per event with full structured data:
```json
{
  "id": "123456789",
  "url": "https://www.meetup.com/group/events/123456789/",
  "name": "Event Title",
  "date": "Wednesday, January 15, 2025",
  "time": "7:00 PM to 9:00 PM PST",
  "attendees": 42,
  "host": "Host Name", 
  "location": "Event Location",
  "details": "Event description...",
  "cancelled": false
}
``` 