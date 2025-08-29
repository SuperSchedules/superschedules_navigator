"""Test LLM context window requirements for our HTML fixtures."""

import os
import sys
import json

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.llm_link_finder import LLMLinkFinder


class TestLLMContext:
    """Test LLM context window analysis for real website HTML."""
    
    def test_analyze_fixture_context_requirements(self):
        """Analyze context requirements for all fixtures."""
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        finder = LLMLinkFinder()
        
        analysis = finder.analyze_all_fixtures(fixtures_dir)
        
        # Print detailed analysis
        print("\n" + "="*80)
        print("LLM CONTEXT WINDOW ANALYSIS")
        print("="*80)
        
        for filename, model_results in analysis.items():
            print(f"\n📄 {filename}")
            print("-" * 60)
            
            for model, results in model_results.items():
                status = "✅ FITS" if results["fits"] else "❌ TOO LARGE"
                compression = " (compressed)" if results["compressed"] else ""
                
                print(f"  {model:15} | {results['html_tokens']:6,} tokens | {results['utilization']:5.1%} | {status}{compression}")
        
        # Summary statistics
        print(f"\n" + "="*80)
        print("SUMMARY")
        print("="*80)
        
        # Count which fixtures fit in which models
        model_fit_counts = {}
        for filename, model_results in analysis.items():
            for model, results in model_results.items():
                if model not in model_fit_counts:
                    model_fit_counts[model] = {"fits": 0, "total": 0}
                model_fit_counts[model]["total"] += 1
                if results["fits"]:
                    model_fit_counts[model]["fits"] += 1
        
        for model, counts in model_fit_counts.items():
            percentage = counts["fits"] / counts["total"] * 100
            print(f"{model:15} | {counts['fits']}/{counts['total']} fixtures fit ({percentage:4.1f}%)")
        
        # Assert that at least one model can handle all fixtures
        has_universal_model = any(
            counts["fits"] == counts["total"] 
            for counts in model_fit_counts.values()
        )
        
        assert len(analysis) > 0, "Should analyze at least one fixture"
        print(f"\n✅ Analysis complete: {len(analysis)} fixtures analyzed")
        
        if has_universal_model:
            print("✅ Found model(s) that can handle all fixtures")
        else:
            print("⚠️  No single model handles all fixtures - compression needed")
    
    def test_specific_fixture_analysis(self):
        """Detailed analysis of specific fixtures."""
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        
        test_cases = [
            ("gardner_museum_home.html", "https://www.gardnermuseum.org/"),
            ("needham_library_home.html", "https://needhamlibrary.org/"),
            ("wellesley_library_home.html", "https://www.wellesleyfreelibrary.org/")
        ]
        
        print("\n" + "="*80)
        print("DETAILED FIXTURE ANALYSIS")
        print("="*80)
        
        for filename, base_url in test_cases:
            filepath = os.path.join(fixtures_dir, filename)
            
            if not os.path.exists(filepath):
                continue
                
            with open(filepath, 'r', encoding='utf-8') as f:
                html = f.read()
            
            print(f"\n📄 {filename}")
            print(f"🔗 {base_url}")
            print("-" * 60)
            
            # Test different models
            models = ["gemma2:7b", "llama3.1:8b", "mistral:7b"]
            
            for model in models:
                finder = LLMLinkFinder(model)
                result = finder.find_event_links_llm(html, base_url)
                
                fit_info = result["fit_analysis"]
                status = "✅" if result["ready_for_llm"] else "❌"
                compressed = " (compressed)" if result.get("compressed", False) else ""
                
                print(f"  {model:15} | {fit_info['html_tokens']:6,} tokens | {fit_info['utilization']:5.1%} | {status}{compressed}")
    
    def test_compression_effectiveness(self):
        """Test how well HTML compression works."""
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        
        # Test with the largest file (Needham Library)
        filepath = os.path.join(fixtures_dir, "needham_library_home.html")
        
        if not os.path.exists(filepath):
            return  # Skip if file doesn't exist
            
        with open(filepath, 'r', encoding='utf-8') as f:
            original_html = f.read()
        
        finder = LLMLinkFinder("gemma2:7b")  # Small context model
        
        # Test compression
        compressed_html = finder.compress_html_for_llm(original_html)
        
        original_tokens = finder.estimate_tokens(original_html)
        compressed_tokens = finder.estimate_tokens(compressed_html)
        
        compression_ratio = compressed_tokens / original_tokens
        
        print(f"\n📊 COMPRESSION ANALYSIS (needham_library_home.html)")
        print(f"Original:   {original_tokens:,} tokens")
        print(f"Compressed: {compressed_tokens:,} tokens") 
        print(f"Ratio:      {compression_ratio:.2f} ({100-compression_ratio*100:.1f}% reduction)")
        
        # Test if compressed version fits
        base_url = "https://needhamlibrary.org/"
        fit_original = finder.can_fit_in_context(original_html, base_url)
        fit_compressed = finder.can_fit_in_context(compressed_html, base_url)
        
        print(f"Original fits:   {'✅' if fit_original['fits'] else '❌'}")
        print(f"Compressed fits: {'✅' if fit_compressed['fits'] else '❌'}")
        
        # Compression should make it smaller
        assert compressed_tokens < original_tokens, "Compression should reduce token count"
        assert compression_ratio < 1.0, "Compression ratio should be less than 1.0"
    
    def test_prompt_generation(self):
        """Test LLM prompt generation."""
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        filepath = os.path.join(fixtures_dir, "gardner_museum_home.html")
        
        if not os.path.exists(filepath):
            return
            
        with open(filepath, 'r', encoding='utf-8') as f:
            html = f.read()
        
        finder = LLMLinkFinder("gemma2:7b")
        result = finder.find_event_links_llm(html, "https://www.gardnermuseum.org/")
        
        prompt = result["prompt"]
        
        # Should contain key elements
        assert "gardnermuseum.org" in prompt
        assert "event" in prompt.lower()
        assert "calendar" in prompt.lower()
        assert "JSON" in prompt
        assert len(prompt) > 100
        
        print(f"\n📝 PROMPT ANALYSIS")
        print(f"Prompt length: {len(prompt):,} characters")
        print(f"Estimated tokens: {finder.estimate_tokens(prompt):,}")
        print(f"Ready for LLM: {'✅' if result['ready_for_llm'] else '❌'}")
        
        # Print first part of prompt for inspection
        print(f"\nPrompt preview:")
        print(prompt[:500] + "..." if len(prompt) > 500 else prompt)