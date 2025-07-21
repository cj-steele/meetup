#!/bin/bash

# Meetup Scraper Setup Script

echo "🚀 Setting up Meetup Group Past Events Scraper..."
echo "=" * 50

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.7+ first."
    exit 1
fi

echo "✅ Python 3 found"

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip3 install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "❌ Failed to install Python dependencies"
    exit 1
fi

echo "✅ Python dependencies installed"

# Install Playwright browsers
echo "🌐 Installing Playwright browsers..."
playwright install chromium

if [ $? -ne 0 ]; then
    echo "❌ Failed to install Playwright browsers"
    exit 1
fi

echo "✅ Playwright browsers installed"

# Make script executable
chmod +x meetup_scraper.py

echo "🎉 Setup complete!"
echo ""
echo "Usage:"
echo "  python3 meetup_scraper.py GROUP_NAME"
echo ""
echo "Example:"
echo "  python3 meetup_scraper.py python-seattle"
echo ""
echo "For more information, see README.md" 