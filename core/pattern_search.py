"""
Pattern-Based Event Search Module

Generates and executes search queries to discover event pages across:
- Government sites (.gov)
- Educational institutions (.edu)
- Libraries and cultural institutions
- Parks & Recreation departments
- Museums and arts organizations

Uses search patterns like:
- site:.gov (events|calendar) "City of" boston
- inurl:/events OR inurl:/calendar library
- filetype:ics events calendar
"""

import re
import time
from typing import List, Dict, Optional, Set
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup


class PatternSearcher:
    """Generates and executes pattern-based searches for event pages"""

    # Search query templates
    SEARCH_PATTERNS = {
        'gov_city': 'site:.gov (events OR calendar) "City of" {city}',
        'gov_county': 'site:.gov (events OR calendar) "{county} County"',
        'gov_state': 'site:{state}.gov (events OR calendar)',
        'edu_general': 'site:.edu (events OR calendar) {location}',
        'library_general': 'inurl:/events OR inurl:/calendar (library OR "public library") {location}',
        'library_platforms': 'site:libcal.com OR site:bibliocommons.com {location}',
        'parks_rec': 'inurl:/events OR inurl:/calendar (parks OR recreation OR "parks and recreation") {location}',
        'museums': 'inurl:/events OR inurl:/calendar (museum OR gallery OR "art center") {location}',
        'community': 'inurl:/events OR inurl:/calendar (community OR "community center") {location}',
        'ics_feeds': 'filetype:ics (events OR calendar) {keywords}',
        'general_events': '(events OR calendar OR "what\'s on") {organization_type} {location}'
    }

    # Common endpoints to test on discovered domains
    COMMON_ENDPOINTS = [
        '/events',
        '/events/',
        '/event',
        '/calendar',
        '/calendar/',
        '/event-calendar',
        '/events-calendar',
        '/whats-on',
        '/whatson',
        '/news-events',
        '/things-to-do',
        '/programs-events',
        '/programs',
        '/activities',
        '/schedule',
        '/happenings',
        '/upcoming',
        '/upcoming-events',
        # ICS feeds
        '/events/feed.ics',
        '/calendar.ics',
        '/events.ics',
        '/calendar/feed',
        '/events/feed'
    ]

    # Organization types
    ORG_TYPES = [
        'library', 'museum', 'parks', 'recreation',
        'community center', 'arts center', 'university',
        'college', 'theater', 'theatre', 'gallery'
    ]

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def search_for_events(
        self,
        location: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        county: Optional[str] = None,
        org_types: Optional[List[str]] = None,
        search_patterns: Optional[List[str]] = None
    ) -> List[Dict[str, any]]:
        """
        Execute pattern-based searches for event pages

        Args:
            location: General location (e.g., "boston", "seattle")
            city: Specific city name
            state: State code (e.g., "ma", "wa")
            county: County name
            org_types: Organization types to search for
            search_patterns: Specific patterns to use (if None, uses all relevant)

        Returns:
            List of discovered event URLs with metadata
        """
        results = []
        discovered_urls = set()

        # Determine which patterns to use
        if search_patterns is None:
            search_patterns = self._select_patterns(
                location, city, state, county, org_types
            )

        # Generate search queries
        queries = self._generate_queries(
            search_patterns, location, city, state, county, org_types
        )

        # Execute each query
        for query_info in queries:
            query = query_info['query']
            pattern_type = query_info['pattern_type']

            # Get search results (using DuckDuckGo to avoid API keys)
            urls = self._execute_search(query)

            for url in urls:
                if url not in discovered_urls:
                    discovered_urls.add(url)
                    results.append({
                        'url': url,
                        'source': 'pattern_search',
                        'pattern_type': pattern_type,
                        'query': query,
                        'domain': urlparse(url).netloc
                    })

            # Rate limiting
            time.sleep(1)

        return results

    def test_common_endpoints(self, domain: str) -> List[str]:
        """
        Test common event page endpoints on a domain

        Args:
            domain: Domain to test (e.g., "boston.gov")

        Returns:
            List of valid event URLs
        """
        valid_urls = []

        base_url = domain if domain.startswith('http') else f'https://{domain}'

        for endpoint in self.COMMON_ENDPOINTS:
            url = urljoin(base_url, endpoint)

            try:
                response = self.session.head(
                    url,
                    timeout=5,
                    allow_redirects=True
                )

                if response.status_code == 200:
                    valid_urls.append(url)

            except:
                continue

            # Rate limiting
            time.sleep(0.1)

        return valid_urls

    def discover_domain_endpoints(
        self,
        domains: List[str],
        test_endpoints: bool = True
    ) -> List[Dict[str, any]]:
        """
        For a list of domains, discover event page endpoints

        Args:
            domains: List of domain names
            test_endpoints: Whether to test common endpoints

        Returns:
            List of results with discovered URLs
        """
        results = []

        for domain in domains:
            result = {
                'domain': domain,
                'event_urls': []
            }

            if test_endpoints:
                event_urls = self.test_common_endpoints(domain)
                result['event_urls'] = event_urls

            results.append(result)

        return results

    def _select_patterns(
        self,
        location: Optional[str],
        city: Optional[str],
        state: Optional[str],
        county: Optional[str],
        org_types: Optional[List[str]]
    ) -> List[str]:
        """Select which search patterns to use based on input"""
        patterns = []

        if city:
            patterns.append('gov_city')

        if county:
            patterns.append('gov_county')

        if state:
            patterns.append('gov_state')

        if location or city:
            patterns.extend([
                'edu_general',
                'library_general',
                'library_platforms',
                'parks_rec',
                'museums',
                'community'
            ])

        # Always include ICS feeds search
        patterns.append('ics_feeds')

        # Add general pattern if org_types specified
        if org_types:
            patterns.append('general_events')

        return patterns

    def _generate_queries(
        self,
        patterns: List[str],
        location: Optional[str],
        city: Optional[str],
        state: Optional[str],
        county: Optional[str],
        org_types: Optional[List[str]]
    ) -> List[Dict[str, str]]:
        """Generate search queries from patterns and parameters"""
        queries = []

        for pattern in patterns:
            if pattern not in self.SEARCH_PATTERNS:
                continue

            template = self.SEARCH_PATTERNS[pattern]

            # Fill in template based on pattern type
            if pattern == 'gov_city' and city:
                query = template.format(city=city)
                queries.append({'query': query, 'pattern_type': pattern})

            elif pattern == 'gov_county' and county:
                query = template.format(county=county)
                queries.append({'query': query, 'pattern_type': pattern})

            elif pattern == 'gov_state' and state:
                query = template.format(state=state)
                queries.append({'query': query, 'pattern_type': pattern})

            elif pattern == 'edu_general' and (location or city):
                loc = city or location
                query = template.format(location=loc)
                queries.append({'query': query, 'pattern_type': pattern})

            elif pattern == 'library_general' and (location or city):
                loc = city or location
                query = template.format(location=loc)
                queries.append({'query': query, 'pattern_type': pattern})

            elif pattern == 'library_platforms' and (location or city):
                loc = city or location
                query = template.format(location=loc)
                queries.append({'query': query, 'pattern_type': pattern})

            elif pattern == 'parks_rec' and (location or city):
                loc = city or location
                query = template.format(location=loc)
                queries.append({'query': query, 'pattern_type': pattern})

            elif pattern == 'museums' and (location or city):
                loc = city or location
                query = template.format(location=loc)
                queries.append({'query': query, 'pattern_type': pattern})

            elif pattern == 'community' and (location or city):
                loc = city or location
                query = template.format(location=loc)
                queries.append({'query': query, 'pattern_type': pattern})

            elif pattern == 'ics_feeds':
                keywords = city or location or county or 'events'
                query = template.format(keywords=keywords)
                queries.append({'query': query, 'pattern_type': pattern})

            elif pattern == 'general_events' and org_types:
                loc = city or location or ''
                for org_type in org_types:
                    query = template.format(
                        organization_type=org_type,
                        location=loc
                    )
                    queries.append({'query': query, 'pattern_type': pattern})

        return queries

    def _execute_search(self, query: str, max_results: int = 20) -> List[str]:
        """
        Execute a search query using DuckDuckGo

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of URLs from search results
        """
        urls = []

        try:
            # Use DuckDuckGo HTML interface
            search_url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
            response = self.session.get(search_url, timeout=self.timeout)

            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')

                # Find result links
                for link in soup.find_all('a', class_='result__url'):
                    url = link.get('href')
                    if url:
                        # Clean up DuckDuckGo redirect URLs
                        url = self._clean_search_url(url)
                        if url and url.startswith('http'):
                            urls.append(url)

                        if len(urls) >= max_results:
                            break

        except Exception as e:
            print(f"Error executing search for '{query}': {e}")

        return urls

    def _clean_search_url(self, url: str) -> Optional[str]:
        """Clean up search result URLs"""
        # DuckDuckGo sometimes wraps URLs
        if 'uddg=' in url:
            match = re.search(r'uddg=([^&]+)', url)
            if match:
                from urllib.parse import unquote
                return unquote(match.group(1))

        return url


class EventPageSearcher:
    """High-level interface for searching event pages"""

    def __init__(self):
        self.pattern_searcher = PatternSearcher()

    def search_by_location(
        self,
        location: str,
        org_types: Optional[List[str]] = None,
        test_endpoints: bool = True
    ) -> Dict[str, any]:
        """
        Search for event pages in a location

        Args:
            location: City or area name (e.g., "Boston", "Seattle")
            org_types: Types of organizations to search for
            test_endpoints: Whether to test common endpoints on found domains

        Returns:
            Dict with search results and discovered event URLs
        """
        # Execute pattern searches
        search_results = self.pattern_searcher.search_for_events(
            location=location,
            org_types=org_types or self.pattern_searcher.ORG_TYPES
        )

        # Extract unique domains
        domains = list(set([r['domain'] for r in search_results]))

        # Test common endpoints on each domain
        endpoint_results = []
        if test_endpoints:
            endpoint_results = self.pattern_searcher.discover_domain_endpoints(
                domains,
                test_endpoints=True
            )

        # Collect all discovered event URLs
        all_event_urls = set()

        # Add URLs from search results
        for result in search_results:
            all_event_urls.add(result['url'])

        # Add URLs from endpoint testing
        for result in endpoint_results:
            for url in result['event_urls']:
                all_event_urls.add(url)

        return {
            'location': location,
            'search_results': search_results,
            'domains_found': len(domains),
            'domains': domains,
            'endpoint_results': endpoint_results,
            'total_event_urls': len(all_event_urls),
            'event_urls': list(all_event_urls)
        }

    def search_by_city_state(
        self,
        city: str,
        state: str,
        test_endpoints: bool = True
    ) -> Dict[str, any]:
        """
        Search for event pages by city and state

        Args:
            city: City name
            state: State code (e.g., "MA", "WA")
            test_endpoints: Whether to test common endpoints

        Returns:
            Dict with search results
        """
        search_results = self.pattern_searcher.search_for_events(
            city=city,
            state=state.lower(),
            org_types=self.pattern_searcher.ORG_TYPES
        )

        # Extract unique domains
        domains = list(set([r['domain'] for r in search_results]))

        # Test endpoints
        endpoint_results = []
        if test_endpoints:
            endpoint_results = self.pattern_searcher.discover_domain_endpoints(
                domains,
                test_endpoints=True
            )

        # Collect all event URLs
        all_event_urls = set()
        for result in search_results:
            all_event_urls.add(result['url'])
        for result in endpoint_results:
            for url in result['event_urls']:
                all_event_urls.add(url)

        return {
            'city': city,
            'state': state,
            'search_results': search_results,
            'domains_found': len(domains),
            'domains': domains,
            'endpoint_results': endpoint_results,
            'total_event_urls': len(all_event_urls),
            'event_urls': list(all_event_urls)
        }


# Convenience functions
def search_events_in_city(city: str, state: Optional[str] = None) -> List[str]:
    """
    Quick search for event pages in a city

    Args:
        city: City name
        state: Optional state code

    Returns:
        List of event page URLs
    """
    searcher = EventPageSearcher()

    if state:
        results = searcher.search_by_city_state(city, state)
    else:
        results = searcher.search_by_location(city)

    return results['event_urls']
