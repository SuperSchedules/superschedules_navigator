"""Tests for the search API endpoints."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


class TestSearchLocationEndpoint:
    """Tests for POST /search/location endpoint."""

    @patch('api.main._search_by_location_sync')
    def test_search_by_location_success(self, mock_search):
        """Test successful location search."""
        # Mock return value
        mock_search.return_value = {
            'total_event_urls': 5,
            'event_urls': [
                'https://boston.gov/events',
                'https://bpl.org/calendar',
                'https://museums.boston.gov/events',
                'https://bostonparks.org/calendar',
                'https://boston.edu/events'
            ],
            'domains_found': 5,
            'domains': ['boston.gov', 'bpl.org', 'museums.boston.gov', 'bostonparks.org', 'boston.edu'],
            'search_results': [],
            'endpoint_results': []
        }

        # Make request
        response = client.post(
            '/search/location',
            json={
                'location': 'boston',
                'test_endpoints': True
            }
        )

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['query_type'] == 'location'
        assert data['total_event_urls'] == 5
        assert len(data['event_urls']) == 5
        assert data['domains_found'] == 5
        assert 'boston.gov' in data['domains']

    @patch('api.main._search_by_location_sync')
    def test_search_by_city_state_success(self, mock_search):
        """Test successful city + state search."""
        mock_search.return_value = {
            'city': 'Boston',
            'state': 'MA',
            'total_event_urls': 3,
            'event_urls': [
                'https://boston.gov/events',
                'https://ma.gov/events/boston',
                'https://boston.edu/calendar'
            ],
            'domains_found': 3,
            'domains': ['boston.gov', 'ma.gov', 'boston.edu'],
            'search_results': [],
            'endpoint_results': []
        }

        response = client.post(
            '/search/location',
            json={
                'location': 'Boston',
                'city': 'Boston',
                'state': 'MA',
                'test_endpoints': True
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['query_type'] == 'city_state'
        assert data['total_event_urls'] == 3

    @patch('api.main._search_by_location_sync')
    def test_search_location_with_org_types(self, mock_search):
        """Test search with specific organization types."""
        mock_search.return_value = {
            'total_event_urls': 2,
            'event_urls': [
                'https://bostonlibrary.org/events',
                'https://cambridgelibrary.org/calendar'
            ],
            'domains_found': 2,
            'domains': ['bostonlibrary.org', 'cambridgelibrary.org'],
            'search_results': [],
            'endpoint_results': []
        }

        response = client.post(
            '/search/location',
            json={
                'location': 'Boston',
                'org_types': ['library'],
                'test_endpoints': True
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert len(data['event_urls']) == 2

    @patch('api.main._search_by_location_sync')
    def test_search_location_error(self, mock_search):
        """Test error handling in location search."""
        mock_search.return_value = {
            'error': 'Network error'
        }

        response = client.post(
            '/search/location',
            json={
                'location': 'boston'
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'Network error' in data['error_message']
        assert data['total_event_urls'] == 0


class TestSearchPlatformEndpoint:
    """Tests for POST /search/platform endpoint."""

    @patch('api.main._search_by_platform_sync')
    def test_search_platform_libcal_success(self, mock_search):
        """Test successful LibCal platform discovery."""
        mock_search.return_value = {
            'results': [
                {
                    'subdomain': 'boston.libcal.com',
                    'platform': 'libcal',
                    'event_urls': ['https://boston.libcal.com/calendar']
                },
                {
                    'subdomain': 'cambridge.libcal.com',
                    'platform': 'libcal',
                    'event_urls': ['https://cambridge.libcal.com/events']
                }
            ],
            'event_urls': [
                'https://boston.libcal.com/calendar',
                'https://cambridge.libcal.com/events'
            ],
            'domains': ['boston.libcal.com', 'cambridge.libcal.com'],
            'total_instances': 2
        }

        response = client.post(
            '/search/platform',
            json={
                'platform_type': 'libcal',
                'test_endpoints': True
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['query_type'] == 'platform'
        assert data['total_event_urls'] == 2
        assert data['domains_found'] == 2
        assert 'libcal' in data['metadata']['platform_type']
        assert data['metadata']['total_instances'] == 2

    @patch('api.main._search_by_platform_sync')
    def test_search_platform_without_endpoint_testing(self, mock_search):
        """Test platform discovery without endpoint testing."""
        mock_search.return_value = {
            'results': [
                {
                    'subdomain': 'example.libcal.com',
                    'platform': 'libcal',
                    'event_urls': []
                }
            ],
            'event_urls': [],
            'domains': ['example.libcal.com'],
            'total_instances': 1
        }

        response = client.post(
            '/search/platform',
            json={
                'platform_type': 'libcal',
                'test_endpoints': False
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['total_event_urls'] == 0
        assert data['domains_found'] == 1

    @patch('api.main._search_by_platform_sync')
    def test_search_platform_bibliocommons(self, mock_search):
        """Test BiblioCommons platform discovery."""
        mock_search.return_value = {
            'results': [
                {
                    'subdomain': 'seattle.bibliocommons.com',
                    'platform': 'bibliocommons',
                    'event_urls': ['https://seattle.bibliocommons.com/events']
                }
            ],
            'event_urls': ['https://seattle.bibliocommons.com/events'],
            'domains': ['seattle.bibliocommons.com'],
            'total_instances': 1
        }

        response = client.post(
            '/search/platform',
            json={
                'platform_type': 'bibliocommons',
                'test_endpoints': True
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'bibliocommons' in data['metadata']['platform_type']

    @patch('api.main._search_by_platform_sync')
    def test_search_platform_error(self, mock_search):
        """Test error handling in platform search."""
        mock_search.return_value = {
            'error': 'Unknown platform type'
        }

        response = client.post(
            '/search/platform',
            json={
                'platform_type': 'invalid_platform'
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'Unknown platform type' in data['error_message']
        assert data['total_event_urls'] == 0


class TestSearchIntegration:
    """Integration tests for search functionality."""

    def test_root_shows_search_endpoints(self):
        """Test that root endpoint lists search endpoints."""
        response = client.get('/')

        assert response.status_code == 200
        data = response.json()
        assert 'endpoints' in data
        assert 'search_location' in data['endpoints']
        assert 'search_platform' in data['endpoints']

    @patch('api.main._search_by_location_sync')
    def test_search_location_no_endpoints(self, mock_search):
        """Test location search without endpoint testing."""
        mock_search.return_value = {
            'total_event_urls': 0,
            'event_urls': [],
            'domains_found': 0,
            'domains': [],
            'search_results': [],
            'endpoint_results': []
        }

        response = client.post(
            '/search/location',
            json={
                'location': 'nowhere',
                'test_endpoints': False
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['total_event_urls'] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
