"""Test iframe calendar detection and following."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.page_validator import EventPageValidator
from bs4 import BeautifulSoup


class TestIframeDetection:
    """Test detection and following of iframe calendars."""
    
    def load_fixture(self, filename: str) -> str:
        """Load HTML fixture file."""
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        file_path = os.path.join(fixtures_dir, filename)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def test_detect_calendar_iframes(self):
        """Test detection of calendar iframes in HTML."""
        validator = EventPageValidator()
        
        # Test HTML with calendar iframe
        iframe_html = """
        <html>
            <body>
                <h1>Event Calendar</h1>
                <p>Check out our events below:</p>
                <iframe src="https://needhamma.assabetinteractive.com/calendar/" 
                        width="100%" height="600" frameborder="0"></iframe>
                <p>Contact us for more information.</p>
            </body>
        </html>
        """
        
        soup = BeautifulSoup(iframe_html, 'html.parser')
        iframe_urls = validator._find_calendar_iframes(soup)
        
        print(f"Found iframe URLs: {iframe_urls}")
        
        assert len(iframe_urls) == 1
        assert "needhamma.assabetinteractive.com/calendar" in iframe_urls[0]
    
    def test_real_needham_library_iframe_detection(self):
        """Test iframe detection on real Needham Library page."""
        html = self.load_fixture("needham_library_events.html")
        validator = EventPageValidator()
        
        soup = BeautifulSoup(html, 'html.parser')
        iframe_urls = validator._find_calendar_iframes(soup)
        
        print(f"\nNeedham Library iframe detection:")
        print(f"Found {len(iframe_urls)} iframe URLs:")
        for url in iframe_urls:
            print(f"  - {url}")
        
        # Should find the assabetinteractive calendar
        assert len(iframe_urls) >= 1
        found_assabet = any("assabetinteractive.com" in url for url in iframe_urls)
        assert found_assabet, "Should find assabetinteractive calendar iframe"
    
    def test_iframe_scoring_in_validation(self):
        """Test that iframe calendars get high validation scores."""
        validator = EventPageValidator()
        
        iframe_html = """
        <html>
            <body>
                <h1>Our Events</h1>
                <iframe src="https://external-calendar.libcal.com/events" width="100%" height="500"></iframe>
            </body>
        </html>
        """
        
        soup = BeautifulSoup(iframe_html, 'html.parser')
        target_schema = {"content_indicators": ["event", "calendar"]}
        
        analysis = validator._analyze_page_content(soup, target_schema)
        has_events = validator._determine_has_events(analysis)
        
        print(f"\nIframe scoring test:")
        print(f"Score: {analysis['validation_score']:.1f}")
        print(f"Iframe calendars found: {analysis['validation_details']['iframe_calendars_found']}")
        print(f"Has events: {'✅' if has_events else '❌'}")
        
        # Should get high score due to iframe calendar
        assert analysis['validation_score'] >= 8.0, "Iframe calendar should give high score"
        assert has_events, "Page with iframe calendar should be validated as having events"
        assert len(analysis['validation_details']['iframe_calendars_found']) == 1
    
    def test_non_calendar_iframes_ignored(self):
        """Test that non-calendar iframes are ignored."""
        validator = EventPageValidator()
        
        non_calendar_html = """
        <html>
            <body>
                <h1>Welcome</h1>
                <iframe src="https://www.youtube.com/embed/video123" width="560" height="315"></iframe>
                <iframe src="https://maps.google.com/embed?address=123+Main+St" width="400" height="300"></iframe>
                <iframe src="https://example.com/contact-form" width="100%" height="400"></iframe>
            </body>
        </html>
        """
        
        soup = BeautifulSoup(non_calendar_html, 'html.parser')
        iframe_urls = validator._find_calendar_iframes(soup)
        
        print(f"\nNon-calendar iframe test:")
        print(f"Found {len(iframe_urls)} calendar iframe URLs: {iframe_urls}")
        
        # Should not find any calendar iframes
        assert len(iframe_urls) == 0, "Should not detect non-calendar iframes as calendar content"
    
    def test_various_calendar_services(self):
        """Test detection of different calendar service iframes."""
        validator = EventPageValidator()
        
        calendar_services_html = """
        <html>
            <body>
                <iframe src="https://example.libcal.com/calendar"></iframe>
                <iframe src="https://calendar.google.com/embed?src=example"></iframe>
                <iframe src="https://outlook.live.com/calendar/embed"></iframe>
                <iframe src="https://eventbrite.com/e/event-123"></iframe>
                <iframe src="https://library.assabetinteractive.com/schedule"></iframe>
            </body>
        </html>
        """
        
        soup = BeautifulSoup(calendar_services_html, 'html.parser')
        iframe_urls = validator._find_calendar_iframes(soup)
        
        print(f"\nCalendar services test:")
        print(f"Found {len(iframe_urls)} calendar services:")
        for url in iframe_urls:
            print(f"  - {url}")
        
        # Should detect all calendar service iframes
        expected_services = ["libcal.com", "calendar.google", "outlook.live", "eventbrite.com", "assabetinteractive"]
        
        for service in expected_services:
            found_service = any(service in url for url in iframe_urls)
            assert found_service, f"Should detect {service} calendar service"
        
        assert len(iframe_urls) == 5, "Should find all 5 calendar service iframes"
    
    def test_full_validation_with_iframe_following(self):
        """Test complete validation flow that follows iframe URLs."""
        # This test would require actual HTTP requests, so we'll mock it
        validator = EventPageValidator()
        
        # Simulate a page that has an iframe to a calendar
        main_page_html = """
        <html>
            <body>
                <h1>Library Events</h1>
                <iframe src="https://mockservice.com/calendar" width="100%" height="600"></iframe>
            </body>
        </html>
        """
        
        soup = BeautifulSoup(main_page_html, 'html.parser')
        target_schema = {"content_indicators": ["event", "calendar"]}
        
        # Test the analysis (without actual HTTP request)
        analysis = validator._analyze_page_content(soup, target_schema)
        iframe_urls = validator._find_calendar_iframes(soup)
        
        print(f"\nFull validation test:")
        print(f"Main page score: {analysis['validation_score']:.1f}")
        print(f"Iframe URLs to follow: {iframe_urls}")
        print(f"Should validate: {'✅' if validator._determine_has_events(analysis) else '❌'}")
        
        assert len(iframe_urls) == 1
        assert "mockservice.com/calendar" in iframe_urls[0]
        assert validator._determine_has_events(analysis), "Page with iframe should validate as having events"