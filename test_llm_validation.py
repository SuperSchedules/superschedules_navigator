#!/usr/bin/env python
"""
Quick test script for LLM text validation.

Run: python test_llm_validation.py <url> [poi_name] [category] [city]
     python test_llm_validation.py --events <url> [poi_name] [category] [city]

Examples:
    python test_llm_validation.py "https://needhamma.gov/parks" "Memorial Park" park Needham
    python test_llm_validation.py "https://dictionary.com/browse/park" "Memorial Park" park Needham
    python test_llm_validation.py --events "https://needhamma.gov/calendar" "DeFazio Park" park Needham
"""

import asyncio
import sys
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

import requests
from navigator.services.website_finder import strip_html_to_text, validate_with_llm_text
from navigator.services.event_page_finder import validate_events_page_with_llm, _strip_html_to_text

# Simple POI-like object for testing
class FakePOI:
    def __init__(self, name, category, city):
        self.name = name
        self.category = category
        self.city = city
        self.street_address = ''


def fetch_html(url: str) -> str:
    """Fetch HTML from a URL."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    resp = requests.get(url, timeout=15, headers=headers, allow_redirects=True)
    resp.raise_for_status()
    return resp.text


async def test_url(url: str, poi_name: str, category: str, city: str, mode: str = 'website'):
    """Test LLM validation on a URL."""
    print(f"\n{'='*60}")
    print(f"MODE: {mode.upper()} validation")
    print(f"URL: {url}")
    print(f"POI: {poi_name} ({category}) in {city}")
    print('='*60)

    # Fetch HTML
    print("\nFetching HTML...")
    try:
        html = fetch_html(url)
        print(f"  Got {len(html)} bytes")
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    # Strip to text
    text = strip_html_to_text(html)
    print(f"\nStripped text ({len(text)} chars):")
    print("-"*40)
    print(text[:1000])
    print("-"*40)
    if len(text) > 1000:
        print(f"... ({len(text) - 1000} more chars)")

    # Run LLM validation
    poi = FakePOI(poi_name, category, city)

    if mode == 'events':
        print("\nRunning EVENTS page LLM validation...")
        result = await validate_events_page_with_llm(html, url, poi)
        print(f"\nRESULT:")
        print(f"  Has Events: {result['has_events']}")
        print(f"  Confidence: {result['confidence']}")
        print(f"  Reason: {result['reason']}")
    else:
        print("\nRunning WEBSITE LLM validation...")
        result = await validate_with_llm_text(html, poi)
        print(f"\nRESULT:")
        print(f"  Valid: {result['valid']}")
        print(f"  Confidence: {result['confidence']}")
        print(f"  Reason: {result['reason']}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    # Check for --events flag
    mode = 'website'
    args = sys.argv[1:]
    if args[0] == '--events':
        mode = 'events'
        args = args[1:]

    if not args:
        print("Error: URL required")
        print(__doc__)
        return

    url = args[0]
    poi_name = args[1] if len(args) > 1 else "Test POI"
    category = args[2] if len(args) > 2 else "park"
    city = args[3] if len(args) > 3 else "Boston"

    asyncio.run(test_url(url, poi_name, category, city, mode))


if __name__ == '__main__':
    main()
