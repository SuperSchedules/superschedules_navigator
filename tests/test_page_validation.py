"""Test that discovered pages actually contain events."""

import os
import sys
import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.page_validator import EventPageValidator, validate_event_urls_simple


class TestPageValidation:
    """Test event page validation using real HTML fixtures."""
    
    def load_fixture(self, filename: str) -> str:
        """Load HTML fixture file."""
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        file_path = os.path.join(fixtures_dir, filename)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def test_validator_initialization(self):
        """Test validator can be created and configured."""
        validator = EventPageValidator(timeout=5)
        assert validator.timeout == 5
        assert validator.session is not None
    
    def test_analyze_known_event_pages(self):
        """Test validation of pages we know contain events."""
        validator = EventPageValidator()
        
        # Test pages that should have events
        event_pages = [
            ("gardner_museum_calendar.html", "Gardner Museum calendar", True),
        ]
        
        # Test pages that have iframe calendars (should now be detected and followed)
        iframe_pages = [
            ("needham_library_events.html", "Needham Library events (with iframe)", True),
        ]
        
        all_pages = event_pages + iframe_pages
        
        for filename, description, should_have_events in all_pages:
            html = self.load_fixture(filename)
            soup = BeautifulSoup(html, 'html.parser')
            
            target_schema = {
                "content_indicators": ["event", "calendar", "workshop", "program"],
                "required_fields": ["title", "date", "location"]
            }
            
            analysis = validator._analyze_page_content(soup, target_schema)
            has_events = validator._determine_has_events(analysis)
            
            print(f"\n📄 {description}")
            print(f"   Score: {analysis['validation_score']:.1f}")
            print(f"   Estimated events: {analysis['event_count_estimate']}")
            print(f"   Expected: {'✅' if should_have_events else '❌'}")
            print(f"   Actual: {'✅' if has_events else '❌'}")
            print(f"   Details: {analysis['validation_details']}")
            
            # Check against expected result
            if should_have_events:
                assert has_events, f"{description} should be detected as having events"
                assert analysis['validation_score'] > 5.0, f"{description} should have good validation score"
            else:
                assert not has_events, f"{description} should NOT be detected as having events (iframe/redirect)"
    
    def test_analyze_non_event_pages(self):
        """Test that non-event pages are correctly identified."""
        # Create a mock non-event page
        non_event_html = """
        <html>
            <body>
                <h1>About Our Organization</h1>
                <p>We are a wonderful organization founded in 1950.</p>
                <p>Contact us at info@example.com for more information.</p>
                <p>Our staff includes many dedicated professionals.</p>
                <nav>
                    <a href="/about">About</a>
                    <a href="/staff">Staff</a>
                    <a href="/contact">Contact</a>
                </nav>
            </body>
        </html>
        """
        
        validator = EventPageValidator()
        soup = BeautifulSoup(non_event_html, 'html.parser')
        
        target_schema = {
            "content_indicators": ["event", "calendar", "workshop"],
            "required_fields": ["title", "date", "location"]
        }
        
        analysis = validator._analyze_page_content(soup, target_schema)
        has_events = validator._determine_has_events(analysis)
        
        print(f"\n📄 Non-event page test")
        print(f"   Score: {analysis['validation_score']:.1f}")
        print(f"   Has events: {'✅' if has_events else '❌'}")
        
        # Should NOT be detected as having events
        assert not has_events, "Non-event page should not be detected as having events"
        assert analysis['validation_score'] < 5.0, "Non-event page should have low score"
    
    def test_structured_data_detection(self):
        """Test detection of JSON-LD structured events."""
        structured_event_html = """
        <html>
            <head>
                <script type="application/ld+json">
                {
                    "@context": "http://schema.org",
                    "@type": "Event",
                    "name": "Concert in the Park",
                    "startDate": "2025-06-15T19:00:00",
                    "location": "Central Park",
                    "description": "Outdoor summer concert"
                }
                </script>
            </head>
            <body>
                <h1>Concert in the Park</h1>
                <p>Join us June 15th at 7pm for music in Central Park.</p>
            </body>
        </html>
        """
        
        validator = EventPageValidator()
        soup = BeautifulSoup(structured_event_html, 'html.parser')
        
        target_schema = {"content_indicators": ["event", "concert"]}
        
        analysis = validator._analyze_page_content(soup, target_schema)
        has_events = validator._determine_has_events(analysis)
        
        print(f"\n📄 Structured data test")
        print(f"   Structured data found: {analysis['validation_details']['structured_data_found']}")
        print(f"   Score: {analysis['validation_score']:.1f}")
        print(f"   Has events: {'✅' if has_events else '❌'}")
        
        # Should definitely be detected due to structured data
        assert has_events, "Page with JSON-LD events should be detected"
        assert analysis['validation_details']['structured_data_found'], "Should detect structured data"
        assert analysis['validation_score'] >= 10.0, "Structured data should give high score"
    
    def test_validation_scoring_criteria(self):
        """Test different validation scoring criteria."""
        test_cases = [
            {
                "name": "High date/time content",
                "html": """
                <div>
                    <p>Event on Jan 15, 2025 at 7:00 PM</p>
                    <p>Workshop on Feb 20, 2025 at 2:00 PM</p>
                    <p>Meeting on Mar 10, 2025 at 10:00 AM</p>
                    <div class="event">Music Performance</div>
                    <div class="event">Art Workshop</div>
                </div>
                """,
                "should_have_events": True
            },
            {
                "name": "Calendar widget",
                "html": """
                <div class="calendar">
                    <div class="fc-event">Event 1</div>
                    <div class="fc-event">Event 2</div>
                </div>
                """,
                "should_have_events": True
            },
            {
                "name": "Just keywords, no dates",
                "html": """
                <p>We host many events and have a calendar.</p>
                <p>Events are fun and our calendar is updated regularly.</p>
                """,
                "should_have_events": False
            }
        ]
        
        validator = EventPageValidator()
        target_schema = {"content_indicators": ["event", "calendar", "workshop"]}
        
        for case in test_cases:
            soup = BeautifulSoup(case["html"], 'html.parser')
            analysis = validator._analyze_page_content(soup, target_schema)
            has_events = validator._determine_has_events(analysis)
            
            print(f"\n📄 {case['name']}")
            print(f"   Score: {analysis['validation_score']:.1f}")
            print(f"   Expected: {'✅' if case['should_have_events'] else '❌'}")
            print(f"   Actual: {'✅' if has_events else '❌'}")
            
            assert has_events == case["should_have_events"], f"{case['name']} validation failed"
    
    def test_false_positive_prevention(self):
        """Test that we don't get false positives on ambiguous pages."""
        # Page that mentions events but doesn't actually list them
        ambiguous_html = """
        <html>
            <body>
                <h1>Welcome to Our Library</h1>
                <p>We host events throughout the year. Check our calendar for upcoming activities.</p>
                <p>Our event space can be rented for private functions.</p>
                <p>The calendar shows all library hours and holiday closures.</p>
                <a href="/events">View Events</a>
                <a href="/calendar">Library Calendar</a>
            </body>
        </html>
        """
        
        validator = EventPageValidator()
        soup = BeautifulSoup(ambiguous_html, 'html.parser')
        
        target_schema = {"content_indicators": ["event", "calendar"]}
        
        analysis = validator._analyze_page_content(soup, target_schema)
        has_events = validator._determine_has_events(analysis)
        
        print(f"\n📄 Ambiguous page test")
        print(f"   Score: {analysis['validation_score']:.1f}")
        print(f"   Content indicators: {analysis['validation_details']['content_indicators_found']}")
        print(f"   Date patterns: {analysis['validation_details']['date_patterns_found']}")
        print(f"   Has events: {'✅' if has_events else '❌'}")
        
        # Should NOT detect as having events (just mentions them)
        assert not has_events, "Ambiguous page should not be detected as having events"


# Add BeautifulSoup import at module level
from bs4 import BeautifulSoup