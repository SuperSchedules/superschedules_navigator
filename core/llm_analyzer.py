"""LLM-powered analysis of websites for event navigation patterns."""

import os
from typing import Dict, List
import json

from openai import OpenAI


def get_openai_client() -> OpenAI:
    """Get OpenAI client, handling various API key locations."""
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        try:
            with open(os.path.expanduser("~/.secret_keys"), "r") as f:
                for line in f:
                    if line.startswith("OPENAI_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    
    if not api_key:
        raise ValueError("OpenAI API key not found in environment or ~/.secret_keys")
    
    return OpenAI(api_key=api_key)


def analyze_site_for_events(base_url: str, sample_event_urls: List[str]) -> Dict:
    """
    Use LLM to analyze a website and discover event navigation patterns.
    
    Args:
        base_url: Base URL of the website
        sample_event_urls: Sample URLs that contain events
        
    Returns:
        Dictionary with discovered patterns and filters
    """
    try:
        client = get_openai_client()
        
        analysis_prompt = f"""
Analyze this website for event navigation patterns:

Base URL: {base_url}
Sample event URLs:
{chr(10).join(f"- {url}" for url in sample_event_urls)}

Based on these URLs, identify:
1. URL patterns for finding events (use {{variable}} for dynamic parts)
2. Likely filter parameters (date, category, location, etc.)
3. Confidence in your analysis (0.0-1.0)

Focus on practical patterns that would help systematically discover event pages.

Return JSON only:
{{
    "url_patterns": ["/events/{{category}}", "/calendar/{{year}}/{{month}}"],
    "filters": {{
        "date_range": "?start_date={{date}}",
        "category": "?type={{category}}",
        "location": "?venue={{location}}"
    }},
    "confidence": 0.85,
    "notes": "Brief explanation of discovered patterns"
}}
"""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": analysis_prompt}],
            temperature=0.1,
            max_tokens=500
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Parse JSON response
        try:
            result = json.loads(result_text)
            return result
        except json.JSONDecodeError:
            # Fallback if JSON parsing fails
            return {
                "url_patterns": [],
                "filters": {},
                "confidence": 0.3,
                "notes": "Failed to parse LLM response"
            }
            
    except Exception as e:
        print(f"LLM analysis failed: {e}")
        return {
            "url_patterns": [],
            "filters": {},
            "confidence": 0.0,
            "notes": f"Analysis failed: {str(e)}"
        }