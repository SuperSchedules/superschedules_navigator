"""Verify discovered websites using vision LLM."""

import base64
import logging
import os
from io import BytesIO

import httpx
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# Ollama config
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
VISION_MODEL = os.environ.get('VISION_MODEL', 'minicpm-v')


async def take_screenshot(url: str, timeout: int = 15000) -> bytes | None:
    """Take a screenshot of a URL using Playwright."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={'width': 1280, 'height': 800})

            try:
                await page.goto(url, timeout=timeout, wait_until='domcontentloaded')
                # Wait a bit for dynamic content
                await page.wait_for_timeout(1000)
                screenshot = await page.screenshot(type='jpeg', quality=80)
                return screenshot
            except Exception as e:
                logger.warning(f"Failed to screenshot {url}: {e}")
                return None
            finally:
                await browser.close()
    except Exception as e:
        logger.error(f"Playwright error for {url}: {e}")
        return None


# Categories where we expect a department website, not a specific POI website
DEPARTMENT_CATEGORIES = {'park', 'playground'}


def _build_verification_prompt(poi_name: str, poi_category: str, poi_city: str, website_url: str) -> str:
    """Build category-appropriate verification prompt."""
    category_display = poi_category.replace('_', ' ')

    if poi_category in DEPARTMENT_CATEGORIES:
        # For parks/playgrounds, we expect the city's Parks & Rec department
        return f"""Look at this website screenshot.

I want to find park events in {poi_city}, Massachusetts.
The website URL is: {website_url}

Question: Could this website have event information for parks in {poi_city}?

Answer YES if:
- This is a Parks & Recreation department website for {poi_city}
- This is a town/city government page about parks for {poi_city}
- This is a recreation department that serves {poi_city}

Answer NO if:
- This is for a completely different city/town
- This is a business directory or listing site (Yelp, TripAdvisor, etc.)
- This is unrelated to parks or recreation

Respond in this exact format:
IS_CORRECT: yes
CONFIDENCE: high
DETECTED_NAME: Abington Parks and Recreation
REASON: This is the Parks & Recreation page for the town."""

    else:
        # For other categories (museums, libraries, schools, etc.)
        return f"""Look at this website screenshot.

I'm looking for the official website of: {poi_name}
Location: {poi_city}, Massachusetts
Type: {category_display}
URL: {website_url}

Question: Is this the official website for {poi_name} or the organization that runs it?

Answer YES if:
- This is the official website for "{poi_name}"
- This is the parent organization's website (e.g., school district site for a school)
- The website clearly belongs to this specific place

Answer NO if:
- This is for a different place with a similar name
- This is a directory or listing site (Yelp, Google, etc.)
- This is completely unrelated

Respond in this exact format:
IS_CORRECT: yes
CONFIDENCE: high
DETECTED_NAME: Abington High School
REASON: This is the official school website."""


async def verify_website_with_vision(
    screenshot: bytes,
    poi_name: str,
    poi_category: str,
    poi_city: str,
    website_url: str,
) -> dict:
    """
    Ask vision LLM if screenshot matches the expected POI website.

    Returns:
        {
            'is_correct': bool,
            'confidence': 'high' | 'medium' | 'low',
            'reason': str,
            'detected_name': str (what the LLM thinks this site is for)
        }
    """
    # Encode screenshot as base64
    img_base64 = base64.b64encode(screenshot).decode('utf-8')

    # Build category-appropriate prompt
    prompt = _build_verification_prompt(poi_name, poi_category, poi_city, website_url)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    'model': VISION_MODEL,
                    'prompt': prompt,
                    'images': [img_base64],
                    'stream': False,
                }
            )

            if response.status_code != 200:
                logger.error(f"Ollama error: {response.status_code} - {response.text}")
                return {
                    'is_correct': None,
                    'confidence': 'low',
                    'reason': f'Ollama error: {response.status_code}',
                    'detected_name': ''
                }

            result = response.json()
            text = result.get('response', '')

            # Parse response
            return _parse_verification_response(text)

    except Exception as e:
        logger.error(f"Vision verification error: {e}")
        return {
            'is_correct': None,
            'confidence': 'low',
            'reason': f'Error: {str(e)[:100]}',
            'detected_name': ''
        }


def _parse_verification_response(text: str) -> dict:
    """Parse the structured response from the vision model."""
    result = {
        'is_correct': None,
        'confidence': 'low',
        'reason': '',
        'detected_name': '',
        'raw_response': text
    }

    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if line.startswith('IS_CORRECT:'):
            value = line.split(':', 1)[1].strip().lower()
            result['is_correct'] = value in ('yes', 'true', '1')
        elif line.startswith('CONFIDENCE:'):
            value = line.split(':', 1)[1].strip().lower()
            if value in ('high', 'medium', 'low'):
                result['confidence'] = value
        elif line.startswith('DETECTED_NAME:'):
            result['detected_name'] = line.split(':', 1)[1].strip()
        elif line.startswith('REASON:'):
            result['reason'] = line.split(':', 1)[1].strip()

    # If structured parsing failed, try to infer from text
    if result['is_correct'] is None:
        text_lower = text.lower()
        # Look for strong positive signals
        positive_signals = ['is correct', 'is the official', 'is the parks', 'answer: yes', 'answer is yes',
                          'belongs to', 'this is the', 'appears to be the official', 'is likely the official']
        negative_signals = ['is not', 'is incorrect', 'different city', 'wrong city', 'answer: no',
                          'answer is no', 'directory', 'listing site', 'unrelated']

        pos_count = sum(1 for sig in positive_signals if sig in text_lower)
        neg_count = sum(1 for sig in negative_signals if sig in text_lower)

        if pos_count > neg_count and pos_count >= 1:
            result['is_correct'] = True
            result['confidence'] = 'medium'
            if not result['reason']:
                result['reason'] = text[:200]
        elif neg_count > pos_count and neg_count >= 1:
            result['is_correct'] = False
            result['confidence'] = 'medium'
            if not result['reason']:
                result['reason'] = text[:200]

    return result


async def verify_poi_website(poi) -> dict:
    """
    Full verification pipeline for a POI's discovered website.

    Args:
        poi: POI model instance with discovered_website

    Returns:
        {
            'is_correct': bool | None,
            'confidence': str,
            'reason': str,
            'detected_name': str,
            'screenshot_failed': bool
        }
    """
    url = poi.discovered_website
    if not url:
        return {
            'is_correct': None,
            'confidence': 'low',
            'reason': 'No discovered website',
            'detected_name': '',
            'screenshot_failed': False
        }

    # Take screenshot
    screenshot = await take_screenshot(url)
    if not screenshot:
        return {
            'is_correct': None,
            'confidence': 'low',
            'reason': 'Failed to take screenshot',
            'detected_name': '',
            'screenshot_failed': True
        }

    # Verify with vision model
    result = await verify_website_with_vision(
        screenshot=screenshot,
        poi_name=poi.name,
        poi_category=poi.category,
        poi_city=poi.city,
        website_url=url,
    )
    result['screenshot_failed'] = False

    return result
