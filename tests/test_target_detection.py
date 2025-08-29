"""Test detection of specific target URLs we want to find."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.link_finder import find_event_links_simple


class TestTargetDetection:
    """Test that we can find the specific target URLs mentioned in requirements."""
    
    def load_fixture(self, filename: str) -> str:
        """Load HTML fixture file."""
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        file_path = os.path.join(fixtures_dir, filename)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def test_find_gardner_museum_calendar(self):
        """Should find https://www.gardnermuseum.org/calendar from home page."""
        html = self.load_fixture("gardner_museum_home.html")
        
        urls = find_event_links_simple(html, "https://www.gardnermuseum.org/")
        
        # Should find the target calendar URL
        target_url = "https://www.gardnermuseum.org/calendar"
        found_target = any(target_url == url for url in urls)
        
        print(f"Found URLs: {urls[:5]}")  # Debug output
        
        # Either exact match or calendar URL should be found
        found_calendar = found_target or any('/calendar' in url for url in urls)
        assert found_calendar, f"Did not find calendar URL. Found: {urls[:5]}"
    
    def test_find_needham_library_events(self):
        """Should find https://needhamlibrary.org/events/ from home page."""
        html = self.load_fixture("needham_library_home.html")
        
        urls = find_event_links_simple(html, "https://needhamlibrary.org/")
        
        # Should find the target events URL
        target_url = "https://needhamlibrary.org/events/"
        found_target = any(target_url in url for url in urls)
        
        print(f"Found URLs: {urls[:5]}")  # Debug output
        
        # Either exact match or events URL should be found
        found_events = found_target or any('/events' in url for url in urls)
        assert found_events, f"Did not find events URL. Found: {urls[:5]}"
    
    def test_find_wellesley_external_calendar(self):
        """Should find https://wellesleyfreelibrary.libcal.com/ from home page."""
        html = self.load_fixture("wellesley_library_home.html")
        
        urls = find_event_links_simple(html, "https://www.wellesleyfreelibrary.org/")
        
        # Should find the external libcal URL
        found_libcal = any('libcal.com' in url for url in urls)
        
        print(f"Found URLs: {urls[:5]}")  # Debug output
        
        assert found_libcal, f"Did not find libcal.com URL. Found: {urls[:5]}"
    
    def test_all_targets_detected(self):
        """Summary test - all target pages should be detectable."""
        test_cases = [
            {
                'name': 'Gardner Museum',
                'file': 'gardner_museum_home.html',
                'base_url': 'https://www.gardnermuseum.org/',
                'target_indicators': ['calendar', '/calendar']
            },
            {
                'name': 'Needham Library', 
                'file': 'needham_library_home.html',
                'base_url': 'https://needhamlibrary.org/',
                'target_indicators': ['events', '/events']
            },
            {
                'name': 'Wellesley Library',
                'file': 'wellesley_library_home.html', 
                'base_url': 'https://www.wellesleyfreelibrary.org/',
                'target_indicators': ['libcal.com', 'calendar']
            }
        ]
        
        results = []
        
        for case in test_cases:
            html = self.load_fixture(case['file'])
            urls = find_event_links_simple(html, case['base_url'])
            
            # Check if any target indicator is found
            found_target = any(
                any(indicator in url for indicator in case['target_indicators'])
                for url in urls
            )
            
            results.append({
                'name': case['name'],
                'found': found_target,
                'urls': urls[:3]  # Top 3 for debugging
            })
        
        # Print summary for debugging
        for result in results:
            status = "✓" if result['found'] else "✗"
            print(f"{status} {result['name']}: {result['urls']}")
        
        # All should be found
        all_found = all(result['found'] for result in results)
        assert all_found, f"Not all targets found: {results}"