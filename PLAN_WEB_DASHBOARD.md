# Plan: Navigator Web Dashboard

## Goal

Build a Django web interface for running and monitoring the POI discovery pipeline:
- **Run pipeline steps** - Extract, Sync, Discover with progress tracking
- **Monitor status** - Dashboard showing sync rates, discovery coverage, errors
- **Review results** - Use Django Admin (already exists) for curation

## Current State

The Navigator is now a Django app with:
- PostgreSQL database with `POI` model
- Management commands: `poi_extract`, `poi_sync`, `poi_discover`, `poi_stats`
- Streaming OSM extraction using osmium (low memory, ~100MB)
- Django Admin for browsing POIs, filtering by status/category

## Proposed UI

### Dashboard (Home)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  NAVIGATOR DASHBOARD                                            [Admin] [▼] │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────┐  ┌─────────────────────────┐                  │
│  │  POI EXTRACTION         │  │  VENUE SYNC             │                  │
│  │  ═══════════════════    │  │  ═══════════════════    │                  │
│  │  Total: 6,140           │  │  Synced: 4,900 (80%)    │                  │
│  │  Last run: 2 days ago   │  │  Pending: 1,240         │                  │
│  │                         │  │  Failed: 0              │                  │
│  │  [Run Extract]          │  │  [Run Sync]             │                  │
│  └─────────────────────────┘  └─────────────────────────┘                  │
│                                                                             │
│  ┌─────────────────────────┐  ┌─────────────────────────┐                  │
│  │  SOURCE DISCOVERY       │  │  COVERAGE               │                  │
│  │  ═══════════════════    │  │  ═══════════════════    │                  │
│  │  Discovered: 462        │  │  Libraries: 961 (48% w) │                  │
│  │  No events: 126         │  │  Museums: 436 (40% w)   │                  │
│  │  Not started: 312       │  │  Theatres: 220 (50% w)  │                  │
│  │  Skipped: 4,000         │  │  Parks: 4,133 (0% w)    │                  │
│  │                         │  │                         │                  │
│  │  [Run Discovery]        │  │  w = has website        │                  │
│  └─────────────────────────┘  └─────────────────────────┘                  │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  RECENT ACTIVITY                                                            │
│  ───────────────                                                            │
│  ● 10:32 Synced 50 libraries to backend                                    │
│  ● 10:15 Discovered events page for Needham Library                        │
│  ● 09:45 Extracted 6,140 POIs from massachusetts-latest.osm.pbf            │
│  ● Yesterday: Pushed 23 sources to API                                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Pipeline Runner

When clicking "Run Extract/Sync/Discovery", show a modal or page with:
- Category/city filters
- Limit option
- Dry-run checkbox
- Live progress (via WebSocket or polling)
- Log output

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  RUN VENUE SYNC                                                    [×]      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Options:                                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐      │
│  │  Categories: [x] library [x] museum [ ] park [ ] school         │      │
│  │  City:       [_______________] (optional)                        │      │
│  │  Limit:      [100_] (0 = all)                                    │      │
│  │  [ ] Dry run                                                     │      │
│  └──────────────────────────────────────────────────────────────────┘      │
│                                                                             │
│  [Start Sync]                                                               │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  Progress:                                                                  │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 67% [67/100]  │
│                                                                             │
│  Current: Syncing "Needham Free Public Library"...                          │
│                                                                             │
│  Results:                                                                   │
│  Created: 45 | Updated: 12 | Unchanged: 10 | Failed: 0                     │
│                                                                             │
│  Log:                                                                       │
│  ┌──────────────────────────────────────────────────────────────────┐      │
│  │ [10:32:15] Starting sync for 100 POIs                            │      │
│  │ [10:32:16] Synced: Needham Free Public Library (created)         │      │
│  │ [10:32:17] Synced: Newton Free Library (created)                 │      │
│  │ [10:32:18] Synced: Brookline Public Library (unchanged)          │      │
│  └──────────────────────────────────────────────────────────────────┘      │
│                                                                             │
│  [Cancel]                                              [Close when done]    │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Architecture

```
navigator/
├── models.py              # POI, PipelineRun (existing + new)
├── admin.py               # Django Admin (existing)
├── views.py               # Dashboard, pipeline runner views
├── urls.py                # URL routing
├── tasks.py               # Background task functions
├── services/
│   ├── osm_extractor.py   # Streaming extraction (osmium)
│   └── event_page_finder.py
├── templates/navigator/
│   ├── base.html          # Base template with nav
│   ├── dashboard.html     # Main dashboard
│   ├── run_extract.html   # Extract runner
│   ├── run_sync.html      # Sync runner
│   └── run_discover.html  # Discovery runner
└── static/navigator/
    ├── css/
    └── js/
        └── pipeline.js    # Progress polling, form handling
```

## Models

### PipelineRun (new)

Track pipeline executions for history and monitoring.

```python
class PipelineRun(models.Model):
    """Track pipeline step executions."""

    class Step(models.TextChoices):
        EXTRACT = 'extract', 'POI Extraction'
        SYNC = 'sync', 'Venue Sync'
        DISCOVER = 'discover', 'Source Discovery'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    step = models.CharField(max_length=20, choices=Step.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    # Filters used
    categories = models.JSONField(default=list, blank=True)  # ['library', 'museum']
    city_filter = models.CharField(max_length=100, blank=True)
    limit = models.IntegerField(default=0)
    dry_run = models.BooleanField(default=False)

    # Progress
    total_items = models.IntegerField(default=0)
    processed_items = models.IntegerField(default=0)
    current_item = models.CharField(max_length=255, blank=True)

    # Results
    created = models.IntegerField(default=0)
    updated = models.IntegerField(default=0)
    unchanged = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    skipped = models.IntegerField(default=0)

    # Timestamps
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Log output
    log = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']
```

## Implementation Plan

### Phase 1: Dashboard View

1. [ ] Create `navigator/views.py` with dashboard view
2. [ ] Create `navigator/templates/navigator/dashboard.html`
3. [ ] Add URL routing in `navigator/urls.py`
4. [ ] Include navigator URLs in `config/urls.py`
5. [ ] Add basic CSS styling
6. [ ] Query POI stats for dashboard cards

### Phase 2: Pipeline Runner UI

1. [ ] Add `PipelineRun` model and migration
2. [ ] Create runner views (extract, sync, discover)
3. [ ] Create runner templates with forms
4. [ ] Add JavaScript for form submission
5. [ ] Add AJAX endpoint for progress polling

### Phase 3: Background Execution

1. [ ] Refactor management commands to support:
   - Progress callbacks
   - Cancellation
   - PipelineRun updates
2. [ ] Create `tasks.py` with wrapper functions
3. [ ] Run tasks in background thread (or Celery if needed)
4. [ ] Update progress via database

### Phase 4: Polish

1. [ ] Add activity feed to dashboard
2. [ ] Add run history page
3. [ ] Add charts (coverage by category, sync rate over time)
4. [ ] Add error details view for failed items
5. [ ] Mobile-responsive layout

## Tech Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| **Backend** | Django | Already using it |
| **Database** | PostgreSQL | Already using it |
| **Templates** | Django Templates | Simple, no build step |
| **CSS** | Tailwind or Bootstrap | Quick styling |
| **JS** | Vanilla + htmx | Simple interactivity, no build step |
| **Background tasks** | Threading (start), Celery (later) | Keep it simple initially |

## Alternative: htmx for Interactivity

Instead of custom JavaScript, use htmx for:
- Form submission without page reload
- Progress polling with `hx-trigger="every 2s"`
- Partial page updates

```html
<!-- Progress polling with htmx -->
<div hx-get="/navigator/run/123/progress/"
     hx-trigger="every 2s"
     hx-swap="innerHTML">
  <progress value="0" max="100"></progress>
</div>
```

## Open Questions

1. **Background execution**: Threading vs Celery vs Django-Q?
   - Start with threading, migrate to Celery if needed

2. **Real-time updates**: Polling vs WebSocket?
   - Start with polling (simpler), WebSocket later if needed

3. **Authentication**: Require login for pipeline execution?
   - Yes, use Django auth (same as admin)

4. **OSM file upload**: Allow uploading PBF from browser?
   - No, keep on server - files are 300MB+

## Commands Reference

The web UI will wrap these existing commands:

```bash
# Step 1: Extract POIs from OSM
python manage.py poi_extract --pbf massachusetts-latest.osm.pbf --category library --category museum

# Step 2: Sync to backend
python manage.py poi_sync --category library --limit 100

# Step 3: Discover event pages
python manage.py poi_discover --has-website --push-sources

# Stats
python manage.py poi_stats
```

## Migration from Terminal Plan

The original plan proposed a terminal TUI. We're pivoting to Django Web UI because:
- Already have Django with Admin working
- Web UI is more accessible (no terminal needed)
- Easier to share with team members
- Can still use CLI commands directly when needed
- Django Admin handles manual review/curation
