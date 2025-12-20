# Superschedules Navigator

## Project Overview

The Navigator is the **discovery layer** of the Superschedules ecosystem. It finds WHERE events are (URLs and site classifications), while the Collector extracts WHAT the events are.

This is a **Django application** with a local PostgreSQL database for tracking discovery targets and results.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     SUPERSCHEDULES ECOSYSTEM                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │  NAVIGATOR   │───▶│    DJANGO    │◀───│  COLLECTOR   │                  │
│  │  (this repo) │    │  (port 8000) │    │  (port 8001) │                  │
│  │              │    │              │    │              │                  │
│  │ Discovers    │    │ Stores:      │    │ Extracts:    │                  │
│  │ event URLs,  │    │ - Events     │    │ - Event data │                  │
│  │ classifies   │    │ - Venues     │    │ - Venues     │                  │
│  │ sites        │    │ - Sources    │    │ - Details    │                  │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
│                             │                                               │
│                             ▼                                               │
│                      ┌──────────────┐                                       │
│                      │   FRONTEND   │                                       │
│                      │  (port 5173) │                                       │
│                      │  EventZombie │                                       │
│                      └──────────────┘                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Tech Stack

- **Django 5.0** with admin interface
- **PostgreSQL** database (`navigator`)
- **Playwright** for screenshots
- **Ollama** with vision model (minicpm-v) for classification
- **Rich** for CLI output
- **python-dotenv** for environment configuration

## How It Works

Vision-based discovery workflow:
1. **Search** - Query DuckDuckGo for event pages for a target (town, university, museum, etc.)
2. **Screenshot** - Capture each result with Playwright
3. **Classify** - Send screenshot to vision LLM to determine:
   - Is this the correct location?
   - Does it have events?
   - What type of org?
4. **Store** - Save results to PostgreSQL database
5. **Push** - Submit verified URLs to main Django API for scraping

## Directory Structure

```
superschedules_navigator/
├── manage.py                # Django management
├── config/
│   ├── settings.py          # Django settings (loads from .env)
│   ├── urls.py              # URL routing (admin)
│   └── wsgi.py
├── navigator/               # Main Django app
│   ├── models.py            # Target, Discovery, TargetQuery, Run
│   ├── admin.py             # Admin with filters and actions
│   └── management/commands/
│       ├── discover.py      # Run vision-based discovery
│       ├── push.py          # Push verified URLs to API
│       ├── import_csv.py    # Import targets from CSV
│       ├── import_json.py   # Import legacy discovery JSON
│       └── stats.py         # Show discovery statistics
├── .env                     # Environment variables (not in git)
├── .env.example             # Template for .env
├── screenshots/             # Captured screenshots
├── boston_museums.csv       # Museum targets
├── boston_universities.csv  # University targets
└── greater_boston_cities.csv # Town targets
```

## Models

### Target
A search target - could be a town, university, museum, etc.
- `name` - Name (e.g., "Newton", "MIT")
- `target_type` - town, university, museum, library, organization, venue
- `location` - For disambiguation (e.g., "MA", "Boston, MA")
- `status` - pending, processing, completed, failed

### Discovery
A discovered URL from searching for a target.
- `target` - FK to Target
- `url`, `domain`, `title`
- `location_correct` - Is this the correct location?
- `has_events` - Does this page have events?
- `event_count`, `org_type`, `confidence`, `reason`
- `pushed_to_api`, `pushed_at` - API push tracking

## Management Commands

### discover - Run Vision Discovery
```bash
# All pending targets
python manage.py discover

# Specific type
python manage.py discover --type museum
python manage.py discover --type university

# Specific target
python manage.py discover --target "Harvard"

# Limit and dry-run
python manage.py discover --limit 10
python manage.py discover --dry-run

# Different vision model
python manage.py discover --model llava
```

**Behavior by target type:**
- **Museums/Libraries**: 3 search results per query, stops early on high-confidence match
- **Towns/Universities**: 5 search results per query, searches all categories

### push - Push to API
```bash
# Dry run to preview
python manage.py push --dry-run

# Push all verified event sources
python manage.py push

# Filter by type or target
python manage.py push --type museum
python manage.py push --target "MIT"

# Re-push already pushed URLs
python manage.py push --include-pushed
```

### import_csv - Import Targets
```bash
python manage.py import_csv cities.csv --type town
python manage.py import_csv universities.csv --type university
python manage.py import_csv museums.csv --type museum --location "Boston, MA"
```

### stats - Show Statistics
```bash
python manage.py stats
```

## Environment Variables

Configured via `.env` file (copy from `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `SUPERSCHEDULES_API_TOKEN` | API token for push command | (required for push) |
| `SUPERSCHEDULES_API_URL` | Main API URL | `https://api.eventzombie.com` |
| `DB_NAME` | Database name | `navigator` |
| `DB_USER` | Database user | `$USER` |
| `DB_HOST` | Database host | (Unix socket) |
| `VISION_MODEL` | Ollama vision model | `minicpm-v` |
| `OLLAMA_URL` | Ollama server URL | `http://localhost:11434` |

## Database

PostgreSQL database: `navigator`

```bash
# Create database
createdb navigator

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

## Current Data

- **101 towns** (Greater Boston, completed)
- **64 museums** (Boston area, pending)
- **64 universities** (Greater Boston, pending)
- **~1400 discovered URLs**, ~460 verified event sources

## Related Repositories

| Repo | Purpose |
|------|---------|
| `superschedules` | Django backend - stores events, venues, sources |
| `superschedules_collector` | Extracts event data from discovered URLs |
| `superschedules_frontend` | React frontend (EventZombie) |
| `superschedules_IAC` | Infrastructure as Code |

## Development

### Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# Edit .env with your API token
createdb navigator
python manage.py migrate
python manage.py createsuperuser
```

### Run Ollama
```bash
ollama serve
ollama pull minicpm-v
```

### Testing
```bash
.venv/bin/pytest
```

## For AI Assistants

- **NEVER create files unless absolutely necessary** - Always prefer editing existing files
- **NEVER proactively create documentation files** unless explicitly requested
- Reference file locations with `file_path:line_number` format
- **Line length: 120 characters maximum**
- Use Django ORM for all database operations
- Management commands go in `navigator/management/commands/`
- Environment variables loaded from `.env` via python-dotenv in settings.py
