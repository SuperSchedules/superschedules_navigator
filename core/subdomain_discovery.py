"""
Subdomain Discovery Module

Discovers subdomains for platforms like libcal.com, bibliocommons.com, etc.
Uses multiple techniques:
1. Certificate Transparency (CT) logs
2. Search engine discovery
3. Common pattern testing (city names, library names)
"""

import re
import time
from typing import List, Set, Optional, Dict
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup


class SubdomainDiscoverer:
    """Discovers subdomains for event platforms"""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def discover_subdomains(
        self,
        domain: str,
        methods: Optional[List[str]] = None
    ) -> List[Dict[str, str]]:
        """
        Discover subdomains for a given domain.

        Args:
            domain: Base domain (e.g., 'libcal.com')
            methods: List of methods to use ['ct_logs', 'search_engines', 'common_patterns']
                    If None, uses all methods

        Returns:
            List of dicts with 'subdomain' and 'source' keys
        """
        if methods is None:
            methods = ['ct_logs', 'search_engines', 'common_patterns']

        all_subdomains = set()
        results = []

        # 1. Certificate Transparency Logs
        if 'ct_logs' in methods:
            ct_subdomains = self._query_ct_logs(domain)
            for subdomain in ct_subdomains:
                if subdomain not in all_subdomains:
                    all_subdomains.add(subdomain)
                    results.append({
                        'subdomain': subdomain,
                        'source': 'certificate_transparency'
                    })

        # 2. Search Engine Discovery
        if 'search_engines' in methods:
            search_subdomains = self._search_engine_discovery(domain)
            for subdomain in search_subdomains:
                if subdomain not in all_subdomains:
                    all_subdomains.add(subdomain)
                    results.append({
                        'subdomain': subdomain,
                        'source': 'search_engine'
                    })

        # 3. Common Pattern Testing
        if 'common_patterns' in methods:
            pattern_subdomains = self._test_common_patterns(domain)
            for subdomain in pattern_subdomains:
                if subdomain not in all_subdomains:
                    all_subdomains.add(subdomain)
                    results.append({
                        'subdomain': subdomain,
                        'source': 'common_pattern'
                    })

        return results

    def _query_ct_logs(self, domain: str) -> Set[str]:
        """
        Query Certificate Transparency logs via crt.sh

        Returns:
            Set of discovered subdomains
        """
        subdomains = set()

        try:
            # Query crt.sh JSON API
            url = f"https://crt.sh/?q=%.{domain}&output=json"
            response = self.session.get(url, timeout=self.timeout)

            if response.status_code == 200:
                try:
                    data = response.json()

                    for entry in data:
                        # Extract name_value field which contains the domain
                        name_value = entry.get('name_value', '')

                        # Split by newlines (some entries have multiple domains)
                        for name in name_value.split('\n'):
                            name = name.strip().lower()

                            # Skip wildcards and invalid entries
                            if '*' in name or not name.endswith(domain):
                                continue

                            # Verify it's a valid subdomain
                            if self._is_valid_subdomain(name, domain):
                                subdomains.add(name)

                except Exception as e:
                    print(f"Error parsing CT logs JSON: {e}")

        except Exception as e:
            print(f"Error querying CT logs: {e}")

        return subdomains

    def _search_engine_discovery(self, domain: str) -> Set[str]:
        """
        Discover subdomains via search engines (DuckDuckGo to avoid rate limits)

        Returns:
            Set of discovered subdomains
        """
        subdomains = set()

        # Common search terms for event platforms
        search_terms = [
            f"site:{domain}",
            f"site:{domain} calendar",
            f"site:{domain} events"
        ]

        for search_term in search_terms:
            try:
                # Use DuckDuckGo HTML (no API key needed)
                url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(search_term)}"
                response = self.session.get(url, timeout=self.timeout)

                if response.status_code == 200:
                    # Extract URLs from results
                    urls = re.findall(r'https?://([a-zA-Z0-9\-\.]+\.' + re.escape(domain) + r')', response.text)

                    for url in urls:
                        url = url.lower()
                        if self._is_valid_subdomain(url, domain):
                            subdomains.add(url)

                # Be respectful with rate limits
                time.sleep(1)

            except Exception as e:
                print(f"Error with search engine discovery: {e}")

        return subdomains

    def _test_common_patterns(self, domain: str) -> Set[str]:
        """
        Test common subdomain patterns for library/city platforms

        Returns:
            Set of valid subdomains
        """
        subdomains = set()

        # Common US city names (top 100 by population)
        cities = [
            'boston', 'cambridge', 'somerville', 'brookline', 'newton',
            'nyc', 'newyork', 'manhattan', 'brooklyn', 'queens',
            'chicago', 'losangeles', 'la', 'houston', 'phoenix',
            'philadelphia', 'sanantonio', 'sandiego', 'dallas', 'sanjose',
            'austin', 'jacksonville', 'fortworth', 'columbus', 'charlotte',
            'sanfrancisco', 'sf', 'indianapolis', 'seattle', 'denver',
            'washington', 'dc', 'nashville', 'oklahoma', 'elpaso',
            'boston', 'portland', 'lasvegas', 'detroit', 'memphis',
            'louisville', 'baltimore', 'milwaukee', 'albuquerque', 'tucson',
            'fresno', 'mesa', 'sacramento', 'atlanta', 'kansas',
            'miami', 'raleigh', 'omaha', 'longbeach', 'virginiabeach',
            'oakland', 'minneapolis', 'tulsa', 'tampa', 'arlington',
            'neworleans', 'wichita', 'cleveland', 'bakersfield', 'aurora',
            'anaheim', 'honolulu', 'santaana', 'riverside', 'corpuschristi',
            'lexington', 'stockton', 'stpaul', 'cincinnati', 'pittsburgh',
            'anchorage', 'henderson', 'greensboro', 'plano', 'newark',
            'lincoln', 'orlando', 'irvine', 'toledo', 'jersey',
            'chula', 'buffalo', 'madison', 'reno', 'fortwayne'
        ]

        # Common library/institution prefixes
        prefixes = [
            'library', 'lib', 'publiclibrary', 'public',
            'university', 'college', 'edu',
            'city', 'town', 'county',
            'events', 'calendar'
        ]

        # Generate candidate subdomains
        candidates = []

        # City names
        for city in cities:
            candidates.append(f"{city}.{domain}")

        # City + library
        for city in cities[:20]:  # Limit to top 20 to avoid too many requests
            candidates.append(f"{city}library.{domain}")
            candidates.append(f"{city}pl.{domain}")  # public library

        # Test candidates (with HEAD requests to be fast)
        for candidate in candidates:
            try:
                # Try HTTP and HTTPS
                for protocol in ['https', 'http']:
                    try:
                        url = f"{protocol}://{candidate}"
                        response = self.session.head(url, timeout=5, allow_redirects=True)

                        if response.status_code in [200, 301, 302, 403]:  # 403 means exists but forbidden
                            subdomains.add(candidate)
                            break
                    except:
                        continue

                # Rate limit
                time.sleep(0.1)

            except Exception as e:
                continue

        return subdomains

    def _is_valid_subdomain(self, hostname: str, base_domain: str) -> bool:
        """
        Validate that a hostname is a valid subdomain of base_domain

        Args:
            hostname: The full hostname (e.g., 'boston.libcal.com')
            base_domain: The base domain (e.g., 'libcal.com')

        Returns:
            True if valid subdomain
        """
        hostname = hostname.lower().strip()
        base_domain = base_domain.lower().strip()

        # Must end with base domain
        if not hostname.endswith(base_domain):
            return False

        # Must have at least one subdomain level
        if hostname == base_domain:
            return False

        # Must have valid characters
        if not re.match(r'^[a-z0-9\-\.]+$', hostname):
            return False

        return True


class PlatformDiscoverer:
    """Discovers event pages across multiple platform types"""

    # Known event platform domains
    KNOWN_PLATFORMS = {
        'libcal': ['libcal.com'],
        'bibliocommons': ['bibliocommons.com'],
        'assabet': ['assabetinteractive.com'],
        'eventbrite': ['eventbrite.com'],
        'google_calendar': ['calendar.google.com']
    }

    # Common endpoints to test
    COMMON_ENDPOINTS = [
        '/events',
        '/event',
        '/calendar',
        '/event-calendar',
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
        '/events/feed.ics',
        '/calendar.ics',
        '/events.ics'
    ]

    def __init__(self):
        self.subdomain_discoverer = SubdomainDiscoverer()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def discover_platform_instances(
        self,
        platform_type: str,
        test_endpoints: bool = True
    ) -> List[Dict[str, any]]:
        """
        Discover all instances of a platform type (e.g., all libcal sites)

        Args:
            platform_type: Type of platform ('libcal', 'bibliocommons', etc.)
            test_endpoints: Whether to test common endpoints on each subdomain

        Returns:
            List of dicts with subdomain info and discovered event URLs
        """
        results = []

        if platform_type not in self.KNOWN_PLATFORMS:
            raise ValueError(f"Unknown platform type: {platform_type}")

        # Get base domains for this platform
        base_domains = self.KNOWN_PLATFORMS[platform_type]

        for base_domain in base_domains:
            # Discover subdomains
            subdomains = self.subdomain_discoverer.discover_subdomains(base_domain)

            for subdomain_info in subdomains:
                subdomain = subdomain_info['subdomain']

                result = {
                    'subdomain': subdomain,
                    'platform': platform_type,
                    'discovery_source': subdomain_info['source'],
                    'event_urls': []
                }

                # Test common endpoints if requested
                if test_endpoints:
                    event_urls = self._test_endpoints(subdomain)
                    result['event_urls'] = event_urls

                results.append(result)

        return results

    def _test_endpoints(self, domain: str) -> List[str]:
        """
        Test common endpoints on a domain to find event pages

        Args:
            domain: The domain to test (e.g., 'boston.libcal.com')

        Returns:
            List of valid event URLs
        """
        valid_urls = []

        for endpoint in self.COMMON_ENDPOINTS:
            for protocol in ['https', 'http']:
                url = f"{protocol}://{domain}{endpoint}"

                try:
                    response = self.session.head(url, timeout=5, allow_redirects=True)

                    # Consider it valid if we get a 200
                    if response.status_code == 200:
                        valid_urls.append(url)
                        break  # No need to try http if https worked

                except:
                    continue

                # Rate limit
                time.sleep(0.1)

        return valid_urls


def discover_libcal_sites() -> List[Dict[str, any]]:
    """
    Convenience function to discover all LibCal instances

    Returns:
        List of LibCal sites with event URLs
    """
    discoverer = PlatformDiscoverer()
    return discoverer.discover_platform_instances('libcal', test_endpoints=True)


def discover_bibliocommons_sites() -> List[Dict[str, any]]:
    """
    Convenience function to discover all BiblioCommons instances

    Returns:
        List of BiblioCommons sites with event URLs
    """
    discoverer = PlatformDiscoverer()
    return discoverer.discover_platform_instances('bibliocommons', test_endpoints=True)
