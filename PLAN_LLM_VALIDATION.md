# LLM URL Validation - Implementation Plan

## Context

We've added LLM-based text validation to filter garbage URLs during discovery. This document captures the current state and remaining work.

## What's Been Done

### 1. LLM Text Validation Added
- **website_finder.py**: `validate_with_llm_text()` validates discovered websites
- **event_page_finder.py**: `validate_events_page_with_llm()` validates event URLs
- Category-specific prompts (parks accept town .gov sites, townhalls accept main gov site)
- `/no_think` flag added for qwen3 speed optimization

### 2. Model Upgraded
- Changed from `llama3.2:3b` (2GB) → `qwen3:8b` (5.2GB)
- With `/no_think`: ~2.1s per validation (faster than qwen2.5:7b)
- Better at catching garbage (kith.com, biblegateway.com, zhihu.com)

### 3. Test Scripts Created
- `test_llm_validation.py` - Manual testing of individual URLs
  ```bash
  .venv/bin/python test_llm_validation.py <url> [name] [category] [city]
  .venv/bin/python test_llm_validation.py --events <url> [name] [category] [city]
  ```
- `validate_existing.py` - Batch validation of existing discovered URLs
  ```bash
  .venv/bin/python validate_existing.py websites --limit 20
  .venv/bin/python validate_existing.py events --limit 20 --category park
  ```

### 4. Garbage Domains Blocked
Added to BlockedDomain model:
- nces.ed.gov (federal education stats)
- educationbug.org, schoolbug.org, trueschools.com (school directories)
- jalopyjournal.com, flickr.com, opencorporates.com (unrelated sites)
- zhihu.com (Chinese Q&A), topoquest.com (map viewer)

### 5. POIs Reset for Re-discovery
- ~114 POIs with known garbage domains were reset (discovered_website cleared, website_status=NOT_STARTED)

## Remaining Work

### 1. Create Management Command for Batch Validation + Cleanup
Need a proper `manage.py validate_urls` command that:
- Validates all discovered websites with LLM
- Auto-blocks garbage domains found
- Resets invalid POIs for re-discovery
- Generates report of what was cleaned up

### 2. School Sites - Be Conservative
Schools have lots of garbage (directories, wrong schools, etc.). Options:
- Skip schools entirely in discovery
- Require higher confidence threshold for schools
- Only accept .edu or .k12.ma.us domains for schools

### 3. Run Full Validation on Existing URLs
Current stats:
- ~6,800 POIs with discovered_website
- ~3,100 POIs with events_url (source_status=DISCOVERED)
- Batch validation shows ~40-50% may be garbage

### 4. Reset Remaining Garbage POIs
Still need to reset POIs with recently found garbage domains:
```python
# Domains to block and reset:
zhihu.com (9 POIs)
topoquest.com (3 POIs)
# Plus any new ones found during full validation
```

### 5. Edge Cases to Handle
- Combined town departments (e.g., Hamilton-Wenham rec for Wenham parks) - currently false positives
- myrec.com domains - these ARE valid (official rec dept platforms)
- .org library/museum sites - valid if they're the actual organization

## Validation Results Summary

### Correctly Rejected (garbage)
- dictionary.com, Wikipedia, encyclopedias
- School directories (trueschools, nces.ed.gov, greatschools)
- News/aggregators (patch.com, eventbrite)
- Completely wrong sites (zhihu.com, kith.com, biblegateway.com)
- Meeting agendas (gov AgendaCenter pages)

### Correctly Accepted
- Town .gov websites for parks/townhalls
- Official organization websites (.org for libraries/museums)
- myrec.com recreation department platforms
- School district websites (.k12.ma.us)

### Known False Positives
- Combined town departments (Hamilton-Wenham for Wenham) - city name mismatch
- Some valid sites being too strictly rejected

## Commands Reference

```bash
# Test individual URL
.venv/bin/python test_llm_validation.py "https://example.com" "POI Name" category City

# Test events URL
.venv/bin/python test_llm_validation.py --events "https://example.com/calendar" "POI Name" category City

# Batch validate websites
.venv/bin/python validate_existing.py websites --limit 50
.venv/bin/python validate_existing.py websites --category school --limit 30

# Batch validate events URLs
.venv/bin/python validate_existing.py events --limit 50

# Check blocked domains
.venv/bin/python manage.py shell -c "from navigator.models import BlockedDomain; print(BlockedDomain.objects.count())"

# Reset POIs with specific domain
.venv/bin/python manage.py shell -c "
from navigator.models import POI
POI.objects.filter(discovered_website__contains='garbage.com').update(
    discovered_website='',
    website_status=POI.WebsiteStatus.NOT_STARTED,
    events_url='',
    source_status=POI.SourceStatus.NOT_STARTED
)
"
```

## Files Modified

- `navigator/services/website_finder.py` - Added validate_with_llm_text(), using qwen3:8b
- `navigator/services/event_page_finder.py` - Added validate_events_page_with_llm(), integrated into discovery flow
- `test_llm_validation.py` - Manual test script (new)
- `validate_existing.py` - Batch validation script (new)
