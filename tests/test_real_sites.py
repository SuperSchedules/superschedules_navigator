"""Tests using real website HTML to verify link detection works correctly."""

import os
import sys
import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.link_finder import EventLinkFinder, find_event_links_simple


class TestRealSiteDetection:
    """Test event link detection using real website HTML."""
    
    def load_fixture(self, filename: str) -> str:
        """Load HTML fixture file."""
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        file_path = os.path.join(fixtures_dir, filename)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def test_gardner_museum_calendar_detection(self):
        """Test finding Gardner Museum calendar page."""
        html = self.load_fixture("gardner_museum_home.html")
        finder = EventLinkFinder()
        
        results = finder.find_event_links(html, "https://www.gardnermuseum.org/")
        
        # Should find the /calendar link
        calendar_links = [r for r in results if '/calendar' in r['url']]
        assert len(calendar_links) > 0
        
        # Check that we found the right target URL or similar
        found_urls = [r['url'] for r in results]
        has_calendar = any('calendar' in url for url in found_urls)
        assert has_calendar
        
        # Top result should be high-scoring
        if results:
            assert results[0]['score'] > 2.0
    
    def test_needham_library_events_detection(self):
        """Test finding Needham Library events page."""
        html = self.load_fixture("needham_library_home.html")
        finder = EventLinkFinder()
        
        results = finder.find_event_links(html, "https://needhamlibrary.org/")
        
        # Should find the /events/ link
        events_links = [r for r in results if '/events/' in r['url'] or r['url'].endswith('/events')]
        assert len(events_links) > 0
        
        # Check the target URL specifically
        found_urls = [r['url'] for r in results]
        target_found = any('needhamlibrary.org/events' in url for url in found_urls)
        assert target_found
        
        # Should have events-related link text
        events_texts = [r['text'] for r in results if 'events' in r['text'].lower()]
        assert len(events_texts) > 0
    
    def test_wellesley_library_external_calendar(self):
        """Test finding Wellesley Library external calendar (libcal.com)."""
        html = self.load_fixture("wellesley_library_home.html") 
        finder = EventLinkFinder()
        
        results = finder.find_event_links(html, "https://www.wellesleyfreelibrary.org/")
        
        # Should find the libcal.com external calendar
        libcal_links = [r for r in results if 'libcal.com' in r['url']]
        assert len(libcal_links) > 0
        
        # Should be marked as external
        for link in libcal_links:
            assert link['is_external'] is True
            
        # Should get high score for external calendar domain
        for link in libcal_links:
            assert link['score'] > 3.0  # Should get bonus for external calendar domain
    
    def test_simplified_interface(self):
        """Test the simplified find_event_links_simple interface."""
        html = self.load_fixture("gardner_museum_home.html")
        
        urls = find_event_links_simple(html, "https://www.gardnermuseum.org/")
        
        assert isinstance(urls, list)
        assert len(urls) > 0
        
        # Should find event-related URLs
        has_event_url = any('calendar' in url or 'events' in url for url in urls)
        assert has_event_url
    
    def test_link_scoring_priorities(self):
        """Test that different detection methods get appropriate scores."""
        html = self.load_fixture("needham_library_home.html")
        finder = EventLinkFinder()
        
        results = finder.find_event_links(html, "https://needhamlibrary.org/")
        
        # Links should be sorted by score (highest first)
        for i in range(len(results) - 1):
            assert results[i]['score'] >= results[i + 1]['score']
        
        # Check detection methods are being recorded
        for result in results:
            assert 'detection_method' in result
            assert result['detection_method'] != ''
    
    def test_external_vs_internal_links(self):
        """Test proper classification of external vs internal links."""
        html = self.load_fixture("wellesley_library_home.html")
        finder = EventLinkFinder()
        
        results = finder.find_event_links(html, "https://www.wellesleyfreelibrary.org/")
        
        # Should have both internal and external links
        internal_links = [r for r in results if not r['is_external']]
        external_links = [r for r in results if r['is_external']]
        
        # Wellesley should have external libcal link
        libcal_external = [r for r in external_links if 'libcal.com' in r['url']]
        assert len(libcal_external) > 0
    
    def test_all_sites_find_something(self):
        """Test that we find event-related links on all test sites."""
        test_cases = [
            ("gardner_museum_home.html", "https://www.gardnermuseum.org/"),
            ("needham_library_home.html", "https://needhamlibrary.org/"),
            ("wellesley_library_home.html", "https://www.wellesleyfreelibrary.org/")
        ]
        
        finder = EventLinkFinder()
        
        for filename, base_url in test_cases:
            html = self.load_fixture(filename)
            results = finder.find_event_links(html, base_url)
            
            # Each site should have at least one potential event link
            high_scoring = [r for r in results if r['score'] >= 2.0]
            assert len(high_scoring) > 0, f"No high-scoring links found for {filename}"
    
    def test_detection_methods_coverage(self):
        """Test that different detection methods are working."""
        html = self.load_fixture("gardner_museum_home.html")
        finder = EventLinkFinder()
        
        results = finder.find_event_links(html, "https://www.gardnermuseum.org/")
        
        # Should have various detection methods
        all_methods = set()
        for result in results:
            methods = result['detection_method'].split('+')
            all_methods.update(methods)
        
        # Should detect links using multiple methods
        expected_methods = ['url_keyword', 'link_text', 'url_pattern']
        found_methods = [method for method in expected_methods if method in all_methods]
        assert len(found_methods) >= 2  # Should find at least 2 different methods
    
    def test_skip_non_event_links(self):
        """Test that non-event links get low scores or are filtered out."""
        html = self.load_fixture("needham_library_home.html")
        finder = EventLinkFinder()
        
        results = finder.find_event_links(html, "https://needhamlibrary.org/")
        
        # High-scoring results should not include obvious non-event pages
        high_scoring = [r for r in results if r['score'] >= 3.0]
        
        for result in high_scoring:
            url_lower = result['url'].lower()
            # These should not appear in high-scoring results
            assert 'about' not in url_lower
            assert 'contact' not in url_lower
            assert 'staff' not in url_lower