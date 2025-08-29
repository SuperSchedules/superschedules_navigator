# Superschedules Navigator

A focused service for discovering event pages and navigation patterns on websites. Works with the superschedules_collector to provide efficient two-stage event scraping.

## Purpose

Instead of rediscovering site structure on every scrape, the navigator finds event-related URLs once and caches the navigation strategy. The collector then uses this information for efficient periodic extraction.

## Architecture

```
Website → Navigator (discovers event pages) → Django (stores patterns) → Collector (extracts events)
```

## API

### POST /discover

**Input:** Website URL + optional hints
**Output:** Event URLs, navigation patterns, and filtering strategies

```json
{
  "base_url": "https://library.org",
  "target_schema": {
    "type": "events", 
    "required_fields": ["title", "date", "location"],
    "content_indicators": ["calendar", "event", "workshop"]
  }
}
```

**Response:**
```json
{
  "success": true,
  "site_profile": {
    "domain": "library.org",
    "event_urls": [
      "https://library.org/events/upcoming",
      "https://library.org/calendar/2025"
    ],
    "url_patterns": [
      "/events/{category}",
      "/calendar/{year}/{month}"
    ],
    "navigation_strategy": {
      "pagination_type": "next_button",
      "pagination_selector": ".next-page",
      "items_per_page": 20
    },
    "discovered_filters": {
      "date_range": "?start_date={date}",
      "category": "?type={category}",
      "location": "?venue={venue}"
    },
    "skip_patterns": [
      "/about",
      "/staff", 
      "/policies"
    ]
  },
  "confidence": 0.85,
  "processing_time_seconds": 3.2
}
```

## Use Cases

1. **Library/University Events**: Navigate complex site hierarchies to find calendar sections
2. **Municipality Events**: Discover city calendar pages and event categories  
3. **Organization Events**: Find event listings within larger organizational websites

## Integration with Django Backend

Django stores navigation profiles and uses them for efficient periodic scraping:

```python
# Navigate once per week
profile = navigator.discover("https://library.org")
django.store_navigation_profile(profile)

# Extract daily using cached patterns  
for url in profile.event_urls:
    events = collector.extract(url)
    django.store_events(events)
```

## Benefits

- **Efficiency**: Navigate once, extract many times
- **Focus**: Each service has a single clear responsibility
- **Scalability**: Navigation and extraction can be scaled independently  
- **Reliability**: Cached navigation patterns reduce failure points

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
python start_api.py

# Run tests
pytest tests/

# Production server
python start_api.py --prod
```

## Environment Variables

- `OPENAI_API_KEY`: For LLM-powered site analysis
- `API_PORT`: Server port (default: 8002)