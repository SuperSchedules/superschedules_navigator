"""Local LLM-based link detection for event pages."""

import json
import re
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


class LLMLinkFinder:
    """Find event links using local LLM instead of rule-based detection."""
    
    def __init__(self, model_name: str = "gemma2:7b"):
        """
        Initialize with local LLM model.
        
        Args:
            model_name: Ollama model name (e.g., "gemma2:7b", "llama3.1:8b")
        """
        self.model_name = model_name
        self.max_context_tokens = self._get_model_context_limit(model_name)
    
    def _get_model_context_limit(self, model_name: str) -> int:
        """Get approximate context window size for different models."""
        context_limits = {
            "gemma2:7b": 8192,     # 8K context window
            "gemma2:27b": 8192,    # 8K context window  
            "llama3.1:8b": 128000,  # 128K context window
            "llama3.1:70b": 128000, # 128K context window
            "mistral:7b": 32768,   # 32K context window
            "codellama:7b": 16384, # 16K context window
        }
        return context_limits.get(model_name, 8192)  # Default to 8K
    
    def estimate_tokens(self, text: str) -> int:
        """
        Rough token estimation (words * 1.3 for HTML content).
        
        HTML tends to be more token-dense due to markup.
        """
        word_count = len(text.split())
        return int(word_count * 1.3)
    
    def can_fit_in_context(self, html: str, base_url: str) -> Dict[str, any]:
        """
        Check if HTML + prompt can fit in model's context window.
        
        Returns:
            Dict with fit analysis and recommendations
        """
        html_tokens = self.estimate_tokens(html)
        
        # Estimate prompt overhead (instructions + output)
        prompt_overhead = 500  # Rough estimate
        total_tokens = html_tokens + prompt_overhead
        
        fits = total_tokens <= self.max_context_tokens
        
        return {
            "fits": fits,
            "html_tokens": html_tokens,
            "total_tokens": total_tokens,
            "max_tokens": self.max_context_tokens,
            "utilization": total_tokens / self.max_context_tokens,
            "model": self.model_name,
            "base_url": base_url,
            "compression_needed": not fits
        }
    
    def compress_html_for_llm(self, html: str) -> str:
        """
        Compress HTML to fit in context window while preserving link information.
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Remove unnecessary elements that don't contain links
        for tag in soup(['script', 'style', 'meta', 'head', 'noscript']):
            tag.decompose()
        
        # Keep only elements that might contain or lead to event links
        useful_elements = []
        
        # Find navigation areas
        nav_elements = soup.find_all(['nav', 'header', 'menu'])
        for nav in nav_elements:
            useful_elements.append(str(nav))
        
        # Find all links with their surrounding context
        for link in soup.find_all('a', href=True):
            # Get parent context for better understanding
            parent = link.parent
            if parent:
                useful_elements.append(str(parent))
            else:
                useful_elements.append(str(link))
        
        # Create compressed HTML with just the useful parts
        compressed = '<html><body>' + '\n'.join(useful_elements) + '</body></html>'
        
        # Remove excessive whitespace
        compressed = re.sub(r'\s+', ' ', compressed)
        compressed = re.sub(r'>\s+<', '><', compressed)
        
        return compressed
    
    def find_event_links_llm(self, html: str, base_url: str, 
                            compress_if_needed: bool = True) -> Dict:
        """
        Use local LLM to find event/calendar links.
        
        Args:
            html: HTML content
            base_url: Base URL for the site
            compress_if_needed: Whether to compress HTML if it's too large
            
        Returns:
            Dict with analysis results and found links
        """
        # Check if it fits in context
        fit_analysis = self.can_fit_in_context(html, base_url)
        
        # Compress if needed and allowed
        final_html = html
        if not fit_analysis["fits"] and compress_if_needed:
            final_html = self.compress_html_for_llm(html)
            fit_analysis = self.can_fit_in_context(final_html, base_url)
            fit_analysis["was_compressed"] = True
        
        # Create the LLM prompt
        prompt = self._create_llm_prompt(final_html, base_url)
        
        return {
            "fit_analysis": fit_analysis,
            "prompt": prompt,
            "prompt_tokens": self.estimate_tokens(prompt),
            "ready_for_llm": fit_analysis["fits"],
            "compressed": compress_if_needed and "was_compressed" in fit_analysis
        }
    
    def _create_llm_prompt(self, html: str, base_url: str) -> str:
        """Create the prompt for the LLM to find event links."""
        
        domain = urlparse(base_url).netloc
        
        return f"""You are analyzing a website to find links to event and calendar pages.

Website: {base_url}
Domain: {domain}

Look through this HTML and find URLs that likely lead to:
- Event calendars
- Event listings  
- Program schedules
- Activity calendars
- Workshop/class listings

HTML content:
{html}

Return a JSON object with:
{{
    "event_links": [
        {{
            "url": "full URL",
            "text": "link text",
            "confidence": 0.9,
            "reason": "why you think this leads to events"
        }}
    ],
    "external_calendars": [
        {{
            "url": "external calendar service URL", 
            "service": "libcal.com/eventbrite/etc",
            "confidence": 0.95
        }}
    ]
}}

Focus on high-confidence matches. Look for:
- URLs containing "calendar", "events", "programs", "activities"
- Link text mentioning events, calendar, schedule, programs
- External calendar services (libcal.com, eventbrite.com, etc.)

Return only the JSON, no other text."""

    def analyze_all_fixtures(self, fixtures_dir: str) -> Dict[str, Dict]:
        """
        Analyze all HTML fixtures to see which ones fit in different model contexts.
        
        Returns:
            Dict mapping fixture names to analysis results
        """
        import os
        
        results = {}
        
        # Test with different model sizes
        models_to_test = [
            "gemma2:7b",      # 8K context
            "llama3.1:8b",    # 128K context  
            "mistral:7b",     # 32K context
        ]
        
        for filename in os.listdir(fixtures_dir):
            if filename.endswith('.html'):
                filepath = os.path.join(fixtures_dir, filename)
                
                with open(filepath, 'r', encoding='utf-8') as f:
                    html = f.read()
                
                # Determine base URL from filename
                if 'gardner' in filename:
                    base_url = 'https://www.gardnermuseum.org/'
                elif 'needham' in filename:
                    base_url = 'https://needhamlibrary.org/'
                elif 'wellesley' in filename:
                    base_url = 'https://www.wellesleyfreelibrary.org/'
                else:
                    base_url = 'https://example.com/'
                
                fixture_results = {}
                
                for model in models_to_test:
                    finder = LLMLinkFinder(model)
                    analysis = finder.find_event_links_llm(html, base_url)
                    
                    fixture_results[model] = {
                        "fits": analysis["ready_for_llm"],
                        "html_tokens": analysis["fit_analysis"]["html_tokens"],
                        "total_tokens": analysis["fit_analysis"]["total_tokens"],
                        "max_tokens": analysis["fit_analysis"]["max_tokens"],
                        "utilization": analysis["fit_analysis"]["utilization"],
                        "compressed": analysis.get("compressed", False)
                    }
                
                results[filename] = fixture_results
        
        return results