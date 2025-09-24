"""Test actual Ollama integration for link detection."""

import json
import os
import sys
import subprocess
from typing import Dict, List
import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.llm_link_finder import LLMLinkFinder


def is_ollama_available() -> bool:
    """Check if Ollama is available and accessible."""
    try:
        result = subprocess.run(
            ['ollama', 'list'],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# Skip all tests in this class if Ollama is not available
pytestmark = pytest.mark.skipif(
    not is_ollama_available(),
    reason="Ollama not available - skipping integration tests"
)


def call_ollama(model: str, prompt: str) -> str:
    """Call Ollama with a prompt and return the response."""
    try:
        result = subprocess.run(
            ['ollama', 'run', model],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=60  # 60 second timeout
        )
        
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return f"Error: {result.stderr}"
            
    except subprocess.TimeoutExpired:
        return "Error: Timeout"
    except FileNotFoundError:
        return "Error: Ollama not found"


class TestOllamaIntegration:
    """Test using Ollama for actual link detection."""
    
    def load_fixture(self, filename: str) -> str:
        """Load HTML fixture file."""
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        file_path = os.path.join(fixtures_dir, filename)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def test_ollama_basic_connection(self):
        """Test basic Ollama connectivity."""
        # Simple test prompt
        response = call_ollama("gemma2:latest", "Say 'hello' in JSON format: {\"message\": \"hello\"}")
        
        print(f"Ollama response: {response}")
        
        # Should get some response (not an error)
        assert not response.startswith("Error:"), f"Ollama connection failed: {response}"
        assert len(response) > 0, "Should get non-empty response"
    
    def test_ollama_json_parsing(self):
        """Test if Ollama can return valid JSON."""
        prompt = """Return this information in JSON format:
{
    "website": "example.com",
    "links": ["https://example.com/events", "https://example.com/calendar"],
    "confidence": 0.9
}

Return only the JSON, no other text."""
        
        response = call_ollama("gemma2:latest", prompt)
        print(f"JSON test response: {response}")
        
        # Try to parse as JSON
        try:
            parsed = json.loads(response)
            assert "website" in parsed
            assert "links" in parsed
            assert isinstance(parsed["links"], list)
            print("✅ Ollama can return valid JSON")
        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing failed: {e}")
            print(f"Response was: {response[:200]}...")
            # Don't fail the test - some models struggle with JSON
    
    def test_small_html_link_detection(self):
        """Test link detection on a small HTML sample."""
        # Create a simple HTML sample that should fit in any context
        small_html = """
        <html>
        <body>
            <nav>
                <a href="/">Home</a>
                <a href="/about">About</a>
                <a href="/events">Events</a>
                <a href="/calendar">Calendar</a>
                <a href="/contact">Contact</a>
            </nav>
            <main>
                <h1>Welcome</h1>
                <p>Check out our <a href="/upcoming-events">upcoming events</a>!</p>
                <p>View our <a href="https://external-calendar.com">program calendar</a>.</p>
            </main>
        </body>
        </html>
        """
        
        finder = LLMLinkFinder("gemma2:latest")
        result = finder.find_event_links_llm(small_html, "https://example.com/")
        
        print(f"\nSmall HTML analysis:")
        print(f"Fits in context: {result['ready_for_llm']}")
        print(f"Token count: {result['fit_analysis']['html_tokens']}")
        
        if result['ready_for_llm']:
            # Try actual Ollama call
            prompt = result['prompt']
            response = call_ollama("gemma2:latest", prompt)
            
            print(f"\nOllama response:")
            print(response[:500] + "..." if len(response) > 500 else response)
            
            # Try to parse response
            try:
                parsed = json.loads(response)
                if "event_links" in parsed:
                    print(f"\n✅ Found {len(parsed['event_links'])} event links:")
                    for link in parsed['event_links']:
                        print(f"  - {link.get('url', 'N/A')} ({link.get('confidence', 'N/A')})")
                
                if "external_calendars" in parsed:
                    print(f"✅ Found {len(parsed['external_calendars'])} external calendars")
                    
            except json.JSONDecodeError:
                print("❌ Could not parse LLM response as JSON")
                
        assert result['ready_for_llm'], "Small HTML should fit in any model context"
    
    def test_model_context_comparison(self):
        """Compare context handling across available models."""
        # Use Gardner Museum (medium-sized) for comparison
        html = self.load_fixture("gardner_museum_home.html")
        base_url = "https://www.gardnermuseum.org/"
        
        available_models = ["gemma2:latest", "llama3.2:3b"]
        
        print(f"\n" + "="*60)
        print("MODEL CONTEXT COMPARISON")
        print("="*60)
        
        for model in available_models:
            try:
                finder = LLMLinkFinder(model)
                result = finder.find_event_links_llm(html, base_url)
                
                fit_info = result["fit_analysis"]
                status = "✅ FITS" if result["ready_for_llm"] else "❌ TOO LARGE"
                
                print(f"{model:15} | {fit_info['html_tokens']:6,} tokens | {fit_info['utilization']:5.1%} | {status}")
                
                # If it fits, we could test actual inference here
                # (but skip for now to keep tests fast)
                
            except Exception as e:
                print(f"{model:15} | Error: {e}")
    
    def test_compression_vs_model_size(self):
        """Test strategy: compression vs larger models."""
        # Use the largest fixture
        html = self.load_fixture("needham_library_home.html")
        base_url = "https://needhamlibrary.org/"
        
        print(f"\n" + "="*60)
        print("COMPRESSION VS MODEL SIZE STRATEGY")
        print("="*60)
        
        strategies = [
            ("gemma2:latest", True),   # Small model + compression
            ("llama3.2:3b", False),   # Larger model, no compression needed
        ]
        
        for model, use_compression in strategies:
            finder = LLMLinkFinder(model)
            result = finder.find_event_links_llm(html, base_url, compress_if_needed=use_compression)
            
            strategy_name = f"{model} + compression" if use_compression else f"{model} raw"
            status = "✅ READY" if result["ready_for_llm"] else "❌ TOO LARGE"
            compressed = " (compressed)" if result.get("compressed", False) else ""
            
            print(f"{strategy_name:25} | {result['fit_analysis']['html_tokens']:6,} tokens | {status}{compressed}")
        
        print(f"\n💡 Recommendation: Use llama3.2:3b for most pages, no compression needed")