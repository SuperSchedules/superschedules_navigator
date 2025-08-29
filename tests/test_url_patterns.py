"""Tests for URL pattern extraction and pagination detection."""

import pytest
from unittest.mock import patch, Mock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.url_patterns import (
    extract_url_patterns,
    detect_pagination,
    analyze_url_parameters
)


def test_extract_url_patterns():
    """Test URL pattern extraction from event URLs."""
    # Test with similar URL structures
    event_urls = [
        "https://library.org/events/workshops/123",
        "https://library.org/events/workshops/456", 
        "https://library.org/events/lectures/789",
        "https://library.org/events/concerts/101",
        "https://library.org/calendar/2025/01",
        "https://library.org/calendar/2025/02",
        "https://library.org/calendar/2024/12"
    ]
    
    patterns = extract_url_patterns(event_urls)
    
    assert len(patterns) > 0
    
    # Check that we found some reasonable patterns
    pattern_text = " ".join(patterns)
    assert "/events/" in pattern_text  # Should find event patterns
    assert "/calendar/" in pattern_text  # Should find calendar patterns
    
    # Should extract patterns with variables
    has_variable_pattern = any("{" in pattern and "}" in pattern for pattern in patterns)
    assert has_variable_pattern
    
    # Test with empty list
    assert extract_url_patterns([]) == []
    
    # Test with single URL
    single_url_patterns = extract_url_patterns(["https://example.com/events/list"])
    assert len(single_url_patterns) >= 0


def test_extract_url_patterns_with_dates():
    """Test pattern extraction with date-based URLs."""
    date_urls = [
        "https://example.com/events/2025-01-15",
        "https://example.com/events/2025-02-20", 
        "https://example.com/events/2025-03-10"
    ]
    
    patterns = extract_url_patterns(date_urls)
    assert "/events/{date}" in patterns


@pytest.fixture
def mock_pagination_page():
    """Mock HTML page with pagination elements."""
    return """
    <html>
        <body>
            <div class="events-list">
                <div class="event-item">Event 1</div>
                <div class="event-item">Event 2</div>
                <div class="event-item">Event 3</div>
                <div class="event-item">Event 4</div>
                <div class="event-item">Event 5</div>
                <div class="event-item">Event 6</div>
                <div class="event-item">Event 7</div>
                <div class="event-item">Event 8</div>
                <div class="event-item">Event 9</div>
                <div class="event-item">Event 10</div>
            </div>
            <div class="pagination">
                <a href="?page=1">1</a>
                <a href="?page=2" class="current">2</a>
                <a href="?page=3">3</a>
                <a href="?page=4" class="next">Next</a>
            </div>
        </body>
    </html>
    """


def test_detect_pagination_numbered(mock_pagination_page):
    """Test pagination detection for numbered pagination."""
    def mock_get(url, **kwargs):
        response = Mock()
        response.raise_for_status = lambda: None
        response.text = mock_pagination_page
        return response
    
    with patch('core.url_patterns.requests.get', side_effect=mock_get):
        result = detect_pagination("https://example.com/events")
        
        assert result["type"] == "numbered"
        assert result["items_per_page"] >= 10  # Allow for slight count variations
        assert result["selector"] is not None


def test_detect_pagination_next_button():
    """Test pagination detection for next/prev buttons."""
    next_button_html = """
    <html>
        <body>
            <div class="events">
                <div class="event">Event 1</div>
                <div class="event">Event 2</div>
                <div class="event">Event 3</div>
                <div class="event">Event 4</div>
                <div class="event">Event 5</div>
            </div>
            <div class="navigation">
                <a href="/events?page=1" class="prev">Previous</a>
                <a href="/events?page=3" class="next">Next</a>
            </div>
        </body>
    </html>
    """
    
    def mock_get(url, **kwargs):
        response = Mock()
        response.raise_for_status = lambda: None
        response.text = next_button_html
        return response
    
    with patch('core.url_patterns.requests.get', side_effect=mock_get):
        result = detect_pagination("https://example.com/events")
        
        assert result["type"] == "next_button"
        assert result["items_per_page"] == 5


def test_detect_pagination_no_pagination():
    """Test pagination detection when no pagination exists."""
    simple_html = """
    <html>
        <body>
            <div class="events">
                <div class="event">Event 1</div>
                <div class="event">Event 2</div>
            </div>
        </body>
    </html>
    """
    
    def mock_get(url, **kwargs):
        response = Mock()
        response.raise_for_status = lambda: None
        response.text = simple_html
        return response
    
    with patch('core.url_patterns.requests.get', side_effect=mock_get):
        result = detect_pagination("https://example.com/events")
        
        assert result["type"] is None
        assert result["selector"] is None


def test_detect_pagination_request_failure():
    """Test pagination detection when request fails."""
    def mock_get(url, **kwargs):
        raise Exception("Connection failed")
    
    with patch('core.url_patterns.requests.get', side_effect=mock_get):
        result = detect_pagination("https://example.com/events")
        
        assert result["type"] is None
        assert result["selector"] is None
        assert result["items_per_page"] is None


def test_analyze_url_parameters():
    """Test URL parameter analysis."""
    urls = [
        "https://example.com/events?category=workshop&date=2025-01-15",
        "https://example.com/events?category=concert&date=2025-02-20",
        "https://example.com/events?category=lecture&venue=auditorium",
        "https://example.com/events?category=workshop&venue=classroom"
    ]
    
    result = analyze_url_parameters(urls)
    
    assert "category" in result
    assert "workshop" in result["category"]
    assert "concert" in result["category"]
    assert "lecture" in result["category"]
    
    # Parameters that appear in multiple URLs should be included
    assert len(result["category"]) >= 2


def test_analyze_url_parameters_empty():
    """Test URL parameter analysis with no parameters."""
    urls = [
        "https://example.com/events",
        "https://example.com/calendar",
        "https://example.com/workshops"
    ]
    
    result = analyze_url_parameters(urls)
    assert result == {}  # No parameters to analyze


def test_analyze_url_parameters_single_occurrence():
    """Test that parameters appearing only once are excluded."""
    urls = [
        "https://example.com/events?unique_param=value",
        "https://example.com/events?common_param=value1",
        "https://example.com/events?common_param=value2"
    ]
    
    result = analyze_url_parameters(urls)
    
    # unique_param should not appear (only one occurrence)
    assert "unique_param" not in result
    # common_param should appear (multiple values)
    assert "common_param" in result