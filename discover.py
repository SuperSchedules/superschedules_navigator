#!/usr/bin/env python3
"""
Proof of Concept: Vision-based Event Page Discovery

Tests the workflow:
1. Search DuckDuckGo for event pages in a town
2. Screenshot each result with Playwright
3. Send to Moondream (via Ollama) for classification
"""

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests
from ddgs import DDGS


# Configuration
OLLAMA_URL = "http://localhost:11434"
VISION_MODEL = os.environ.get("VISION_MODEL", "minicpm-v")  # or "moondream", "llava"
SCREENSHOT_DIR = Path("screenshots")

# API Configuration for pushing results
API_URL = os.environ.get("SUPERSCHEDULES_API_URL", "https://api.eventzombie.com")
API_TOKEN = os.environ.get("SUPERSCHEDULES_API_TOKEN", "")


def check_ollama_available() -> bool:
    """Check if Ollama is running and model is available"""
    try:
        # Check Ollama is running
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code != 200:
            return False

        # Check if vision model is available
        models = response.json().get("models", [])
        model_names = [m.get("name", "").split(":")[0] for m in models]

        if VISION_MODEL not in model_names:
            print(f"Model '{VISION_MODEL}' not found. Available models: {model_names}")
            print(f"\nRun: ollama pull {VISION_MODEL}")
            return False

        return True
    except Exception as e:
        print(f"Ollama not available: {e}")
        print("Make sure Ollama is running: ollama serve")
        return False


def search_duckduckgo(query: str, max_results: int = 5) -> list[dict]:
    """Search DuckDuckGo and return URLs with titles"""
    results = []

    try:
        ddg_results = DDGS().text(query, max_results=max_results)

        for r in ddg_results:
            results.append({
                'url': r.get('href', ''),
                'title': r.get('title', ''),
                'snippet': r.get('body', '')
            })

    except Exception as e:
        print(f"Search error: {e}")

    return results


async def screenshot_url(url: str, output_path: Path) -> bool:
    """Take a screenshot of a URL using Playwright"""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={'width': 1280, 'height': 800})

            try:
                await page.goto(url, timeout=15000, wait_until='domcontentloaded')
                # Wait a bit for JS to render
                await asyncio.sleep(2)
                await page.screenshot(path=str(output_path), full_page=False)
                await browser.close()
                return True
            except Exception as e:
                print(f"  Screenshot failed for {url}: {e}")
                await browser.close()
                return False

    except Exception as e:
        print(f"  Playwright error: {e}")
        return False


def classify_with_vision(image_path: Path, target_town: str = "", target_state: str = "") -> dict:
    """Send screenshot to Moondream for event classification"""

    # Read and encode image
    with open(image_path, 'rb') as f:
        image_data = base64.b64encode(f.read()).decode('utf-8')

    # Build location context for prompt
    if target_state == "MA":
        location_context = f"{target_town}, Massachusetts"
        wrong_locations = "Illinois, Kansas, North Carolina, New Jersey, or any state other than Massachusetts"
    else:
        location_context = f"{target_town}, {target_state}"
        wrong_locations = "a different state or city"

    prompt = f"""Analyze this webpage screenshot carefully.

TARGET LOCATION: {location_context}

TASK 1 - LOCATION CHECK:
Look for city/state/location text on the page (headers, footers, addresses, contact info).
- If you see "{target_town}, IL" or "{target_town}, NC" or any other state besides Massachusetts - WRONG location
- If you see "{target_town}, MA" or "Massachusetts" or just "{target_town}" with no conflicting state - CORRECT

TASK 2 - EVENT CHECK (only if location is correct):
An EVENT is something people can attend. It must have:
- A specific DATE (like "December 14" or "Jan 5, 2025")
- A TITLE or DESCRIPTION (like "Story Time", "Concert in the Park", "Town Meeting")
- It's something you would GO TO (not just news or announcements)

Examples of REAL events: "Holiday Concert - Dec 20, 7pm", "Yoga in the Park - Saturdays 9am"
NOT events: news articles, meeting minutes, press releases, "about us" pages

Does this page show a LIST or CALENDAR with multiple upcoming events that people can attend?

JSON response:
{{"location_correct": true/false, "location_found": "city/state seen on page", "has_events": true/false, "event_count": number_of_events_visible, "org_type": "library/museum/parks/town_government/university/event_aggregator/null", "confidence": "high/medium/low", "reason": "what you see"}}"""

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": VISION_MODEL,
                "prompt": prompt,
                "images": [image_data],
                "stream": False,
                "options": {
                    "temperature": 0.1
                }
            },
            timeout=60
        )

        if response.status_code == 200:
            result_text = response.json().get("response", "")

            # Try to parse JSON from response
            try:
                # Find JSON in response
                import re
                json_match = re.search(r'\{[^}]+\}', result_text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except:
                pass

            # Return raw text if JSON parsing fails
            return {"raw_response": result_text, "parse_error": True}
        else:
            return {"error": f"Ollama returned {response.status_code}"}

    except Exception as e:
        return {"error": str(e)}


def load_previously_submitted_urls() -> set[str]:
    """
    Load URLs that have already been submitted from all discovery_*.json files

    Returns:
        Set of URLs that have already been processed and submitted
    """
    submitted_urls = set()

    # Find all discovery JSON files in current directory
    for json_file in Path('.').glob('discovery_*.json'):
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)

            # Extract URLs from results
            for result in data:
                url = result.get('url')
                # Include all URLs we've checked before (whether they had events or not)
                # This avoids re-checking the same URLs
                if url:
                    submitted_urls.add(url)

        except Exception as e:
            print(f"Warning: Could not load {json_file}: {e}")
            continue

    return submitted_urls


async def discover_town_events(town: str, state: str = "MA") -> list[dict]:
    """
    Discover event sources for a town

    Args:
        town: Town name (e.g., "Newton")
        state: State abbreviation (default: "MA")

    Returns:
        List of discovered event sources with classifications
    """
    print(f"\n{'='*60}")
    print(f"Discovering event sources for: {town}, {state}")
    print('='*60)

    # Load previously submitted URLs to avoid re-processing
    previously_submitted = load_previously_submitted_urls()
    if previously_submitted:
        print(f"\nLoaded {len(previously_submitted)} previously processed URLs (will skip these)")

    # Create screenshots directory
    SCREENSHOT_DIR.mkdir(exist_ok=True)

    # Search categories - include full state name for disambiguation
    state_full = "Massachusetts" if state == "MA" else state
    categories = [
        ("library", f'{town} public library events {state_full}'),
        ("parks", f'{town} parks recreation events calendar {state_full}'),
        ("town", f'{town} town hall events calendar {state_full}'),
        ("museum", f'{town} museum events {state_full}'),
        ("community", f'{town} community events calendar {state_full}'),
    ]

    all_results = []
    seen_domains = set()

    for category, query in categories:
        print(f"\n--- Searching: {category} ---")
        print(f"Query: {query}")

        search_results = search_duckduckgo(query, max_results=5)

        if not search_results:
            print("  No results found")
            continue

        for i, result in enumerate(search_results):
            url = result['url']
            domain = url.split('/')[2] if len(url.split('/')) > 2 else url

            # Skip if we've already processed this URL in a previous run
            if url in previously_submitted:
                print(f"  Skipping previously processed URL: {url[:60]}...")
                continue

            # Skip if we've already processed this domain in this run
            if domain in seen_domains:
                print(f"  Skipping duplicate domain: {domain}")
                continue
            seen_domains.add(domain)

            print(f"\n  [{i+1}] {result['title'][:50]}...")
            print(f"      URL: {url[:60]}...")

            # Screenshot
            safe_name = f"{town}_{category}_{i}.png".replace(' ', '_')
            screenshot_path = SCREENSHOT_DIR / safe_name

            print(f"      Taking screenshot...")
            success = await screenshot_url(url, screenshot_path)

            if not success:
                continue

            # Classify with vision model
            print(f"      Classifying with {VISION_MODEL}...")
            classification = classify_with_vision(screenshot_path, target_town=town, target_state=state)

            print(f"      Result: {json.dumps(classification, indent=2)}")

            all_results.append({
                'town': town,
                'state': state,
                'category': category,
                'url': url,
                'title': result['title'],
                'domain': domain,
                'screenshot': str(screenshot_path),
                'classification': classification
            })

            # Small delay between requests
            time.sleep(0.5)

    return all_results


async def main():
    """Main entry point

    Usage: python poc_vision_discovery.py [town] [state] [--model MODEL] [--push]

    Examples:
        python poc_vision_discovery.py Newton MA
        python poc_vision_discovery.py Newton MA --model minicpm-v
        python poc_vision_discovery.py Newton MA --push  # Push results to API

    Environment variables:
        VISION_MODEL - Vision model to use (default: minicpm-v)
        SUPERSCHEDULES_API_URL - API URL (default: https://api.eventzombie.com)
        SUPERSCHEDULES_API_TOKEN - Service token for API auth (required for --push)
    """
    global VISION_MODEL

    # Parse args
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    town = args[0] if len(args) > 0 else "Newton"
    state = args[1] if len(args) > 1 else "MA"

    # Check for --model flag
    if '--model' in sys.argv:
        idx = sys.argv.index('--model')
        if idx + 1 < len(sys.argv):
            VISION_MODEL = sys.argv[idx + 1]

    # Check Ollama is available
    print("Checking Ollama availability...")
    if not check_ollama_available():
        print("\nPlease ensure Ollama is running with a vision model:")
        print("  1. ollama serve")
        print(f"  2. ollama pull {VISION_MODEL}")
        sys.exit(1)

    print(f"Ollama OK, using model: {VISION_MODEL}")

    results = await discover_town_events(town, state)

    # Summary
    print("\n" + "="*60)
    print("DISCOVERY SUMMARY")
    print("="*60)

    # Filter to only pages with actual event listings AND correct location
    event_sources = [
        r for r in results
        if r.get('classification', {}).get('has_events')
        and r.get('classification', {}).get('location_correct', True)  # Must be right location
    ]

    print(f"\nTotal URLs checked: {len(results)}")
    print(f"Event sources found: {len(event_sources)}")

    if event_sources:
        print("\nVerified event sources:")
        for source in event_sources:
            cls = source['classification']
            print(f"  - {source['title'][:50]}...")
            print(f"    URL: {source['url']}")
            print(f"    Type: {cls.get('org_type', 'unknown')}")
            print(f"    Location: {cls.get('location_found', 'unknown')}")
            print(f"    Events: ~{cls.get('event_count', '?')}")
            if cls.get('reason'):
                print(f"    Notes: {cls.get('reason')}")
            print()

    # Also show rejected (wrong location)
    wrong_location = [
        r for r in results
        if not r.get('classification', {}).get('location_correct', True)
    ]
    if wrong_location:
        print(f"\nRejected (wrong location): {len(wrong_location)}")
        for source in wrong_location:
            cls = source['classification']
            print(f"  - {source['domain']}: {cls.get('location_found', '?')}")

    # Save results
    output_file = Path(f"discovery_{town.lower().replace(' ', '_')}.json")
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results saved to: {output_file}")

    # Push to API if requested
    if '--push' in sys.argv and event_sources:
        push_to_api(event_sources)


def push_to_api(event_sources: list[dict]) -> bool:
    """Push discovered event source URLs to the superschedules API"""

    if not API_TOKEN:
        print("\nNo API token configured. Set SUPERSCHEDULES_API_TOKEN env var.")
        print("Skipping API push.")
        return False

    urls = [s['url'] for s in event_sources]

    print(f"\n{'='*60}")
    print(f"PUSHING {len(urls)} URLs TO API")
    print('='*60)
    print(f"API: {API_URL}")

    try:
        response = requests.post(
            f"{API_URL}/api/v1/queue/bulk-submit-service",
            json={"urls": urls},
            headers={"Authorization": f"Bearer {API_TOKEN}"},
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            print(f"Success! Submitted: {result.get('submitted', '?')} URLs")
            print(f"Job IDs: {result.get('job_ids', [])[:5]}{'...' if len(result.get('job_ids', [])) > 5 else ''}")
            return True
        else:
            print(f"API Error: {response.status_code}")
            print(f"Response: {response.text[:200]}")
            return False

    except Exception as e:
        print(f"Failed to push to API: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(main())
