# Discovery Code Fixes Plan

## Overview

Fixes for issues found in the POI discovery pipeline (`local_url_update_worker.py` and related services).

---

## Issue 1: Legacy `discovery__isnull=True` Constraint

**Location**: `local_url_update_worker.py:217`

**Problem**: Checking for a legacy FK that's never set in the new flow. Confusing and might prevent re-processing.

**Fix**: Remove the constraint from `get_next_poi()`.

```python
# Before
poi = POI.objects.filter(
    source_status=POI.SourceStatus.NOT_STARTED,
    discovery__isnull=True,  # Remove this
)

# After
poi = POI.objects.filter(
    source_status=POI.SourceStatus.NOT_STARTED,
)
```

**Risk**: Low - this is dead code cleanup.

---

## Issue 2: O(n) Loop in `find_existing_events_url()` Strategy 2

**Location**: `local_url_update_worker.py:175-190`

**Problem**: Iterates through ALL POIs with events_url to find domain match. Slow and potentially incorrect.

**Fix**: Replace Python loop with DB query. Also reconsider if domain matching is even a good strategy.

```python
# Before - O(n) Python loop
for other in similar_poi.iterator():
    if urlparse(other.events_url).netloc.lower() == poi_domain:
        return other.events_url

# After - DB query (if we keep this strategy)
# Actually, maybe REMOVE Strategy 2 entirely - it's too aggressive
```

**Recommendation**: Remove Strategy 2. Domain matching is risky - a university with `mit.edu` website shouldn't share events URLs between athletics dept and music dept.

**Risk**: Medium - might reduce reuse, but improves correctness.

---

## Issue 3: Website Reuse Ignores `osm_website`

**Location**: `local_url_update_worker.py:138-144`

**Problem**: Only checks `discovered_website`, ignores POIs that have `osm_website`.

**Fix**: Check both `osm_website` and `discovered_website` when looking for reusable websites.

```python
# Before
similar_poi = POI.objects.filter(
    city__iexact=poi.city,
    category=poi.category,
    website_status=POI.WebsiteStatus.FOUND,
).exclude(discovered_website='')

# After - also consider POIs with osm_website
similar_poi = POI.objects.filter(
    city__iexact=poi.city,
    category=poi.category,
).filter(
    Q(osm_website__isnull=False) & ~Q(osm_website='') |
    Q(discovered_website__isnull=False) & ~Q(discovered_website='')
).first()

if similar_poi:
    return similar_poi.website  # Uses property that returns osm_website or discovered_website
```

**Risk**: Low - expands reuse correctly.

---

## Issue 4: Aggressive Events URL Sharing

**Location**: `local_url_update_worker.py:161-173`

**Problem**: All parks in same city share one events_url. Wrong for state/federal/private parks.

**Fix**: Add smarter matching logic:
1. Check `osm_operator` field - only share if same operator
2. For parks, check if operator contains "DCR", "NPS", "state" → don't share with city parks
3. Maybe use website domain as a grouping key instead of city

```python
def find_existing_events_url(poi: POI) -> str | None:
    if poi.category not in SHARED_WEBSITE_CATEGORIES:
        return None

    if not poi.city:
        return None

    # Build filter for similar POIs
    filters = {
        'city__iexact': poi.city,
        'category': poi.category,
        'source_status': POI.SourceStatus.DISCOVERED,
    }

    # If POI has an operator, only match same operator
    if poi.osm_operator:
        filters['osm_operator__iexact'] = poi.osm_operator
    else:
        # If no operator, only match other POIs without operator
        filters['osm_operator'] = ''

    similar_poi = POI.objects.filter(**filters).exclude(
        events_url=''
    ).exclude(id=poi.id).first()

    if similar_poi:
        return similar_poi.events_url

    return None
```

**Risk**: Medium - reduces reuse but improves correctness.

---

## Issue 5: No Web Search Fallback for Events Pages

**Location**: `navigator/services/event_page_finder.py:66-74`

**Problem**: If direct paths and link crawling fail, gives up. No web search fallback.

**Fix**: Add Strategy 3 - web search for "{POI name} events {city} MA"

```python
# Strategy 3: Web search for events page
result = await _search_for_events_page(poi)
if result:
    return result
```

**Risk**: Low - adds capability without breaking existing logic.

**Note**: This is lower priority since most official sites have /events or links.

---

## Implementation Order

1. **Issue 1** - Remove legacy constraint (5 min, low risk)
2. **Issue 2** - Remove Strategy 2 domain matching (10 min, medium risk)
3. **Issue 3** - Include osm_website in reuse (15 min, low risk)
4. **Issue 4** - Smart operator-based sharing (30 min, medium risk)
5. **Issue 5** - Web search fallback (45 min, low priority)

---

## Testing

After each fix:
1. Run worker on small batch: `python manage.py shell` → manual test
2. Check logs for reuse behavior
3. Spot-check discovered URLs for correctness

---

## Questions for Greg

1. Should we completely remove Strategy 2 (domain matching) or fix it?
2. For Issue 4, is operator-based matching good enough, or do we need more signals?
3. Is Issue 5 (web search fallback) worth the complexity?
