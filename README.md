# Meetup Event Scraper

A Python tool to scrape past event data from Meetup groups using Playwright automation.

## Features

- ✅ **Smart lazy loading** - Handles groups with 400+ events
- ✅ **Two-phase scraping** - Fast URL caching then detailed extraction
- ✅ **Session persistence** - Remembers login between runs
- ✅ **Multiple output formats** - JSON files and CSV export
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

**Scrape specific number of events:**
```bash
python meetup_scraper.py group-name --max-events 50
```

**Scrape all available events:**
```bash
python meetup_scraper.py group-name --all
```

**Export to CSV:**
```bash
python meetup_scraper.py group-name --max-events 100 --csv
```

### First Run

On the first run, you'll be prompted to log in to Meetup:
1. A browser window will open
2. Log in with your Meetup credentials 
3. Press ENTER in the terminal when done
4. Your session will be saved for future runs

### Output

Events are saved to:
- **JSON files**: `events/YYYY-MM-DD/event-name.json` (one per event)
- **CSV file**: `events/events.csv` (all events in one file, if `--csv` used)

## Cross-Platform Notes

- **Windows**: Uses Windows Chrome user agent and paths
- **macOS**: Uses macOS Safari user agent and Unix paths  
- **Linux**: Uses Linux Chrome user agent and Unix paths
- **Browser state**: Automatically saved in `browser_state/` directory on all platforms

## Examples

```bash
# Scrape 25 recent events from Python Glasgow
python meetup_scraper.py python-glasgow --max-events 25

# Scrape all events from London Tech Meetups and export CSV
python meetup_scraper.py london-tech-meetups --all --csv

# Scrape 100 events from React London
python meetup_scraper.py react-london --max-events 100
```

## Troubleshooting

**Login issues:**
- Delete `browser_state/` directory to force fresh login
- Ensure you have valid Meetup account

**Slow loading:**
- Large groups (400+ events) may take several minutes
- Progress is shown in real-time

**Platform issues:**
- Ensure Playwright browsers are installed: `playwright install chromium`
- On Linux, you may need additional dependencies: `playwright install-deps` 