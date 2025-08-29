"""Core navigation discovery logic for finding event pages on websites."""

import re
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .llm_analyzer import analyze_site_for_events
from .url_patterns import extract_url_patterns, detect_pagination
from .link_finder import find_event_links_simple
from .page_validator import validate_event_urls_simple


def discover_site_navigation(base_url: str, target_schema: Optional[Dict] = None, 
                           max_depth: int = 3, follow_external_links: bool = False) -> Dict:
    """
    Discover event-related navigation patterns on a website.
    
    Args:
        base_url: Starting URL to analyze
        target_schema: Schema definition for target content
        max_depth: Maximum crawl depth
        follow_external_links: Whether to follow external domains
        
    Returns:
        Dictionary with discovered navigation patterns
    """
    if target_schema is None:
        target_schema = {
            "type": "events",
            "required_fields": ["title", "date", "location"],
            "content_indicators": ["calendar", "event", "workshop", "meeting"]
        }
    
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc
    
    visited_urls = set()
    event_urls = []
    all_discovered_urls = []
    skip_patterns = []
    
    # Use enhanced link detection on the home page first
    try:
        response = requests.get(base_url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; SuperschedulesNavigator/1.0)"
        })
        response.raise_for_status()
        
        # Find event links using the enhanced detector
        quick_event_links = find_event_links_simple(response.text, base_url)
        print(f"Quick detection found {len(quick_event_links)} potential event URLs")
        
        # Validate that these URLs actually contain events
        if quick_event_links:
            validated_urls = validate_event_urls_simple(quick_event_links[:5])  # Validate top 5
            event_urls.extend(validated_urls)
            print(f"Validated {len(validated_urls)} URLs that actually contain events")
        
    except Exception as e:
        print(f"Quick detection failed: {e}")
    
    # Fall back to traditional crawling if needed
    if len(event_urls) == 0:
        _crawl_for_event_pages(
            base_url, base_domain, target_schema, visited_urls, 
            event_urls, all_discovered_urls, skip_patterns,
            max_depth, follow_external_links
        )
    
    # Extract URL patterns from discovered URLs
    url_patterns = extract_url_patterns(event_urls)
    
    # Detect pagination strategies
    pagination_info = {}
    if event_urls:
        pagination_info = detect_pagination(event_urls[0])  # Analyze first event URL
    
    # Discover filters using LLM analysis
    discovered_filters = {}
    navigation_confidence = 0.5
    
    if event_urls:
        try:
            llm_analysis = analyze_site_for_events(base_url, event_urls[:3])  # Analyze top 3
            discovered_filters = llm_analysis.get("filters", {})
            navigation_confidence = llm_analysis.get("confidence", 0.5)
        except Exception as e:
            print(f"LLM analysis failed: {e}")
    
    return {
        "event_urls": event_urls,
        "url_patterns": url_patterns,
        "pagination_type": pagination_info.get("type"),
        "pagination_selector": pagination_info.get("selector"),
        "items_per_page": pagination_info.get("items_per_page"),
        "discovered_filters": discovered_filters,
        "skip_patterns": skip_patterns,
        "confidence": navigation_confidence
    }


def _crawl_for_event_pages(base_url: str, base_domain: str, target_schema: Dict,
                          visited_urls: Set[str], event_urls: List[str], 
                          all_discovered_urls: List[str], skip_patterns: List[str],
                          max_depth: int, follow_external_links: bool,
                          current_depth: int = 0) -> None:
    """
    Recursively crawl site to find event-related pages.
    """
    if current_depth >= max_depth or base_url in visited_urls:
        return
    
    visited_urls.add(base_url)
    
    try:
        response = requests.get(base_url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; SuperschedulesNavigator/1.0)"
        })
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Check if current page contains events
        if _page_contains_events(soup, target_schema):
            event_urls.append(base_url)
            print(f"Found event page: {base_url}")
        
        # Find all links on the page
        links = soup.find_all('a', href=True)
        
        for link in links:
            href = link.get('href')
            if not href:
                continue
                
            # Convert relative URLs to absolute
            full_url = urljoin(base_url, href)
            parsed_url = urlparse(full_url)
            
            # Skip if external domain and not following external links
            if not follow_external_links and parsed_url.netloc != base_domain:
                continue
                
            # Skip common non-event pages
            if _should_skip_url(full_url, link.get_text(strip=True)):
                if full_url not in skip_patterns:
                    skip_patterns.append(_extract_skip_pattern(full_url))
                continue
            
            # Check if link looks event-related
            if _link_looks_like_events(link, target_schema):
                all_discovered_urls.append(full_url)
                
                # Recursively crawl promising links
                if current_depth < max_depth - 1:
                    _crawl_for_event_pages(
                        full_url, base_domain, target_schema, visited_urls,
                        event_urls, all_discovered_urls, skip_patterns, 
                        max_depth, follow_external_links, current_depth + 1
                    )
                    
    except Exception as e:
        print(f"Error crawling {base_url}: {e}")


def _page_contains_events(soup: BeautifulSoup, target_schema: Dict) -> bool:
    """
    Determine if a page contains events based on content analysis.
    """
    content_indicators = target_schema.get("content_indicators", ["event", "calendar"])
    page_text = soup.get_text().lower()
    
    # Look for event indicators in page text
    indicator_count = sum(1 for indicator in content_indicators if indicator in page_text)
    
    # Look for date patterns that suggest events
    date_patterns = [
        r'\b\d{1,2}/\d{1,2}/\d{4}\b',  # MM/DD/YYYY
        r'\b\d{4}-\d{2}-\d{2}\b',      # YYYY-MM-DD
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}\b',  # Month DD
    ]
    
    date_matches = 0
    for pattern in date_patterns:
        if re.search(pattern, page_text):
            date_matches += 1
    
    # Page likely contains events if it has indicators and date patterns
    return indicator_count >= 2 and date_matches >= 1


def _link_looks_like_events(link_tag, target_schema: Dict) -> bool:
    """
    Determine if a link is likely to lead to event content.
    """
    href = link_tag.get('href', '').lower()
    link_text = link_tag.get_text(strip=True).lower()
    content_indicators = [indicator.lower() for indicator in target_schema.get("content_indicators", [])]
    
    # Check URL path
    for indicator in content_indicators:
        if indicator in href:
            return True
    
    # Check link text
    for indicator in content_indicators:
        if indicator in link_text:
            return True
    
    # Look for calendar-like patterns
    calendar_patterns = ['calendar', 'schedule', 'upcoming', 'what\'s on']
    for pattern in calendar_patterns:
        if pattern in href or pattern in link_text:
            return True
            
    return False


def _should_skip_url(url: str, link_text: str) -> bool:
    """
    Determine if a URL should be skipped as non-event related.
    """
    url_lower = url.lower()
    text_lower = link_text.lower()
    
    skip_patterns = [
        # Common non-content pages
        '/about', '/contact', '/staff', '/faculty', '/directory',
        '/admin', '/login', '/account', '/profile', '/settings',
        '/privacy', '/terms', '/policy', '/legal',
        # File extensions
        '.pdf', '.doc', '.xls', '.jpg', '.png', '.gif',
        # Common non-event sections
        '/news', '/blog', '/press', '/media', '/gallery',
        '/donate', '/give', '/support', '/membership'
    ]
    
    skip_text_patterns = [
        'about us', 'contact us', 'staff directory', 'faculty',
        'privacy policy', 'terms of service', 'donate', 'membership'
    ]
    
    # Check URL patterns
    for pattern in skip_patterns:
        if pattern in url_lower:
            return True
            
    # Check link text patterns
    for pattern in skip_text_patterns:
        if pattern in text_lower:
            return True
            
    return False


def _extract_skip_pattern(url: str) -> str:
    """
    Extract a general skip pattern from a specific URL.
    """
    parsed = urlparse(url)
    path_parts = parsed.path.split('/')
    
    # Return the first non-empty path component as a pattern
    for part in path_parts:
        if part and not part.isdigit():  # Skip numeric parts (likely IDs)
            return f"/{part}"
    
    return parsed.path