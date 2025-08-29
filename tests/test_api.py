"""Tests for the navigation discovery API."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.main import app

client = TestClient(app)


def test_health_endpoint():
    """Test the health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert "version" in data


def test_root_endpoint():
    """Test the root endpoint returns API info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "Superschedules Navigator" in data["name"]
    assert "docs" in data
    assert "health" in data


@pytest.fixture
def mock_navigation_result():
    """Mock navigation discovery result."""
    return {
        "event_urls": [
            "https://library.org/events/upcoming",
            "https://library.org/calendar/2025/01"
        ],
        "url_patterns": [
            "/events/{category}",
            "/calendar/{year}/{month}"
        ],
        "pagination_type": "next_button",
        "pagination_selector": ".next-page",
        "items_per_page": 20,
        "discovered_filters": {
            "date_range": "?start_date={date}",
            "category": "?type={category}"
        },
        "skip_patterns": ["/about", "/staff"],
        "confidence": 0.85
    }


def test_discover_endpoint_success(mock_navigation_result):
    """Test successful navigation discovery."""
    with patch("api.main._discover_sync") as mock_discover:
        mock_discover.return_value = mock_navigation_result
        
        response = client.post("/discover", json={
            "base_url": "https://library.org",
            "target_schema": {
                "type": "events",
                "required_fields": ["title", "date", "location"],
                "content_indicators": ["calendar", "event", "workshop"]
            },
            "max_depth": 2
        })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert data["confidence"] == 0.85
    assert len(data["site_profile"]["event_urls"]) == 2
    assert data["site_profile"]["domain"] == "library.org"
    assert data["site_profile"]["navigation_strategy"]["pagination_type"] == "next_button"
    assert "date_range" in data["site_profile"]["discovered_filters"]
    assert "/about" in data["site_profile"]["skip_patterns"]
    assert "processing_time_seconds" in data


def test_discover_endpoint_minimal_request():
    """Test discovery with minimal request parameters."""
    with patch("api.main._discover_sync") as mock_discover:
        mock_discover.return_value = {
            "event_urls": ["https://example.com/events"],
            "url_patterns": ["/events"],
            "pagination_type": None,
            "pagination_selector": None,
            "items_per_page": None,
            "discovered_filters": {},
            "skip_patterns": [],
            "confidence": 0.5
        }
        
        response = client.post("/discover", json={
            "base_url": "https://example.com"
        })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert data["site_profile"]["domain"] == "example.com"
    assert len(data["site_profile"]["event_urls"]) == 1


def test_discover_endpoint_error():
    """Test discovery when an error occurs."""
    with patch("api.main._discover_sync") as mock_discover:
        mock_discover.return_value = {"error": "Connection timeout"}
        
        response = client.post("/discover", json={
            "base_url": "https://invalid-site.com"
        })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is False
    assert data["confidence"] == 0.0
    assert data["error_message"] == "Connection timeout"
    assert data["site_profile"] is None


def test_discover_endpoint_invalid_url():
    """Test discovery with missing URL."""
    response = client.post("/discover", json={})
    
    assert response.status_code == 422  # Validation error


def test_discover_endpoint_with_all_options():
    """Test discovery with all optional parameters."""
    with patch("api.main._discover_sync") as mock_discover:
        mock_discover.return_value = {
            "event_urls": ["https://university.edu/events"],
            "url_patterns": ["/events/{dept}"],
            "pagination_type": "numbered",
            "pagination_selector": ".page-numbers a",
            "items_per_page": 15,
            "discovered_filters": {"department": "?dept={dept}"},
            "skip_patterns": ["/admin"],
            "confidence": 0.9
        }
        
        response = client.post("/discover", json={
            "base_url": "https://university.edu",
            "target_schema": {
                "type": "academic_events",
                "required_fields": ["title", "date", "department"],
                "content_indicators": ["seminar", "lecture", "conference"]
            },
            "max_depth": 4,
            "follow_external_links": True
        })
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success"] is True
    assert data["confidence"] == 0.9
    
    # Verify the sync function was called with correct parameters
    mock_discover.assert_called_once()
    call_args = mock_discover.call_args[0]
    assert call_args[0] == "https://university.edu"  # base_url
    assert call_args[2] == 4  # max_depth
    assert call_args[3] is True  # follow_external_links


def test_liveness_endpoint():
    """Test liveness check endpoint."""
    response = client.get("/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"


def test_readiness_endpoint():
    """Test readiness check endpoint."""
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"