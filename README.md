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
│   ├── models.py          # Target, Discovery models
│   ├── admin.py           # Admin interface
│   └── management/commands/
│       ├── discover.py    # Run discovery
│       ├── push.py        # Push to API
│       ├── import_csv.py  # Import targets
│       ├── import_json.py # Import legacy JSON
│       └── stats.py       # Show statistics
├── .env                   # Environment variables (not in git)
├── .env.example           # Template for .env
└── requirements.txt
```

## Admin Interface

Browse targets, discoveries, and statistics at http://localhost:8000/admin/

- **Targets** - View/edit search targets, filter by type and status
- **Discoveries** - View discovered URLs, filter by has_events, pushed status
- **Runs** - Track discovery session statistics

## Related Repos

- [superschedules](../superschedules) - Main Django backend
- [superschedules_collector](../superschedules_collector) - Event extraction
- [superschedules_frontend](../superschedules_frontend) - React UI

## License

MIT
