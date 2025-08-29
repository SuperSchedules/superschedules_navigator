"""Validate that discovered pages actually contain events."""

import re
from typing import Dict, List, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


class EventPageValidator:
    """Validates that a page actually contains events, not just event-related links."""
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; SuperschedulesNavigator/1.0)"
        })
    
    def validate_event_urls(self, candidate_urls: List[str], 
                           target_schema: Dict = None) -> List[Dict]:
        """
        Validate a list of candidate URLs to see which actually contain events.
        Also discovers iframe URLs that should be followed.
        
        Args:
            candidate_urls: List of URLs that might contain events
            target_schema: Schema defining what we're looking for
            
        Returns:
            List of validated URLs with validation scores (includes iframe URLs)
        """
        if target_schema is None:
            target_schema = {
                "content_indicators": ["event", "calendar", "workshop", "meeting"],
                "required_fields": ["title", "date", "location"]
            }
        
        validated_urls = []
        discovered_iframe_urls = set()
        
        for url in candidate_urls:
            validation_result = self.validate_single_url(url, target_schema)
            
            # Check if page has iframe calendars
            iframe_urls = validation_result.get("iframe_urls", [])
            for iframe_url in iframe_urls:
                discovered_iframe_urls.add(iframe_url)
            
            # Include page if it has events OR if it has iframe calendars
            if validation_result["has_events"] or iframe_urls:
                validated_urls.append(validation_result)
        
        # Validate discovered iframe URLs as well
        for iframe_url in discovered_iframe_urls:
            if iframe_url not in [result["url"] for result in validated_urls]:
                iframe_result = self.validate_single_url(iframe_url, target_schema)
                iframe_result["source_type"] = "iframe"
                if iframe_result["has_events"]:
                    validated_urls.append(iframe_result)
        
        # Sort by validation score (highest first)
        validated_urls.sort(key=lambda x: x["validation_score"], reverse=True)
        
        return validated_urls
    
    def validate_single_url(self, url: str, target_schema: Dict) -> Dict:
        """
        Validate a single URL to check if it contains events.
        
        Returns:
            Dict with validation results
        """
        result = {
            "url": url,
            "has_events": False,
            "validation_score": 0.0,
            "event_count_estimate": 0,
            "validation_details": {},
            "iframe_urls": [],
            "error": None
        }
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Perform validation checks
            validation_details = self._analyze_page_content(soup, target_schema)
            result.update(validation_details)
            
            # Extract iframe URLs
            iframe_urls = self._find_calendar_iframes(soup)
            result["iframe_urls"] = iframe_urls
            
            # Determine if page has events based on multiple factors
            result["has_events"] = self._determine_has_events(validation_details)
            
        except Exception as e:
            result["error"] = str(e)
            result["validation_score"] = 0.0
        
        return result
    
    def _analyze_page_content(self, soup: BeautifulSoup, target_schema: Dict) -> Dict:
        """Analyze page content for event indicators."""
        page_text = soup.get_text().lower()
        content_indicators = target_schema.get("content_indicators", [])
        
        analysis = {
            "validation_score": 0.0,
            "event_count_estimate": 0,
            "validation_details": {
                "content_indicators_found": [],
                "date_patterns_found": 0,
                "time_patterns_found": 0,
                "event_like_elements": 0,
                "structured_data_found": False,
                "calendar_widgets_found": 0,
                "iframe_calendars_found": [],
                "detail_pages_found": [],
                "page_type": "unknown"
            }
        }
        
        # Check for calendar/event iframes that should be followed
        iframe_urls = self._find_calendar_iframes(soup)
        if iframe_urls:
            analysis["validation_details"]["iframe_calendars_found"] = iframe_urls
            # Treat iframe calendar as high confidence for events
            analysis["validation_score"] += 8.0
            analysis["event_count_estimate"] += 5  # Assume some events in iframe
            analysis["validation_details"]["page_type"] = "iframe_calendar"
        
        # Check for event detail page links - these are much better targets for LLM extraction
        detail_pages = self._find_event_detail_pages(soup)
        if detail_pages:
            analysis["validation_details"]["detail_pages_found"] = detail_pages
            # Boost score for pages with detail links (listing pages are less useful)
            analysis["validation_score"] += min(len(detail_pages) * 0.5, 3.0)
            analysis["validation_details"]["page_type"] = "event_listing_with_details"
        
        # 1. Check for content indicators
        for indicator in content_indicators:
            if indicator.lower() in page_text:
                analysis["validation_details"]["content_indicators_found"].append(indicator)
                analysis["validation_score"] += 1.0
        
        # 2. Look for date patterns (strong indicator of events)
        date_patterns = [
            r'\b\d{1,2}/\d{1,2}/\d{4}\b',  # MM/DD/YYYY
            r'\b\d{4}-\d{2}-\d{2}\b',      # YYYY-MM-DD  
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}(?:,? \d{4})?\b',  # Month DD, YYYY
            r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[,\s]+\w+\s+\d{1,2}\b'  # Day, Month DD
        ]
        
        date_matches = 0
        for pattern in date_patterns:
            matches = re.findall(pattern, page_text, re.IGNORECASE)
            if matches:
                date_matches += len(matches)
        
        analysis["validation_details"]["date_patterns_found"] = date_matches
        analysis["validation_score"] += min(date_matches * 0.5, 5.0)  # Cap at 5 points
        
        # 3. Look for time patterns
        time_patterns = [
            r'\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)\b',
            r'\b\d{1,2}:\d{2}\b'
        ]
        
        time_matches = 0
        for pattern in time_patterns:
            matches = re.findall(pattern, page_text)
            if matches:
                time_matches += len(matches)
        
        analysis["validation_details"]["time_patterns_found"] = time_matches
        analysis["validation_score"] += min(time_matches * 0.3, 3.0)  # Cap at 3 points
        
        # 4. Look for event-like structural elements
        event_selectors = [
            '.event', '.calendar-event', '.program', '.workshop',
            '[class*="event"]', '[class*="calendar"]', '.activity'
        ]
        
        event_elements = 0
        for selector in event_selectors:
            elements = soup.select(selector)
            event_elements += len(elements)
        
        analysis["validation_details"]["event_like_elements"] = event_elements
        analysis["validation_score"] += min(event_elements * 0.8, 8.0)  # Cap at 8 points
        analysis["event_count_estimate"] = max(event_elements, date_matches // 2)
        
        # 5. Check for structured data (JSON-LD events)
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Event':
                    analysis["validation_details"]["structured_data_found"] = True
                    analysis["validation_score"] += 10.0  # High score for structured events
                elif isinstance(data, list):
                    events = [item for item in data if isinstance(item, dict) and item.get('@type') == 'Event']
                    if events:
                        analysis["validation_details"]["structured_data_found"] = True
                        analysis["validation_score"] += 10.0
                        analysis["event_count_estimate"] += len(events)
            except:
                pass
        
        # 6. Look for calendar widgets or event listings
        calendar_indicators = soup.select('.calendar, .event-calendar, .fc-event, .tribe-events')
        analysis["validation_details"]["calendar_widgets_found"] = len(calendar_indicators)
        if calendar_indicators:
            analysis["validation_score"] += 5.0
        
        return analysis
    
    def _determine_has_events(self, validation_details: Dict) -> bool:
        """
        Determine if page likely has events based on validation analysis.
        
        Uses multiple criteria to avoid false positives.
        """
        score = validation_details["validation_score"]
        details = validation_details["validation_details"]
        
        # Strong positive indicators
        if details["structured_data_found"]:
            return True  # JSON-LD events are definitive
        
        if details["calendar_widgets_found"] > 0:
            return True  # Calendar widgets strongly suggest events
        
        # Multiple weak indicators can add up
        if score >= 8.0:  # High overall score
            return True
        
        # Must have both content indicators AND temporal patterns
        has_content_indicators = len(details["content_indicators_found"]) >= 2
        has_temporal_patterns = (details["date_patterns_found"] >= 3 and 
                               details["time_patterns_found"] >= 2)
        has_structural_elements = details["event_like_elements"] >= 5
        
        # Need at least two types of evidence
        evidence_count = sum([
            has_content_indicators,
            has_temporal_patterns, 
            has_structural_elements
        ])
        
        return evidence_count >= 2
    
    def _find_calendar_iframes(self, soup: BeautifulSoup) -> List[str]:
        """
        Find iframe URLs that likely contain calendar/event content.
        
        Returns:
            List of iframe URLs that should be followed
        """
        iframe_urls = []
        
        # Find all iframe elements
        iframes = soup.find_all('iframe', src=True)
        
        for iframe in iframes:
            src = iframe.get('src')
            if not src:
                continue
            
            # Convert relative URLs to absolute if needed
            from urllib.parse import urljoin, urlparse
            if not src.startswith(('http://', 'https://')):
                continue  # Skip relative URLs for now (would need base URL)
            
            src_lower = src.lower()
            
            # Check for calendar/event indicators in iframe URL
            calendar_indicators = [
                'calendar', 'events', 'event', 'libcal', 'eventbrite',
                'assabetinteractive', 'calendar.google', 'outlook.live',
                'schedule', 'booking', 'registration'
            ]
            
            for indicator in calendar_indicators:
                if indicator in src_lower:
                    iframe_urls.append(src)
                    break
        
        return iframe_urls
    
    def _find_event_detail_pages(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Find links to individual event detail pages within event listings.
        These are better targets for LLM extraction than listing pages.
        
        Returns:
            List of dicts with detail page URLs and metadata
        """
        detail_pages = []
        
        # Common patterns for detail links
        detail_link_patterns = [
            'more info', 'details', 'learn more', 'read more', 'view details',
            'full details', 'see details', 'more', 'register', 'buy tickets',
            'get tickets', 'book now', 'sign up', 'rsvp', 'join us'
        ]
        
        # CSS classes that suggest detail links
        detail_class_patterns = [
            'detail', 'more', 'info', 'read-more', 'learn-more', 'view-more',
            'register', 'ticket', 'event-link', 'event-detail', 'btn-secondary'
        ]
        
        # URL patterns for individual event pages
        event_url_patterns = [
            r'/calendar/[^/]+$',     # /calendar/event-name
            r'/events?/[^/]+$',      # /events/event-name
            r'/programs?/[^/]+$',    # /programs/event-name
            r'[^/]+/event-\d+',      # various/event-123
            r'[^/]+/\d{4}/\d{2}/\d{2}',  # date-based URLs
        ]
        
        # Find event containers first
        event_containers = soup.select('.event, .calendar-event, .program, .activity, [class*="event"], [class*="calendar"], .isg-events-list__item-wrapper, .views-rendered-node')
        
        # Look for detail links within event containers
        for container in event_containers:
            links = container.find_all('a', href=True)
            
            for link in links:
                href = link.get('href', '').strip()
                if not href:
                    continue
                    
                link_text = link.get_text(strip=True).lower()
                link_classes = ' '.join(link.get('class', [])).lower()
                
                # Check if this looks like a detail link
                is_detail_link = False
                match_reasons = []
                
                # Check text patterns
                for pattern in detail_link_patterns:
                    if pattern in link_text:
                        is_detail_link = True
                        match_reasons.append(f'text:{pattern}')
                        break
                
                # Check class patterns
                if not is_detail_link:
                    for pattern in detail_class_patterns:
                        if pattern in link_classes:
                            is_detail_link = True
                            match_reasons.append(f'class:{pattern}')
                            break
                
                # Check URL patterns
                if not is_detail_link:
                    for pattern in event_url_patterns:
                        if re.search(pattern, href):
                            is_detail_link = True
                            match_reasons.append(f'url:{pattern}')
                            break
                
                if is_detail_link:
                    detail_pages.append({
                        'url': href,
                        'text': link_text[:50],  # Truncate for storage
                        'match_reasons': match_reasons,
                        'priority': self._calculate_detail_link_priority(link_text, match_reasons)
                    })
        
        # Sort by priority (higher is better)
        detail_pages.sort(key=lambda x: x['priority'], reverse=True)
        
        return detail_pages
    
    def _calculate_detail_link_priority(self, link_text: str, match_reasons: List[str]) -> float:
        """
        Calculate priority score for detail links.
        Higher priority links are better targets for LLM extraction.
        """
        priority = 0.0
        
        # High priority text patterns
        high_priority_texts = ['more info', 'details', 'full details', 'view details']
        medium_priority_texts = ['register', 'buy tickets', 'get tickets', 'sign up']
        low_priority_texts = ['more', 'learn more', 'read more']
        
        for text in high_priority_texts:
            if text in link_text:
                priority += 3.0
                break
                
        for text in medium_priority_texts:
            if text in link_text:
                priority += 2.0
                break
                
        for text in low_priority_texts:
            if text in link_text:
                priority += 1.0
                break
        
        # URL-based matches get bonus
        if any('url:' in reason for reason in match_reasons):
            priority += 1.0
            
        return priority
    
    def get_iframe_urls(self, url: str) -> List[str]:
        """
        Public method to get iframe URLs from a page without full validation.
        
        Used by navigator to discover additional URLs to check.
        """
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            return self._find_calendar_iframes(soup)
            
        except Exception as e:
            print(f"Error getting iframe URLs from {url}: {e}")
            return []
    
    def get_detail_page_urls(self, url: str) -> List[str]:
        """
        Public method to get detail page URLs from a listing page.
        
        These URLs are better targets for LLM event extraction than listing pages.
        Returns URLs sorted by priority (highest priority first).
        """
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            detail_pages = self._find_event_detail_pages(soup)
            
            # Convert relative URLs to absolute and return sorted list
            from urllib.parse import urljoin
            detail_urls = []
            for page in detail_pages:
                absolute_url = urljoin(url, page['url'])
                detail_urls.append(absolute_url)
            
            return detail_urls
            
        except Exception as e:
            print(f"Error getting detail page URLs from {url}: {e}")
            return []


def validate_event_urls_simple(urls: List[str]) -> List[str]:
    """
    Simplified interface - return just the URLs that actually contain events.
    
    Args:
        urls: List of candidate URLs
        
    Returns:
        List of validated URLs that contain events
    """
    validator = EventPageValidator()
    validated = validator.validate_event_urls(urls)
    return [result["url"] for result in validated]