#!/usr/bin/env python
"""
Local worker for discovering event URLs for POIs.

Run this as a standalone process:
    python local_url_update_worker.py

It will continuously process POIs that need event URL discovery,
sharing discoveries across similar POIs (e.g., all parks in a city).
"""

import asyncio
import logging
import os
import signal
import socket
import sys
import time
from datetime import timedelta
from urllib.parse import urlparse

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.db import connection
from django.db.models import Q
from django.utils import timezone

import requests

from django.conf import settings

from navigator.models import POI, WorkerStatus, BlockedDomain
from navigator.services.event_page_finder import find_events_page
from navigator.services.website_finder import find_official_website

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Worker config
HEARTBEAT_INTERVAL = 10  # seconds
MAX_ERRORS_BEFORE_PAUSE = 10
ERROR_PAUSE_SECONDS = 60

# AIMD (Additive Increase, Multiplicative Decrease) rate limiting - like TCP Reno
# Converges to optimal rate: probe upward slowly, back off quickly on rate limit
SLEEP_MIN = 1.0          # Minimum sleep between POIs
SLEEP_MAX = 4.0          # Maximum sleep when rate limited
SLEEP_START = 1.0        # Starting sleep time
SLEEP_ADDITIVE_DEC = 0.5 # Decrease sleep by this on success (probe faster)
SLEEP_MULT_INC = 2.0     # Multiply sleep by this on rate limit (back off)

# Global state
shutdown_requested = False
current_sleep = SLEEP_START  # Dynamic sleep time


def signal_handler(signum, frame):
    """Handle shutdown signals - exit immediately on second signal."""
    global shutdown_requested
    if shutdown_requested:
        # Second signal - force exit
        logger.info("Forced shutdown")
        sys.exit(1)
    logger.info(f"Received signal {signum}, shutting down after current POI...")
    logger.info("(Press Ctrl+C again to force quit)")
    shutdown_requested = True


def get_or_create_worker_status() -> WorkerStatus:
    """Get or create the worker status record."""
    worker, created = WorkerStatus.objects.get_or_create(
        worker_type=WorkerStatus.WorkerType.URL_DISCOVERY,
        defaults={
            'hostname': socket.gethostname(),
            'pid': os.getpid(),
        }
    )
    return worker


def update_heartbeat(worker: WorkerStatus, poi: POI = None, phase: str = '', sleep_time: float = None):
    """Update worker heartbeat and current work."""
    worker.last_heartbeat = timezone.now()
    worker.hostname = socket.gethostname()
    worker.pid = os.getpid()
    worker.is_running = True

    if poi:
        worker.current_poi = poi
        worker.current_poi_name = poi.name[:255]
    else:
        worker.current_poi = None
        worker.current_poi_name = ''

    if phase:
        worker.current_phase = phase

    if sleep_time is not None:
        worker.sleep_seconds = sleep_time

    worker.save()


def mark_worker_stopped(worker: WorkerStatus):
    """Mark worker as stopped."""
    worker.is_running = False
    worker.current_poi = None
    worker.current_poi_name = ''
    worker.save()


def get_blocked_domains() -> set:
    """Get set of blocked domains."""
    return set(BlockedDomain.objects.values_list('domain', flat=True))


# Categories where POIs in the same city likely share a website (e.g., Parks & Rec)
SHARED_WEBSITE_CATEGORIES = {'park', 'playground'}


def find_existing_website(poi: POI) -> str | None:
    """
    Find an existing website that can be reused for this POI.

    Only applies to certain categories (parks, playgrounds) where multiple
    POIs in the same city typically share a common website (Parks & Rec dept).

    Checks both osm_website and discovered_website from similar POIs.
    Also matches by operator to avoid mixing city/state/federal parks.
    """
    if poi.category not in SHARED_WEBSITE_CATEGORIES:
        return None

    if not poi.city:
        return None

    # Build query for same city + category
    queryset = POI.objects.filter(
        city__iexact=poi.city,
        category=poi.category,
    ).filter(
        # Has either osm_website or discovered_website
        Q(osm_website__isnull=False) & ~Q(osm_website='') |
        Q(discovered_website__isnull=False) & ~Q(discovered_website='')
    ).exclude(id=poi.id)

    # Match by operator to avoid mixing city/state/federal parks
    if poi.osm_operator:
        # Has operator - only match same operator
        queryset = queryset.filter(osm_operator__iexact=poi.osm_operator)
    else:
        # No operator - only match other POIs without operator (likely city-owned)
        queryset = queryset.filter(Q(osm_operator='') | Q(osm_operator__isnull=True))

    similar_poi = queryset.first()

    if similar_poi and similar_poi.website:  # .website property returns osm or discovered
        logger.info(f"  Reusing website from {similar_poi.name}: {similar_poi.website}")
        return similar_poi.website

    return None


def find_existing_events_url(poi: POI) -> str | None:
    """
    Find an existing events_url that can be reused for this POI.

    Only applies to categories where POIs typically share an events page
    (e.g., city parks all share the Parks & Rec events page).

    Also matches by operator to avoid mixing city/state/federal parks.
    """
    # Only reuse for categories that typically share events pages
    if poi.category not in SHARED_WEBSITE_CATEGORIES:
        return None

    if not poi.city:
        return None

    # Build query for same city + category with existing events_url
    queryset = POI.objects.filter(
        city__iexact=poi.city,
        category=poi.category,
        source_status=POI.SourceStatus.DISCOVERED,
    ).exclude(
        events_url=''
    ).exclude(id=poi.id)

    # Match by operator to avoid mixing city/state/federal parks
    if poi.osm_operator:
        queryset = queryset.filter(osm_operator__iexact=poi.osm_operator)
    else:
        queryset = queryset.filter(Q(osm_operator='') | Q(osm_operator__isnull=True))

    similar_poi = queryset.first()

    if similar_poi and similar_poi.events_url:
        logger.info(f"  Reusing events_url from {similar_poi.name}: {similar_poi.events_url}")
        return similar_poi.events_url

    return None


def get_next_poi() -> POI | None:
    """
    Get the next POI that needs processing.

    Priority:
    1. POIs without osm_website that need website discovery
    2. POIs with a website that need event URL discovery

    Skips schools entirely - use prioritize_universities command for higher ed.
    """
    # Priority 1: POIs without osm_website that need website discovery
    poi = POI.objects.filter(
        osm_website='',
        website_status=POI.WebsiteStatus.NOT_STARTED,
    ).exclude(
        city=''
    ).exclude(
        category='school'
    ).order_by('category', 'city', 'name').first()

    if poi:
        return poi

    # Priority 2: POIs with a website (osm or discovered) that need event URL discovery
    poi = POI.objects.filter(
        source_status=POI.SourceStatus.NOT_STARTED,
    ).exclude(
        city=''
    ).exclude(
        category='school'
    ).filter(
        # Has either osm_website or discovered_website
        Q(osm_website__isnull=False) & ~Q(osm_website='') |
        Q(discovered_website__isnull=False) & ~Q(discovered_website='')
    ).order_by('category', 'city', 'name').first()

    return poi


def sync_poi_to_backend(poi: POI) -> bool:
    """
    Sync a POI to the backend as a Venue.

    Returns True if successful, False if error.
    """
    if not settings.SUPERSCHEDULES_API_TOKEN:
        logger.warning("  No API token - skipping sync")
        return True  # Continue with discovery anyway

    payload = {
        'osm_type': poi.osm_type,
        'osm_id': poi.osm_id,
        'name': poi.name,
        'category': poi.category,
        'street_address': poi.street_address,
        'city': poi.city,
        'state': poi.state,
        'postal_code': poi.postal_code,
        'latitude': float(poi.latitude) if poi.latitude else None,
        'longitude': float(poi.longitude) if poi.longitude else None,
        'website': poi.website,  # Uses osm_website if available, else discovered_website
        'events_url': poi.events_url or None,  # Where to scrape events
        'phone': poi.osm_phone,
        'opening_hours': poi.osm_opening_hours,
        'operator': poi.osm_operator,
        'wikidata': poi.osm_wikidata,
    }

    try:
        response = requests.post(
            f"{settings.SUPERSCHEDULES_API_URL}/api/v1/venues/from-osm/",
            json=payload,
            headers={"Authorization": f"Bearer {settings.SUPERSCHEDULES_API_TOKEN}"},
            timeout=30
        )

        if response.status_code in (200, 201):
            result = response.json()
            poi.venue_id = result.get('venue_id')
            poi.venue_status = POI.VenueStatus.SYNCED
            poi.venue_synced_at = timezone.now()
            poi.venue_sync_error = ''
            poi.save(update_fields=['venue_id', 'venue_status', 'venue_synced_at', 'venue_sync_error'])
            logger.info(f"  Synced to backend (venue_id={poi.venue_id})")
            return True
        else:
            poi.venue_status = POI.VenueStatus.FAILED
            poi.venue_sync_error = f"HTTP {response.status_code}: {response.text[:500]}"
            poi.save(update_fields=['venue_status', 'venue_sync_error'])
            logger.warning(f"  Sync failed: HTTP {response.status_code} - {response.text[:200]}")
            return False

    except Exception as e:
        poi.venue_status = POI.VenueStatus.FAILED
        poi.venue_sync_error = str(e)[:500]
        poi.save(update_fields=['venue_status', 'venue_sync_error'])
        logger.warning(f"  Sync error: {e}")
        return False


def process_website_discovery(poi: POI, worker: WorkerStatus) -> tuple[bool, bool]:
    """
    Discover official website for a POI that has no osm_website.

    Returns (success, was_rate_limited):
        - success: True if completed (found, not found, or reused), False if error
        - was_rate_limited: True if we hit rate limits (should back off)
    """
    logger.info(f"Website discovery: {poi.name} ({poi.category}) - {poi.city}")

    # First, check if we can reuse a website from same city+category
    existing = find_existing_website(poi)
    if existing:
        poi.discovered_website = existing
        poi.website_status = POI.WebsiteStatus.FOUND
        poi.website_discovery_notes = 'Reused from similar POI in same city'
        poi.save(update_fields=['discovered_website', 'website_status', 'website_discovery_notes'])

        logger.info(f"  Reused website: {existing}")
        worker.pois_processed += 1
        worker.discoveries_reused += 1
        worker.save(update_fields=['pois_processed', 'discoveries_reused'])
        return (True, False)  # Success, no rate limit

    poi.website_status = POI.WebsiteStatus.PROCESSING
    poi.save(update_fields=['website_status'])

    try:
        result = find_official_website(poi)
        notes = result.get('notes', '')

        # Detect rate limiting from response
        was_rate_limited = 'ratelimit' in notes.lower() or 'no search results' in notes.lower()

        if result.get('website'):
            poi.discovered_website = result['website']
            poi.website_status = POI.WebsiteStatus.FOUND
            poi.website_discovery_notes = notes
            poi.save(update_fields=['discovered_website', 'website_status', 'website_discovery_notes'])

            logger.info(f"  Found website: {result['website']}")
            worker.pois_processed += 1
            worker.discoveries_found += 1
            worker.websites_found += 1
            worker.save(update_fields=['pois_processed', 'discoveries_found', 'websites_found'])
        else:
            poi.website_status = POI.WebsiteStatus.NOT_FOUND
            poi.website_discovery_notes = notes
            poi.save(update_fields=['website_status', 'website_discovery_notes'])

            logger.info(f"  No website found: {notes}")
            worker.pois_processed += 1
            worker.websites_not_found += 1
            worker.save(update_fields=['pois_processed', 'websites_not_found'])

        return (True, was_rate_limited)

    except Exception as e:
        error_str = str(e).lower()
        logger.error(f"  Website discovery error: {e}")
        poi.website_status = POI.WebsiteStatus.FAILED
        poi.website_discovery_notes = f"Error: {str(e)[:200]}"
        poi.save(update_fields=['website_status', 'website_discovery_notes'])

        # Check if error was rate limit related
        was_rate_limited = 'ratelimit' in error_str or 'timeout' in error_str

        worker.errors += 1
        worker.save(update_fields=['errors'])
        return (False, was_rate_limited)


def is_website_blocked(website: str, blocked_domains: set) -> bool:
    """Check if website's domain is in the blocklist."""
    if not website:
        return False
    try:
        domain = urlparse(website).netloc.lower()
        # Check exact match
        if domain in blocked_domains:
            return True
        # Check if subdomain of blocked domain
        for blocked in blocked_domains:
            if domain.endswith('.' + blocked):
                return True
    except Exception:
        pass
    return False


def process_event_discovery(poi: POI, worker: WorkerStatus, blocked_domains: set = None) -> bool:
    """
    Find event URL for a POI that has a website (osm or discovered).

    Returns True if successful, False if error.
    """
    website = poi.website  # Uses osm_website or discovered_website
    logger.info(f"Event discovery: {poi.name} ({poi.category}) - {poi.city}")
    logger.info(f"  Website: {website}")

    # Skip if website domain is blocked
    if blocked_domains and is_website_blocked(website, blocked_domains):
        logger.info(f"  Skipped: website domain is blocked")
        poi.source_status = POI.SourceStatus.SKIPPED
        poi.events_url_notes = 'Website domain is blocked'
        poi.save(update_fields=['source_status', 'events_url_notes'])
        worker.pois_processed += 1
        worker.save(update_fields=['pois_processed'])
        return True

    poi.source_status = POI.SourceStatus.PROCESSING
    poi.save(update_fields=['source_status'])

    try:
        # Step 1: Check for reusable events_url from similar POI
        existing_url = find_existing_events_url(poi)
        if existing_url:
            poi.events_url = existing_url
            poi.events_url_method = 'reused'
            poi.events_url_notes = 'Reused from similar POI'
            poi.source_status = POI.SourceStatus.DISCOVERED
            poi.save(update_fields=['events_url', 'events_url_method', 'events_url_notes', 'source_status'])

            logger.info(f"  Reused events URL: {existing_url}")
            worker.discoveries_reused += 1
            worker.pois_processed += 1
            worker.save(update_fields=['discoveries_reused', 'pois_processed'])

            # Sync to backend with the events_url
            if poi.venue_status != POI.VenueStatus.SYNCED:
                sync_poi_to_backend(poi)
            return True

        # Step 2: Run event page discovery (with vision verification)
        result = asyncio.run(find_events_page(poi))

        if result.get('events_url') and result.get('has_events', True):
            url = result['events_url']

            # Set events_url directly on POI
            poi.events_url = url
            poi.events_url_method = result.get('method', '')
            poi.events_url_confidence = result.get('confidence')
            notes = result.get('notes', '')
            if result.get('event_count'):
                notes += f" ({result['event_count']} events visible)"
            poi.events_url_notes = notes
            poi.source_status = POI.SourceStatus.DISCOVERED
            poi.save(update_fields=[
                'events_url', 'events_url_method', 'events_url_confidence',
                'events_url_notes', 'source_status'
            ])

            verified_str = "vision verified" if result.get('vision_verified') else "not verified"
            logger.info(f"  Found events page ({verified_str}): {url}")
            worker.discoveries_found += 1
            worker.pois_processed += 1
            worker.save(update_fields=['discoveries_found', 'pois_processed'])

            # Sync to backend with the events_url
            if poi.venue_status != POI.VenueStatus.SYNCED:
                sync_poi_to_backend(poi)
        else:
            poi.source_status = POI.SourceStatus.NO_EVENTS
            poi.events_url_notes = result.get('notes', 'No events page found')
            poi.save(update_fields=['source_status', 'events_url_notes'])

            logger.info(f"  No events page found: {result.get('notes', '')[:50]}")
            worker.pois_processed += 1
            worker.save(update_fields=['pois_processed'])

            # Still sync to backend (without events_url)
            if poi.venue_status != POI.VenueStatus.SYNCED:
                sync_poi_to_backend(poi)

        return True

    except Exception as e:
        logger.error(f"  Event discovery error: {e}")
        poi.source_status = POI.SourceStatus.NOT_STARTED  # Reset to retry later
        poi.events_url_notes = f"Error: {str(e)[:200]}"
        poi.save(update_fields=['source_status', 'events_url_notes'])

        worker.errors += 1
        worker.save(update_fields=['errors'])
        return False


def process_poi(poi: POI, worker: WorkerStatus, blocked_domains: set = None) -> tuple[bool, bool]:
    """
    Process a single POI based on what it needs.

    - If no osm_website and website_status NOT_STARTED: discover website
    - If has website and source_status NOT_STARTED: discover events page

    Returns (success, was_rate_limited):
        - success: True if completed, False if error
        - was_rate_limited: True if we should back off
    """
    # Determine what this POI needs
    needs_website_discovery = (not poi.osm_website and poi.website_status == POI.WebsiteStatus.NOT_STARTED)
    needs_event_discovery = (poi.website and poi.source_status == POI.SourceStatus.NOT_STARTED)

    if needs_website_discovery:
        worker.current_phase = 'website'
        worker.save(update_fields=['current_phase'])
        return process_website_discovery(poi, worker)
    elif needs_event_discovery:
        worker.current_phase = 'events'
        worker.save(update_fields=['current_phase'])
        # Event discovery doesn't use web search, no rate limiting concern
        success = process_event_discovery(poi, worker, blocked_domains)
        return (success, False)
    else:
        logger.warning(f"POI {poi.name} doesn't need processing - skipping")
        return (True, False)


def adjust_sleep(was_rate_limited: bool) -> float:
    """
    Adjust sleep time using AIMD (Additive Increase, Multiplicative Decrease).

    Like TCP congestion control - converges to optimal rate:
    - Success: probe faster by decreasing sleep additively
    - Rate limit: back off quickly by multiplying sleep
    """
    global current_sleep
    old_sleep = current_sleep

    if was_rate_limited:
        # Multiplicative increase in sleep (back off quickly)
        current_sleep = min(SLEEP_MAX, current_sleep * SLEEP_MULT_INC)
        if old_sleep != current_sleep:
            logger.warning(f"Rate limited! AIMD backoff: {old_sleep:.1f}s -> {current_sleep:.1f}s")
    else:
        # Additive decrease in sleep (probe faster slowly)
        current_sleep = max(SLEEP_MIN, current_sleep - SLEEP_ADDITIVE_DEC)
        if old_sleep != current_sleep:
            logger.info(f"Success, AIMD probe: {old_sleep:.1f}s -> {current_sleep:.1f}s")

    return current_sleep


def run_worker():
    """Main worker loop."""
    global shutdown_requested, current_sleep

    logger.info("=" * 60)
    logger.info("URL Discovery Worker starting")
    logger.info("=" * 60)

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Get/create worker status
    worker = get_or_create_worker_status()
    worker.started_at = timezone.now()
    worker.pois_processed = 0
    worker.discoveries_found = 0
    worker.discoveries_reused = 0
    worker.errors = 0
    worker.websites_found = 0
    worker.websites_not_found = 0
    worker.current_phase = ''
    worker.sleep_seconds = current_sleep
    worker.save()

    logger.info(f"Worker ID: {worker.id}")
    logger.info(f"Hostname: {socket.gethostname()}")
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"Starting sleep: {current_sleep:.1f}s (min={SLEEP_MIN}, max={SLEEP_MAX})")

    # Load blocked domains
    blocked_domains = get_blocked_domains()
    logger.info(f"Loaded {len(blocked_domains)} blocked domains")

    last_heartbeat = time.time()
    consecutive_errors = 0

    try:
        while not shutdown_requested:
            # Update heartbeat periodically
            if time.time() - last_heartbeat > HEARTBEAT_INTERVAL:
                update_heartbeat(worker)
                last_heartbeat = time.time()

            # Get next POI
            poi = get_next_poi()

            if not poi:
                logger.info("No POIs to process, sleeping 30 seconds...")
                update_heartbeat(worker)
                time.sleep(30)
                continue

            # Update heartbeat with current POI
            update_heartbeat(worker, poi)

            # Process POI
            success, was_rate_limited = process_poi(poi, worker, blocked_domains)

            if success:
                consecutive_errors = 0
            else:
                consecutive_errors += 1

                if consecutive_errors >= MAX_ERRORS_BEFORE_PAUSE:
                    logger.warning(f"Too many consecutive errors ({consecutive_errors}), pausing {ERROR_PAUSE_SECONDS}s...")
                    time.sleep(ERROR_PAUSE_SECONDS)
                    consecutive_errors = 0

            # Adjust sleep based on rate limiting
            sleep_time = adjust_sleep(was_rate_limited)

            # Update worker's sleep_seconds so dashboard can show current AIMD value
            worker.sleep_seconds = sleep_time
            worker.save(update_fields=['sleep_seconds'])

            # Close DB connection to avoid stale connections
            connection.close()

            # Sleep between POIs
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        mark_worker_stopped(worker)
        logger.info("=" * 60)
        logger.info("Worker stopped")
        logger.info(f"  POIs processed: {worker.pois_processed}")
        logger.info(f"  Discoveries found: {worker.discoveries_found}")
        logger.info(f"  Discoveries reused: {worker.discoveries_reused}")
        logger.info(f"  Errors: {worker.errors}")
        logger.info("=" * 60)


if __name__ == '__main__':
    run_worker()
