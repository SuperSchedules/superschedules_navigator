"""Tests for the core navigation discovery logic."""

import pytest
from unittest.mock import patch, Mock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.navigator import (
    discover_site_navigation,
    _page_contains_events,
    _link_looks_like_events,
    _should_skip_url
)
from bs4 import BeautifulSoup


@pytest.fixture
def mock_requests_get():
    """Mock requests.get for testing."""
    def _mock_get(url, **kwargs):
        response = Mock()
        response.raise_for_status = lambda: None
        
        if "events" in url:
            response.text = """
            <html>
                <body>
                    <h1>Upcoming Events</h1>
                    <div class="event-item">
                        <h3>Workshop on Jan 15, 2025</h3>
                        <p>Join us for a photography workshop</p>
                    </div>
                    <div class="event-item">
                        <h3>Concert on Feb 20, 2025</h3>
                        <p>Evening concert in the main hall</p>
                    </div>
                    <a href="/events/workshops">Workshops</a>
                    <a href="/events/concerts">Concerts</a>
                    <a href="/about">About Us</a>
                </body>
            </html>
            """
        elif "calendar" in url:
            response.text = """
            <html>
                <body>
                    <h1>Calendar</h1>
                    <div class="calendar-event">
                        <h3>Meeting on 2025-01-10</h3>
                        <p>Board meeting at 2:00 PM</p>
                    </div>
                    <a href="/calendar/2025/01">January 2025</a>
                    <a href="/calendar/2025/02">February 2025</a>
                </body>
            </html>
            """
        else:
            response.text = """
            <html>
                <body>
                    <h1>Home Page</h1>
                    <p>Welcome to our website</p>
                    <a href="/events">Events</a>
                    <a href="/calendar">Calendar</a>
                    <a href="/about">About</a>
                    <a href="/contact">Contact</a>
                </body>
            </html>
            """
        return response
    
    return _mock_get


def test_discover_site_navigation_basic(mock_requests_get):
    """Test basic site navigation discovery."""
    with patch('core.navigator.requests.get', side_effect=mock_requests_get):
        with patch('core.navigator.analyze_site_for_events') as mock_llm:
            mock_llm.return_value = {
                "filters": {"category": "?type={category}"},
                "confidence": 0.8
            }
            
            result = discover_site_navigation("https://example.com", max_depth=2)
            
            assert "event_urls" in result
            assert "url_patterns" in result
            assert "confidence" in result
            assert result["confidence"] > 0.0


def test_page_contains_events():
    """Test event detection in page content."""
    # Page with events
    event_html = """
    <html>
        <body>
            <h1>Upcoming Events</h1>
            <div>Workshop on January 15, 2025 at 2:00 PM</div>
            <div>Concert on 2025-02-20 in the auditorium</div>
            <div>Meeting scheduled for Feb 10</div>
        </body>
    </html>
    """
    
    soup = BeautifulSoup(event_html, 'html.parser')
    target_schema = {
        "content_indicators": ["event", "workshop", "concert", "meeting"]
    }
    
    assert _page_contains_events(soup, target_schema) is True
    
    # Page without events
    non_event_html = """
    <html>
        <body>
            <h1>About Us</h1>
            <p>We are a great organization.</p>
            <p>Contact us for more information.</p>
        </body>
    </html>
    """
    
    soup = BeautifulSoup(non_event_html, 'html.parser')
    assert _page_contains_events(soup, target_schema) is False


def test_link_looks_like_events():
    """Test link classification for event relevance."""
    target_schema = {
        "content_indicators": ["event", "calendar", "workshop"]
    }
    
    # Event-related links
    event_link_html = '<a href="/events/workshops">Workshop Schedule</a>'
    link = BeautifulSoup(event_link_html, 'html.parser').find('a')
    assert _link_looks_like_events(link, target_schema) is True
    
    calendar_link_html = '<a href="/calendar">Calendar</a>'
    link = BeautifulSoup(calendar_link_html, 'html.parser').find('a')
    assert _link_looks_like_events(link, target_schema) is True
    
    # Non-event links
    about_link_html = '<a href="/about">About Us</a>'
    link = BeautifulSoup(about_link_html, 'html.parser').find('a')
    assert _link_looks_like_events(link, target_schema) is False


def test_should_skip_url():
    """Test URL skip logic."""
    # URLs that should be skipped
    skip_urls = [
        ("https://example.com/about", "About Us"),
        ("https://example.com/contact", "Contact"),
        ("https://example.com/staff/directory", "Staff Directory"),
        ("https://example.com/document.pdf", "Download PDF"),
        ("https://example.com/admin/login", "Admin Login"),
    ]
    
    for url, text in skip_urls:
        assert _should_skip_url(url, text) is True
    
    # URLs that should not be skipped
    keep_urls = [
        ("https://example.com/events", "Events"),
        ("https://example.com/calendar", "Calendar"),
        ("https://example.com/programs", "Programs"),
        ("https://example.com/workshops", "Workshops"),
    ]
    
    for url, text in keep_urls:
        assert _should_skip_url(url, text) is False


def test_discover_with_custom_schema(mock_requests_get):
    """Test discovery with custom target schema."""
    with patch('core.navigator.requests.get', side_effect=mock_requests_get):
        with patch('core.navigator.analyze_site_for_events') as mock_llm:
            mock_llm.return_value = {
                "filters": {"type": "?category={type}"},
                "confidence": 0.7
            }
            
            custom_schema = {
                "type": "academic_events",
                "required_fields": ["title", "date", "department"],
                "content_indicators": ["seminar", "lecture", "conference", "workshop"]
            }
            
            result = discover_site_navigation(
                "https://university.edu", 
                target_schema=custom_schema,
                max_depth=2
            )
            
            assert result is not None
            assert "confidence" in result


def test_discover_with_follow_external_links(mock_requests_get):
    """Test discovery with external link following enabled."""
    with patch('core.navigator.requests.get', side_effect=mock_requests_get):
        with patch('core.navigator.analyze_site_for_events') as mock_llm:
            mock_llm.return_value = {
                "filters": {},
                "confidence": 0.6
            }
            
            result = discover_site_navigation(
                "https://example.com",
                max_depth=1,
                follow_external_links=True
            )
            
            assert result is not None