"""Find and verify event pages for POIs using vision LLM."""

import asyncio
import base64
import json
import logging
import os
import re
from urllib.parse import urljoin, urlparse

import httpx
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# Ollama config
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
VISION_MODEL = os.environ.get('VISION_MODEL', 'minicpm-v')
TEXT_MODEL = os.environ.get('TEXT_MODEL', 'qwen3:8b')  # With /no_think in prompts for speed

# Common events page URL patterns
EVENTS_PATH_PATTERNS = [
    '/events',
    '/calendar',
    '/events-calendar',
    '/whats-happening',
    '/programs',
    '/programs-events',
    '/upcoming-events',
    '/schedule',
    '/activities',
    '/programs-and-events',
    '/happenings',
    '/whats-on',
]

# Keywords that suggest an events link
EVENTS_LINK_KEYWORDS = ['event', 'calendar', 'happening', 'program', 'schedule', 'activities', 'what\'s on']

# Content indicators that a page has events (quick check before vision)
EVENT_CONTENT_INDICATORS = ['event', 'calendar', 'upcoming', 'schedule', 'program', 'register', 'rsvp']


def _strip_html_to_text(html: str, max_chars: int = 6000) -> str:
    """Strip HTML tags and get plain text content."""
    # Remove script and style content
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars]


async def validate_events_page_with_llm(html: str, url: str, poi) -> dict:
    """
    Validate that a page actually has events using LLM text analysis.

    Returns:
        {
            'has_events': bool,
            'confidence': float (0-1),
            'reason': str
        }
    """
    text = _strip_html_to_text(html)
    if len(text) < 100:
        return {'has_events': False, 'confidence': 0.5, 'reason': 'Page has too little text content'}

    prompt = f'''TASK: Is this an official events/calendar page for "{poi.name}" in {poi.city}?

URL: {url}

WEBPAGE TEXT:
{text[:4000]}

ANSWER YES if:
- This is the official events page run BY this organization or its parent department
- A .gov website calendar (Parks & Rec, library, town events, etc.)
- The organization's own website (museum.org, library.org, school district site, etc.)
- Events listed are specifically for this place or its parent organization

ANSWER NO if:
- This is an EVENT AGGREGATOR that lists events from many different places:
  patch.com, eventbrite.com, meetup.com, facebook.com, boston.com, timeout.com,
  bostonmagazine.com, do617.com, thebostoncalendar.com, allston.com, eventful.com
- This is a NEWS site with event listings (not run by the organization)
- Events are for a DIFFERENT location or organization (wrong town, wrong place)
- This is a general community calendar not specifically for this place

IMPORTANT: The key question is - does this organization RUN this events page, or is it a third-party site?

First line: YES or NO. Then briefly explain. /no_think'''

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    'model': TEXT_MODEL,
                    'prompt': prompt,
                    'stream': False,
                    'options': {'temperature': 0}
                }
            )

            if response.status_code != 200:
                logger.error(f"LLM error: {response.status_code}")
                return {'has_events': None, 'confidence': 0, 'reason': f'LLM error: {response.status_code}'}

            result_text = response.json().get('response', '').strip()

            # Strip qwen3 thinking tags if present
            if '<think>' in result_text:
                result_text = re.sub(r'<think>.*?</think>', '', result_text, flags=re.DOTALL).strip()

            # Parse response - first word should be YES or NO
            first_line = result_text.split('\n')[0].strip().upper()
            has_events = first_line.startswith('YES')

            # Get reason from rest of response
            reason = result_text.split('\n', 1)[1].strip() if '\n' in result_text else result_text
            reason = reason[:150]

            confidence = 0.8 if has_events else 0.7

            return {
                'has_events': has_events,
                'confidence': confidence,
                'reason': reason
            }

    except Exception as e:
        logger.error(f"LLM events validation error: {e}")
        return {'has_events': None, 'confidence': 0, 'reason': f'Error: {str(e)[:100]}'}


async def find_events_page(poi, use_vision: bool = True) -> dict:
    """
    Find and verify events page for a POI.

    Strategy:
    1. Try common URL patterns directly (/events, /calendar, etc.)
    2. Crawl homepage for events links
    3. If found, verify with vision model that it actually has events

    Args:
        poi: POI model instance
        use_vision: Whether to verify with vision model (default True)

    Returns:
        {
            'events_url': str or None,
            'method': 'direct_path' | 'link_crawl' | None,
            'confidence': float (0-1),
            'has_events': bool or None (from vision),
            'event_count': int or None (from vision),
            'vision_verified': bool,
            'notes': str
        }
    """
    website = poi.website  # Uses osm_website if available, else discovered_website

    if not website:
        return {
            'events_url': None,
            'method': None,
            'confidence': 0,
            'has_events': None,
            'event_count': None,
            'vision_verified': False,
            'notes': 'No website available'
        }

    # Strategy 1: Try common URL patterns directly (fastest)
    candidates = await _find_candidate_urls(website)

    # Strategy 2: Crawl homepage for events links
    if not candidates:
        link_candidate = await _find_events_link_on_page(website)
        if link_candidate:
            candidates.append(link_candidate)

    if not candidates:
        return {
            'events_url': None,
            'method': None,
            'confidence': 0,
            'has_events': None,
            'event_count': None,
            'vision_verified': False,
            'notes': 'No events page found via direct paths or link crawling'
        }

    # Verify candidates with LLM text analysis (fast), then optionally vision
    for candidate in candidates:
        url = candidate['url']
        method = candidate['method']
        html = candidate.get('html', '')

        # Step 1: LLM text validation (fast pre-filter)
        if html:
            logger.info(f"LLM validating: {url}")
            llm_result = await validate_events_page_with_llm(html, url, poi)
            logger.info(f"LLM result: has_events={llm_result.get('has_events')}, reason={llm_result.get('reason', '')[:60]}")

            if llm_result.get('has_events') is False:
                logger.info(f"LLM rejected {url}: {llm_result.get('reason', 'no events')}")
                continue  # Try next candidate

        # Step 2: Vision validation (optional, for higher confidence)
        if use_vision:
            logger.info(f"Verifying with vision: {url}")
            vision_result = await _verify_with_vision(url, poi)

            if vision_result.get('has_events'):
                return {
                    'events_url': url,
                    'method': method,
                    'confidence': 0.95 if vision_result.get('confidence') == 'high' else 0.85,
                    'has_events': True,
                    'event_count': vision_result.get('event_count'),
                    'vision_verified': True,
                    'notes': f"LLM+Vision verified: {vision_result.get('reason', '')}"
                }
            else:
                logger.info(f"Vision rejected {url}: {vision_result.get('reason', 'no events')}")
        else:
            # No vision - LLM passed, return candidate
            llm_reason = llm_result.get('reason', '') if html else 'no HTML check'
            return {
                'events_url': url,
                'method': method,
                'confidence': 0.75,
                'has_events': True if html else None,
                'event_count': None,
                'vision_verified': False,
                'notes': f'LLM verified: {llm_reason[:80]}'
            }

    # All candidates rejected
    return {
        'events_url': None,
        'method': None,
        'confidence': 0,
        'has_events': False,
        'event_count': 0,
        'vision_verified': use_vision,
        'notes': 'Found candidate URLs but validation rejected them (no events found)'
    }


async def _find_candidate_urls(base_url: str) -> list[dict]:
    """Try common URL patterns and return candidates that respond with 200."""
    candidates = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        for path in EVENTS_PATH_PATTERNS:
            url = urljoin(base_url, path)
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    # Quick keyword check before adding as candidate
                    if _page_has_events_content(resp.text):
                        candidates.append({
                            'url': str(resp.url),  # Use final URL after redirects
                            'method': 'direct_path',
                            'path': path,
                            'html': resp.text,  # Include HTML for LLM validation
                        })
                        logger.debug(f"Found candidate via direct path: {url}")
                        # Don't early exit - collect a few candidates for LLM to evaluate
                        if len(candidates) >= 3:
                            return candidates
            except Exception as e:
                logger.debug(f"Failed to fetch {url}: {e}")
                continue

    return candidates


async def _find_events_link_on_page(url: str) -> dict | None:
    """Crawl page and find link to events section."""
    logger.debug(f"Crawling {url} for events links")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(url, timeout=15000, wait_until='domcontentloaded')

                # Look for links containing events-related text
                links = await page.query_selector_all('a')

                for link in links:
                    try:
                        text = (await link.text_content() or '').lower().strip()
                        href = await link.get_attribute('href')

                        if not href or href.startswith('#') or href.startswith('javascript:'):
                            continue

                        # Check if link text contains events keywords
                        if any(kw in text for kw in EVENTS_LINK_KEYWORDS):
                            full_url = urljoin(url, href)

                            # Quick check that URL responds
                            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                                resp = await client.get(full_url)
                                if resp.status_code == 200 and _page_has_events_content(resp.text):
                                    logger.debug(f"Found candidate via link crawl: {full_url}")
                                    return {
                                        'url': str(resp.url),
                                        'method': 'link_crawl',
                                        'link_text': text[:50],
                                        'html': resp.text,  # Include HTML for LLM validation
                                    }
                    except Exception:
                        continue

            finally:
                await browser.close()

    except Exception as e:
        logger.debug(f"Failed to crawl {url}: {e}")

    return None


def _page_has_events_content(html: str) -> bool:
    """Quick check if HTML appears to be an events page."""
    html_lower = html.lower()
    matches = sum(1 for ind in EVENT_CONTENT_INDICATORS if ind in html_lower)
    return matches >= 2


async def _verify_with_vision(url: str, poi) -> dict:
    """
    Take screenshot and verify with vision model that page has events.

    Returns:
        {
            'has_events': bool,
            'event_count': int or None,
            'confidence': 'high' | 'medium' | 'low',
            'reason': str
        }
    """
    # Take screenshot
    screenshot = await _take_screenshot(url)
    if not screenshot:
        return {
            'has_events': None,
            'event_count': None,
            'confidence': 'low',
            'reason': 'Failed to take screenshot'
        }

    # Build prompt
    prompt = f"""Analyze this webpage screenshot.

I'm looking for an EVENTS page for: {poi.name} ({poi.category}) in {poi.city}, Massachusetts.
URL: {url}

Does this page show EVENTS that people can attend?

Events have:
- Specific dates (like "Dec 14", "January 5, 2025", or a calendar view)
- Event titles/names (like "Story Time", "Concert in the Park", "Yoga Class")
- Something you GO TO (not news articles, not meeting minutes, not blog posts)

Answer in this exact format:
HAS_EVENTS: yes/no
EVENT_COUNT: (approximate number of events visible, or 0)
CONFIDENCE: high/medium/low
REASON: (brief explanation)

Example:
HAS_EVENTS: yes
EVENT_COUNT: 12
CONFIDENCE: high
REASON: Calendar showing multiple upcoming programs with dates and registration links."""

    # Call vision model
    try:
        img_base64 = base64.b64encode(screenshot).decode('utf-8')

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    'model': VISION_MODEL,
                    'prompt': prompt,
                    'images': [img_base64],
                    'stream': False,
                    'options': {'temperature': 0}
                }
            )

            if response.status_code != 200:
                logger.error(f"Ollama error: {response.status_code}")
                return {
                    'has_events': None,
                    'event_count': None,
                    'confidence': 'low',
                    'reason': f'Ollama error: {response.status_code}'
                }

            result_text = response.json().get('response', '')
            return _parse_vision_response(result_text)

    except Exception as e:
        logger.error(f"Vision verification error: {e}")
        return {
            'has_events': None,
            'event_count': None,
            'confidence': 'low',
            'reason': f'Error: {str(e)[:100]}'
        }


async def _take_screenshot(url: str) -> bytes | None:
    """Take screenshot of URL using Playwright."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={'width': 1280, 'height': 800})

            try:
                await page.goto(url, timeout=15000, wait_until='domcontentloaded')
                await page.wait_for_timeout(1500)  # Wait for dynamic content
                screenshot = await page.screenshot(type='jpeg', quality=80)
                return screenshot
            except Exception as e:
                logger.warning(f"Screenshot failed for {url}: {e}")
                return None
            finally:
                await browser.close()
    except Exception as e:
        logger.error(f"Playwright error: {e}")
        return None


def _parse_vision_response(text: str) -> dict:
    """Parse structured response from vision model."""
    result = {
        'has_events': None,
        'event_count': None,
        'confidence': 'low',
        'reason': ''
    }

    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if line.startswith('HAS_EVENTS:'):
            value = line.split(':', 1)[1].strip().lower()
            result['has_events'] = value in ('yes', 'true', '1')
        elif line.startswith('EVENT_COUNT:'):
            value = line.split(':', 1)[1].strip()
            match = re.search(r'\d+', value)
            result['event_count'] = int(match.group()) if match else None
        elif line.startswith('CONFIDENCE:'):
            value = line.split(':', 1)[1].strip().lower()
            if value in ('high', 'medium', 'low'):
                result['confidence'] = value
        elif line.startswith('REASON:'):
            result['reason'] = line.split(':', 1)[1].strip()

    # Fallback inference if parsing failed
    if result['has_events'] is None:
        text_lower = text.lower()
        if 'no events' in text_lower or 'does not show' in text_lower or 'not an events' in text_lower:
            result['has_events'] = False
        elif 'events' in text_lower and ('calendar' in text_lower or 'upcoming' in text_lower or 'schedule' in text_lower):
            result['has_events'] = True
            result['confidence'] = 'medium'

    return result


def find_events_page_sync(poi, use_vision: bool = True) -> dict:
    """Synchronous wrapper for find_events_page."""
    return asyncio.run(find_events_page(poi, use_vision=use_vision))
