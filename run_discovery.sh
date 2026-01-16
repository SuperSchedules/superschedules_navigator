#!/bin/bash
#
# POI-based discovery runner
#
# Usage:
#   ./run_discovery.sh              # Start worker (continuous mode)
#   ./run_discovery.sh --test 10    # Test mode: process 10 POIs then stop
#   ./run_discovery.sh --stats      # Show current discovery statistics
#   ./run_discovery.sh --reset      # Reset stuck POIs (PROCESSING → NOT_STARTED)
#

set -e

# Parse arguments
MODE="run"
TEST_LIMIT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --test)
            MODE="test"
            TEST_LIMIT="$2"
            shift 2
            ;;
        --stats)
            MODE="stats"
            shift
            ;;
        --reset)
            MODE="reset"
            shift
            ;;
        --help|-h)
            echo "POI-based Discovery Runner"
            echo ""
            echo "Usage:"
            echo "  ./run_discovery.sh              Start worker (continuous)"
            echo "  ./run_discovery.sh --test N     Process N POIs then stop"
            echo "  ./run_discovery.sh --stats      Show discovery statistics"
            echo "  ./run_discovery.sh --reset      Reset stuck POIs"
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage"
            exit 1
            ;;
    esac
done

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Check PostgreSQL is accessible
check_postgres() {
    if ! python manage.py shell -c "from navigator.models import POI; print(POI.objects.count())" > /dev/null 2>&1; then
        echo "ERROR: Cannot connect to PostgreSQL database"
        echo "Make sure PostgreSQL is running and the navigator database exists"
        exit 1
    fi
}

# Check Ollama is running with the vision model
check_ollama() {
    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "ERROR: Ollama is not running. Start it with: ollama serve"
        exit 1
    fi

    # Check for vision model
    if ! curl -s http://localhost:11434/api/tags | grep -q "minicpm-v"; then
        echo "WARNING: minicpm-v model not found. Vision verification may fail."
        echo "Install with: ollama pull minicpm-v"
    fi
}

# Show discovery statistics
show_stats() {
    python manage.py shell -c "
from navigator.models import POI
from collections import Counter

total = POI.objects.count()
with_website = POI.objects.exclude(osm_website__isnull=True, discovered_website__isnull=True).exclude(osm_website='', discovered_website='').count()

print('='*50)
print('POI DISCOVERY STATISTICS')
print('='*50)
print(f'Total POIs: {total:,}')
print(f'POIs with websites: {with_website:,}')
print()

# Website discovery status
print('Website Discovery Status:')
ws = Counter(POI.objects.values_list('website_status', flat=True))
for status, count in sorted(ws.items()):
    pct = count/total*100 if total > 0 else 0
    print(f'  {status:15} {count:6,} ({pct:5.1f}%)')

print()

# Source/event discovery status
print('Event Discovery Status:')
ss = Counter(POI.objects.values_list('source_status', flat=True))
for status, count in sorted(ss.items()):
    pct = count/total*100 if total > 0 else 0
    print(f'  {status:15} {count:6,} ({pct:5.1f}%)')

# POIs with events_url
with_events = POI.objects.exclude(events_url__isnull=True).exclude(events_url='').count()
print()
print(f'POIs with events_url: {with_events:,}')

# Show stuck POIs
stuck = POI.objects.filter(source_status='processing').count()
if stuck > 0:
    print()
    print(f'WARNING: {stuck} POIs stuck in PROCESSING state')
    print('Run ./run_discovery.sh --reset to fix')
print('='*50)
"
}

# Reset stuck POIs
reset_stuck() {
    python manage.py shell -c "
from navigator.models import POI

# Reset source_status
stuck_source = POI.objects.filter(source_status='processing')
source_count = stuck_source.count()
if source_count > 0:
    stuck_source.update(source_status='not_started')
    print(f'Reset {source_count} POIs with source_status=processing')

# Reset website_status
stuck_website = POI.objects.filter(website_status='processing')
website_count = stuck_website.count()
if website_count > 0:
    stuck_website.update(website_status='not_started')
    print(f'Reset {website_count} POIs with website_status=processing')

if source_count == 0 and website_count == 0:
    print('No stuck POIs found')
"
}

# Run worker in test mode (process N POIs then stop)
run_test() {
    local limit=$1
    echo "Running in TEST mode: processing $limit POIs"
    echo ""

    python manage.py shell -c "
import sys
sys.path.insert(0, '.')
from local_url_update_worker import process_poi, get_next_poi
from navigator.models import POI, WorkerStatus

limit = $limit
processed = 0
discoveries = 0
no_events = 0
errors = 0

# Create or get worker status for tracking
worker, _ = WorkerStatus.objects.get_or_create(
    worker_type='url_discovery',
    defaults={'is_running': True}
)
worker.is_running = True
worker.save()

print('Starting test run...')
print()

try:
    while processed < limit:
        poi = get_next_poi()
        if not poi:
            print('No more POIs to process')
            break

        print(f'[{processed+1}/{limit}] {poi.name} ({poi.city}) - {poi.category}')
        print(f'  Website: {poi.website or \"(none)\"}')

        try:
            success, was_rate_limited = process_poi(poi, worker)
            # Refresh POI to see updated status
            poi.refresh_from_db()
            if poi.events_url:
                print(f'  ✓ Found events: {poi.events_url}')
                discoveries += 1
            elif poi.source_status == 'no_events':
                print(f'  ✗ No events found')
                no_events += 1
            elif poi.discovered_website:
                print(f'  ✓ Found website: {poi.discovered_website}')
            else:
                print(f'  - Status: website={poi.website_status}, source={poi.source_status}')
        except Exception as e:
            print(f'  ERROR: {e}')
            errors += 1

        processed += 1
        print()

finally:
    worker.is_running = False
    worker.save()

print('='*50)
print(f'Test complete: {processed} POIs processed')
print(f'  Events found: {discoveries}')
print(f'  No events: {no_events}')
print(f'  Errors: {errors}')
print('='*50)
"
}

# Run worker in continuous mode
run_continuous() {
    echo "========================================"
    echo "POI Discovery Worker"
    echo "========================================"
    echo "Starting continuous discovery..."
    echo "Press Ctrl+C to stop"
    echo ""

    python local_url_update_worker.py
}

# Main
case $MODE in
    stats)
        check_postgres
        show_stats
        ;;
    reset)
        check_postgres
        reset_stuck
        ;;
    test)
        check_postgres
        check_ollama
        if [ -z "$TEST_LIMIT" ]; then
            echo "ERROR: --test requires a number (e.g., --test 10)"
            exit 1
        fi
        run_test "$TEST_LIMIT"
        ;;
    run)
        check_postgres
        check_ollama
        show_stats
        echo ""
        run_continuous
        ;;
esac
