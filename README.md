# Superschedules Navigator

Event source discovery tool for the Superschedules ecosystem. Finds websites with event calendars using vision-based classification.

## What It Does

1. **Search** - Queries DuckDuckGo for event pages (libraries, parks, town halls, universities, museums)
2. **Screenshot** - Captures each result with Playwright
3. **Classify** - Uses vision LLM (Ollama) to determine if the page has events
4. **Store** - Saves results to PostgreSQL database
5. **Push** - Submits verified URLs to the main Superschedules API for scraping

## Quick Start

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Environment
cp .env.example .env
# Edit .env and add your API token

# Database
createdb navigator
python manage.py migrate
python manage.py createsuperuser

# Run admin
python manage.py runserver
# Visit http://localhost:8000/admin/
```

## Requirements

- Python 3.11+
- PostgreSQL
- Ollama with vision model: `ollama pull minicpm-v`
- osmium (for streaming POI extraction from OpenStreetMap)

## Management Commands

### Import Targets

```bash
# Import towns from CSV
python manage.py import_csv cities.csv --type town

# Import universities
python manage.py import_csv universities.csv --type university

# Import museums
python manage.py import_csv museums.csv --type museum --location "Boston, MA"

# Dry run to preview
python manage.py import_csv data.csv --type museum --dry-run
```

### Run Discovery

```bash
# Discover all pending targets
python manage.py discover

# Discover specific type
python manage.py discover --type museum
python manage.py discover --type university

# Discover specific target
python manage.py discover --target "Harvard"

# Limit number of targets
python manage.py discover --limit 10

# Dry run
python manage.py discover --dry-run

# Use different vision model
python manage.py discover --model llava
```

### Push to API

```bash
# See what would be pushed
python manage.py push --dry-run

# Push all verified event sources
python manage.py push

# Push by type
python manage.py push --type museum

# Push specific target
python manage.py push --target "MIT"

# Re-push already pushed URLs
python manage.py push --include-pushed
```

### Statistics

```bash
python manage.py stats
```

## POI/Venue Discovery Pipeline

Extract venues from OpenStreetMap and sync them to the backend. This creates venues independently of events, enabling search suggestions even without event calendars.

### Step 1: Extract POIs from OpenStreetMap

```bash
# Download the PBF file first
wget https://download.geofabrik.de/north-america/us/massachusetts-latest.osm.pbf

# Extract all POIs from the PBF file
python manage.py poi_extract --pbf massachusetts-latest.osm.pbf

# Extract specific categories only
python manage.py poi_extract --pbf massachusetts-latest.osm.pbf --category library --category museum

# Dry run (preview only)
python manage.py poi_extract --pbf massachusetts-latest.osm.pbf --dry-run
```

### Step 2: Sync Venues to Backend API

```bash
# Sync all pending POIs to backend as Venues
python manage.py poi_sync

# Sync specific category
python manage.py poi_sync --category library

# Sync specific city
python manage.py poi_sync --city Needham

# Re-sync already synced (update data)
python manage.py poi_sync --resync

# Limit batch size
python manage.py poi_sync --limit 100

# Dry run
python manage.py poi_sync --dry-run
```

### Step 3: Discover Event Pages

```bash
# Discover event pages for synced POIs
python manage.py poi_discover

# Specific categories (skip parks, etc.)
python manage.py poi_discover --category library --category museum

# Only POIs with OSM website (faster)
python manage.py poi_discover --has-website

# Also push discovered sources to backend
python manage.py poi_discover --push-sources

# Limit and rate-limit
python manage.py poi_discover --limit 50 --delay 2.0

# Dry run
python manage.py poi_discover --dry-run
```

### Step 4: Check POI Statistics

```bash
python manage.py poi_stats
```

### Typical POI Workflow

```bash
# 1. Download OSM data
wget https://download.geofabrik.de/north-america/us/massachusetts-latest.osm.pbf

# 2. Extract libraries and museums
python manage.py poi_extract --pbf massachusetts-latest.osm.pbf --category library --category museum

# 3. Sync to backend (requires SUPERSCHEDULES_API_TOKEN in .env)
python manage.py poi_sync

# 4. Find event pages and create sources
python manage.py poi_discover --has-website --push-sources
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required for pushing to API
SUPERSCHEDULES_API_TOKEN=your-token-here

# Optional
SUPERSCHEDULES_API_URL=https://api.eventzombie.com
VISION_MODEL=minicpm-v
OLLAMA_URL=http://localhost:11434
```

## Target Types

| Type | Example | What it searches for |
|------|---------|---------------------|
| `town` | Newton, MA | Libraries, parks, town hall, community events |
| `university` | MIT | Student activities, arts, campus events |
| `museum` | MFA Boston | Exhibitions, programs, tours |
| `library` | Boston Public Library | Events, programs, workshops |
| `venue` | TD Garden | Concerts, sports, shows |

## Project Structure

```
├── manage.py              # Django CLI
├── config/                # Django settings
├── navigator/             # Main app
│   ├── models.py          # Target, Discovery, POI models
│   ├── admin.py           # Admin interface
│   ├── services/          # OSM extractor, event page finder
│   └── management/commands/
│       ├── discover.py    # Run vision-based discovery
│       ├── push.py        # Push to API
│       ├── import_csv.py  # Import targets
│       ├── import_json.py # Import legacy JSON
│       ├── stats.py       # Show statistics
│       ├── poi_extract.py # Extract POIs from OSM
│       ├── poi_sync.py    # Sync POIs to backend as Venues
│       ├── poi_discover.py # Find event pages for POIs
│       └── poi_stats.py   # POI statistics
├── .env                   # Environment variables (not in git)
├── .env.example           # Template for .env
└── requirements.txt
```

## Admin Interface

Browse targets, discoveries, and statistics at http://localhost:8000/admin/

- **Targets** - View/edit search targets, filter by type and status
- **Discoveries** - View discovered URLs, filter by has_events, pushed status
- **POIs** - View extracted OpenStreetMap venues, filter by category, sync status
- **Runs** - Track discovery session statistics

## Related Repos

- [superschedules](../superschedules) - Main Django backend
- [superschedules_collector](../superschedules_collector) - Event extraction
- [superschedules_frontend](../superschedules_frontend) - React UI

## License

MIT
