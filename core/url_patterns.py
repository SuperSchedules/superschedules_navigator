"""URL pattern extraction and pagination detection utilities."""

import re
from typing import Dict, List
from urllib.parse import urlparse, parse_qs
from collections import Counter

import requests
from bs4 import BeautifulSoup


def extract_url_patterns(urls: List[str]) -> List[str]:
    """
    Extract common URL patterns from a list of URLs.
    
    Args:
        urls: List of event URLs
        
    Returns:
        List of URL patterns with variables like /events/{category}
    """
    if not urls:
        return []
    
    patterns = []
    
    # Group URLs by their path structure
    path_structures = {}
    for url in urls:
        parsed = urlparse(url)
        path_parts = [part for part in parsed.path.split('/') if part]
        
        # Create a structure key based on path length and non-numeric parts
        structure_key = []
        for part in path_parts:
            if part.isdigit():
                structure_key.append('{id}')
            elif re.match(r'\d{4}-\d{2}-\d{2}', part):  # Date pattern
                structure_key.append('{date}')  
            elif re.match(r'^\d{4}$', part):  # Year (4 digits exactly)
                structure_key.append('{year}')
            elif re.match(r'^\d{1,2}$', part):  # Month/day (1-2 digits exactly)
                structure_key.append('{month}')
            else:
                structure_key.append(part)
                
        structure_tuple = tuple(structure_key)
        
        if structure_tuple not in path_structures:
            path_structures[structure_tuple] = []
        path_structures[structure_tuple].append(url)
    
    # Convert structures to patterns
    for structure, structure_urls in path_structures.items():
        if len(structure_urls) >= 2:  # Only patterns that appear multiple times
            pattern = '/' + '/'.join(structure)
            patterns.append(pattern)
        elif len(structure_urls) == 1 and len(structure) > 1:
            # Single URL but complex path - might be a valid pattern
            pattern = '/' + '/'.join(structure)
            patterns.append(pattern)
    
    return patterns


def detect_pagination(sample_url: str) -> Dict:
    """
    Analyze a sample URL to detect pagination patterns.
    
    Args:
        sample_url: A sample event page URL to analyze
        
    Returns:
        Dictionary with pagination information
    """
    try:
        response = requests.get(sample_url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; SuperschedulesNavigator/1.0)"
        })
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        pagination_info = {
            "type": None,
            "selector": None,
            "items_per_page": None
        }
        
        # Look for common pagination patterns
        
        # Next/Previous buttons
        next_selectors = [
            'a[rel="next"]',
            '.next', '.page-next', 
            'a:contains("Next")', 'a:contains("→")'
        ]
        
        for selector in next_selectors:
            if soup.select(selector):
                pagination_info.update({
                    "type": "next_button",
                    "selector": selector
                })
                break
        
        # Numbered pagination
        page_number_selectors = [
            '.pagination a',
            '.page-numbers a',
            '.pager a'
        ]
        
        for selector in page_number_selectors:
            elements = soup.select(selector)
            if len(elements) > 2:  # More than just prev/next
                pagination_info.update({
                    "type": "numbered",
                    "selector": selector
                })
                break
        
        # Try to estimate items per page by counting event-like elements
        event_selectors = [
            '.event', '.calendar-item', '[class*="event"]',
            '.listing-item', '.item', 'article'
        ]
        
        for selector in event_selectors:
            elements = soup.select(selector)
            if 5 <= len(elements) <= 50:  # Reasonable range for events per page
                pagination_info["items_per_page"] = len(elements)
                break
        
        return pagination_info
        
    except Exception as e:
        print(f"Pagination detection failed for {sample_url}: {e}")
        return {
            "type": None,
            "selector": None,
            "items_per_page": None
        }


def analyze_url_parameters(urls: List[str]) -> Dict[str, List[str]]:
    """
    Analyze URL parameters to discover common filters.
    
    Args:
        urls: List of URLs to analyze
        
    Returns:
        Dictionary of parameter names and their common values
    """
    param_analysis = {}
    
    for url in urls:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        
        for param_name, param_values in params.items():
            if param_name not in param_analysis:
                param_analysis[param_name] = []
            param_analysis[param_name].extend(param_values)
    
    # Summarize common parameters
    common_params = {}
    for param_name, values in param_analysis.items():
        value_counts = Counter(values)
        # Keep parameters that appear multiple times
        if len(value_counts) > 1:
            common_params[param_name] = list(value_counts.keys())
    
    return common_params