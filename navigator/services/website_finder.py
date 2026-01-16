"""Find official websites for POIs via web search."""

import asyncio
import base64
import logging
import os
import re
import time
from urllib.parse import urlparse

import httpx
import requests
from ddgs import DDGS
from playwright.async_api import async_playwright

from navigator.models import BlockedDomain

logger = logging.getLogger(__name__)

# Ollama config for vision validation
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
VISION_MODEL = os.environ.get('VISION_MODEL', 'minicpm-v')
TEXT_MODEL = os.environ.get('TEXT_MODEL', 'qwen3:8b')  # For LLM text validation


class DDG302Detector(logging.Handler):
    """Log handler that detects DDG 302 redirects from httpx logs."""

    def __init__(self):
        super().__init__()
        self.saw_302 = False

    def emit(self, record):
        msg = record.getMessage()
        # Look for: HTTP Request: POST https://html.duckduckgo.com/html/ "HTTP/2 302 Found"
        if 'duckduckgo.com' in msg and '302' in msg:
            self.saw_302 = True

# User agent for requests (many sites block default python-requests)
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# Domains to exclude from search queries (using -site: operator)
SEARCH_EXCLUDE_DOMAINS = [
    'wikipedia.org',
    'facebook.com',
    'yelp.com',
    'yelp.ca',
    'tripadvisor.com',
    'yellowpages.com',
    'mapquest.com',
    'mapcarta.com',
    'latlong.net',
    'cualbondi.org',
    'superpages.com',
    'usnews.com',
    'niche.com',
    'greatschools.org',
    'chamberofcommerce.com',
    'allbiz.com',
    'buzzfile.com',
    'countyoffice.org',
    'usaopps.com',
    'manta.com',
    'dandb.com',
    'loc8nearme.com',
    'muckrock.com',
    'artscopemagazine.com',
    'patch.com',
    'wickedlocal.com',
]

# Domains that are never official websites (backup filter)
NEVER_OFFICIAL_DOMAINS = {
    # Social media
    'facebook.com', 'twitter.com', 'instagram.com', 'linkedin.com',
    'youtube.com', 'tiktok.com', 'pinterest.com',
    # Review/listing sites
    'yelp.com', 'tripadvisor.com', 'foursquare.com',
    'yellowpages.com', 'whitepages.com', 'superpages.com', 'bbb.org',
    # Event aggregators
    'eventbrite.com', 'meetup.com', 'ticketmaster.com',
    # Reference/info sites
    'wikipedia.org', 'wikidata.org',
    # Maps/directions
    'google.com', 'maps.google.com', 'mapquest.com', 'mapcarta.com',
    'latlong.net', 'cualbondi.org',
    # Job sites
    'indeed.com', 'glassdoor.com', 'ziprecruiter.com',
    # School ranking sites
    'usnews.com', 'niche.com', 'greatschools.org',
    # Library aggregators (we want the actual library site)
    'librarytechnology.org', 'worldcat.org',
}

# Patterns that suggest an official website
OFFICIAL_SITE_INDICATORS = [
    r'\.gov$',
    r'\.edu$',
    r'\.org$',
    r'library\.',
    r'parks\.',
    r'recreation\.',
    r'\.us$',
]

# Category-specific search query templates
CATEGORY_SEARCH_TEMPLATES = {
    'park': '{name} {city} MA parks recreation',
    'playground': '{name} {city} MA parks recreation',
    'library': '{name} library {city} MA',
    'museum': '{name} museum {city} MA',
    'community_centre': '{name} {city} MA community center',
    'theatre': '{name} theatre theater {city} MA',
    'arts_centre': '{name} arts center {city} MA',
    'school': '{name} school {city} MA',
    'university': '{name} university {city} MA',
    'sports_centre': '{name} {city} MA recreation',
    'townhall': '{city} MA town hall official',
}


def get_blocked_domains() -> set:
    """Get set of blocked domains from database."""
    return set(BlockedDomain.objects.values_list('domain', flat=True))


def is_domain_blocked(domain: str, blocked_domains: set) -> bool:
    """Check if domain is blocked."""
    domain = domain.lower()
    # Check exact match
    if domain in blocked_domains or domain in NEVER_OFFICIAL_DOMAINS:
        return True
    # Check if subdomain of blocked domain
    for blocked in blocked_domains | NEVER_OFFICIAL_DOMAINS:
        if domain.endswith('.' + blocked):
            return True
    return False


def score_result(url: str, title: str, poi_name: str, poi_city: str) -> float:
    """
    Score a search result for likelihood of being the official website.

    Returns 0.0-1.0
    """
    score = 0.5  # Base score
    domain = urlparse(url).netloc.lower()
    title_lower = title.lower()
    poi_name_lower = poi_name.lower()
    poi_city_lower = poi_city.lower()

    # Domain quality indicators
    for pattern in OFFICIAL_SITE_INDICATORS:
        if re.search(pattern, domain):
            score += 0.15
            break

    # City in domain is good (e.g., needhamma.gov)
    city_slug = poi_city_lower.replace(' ', '')
    if city_slug in domain:
        score += 0.2

    # POI name in title is very good
    # Clean up POI name for matching (remove common suffixes)
    clean_name = re.sub(r'\s+(park|library|museum|center|centre|school)$', '', poi_name_lower, flags=re.IGNORECASE)
    if clean_name in title_lower or poi_name_lower in title_lower:
        score += 0.25

    # City in title is good
    if poi_city_lower in title_lower:
        score += 0.1

    # Penalize generic aggregator domains
    if any(x in domain for x in ['trip', 'travel', 'review', 'directory', 'listing']):
        score -= 0.3

    # Penalize chamber of commerce and business directory patterns
    if 'chamber' in domain:
        score -= 0.4

    # Penalize URLs with directory-like paths
    url_lower = url.lower()
    if any(x in url_lower for x in ['/members/', '/business/', '/directory/', '/listing/', '/biz/']):
        score -= 0.3

    return min(1.0, max(0.0, score))


def verify_website_accessible(url: str) -> tuple[bool, str]:
    """
    Verify that a URL is accessible and returns HTML.

    Returns (accessible, html_content) - html_content is empty string if not accessible.
    """
    try:
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        resp = requests.get(url, timeout=10, allow_redirects=True, headers=headers)
        content_type = resp.headers.get('content-type', '')

        # Reject PDFs and other non-HTML
        if 'application/pdf' in content_type:
            logger.debug(f"Verify failed for {url}: PDF content")
            return False, ''

        # Accept 200 OK with HTML
        if resp.status_code == 200 and 'text/html' in content_type:
            return True, resp.text

        # Accept 403 from likely-legitimate domains (bot protection)
        # These sites exist but block automated requests
        if resp.status_code == 403:
            domain = url.split('/')[2].lower()
            if any(domain.endswith(tld) for tld in ['.gov', '.edu', '.org']):
                logger.debug(f"Accepting 403 from trusted domain: {domain}")
                return True, ''  # Can't validate content but domain is trusted

        logger.debug(f"Verify failed for {url}: HTTP {resp.status_code}")
        return False, ''
    except Exception as e:
        logger.debug(f"Failed to verify {url}: {e}")
        return False, ''


def validate_html_content(html: str, poi) -> dict:
    """
    Validate that HTML content is likely the official website for a POI.

    Returns:
        {
            'valid': bool,
            'confidence': float (0-1),
            'reason': str
        }
    """
    if not html:
        return {'valid': True, 'confidence': 0.5, 'reason': 'No HTML to validate (403 from trusted domain)'}

    html_lower = html.lower()
    poi_name_lower = poi.name.lower()
    poi_city_lower = poi.city.lower() if poi.city else ''

    # Clean POI name - remove common suffixes for matching
    clean_name = re.sub(r'\s+(park|library|museum|center|centre|school|theater|theatre)$', '', poi_name_lower)
    # Also try first significant word (for "Memorial Park" -> "memorial")
    name_words = [w for w in clean_name.split() if len(w) > 3]

    score = 0.0
    reasons = []

    # Check for POI name in content (strong signal)
    if poi_name_lower in html_lower:
        score += 0.4
        reasons.append('exact name match')
    elif clean_name in html_lower:
        score += 0.3
        reasons.append('clean name match')
    elif any(word in html_lower for word in name_words):
        score += 0.15
        reasons.append('partial name match')

    # Check for city name (good signal)
    if poi_city_lower and poi_city_lower in html_lower:
        score += 0.2
        reasons.append('city match')

    # Check for category-related keywords
    category_keywords = {
        'park': ['park', 'recreation', 'trails', 'playground', 'picnic'],
        'playground': ['playground', 'park', 'recreation', 'children'],
        'library': ['library', 'books', 'catalog', 'borrowing', 'circulation'],
        'museum': ['museum', 'exhibit', 'collection', 'admission', 'gallery'],
        'theatre': ['theatre', 'theater', 'performance', 'show', 'ticket', 'stage'],
        'arts_centre': ['arts', 'gallery', 'exhibit', 'artist', 'performance'],
        'community_centre': ['community', 'programs', 'classes', 'recreation'],
        'sports_centre': ['sports', 'gym', 'fitness', 'recreation', 'athletic'],
        'townhall': ['town', 'city', 'municipal', 'government', 'permit', 'clerk'],
        'university': ['university', 'college', 'campus', 'student', 'academic'],
    }

    keywords = category_keywords.get(poi.category, [])
    keyword_matches = sum(1 for kw in keywords if kw in html_lower)
    if keyword_matches >= 2:
        score += 0.2
        reasons.append(f'{keyword_matches} category keywords')
    elif keyword_matches == 1:
        score += 0.1
        reasons.append('1 category keyword')

    # Check for contact/address info (good signal)
    if poi.street_address:
        addr_parts = poi.street_address.lower().split()
        addr_matches = sum(1 for part in addr_parts if len(part) > 3 and part in html_lower)
        if addr_matches >= 2:
            score += 0.15
            reasons.append('address match')

    # Check for Massachusetts indicators
    if any(x in html_lower for x in ['massachusetts', ', ma', ' ma ']):
        score += 0.05
        reasons.append('MA reference')

    # Negative signals - reference/dictionary content
    # Use word boundary patterns to avoid false positives
    # Be conservative - only patterns that strongly indicate reference content
    reference_patterns = [
        r'\bdefinition of\b', r'\bdictionary\b', r'\bencyclopedia\b',
        r'\bmeaning of\b', r'\bwhat does .+ mean\b',
        r'\bsynonyms for\b', r'\bantonyms for\b', r'\bpronunciation\b', r'\betymology\b',
        r'\bword origin\b', r'\bdefine:\b',
    ]
    ref_matches = sum(1 for pattern in reference_patterns if re.search(pattern, html_lower))
    if ref_matches >= 2:
        score -= 0.5
        reasons.append(f'reference site indicators ({ref_matches})')

    # Negative signals - news/article content
    news_indicators = ['subscribe', 'journalist', 'reporter', 'newsroom', 'breaking news']
    news_matches = sum(1 for ind in news_indicators if ind in html_lower)
    if news_matches >= 2:
        score -= 0.3
        reasons.append('news site indicators')

    # Negative signals - social media / forum content (must be specific to avoid false positives)
    social_patterns = [
        r'subreddit', r'reddit\.com/r/', r'/r/\w+',  # Reddit specific (require subreddit pattern)
        r'\bupvote\b', r'\bdownvote\b', r'\bkarma\b',  # Reddit/forum voting
        r'\bretweet\b', r'tweet this',  # Twitter specific
        r'posted by u/', r'submitted \d+ \w+ ago',  # Forum post patterns
        r'join the discussion', r'leave a comment',  # Forum patterns
        r'member since \d', r'\buser profile\b', r'\bview profile\b',  # User profile patterns
    ]
    social_matches = sum(1 for pattern in social_patterns if re.search(pattern, html_lower))
    if social_matches >= 2:
        score -= 0.5
        reasons.append(f'social/forum indicators ({social_matches})')

    # Determine validity
    valid = score >= 0.3
    confidence = min(1.0, max(0.0, score))

    return {
        'valid': valid,
        'confidence': confidence,
        'reason': '; '.join(reasons) if reasons else 'no matches'
    }


async def validate_with_vision(url: str, poi) -> dict:
    """
    Take screenshot and validate with vision model that this is the POI's website.

    Returns:
        {
            'valid': bool,
            'confidence': float (0-1),
            'reason': str
        }
    """
    # Take screenshot
    screenshot = await _take_screenshot(url)
    if not screenshot:
        return {'valid': False, 'confidence': 0, 'reason': 'Failed to take screenshot'}

    # Build prompt
    prompt = f"""Look at this webpage screenshot.

I'm trying to find the official website for: {poi.name}
Location: {poi.city}, Massachusetts
Category: {poi.category}

Is this webpage the official website for this place, or a closely related organization (like a Parks & Recreation department for a park)?

Answer in this exact format:
IS_OFFICIAL: yes/no
CONFIDENCE: high/medium/low
REASON: (brief explanation)

Examples of YES:
- The park's page on the city Parks & Recreation site
- The library's own website
- The museum's official site

Examples of NO:
- A dictionary defining a word
- A news article about the place
- A review site like Yelp
- An unrelated business
- A Wikipedia article"""

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
                return {'valid': False, 'confidence': 0, 'reason': f'Ollama error: {response.status_code}'}

            result_text = response.json().get('response', '')
            return _parse_vision_validation(result_text)

    except Exception as e:
        logger.error(f"Vision validation error: {e}")
        return {'valid': False, 'confidence': 0, 'reason': f'Error: {str(e)[:100]}'}


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


def _parse_vision_validation(text: str) -> dict:
    """Parse structured response from vision validation."""
    result = {
        'valid': False,
        'confidence': 0.0,
        'reason': ''
    }

    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if line.startswith('IS_OFFICIAL:'):
            value = line.split(':', 1)[1].strip().lower()
            result['valid'] = value in ('yes', 'true', '1')
        elif line.startswith('CONFIDENCE:'):
            value = line.split(':', 1)[1].strip().lower()
            if value == 'high':
                result['confidence'] = 0.9
            elif value == 'medium':
                result['confidence'] = 0.6
            else:
                result['confidence'] = 0.3
        elif line.startswith('REASON:'):
            result['reason'] = line.split(':', 1)[1].strip()

    return result


def strip_html_to_text(html: str, max_chars: int = 6000) -> str:
    """Strip HTML tags and get plain text content."""
    # Remove script and style content
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars]


async def validate_with_llm_text(html: str, poi) -> dict:
    """
    Validate website by sending stripped text to LLM (faster than vision).

    Returns:
        {
            'valid': bool,
            'confidence': float (0-1),
            'reason': str
        }
    """
    text = strip_html_to_text(html)
    if len(text) < 100:
        return {'valid': False, 'confidence': 0, 'reason': 'Page has too little text content'}

    # Build category-specific prompt
    if poi.category in ('park', 'playground'):
        prompt = f'''TASK: Is this the official website for {poi.city}, Massachusetts or its Parks department?

WEBPAGE TEXT:
{text[:4000]}

ANSWER YES if this is:
- The official .gov website for {poi.city}
- A Parks & Recreation department website
- A town/city government site that includes parks info

ANSWER NO if this is:
- Wikipedia, a dictionary, or encyclopedia
- A news article or directory listing
- A third-party site not run by the government

First line: YES or NO. Then explain briefly. /no_think'''

    elif poi.category == 'townhall':
        prompt = f'''TASK: Is this the official government website for {poi.city}, Massachusetts?

WEBPAGE TEXT:
{text[:4000]}

ANSWER YES if this is:
- The official .gov website for {poi.city}
- A city/town government website

ANSWER NO if this is:
- Wikipedia or an encyclopedia
- A directory or listing site
- A news site or third-party site

First line: YES or NO. Then explain briefly. /no_think'''

    else:
        prompt = f'''TASK: Is this a usable official website for "{poi.name}" ({poi.category}) in {poi.city}, Massachusetts?

NOTE: The page should be run BY or be about "{poi.name}" specifically.

WEBPAGE TEXT:
{text[:4000]}

ANSWER YES only if this is:
- The official website run BY this place or organization
- A city/town government page (.gov) for this type of place
- The parent organization's official site (school district, library network, etc.)

ANSWER NO if this is:
- Wikipedia or any encyclopedia
- A dictionary defining words
- A news article, blog post, or press release
- A review/listing site (Yelp, TripAdvisor, Google Maps, etc.)
- A school/business directory (GreatSchools, Niche, TruSchools, NCES, etc.)
- A social media page (Facebook, Twitter, Reddit, etc.)
- An event aggregator (Eventbrite, Meetup, etc.)
- A third-party site that lists info ABOUT many places (not run BY the specific place)

IMPORTANT: If the page has navigation to browse OTHER schools/places, it's a directory - answer NO.

The key question: Is this site run BY the organization/government, or just ABOUT it?

First line must be YES or NO. Then explain briefly. /no_think'''

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
                return {'valid': False, 'confidence': 0, 'reason': f'LLM error: {response.status_code}'}

            result_text = response.json().get('response', '').strip()

            # Strip qwen3 thinking tags if present
            if '<think>' in result_text:
                result_text = re.sub(r'<think>.*?</think>', '', result_text, flags=re.DOTALL).strip()

            # Parse response - first word should be YES or NO
            first_line = result_text.split('\n')[0].strip().upper()
            is_valid = first_line.startswith('YES')

            # Get reason from rest of response
            reason = result_text.split('\n', 1)[1].strip() if '\n' in result_text else result_text
            reason = reason[:150]

            # Confidence based on response clarity
            confidence = 0.8 if is_valid else 0.7

            return {
                'valid': is_valid,
                'confidence': confidence,
                'reason': reason
            }

    except Exception as e:
        logger.error(f"LLM text validation error: {e}")
        return {'valid': False, 'confidence': 0, 'reason': f'Error: {str(e)[:100]}'}


def find_official_website(poi) -> dict:
    """
    Find the official website for a POI via web search.

    Args:
        poi: POI model instance (must have name and city)

    Returns:
        {
            'website': str or None,
            'confidence': float (0-1),
            'notes': str
        }
    """
    if not poi.name or not poi.city:
        return {
            'website': None,
            'confidence': 0,
            'notes': 'Missing name or city'
        }

    # Build search query based on category
    template = CATEGORY_SEARCH_TEMPLATES.get(poi.category, '{name} {city} MA official website')
    query = template.format(name=poi.name, city=poi.city)

    # Add street address if available (helps disambiguate)
    street = getattr(poi, 'street_address', '')
    if street:
        query = f'{query} {street}'

    # Add domain exclusions to improve result quality
    exclusions = ' '.join(f'-site:{d}' for d in SEARCH_EXCLUDE_DOMAINS)
    query = f'{query} {exclusions}'

    logger.info(f"Searching for: {query}")

    # Get blocked domains
    blocked_domains = get_blocked_domains()

    try:
        # Search with DuckDuckGo (with retry for rate limiting)
        results = None
        was_rate_limited = False

        # Set up 302 detector on httpx logger
        detector = DDG302Detector()
        httpx_logger = logging.getLogger('httpx')
        httpx_logger.addHandler(detector)

        try:
            for attempt in range(3):
                detector.saw_302 = False  # Reset for each attempt
                try:
                    with DDGS() as ddgs:
                        # Use specific backends - skip wikipedia (not useful) and mojeek (403s)
                        # Available: brave, duckduckgo, yahoo, yandex
                        # We still detect DDG 302s via log interception for AIMD throttling
                        results = list(ddgs.text(query, region='us-en', max_results=5,
                                                 backend='duckduckgo,brave,yahoo,yandex'))

                    # Log DDG 302 for monitoring, but don't trigger backoff if fallbacks worked
                    if detector.saw_302:
                        logger.debug(f"DDG returned 302 (rate limited), using fallback engines")

                    if results:
                        break
                    else:
                        # No results from ANY engine - this is a real problem, trigger backoff
                        was_rate_limited = True
                        logger.warning(f"Search attempt {attempt + 1} returned empty from all engines, retrying...")
                        time.sleep(5 * (attempt + 1))
                except Exception as e:
                    error_str = str(e).lower()
                    if 'ratelimit' in error_str or '302' in error_str or 'redirect' in error_str or attempt < 2:
                        was_rate_limited = True
                        logger.debug(f"Search attempt {attempt + 1} failed ({e}), retrying after delay...")
                        time.sleep(5 * (attempt + 1))  # Exponential backoff: 5s, 10s, 15s
                    else:
                        raise
        finally:
            # Always remove the handler
            httpx_logger.removeHandler(detector)

        if not results:
            return {
                'website': None,
                'confidence': 0,
                'notes': 'No search results found - ratelimit' if was_rate_limited else 'No search results found'
            }

        # Score and filter results
        scored_results = []
        for r in results:
            url = r.get('href', '')
            title = r.get('title', '')
            domain = urlparse(url).netloc.lower()

            # Skip blocked domains
            if is_domain_blocked(domain, blocked_domains):
                logger.debug(f"Skipping blocked domain: {domain}")
                continue

            score = score_result(url, title, poi.name, poi.city)
            scored_results.append({
                'url': url,
                'title': title,
                'domain': domain,
                'score': score,
            })

        if not scored_results:
            notes = 'All results were blocked domains'
            if was_rate_limited:
                notes += ' - ratelimit'
            return {
                'website': None,
                'confidence': 0,
                'notes': notes
            }

        # Sort by score
        scored_results.sort(key=lambda x: x['score'], reverse=True)
        best = scored_results[0]

        # Suffix for rate limit detection by worker (triggers AIMD backoff)
        rl_suffix = ' - ratelimit' if was_rate_limited else ''

        # Try top candidates with validation
        for i, candidate in enumerate(scored_results[:3]):
            url = candidate['url']
            domain = candidate['domain']

            # Step 1: Verify accessible and get HTML
            accessible, html = verify_website_accessible(url)
            if not accessible:
                logger.debug(f"Candidate {i+1} not accessible: {url}")
                continue

            # Step 2: Quick HTML keyword check (fast pre-filter)
            html_result = validate_html_content(html, poi)
            logger.info(f"HTML pre-check for {url}: valid={html_result['valid']}, "
                       f"confidence={html_result['confidence']:.2f}")

            if html_result['confidence'] < 0.2:
                # Very low confidence - definitely garbage, auto-blocklist the domain
                logger.info(f"HTML rejected {url}, adding {domain} to blocklist")
                _auto_blocklist_domain(domain, f"Auto-blocked: {html_result['reason'][:100]}")
                continue

            # Step 3: LLM text validation (smarter than keywords)
            logger.info(f"Running LLM text validation for {url}")
            llm_result = asyncio.run(validate_with_llm_text(html, poi))
            logger.info(f"LLM validation: valid={llm_result['valid']}, reason={llm_result['reason'][:80]}")

            if llm_result['valid']:
                return {
                    'website': url,
                    'confidence': llm_result['confidence'],
                    'notes': f"LLM validated: {llm_result['reason'][:100]}{rl_suffix}"
                }
            else:
                # LLM rejected - auto-blocklist if it's clearly garbage
                if html_result['confidence'] < 0.4:
                    logger.info(f"LLM rejected {url}, adding {domain} to blocklist")
                    _auto_blocklist_domain(domain, f"LLM rejected: {llm_result['reason'][:100]}")

        return {
            'website': None,
            'confidence': 0,
            'notes': f"All candidates failed validation{rl_suffix}"
        }

    except Exception as e:
        logger.error(f"Search error: {e}")
        return {
            'website': None,
            'confidence': 0,
            'notes': f"Search error: {str(e)[:100]}"
        }


def _auto_blocklist_domain(domain: str, reason: str):
    """Add a domain to the blocklist automatically."""
    try:
        # Don't blocklist .gov, .edu, or .org domains automatically
        if any(domain.endswith(tld) for tld in ['.gov', '.edu', '.org', '.us']):
            logger.debug(f"Skipping auto-blocklist for trusted TLD: {domain}")
            return

        obj, created = BlockedDomain.objects.get_or_create(
            domain=domain,
            defaults={'reason': reason}
        )
        if created:
            logger.info(f"Auto-added to blocklist: {domain}")
    except Exception as e:
        logger.warning(f"Failed to auto-blocklist {domain}: {e}")
