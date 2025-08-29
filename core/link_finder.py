"""Enhanced link detection for finding event and calendar pages."""

import re
from typing import List, Set, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag


class EventLinkFinder:
    """Finds links to event and calendar pages using multiple detection strategies."""
    
    # Event-related keywords to look for in URLs and link text
    URL_KEYWORDS = [
        'calendar', 'events', 'event', 'schedule', 'programming',
        'activities', 'workshops', 'classes', 'programs'
    ]
    
    # Text patterns that suggest event/calendar links
    TEXT_KEYWORDS = [
        'calendar', 'events', 'event calendar', 'program calendar',
        'upcoming events', 'what\'s on', 'activities', 'schedule',
        'workshops', 'classes', 'programming', 'happenings'
    ]
    
    # External calendar domains commonly used by libraries/museums
    EXTERNAL_CALENDAR_DOMAINS = [
        'libcal.com', 'events.constantcontact.com', 'eventbrite.com',
        'calendar.google.com', 'outlook.live.com', 'brownpapertickets.com'
    ]
    
    def find_event_links(self, html: str, base_url: str) -> List[dict]:
        """
        Find all potential event/calendar links on a page.
        
        Args:
            html: HTML content of the page
            base_url: Base URL for resolving relative links
            
        Returns:
            List of dictionaries with link information
        """
        soup = BeautifulSoup(html, 'html.parser')
        base_domain = urlparse(base_url).netloc.lower()
        
        found_links = []
        processed_urls = set()  # Avoid duplicates
        
        # Find all links
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            if not href or href.startswith(('javascript:', 'mailto:', 'tel:')):
                continue
                
            # Convert to absolute URL
            full_url = urljoin(base_url, href)
            
            # Skip if we've already processed this URL
            if full_url in processed_urls:
                continue
            processed_urls.add(full_url)
            
            # Get link text and surrounding context
            link_text = link.get_text(strip=True).lower()
            link_title = link.get('title', '').lower()
            
            # Score the link based on multiple factors
            score = self._score_link(href, link_text, link_title, full_url, base_domain)
            
            if score > 0:
                found_links.append({
                    'url': full_url,
                    'text': link_text,
                    'title': link_title,
                    'score': score,
                    'is_external': self._is_external_domain(full_url, base_domain),
                    'detection_method': self._get_detection_method(href, link_text, link_title, full_url)
                })
        
        # Sort by score (highest first)
        found_links.sort(key=lambda x: x['score'], reverse=True)
        
        return found_links
    
    def _score_link(self, href: str, link_text: str, link_title: str, 
                   full_url: str, base_domain: str) -> float:
        """
        Score a link based on how likely it is to contain events.
        
        Returns:
            Float score (0.0 = not event-related, higher = more likely)
        """
        score = 0.0
        href_lower = href.lower()
        full_url_lower = full_url.lower()
        
        # Check URL path for event keywords
        for keyword in self.URL_KEYWORDS:
            if keyword in href_lower:
                score += 3.0
                break
        
        # Check link text
        for keyword in self.TEXT_KEYWORDS:
            if keyword in link_text:
                score += 2.0
                if keyword == link_text:  # Exact match gets bonus
                    score += 1.0
                break
        
        # Check title attribute
        for keyword in self.TEXT_KEYWORDS:
            if keyword in link_title:
                score += 1.5
                break
        
        # Check for external calendar domains
        if self._is_external_calendar_domain(full_url):
            score += 4.0  # High score for known calendar services
        
        # Bonus for common event URL patterns
        if re.search(r'/events?/?$', href_lower):
            score += 2.0
        elif re.search(r'/calendar/?$', href_lower):
            score += 2.0
        elif re.search(r'/programs?/?$', href_lower):
            score += 1.0
        
        # Penalty for obviously non-event URLs
        skip_patterns = [
            'about', 'contact', 'staff', 'admin', 'login', 
            'privacy', 'terms', 'policy', 'donate', 'membership'
        ]
        
        for pattern in skip_patterns:
            if pattern in href_lower:
                score = max(0.0, score - 2.0)
        
        return score
    
    def _is_external_domain(self, url: str, base_domain: str) -> bool:
        """Check if URL is on a different domain than the base."""
        url_domain = urlparse(url).netloc.lower()
        return url_domain != base_domain and url_domain != ''
    
    def _is_external_calendar_domain(self, url: str) -> bool:
        """Check if URL is on a known external calendar service."""
        url_domain = urlparse(url).netloc.lower()
        return any(calendar_domain in url_domain for calendar_domain in self.EXTERNAL_CALENDAR_DOMAINS)
    
    def _get_detection_method(self, href: str, link_text: str, link_title: str, full_url: str) -> str:
        """Determine how this link was detected."""
        methods = []
        
        href_lower = href.lower()
        
        # Check detection methods
        if any(keyword in href_lower for keyword in self.URL_KEYWORDS):
            methods.append('url_keyword')
            
        if any(keyword in link_text for keyword in self.TEXT_KEYWORDS):
            methods.append('link_text')
            
        if any(keyword in link_title for keyword in self.TEXT_KEYWORDS):
            methods.append('title_attribute')
            
        if self._is_external_calendar_domain(full_url):
            methods.append('external_calendar_domain')
            
        if re.search(r'/events?/?$', href_lower) or re.search(r'/calendar/?$', href_lower):
            methods.append('url_pattern')
        
        return '+'.join(methods) if methods else 'low_score'


def find_event_links_simple(html: str, base_url: str) -> List[str]:
    """
    Simplified interface that returns just the URLs of likely event pages.
    
    Args:
        html: HTML content of the page
        base_url: Base URL for resolving relative links
        
    Returns:
        List of URLs sorted by likelihood (best first)
    """
    finder = EventLinkFinder()
    results = finder.find_event_links(html, base_url)
    
    # Filter to only include high-scoring links
    high_score_links = [result['url'] for result in results if result['score'] >= 2.0]
    
    return high_score_links