"""Background task runners for pipeline operations."""

import logging
import threading
from datetime import datetime
from pathlib import Path

import requests
from django.conf import settings
from django.db import connection
from django.utils import timezone

from .models import POI, PipelineRun
from .services.osm_extractor import extract_pois

logger = logging.getLogger(__name__)

# Store for active run threads
_active_runs: dict[int, threading.Thread] = {}


def start_pipeline_run(run: PipelineRun) -> threading.Thread:
    """Start a pipeline run in a background thread."""
    if run.step == PipelineRun.Step.EXTRACT:
        target = run_extract
    elif run.step == PipelineRun.Step.SYNC:
        target = run_sync
    elif run.step == PipelineRun.Step.DISCOVER:
        target = run_discover
    else:
        raise ValueError(f"Unknown step: {run.step}")

    thread = threading.Thread(target=target, args=(run.id,), daemon=True)
    _active_runs[run.id] = thread
    thread.start()
    return thread


def is_run_active(run_id: int) -> bool:
    """Check if a run is still active."""
    thread = _active_runs.get(run_id)
    return thread is not None and thread.is_alive()


def _update_run(run_id: int, **kwargs):
    """Update a PipelineRun record. Creates new DB connection for thread safety."""
    connection.close()  # Close inherited connection
    PipelineRun.objects.filter(id=run_id).update(**kwargs)


def _append_log(run_id: int, message: str):
    """Append a message to the run log."""
    timestamp = datetime.now().strftime('%H:%M:%S')
    log_line = f"[{timestamp}] {message}\n"

    connection.close()
    run = PipelineRun.objects.get(id=run_id)
    run.log += log_line
    run.save(update_fields=['log'])


def run_extract(run_id: int):
    """Run POI extraction from OSM PBF file."""
    connection.close()  # Close inherited connection

    try:
        run = PipelineRun.objects.get(id=run_id)
        run.status = PipelineRun.Status.RUNNING
        run.started_at = timezone.now()
        run.save()

        _append_log(run_id, f"Starting extraction...")

        # Get PBF file path from the run's stored data
        # For now, use first available PBF file
        pbf_files = list(Path('.').glob('*.osm.pbf'))
        if not pbf_files:
            _update_run(run_id, status=PipelineRun.Status.FAILED)
            _append_log(run_id, "ERROR: No PBF file found in project directory")
            return

        pbf_path = pbf_files[0]
        _append_log(run_id, f"Using PBF file: {pbf_path}")

        categories = run.categories if run.categories else None
        dry_run = run.dry_run

        # Count POIs first (we don't know total until we stream through)
        _append_log(run_id, f"Streaming POIs from OSM data...")

        stats = {'created': 0, 'updated': 0, 'unchanged': 0}
        processed = 0

        for poi_data in extract_pois(pbf_path, categories):
            processed += 1

            # Update progress every 100 items
            if processed % 100 == 0:
                _update_run(
                    run_id,
                    processed_items=processed,
                    current_item=poi_data['name'][:100],
                    created=stats['created'],
                    updated=stats['updated'],
                    unchanged=stats['unchanged'],
                )

            if dry_run:
                stats['unchanged'] += 1
                continue

            # Check limit
            if run.limit and processed > run.limit:
                break

            # Upsert POI
            result = _upsert_poi(poi_data)
            stats[result] += 1

        # Final update
        _update_run(
            run_id,
            status=PipelineRun.Status.COMPLETED,
            completed_at=timezone.now(),
            total_items=processed,
            processed_items=processed,
            current_item='',
            created=stats['created'],
            updated=stats['updated'],
            unchanged=stats['unchanged'],
        )
        _append_log(run_id, f"Completed: {stats['created']} created, {stats['updated']} updated, {stats['unchanged']} unchanged")

    except Exception as e:
        logger.exception(f"Extract run {run_id} failed")
        _update_run(run_id, status=PipelineRun.Status.FAILED)
        _append_log(run_id, f"ERROR: {str(e)}")
    finally:
        _active_runs.pop(run_id, None)
        connection.close()


def _upsert_poi(poi_data: dict) -> str:
    """Create or update POI record."""
    osm_type = poi_data['osm_type']
    osm_id = poi_data['osm_id']

    try:
        existing = POI.objects.get(osm_type=osm_type, osm_id=osm_id)
        changed = False
        for key, value in poi_data.items():
            if key in ('osm_type', 'osm_id'):
                continue
            current_value = getattr(existing, key)
            if hasattr(current_value, '__float__') and value is not None:
                if float(current_value) != float(value):
                    setattr(existing, key, value)
                    changed = True
            elif current_value != value:
                setattr(existing, key, value)
                changed = True

        if changed:
            existing.save()
            return 'updated'
        return 'unchanged'

    except POI.DoesNotExist:
        POI.objects.create(**poi_data)
        return 'created'


def run_sync(run_id: int):
    """Run venue sync to backend API."""
    connection.close()

    try:
        run = PipelineRun.objects.get(id=run_id)
        run.status = PipelineRun.Status.RUNNING
        run.started_at = timezone.now()
        run.save()

        _append_log(run_id, "Starting venue sync...")

        # Check API token
        if not run.dry_run and not settings.SUPERSCHEDULES_API_TOKEN:
            _update_run(run_id, status=PipelineRun.Status.FAILED)
            _append_log(run_id, "ERROR: No API token configured. Set SUPERSCHEDULES_API_TOKEN env var.")
            return

        # Build query
        pois = POI.objects.filter(venue_status=POI.VenueStatus.PENDING)

        if run.categories:
            pois = pois.filter(category__in=run.categories)

        if run.city_filter:
            pois = pois.filter(city__icontains=run.city_filter)

        pois = pois.order_by('category', 'name')

        if run.limit:
            pois = pois[:run.limit]

        pois = list(pois)
        total = len(pois)

        if not pois:
            _update_run(run_id, status=PipelineRun.Status.COMPLETED, completed_at=timezone.now())
            _append_log(run_id, "No POIs to sync")
            return

        _update_run(run_id, total_items=total)
        _append_log(run_id, f"Found {total} POIs to sync")

        stats = {'created': 0, 'updated': 0, 'unchanged': 0, 'failed': 0}

        for i, poi in enumerate(pois):
            _update_run(
                run_id,
                processed_items=i + 1,
                current_item=poi.name[:100],
                created=stats['created'],
                updated=stats['updated'],
                unchanged=stats['unchanged'],
                failed=stats['failed'],
            )

            if run.dry_run:
                stats['unchanged'] += 1
                continue

            result = _sync_poi(poi)
            stats[result] += 1

            if (i + 1) % 10 == 0:
                _append_log(run_id, f"Synced {i + 1}/{total}: {poi.name[:50]}")

        _update_run(
            run_id,
            status=PipelineRun.Status.COMPLETED,
            completed_at=timezone.now(),
            current_item='',
            created=stats['created'],
            updated=stats['updated'],
            unchanged=stats['unchanged'],
            failed=stats['failed'],
        )
        _append_log(run_id, f"Completed: +{stats['created']} ~{stats['updated']} ={stats['unchanged']} !{stats['failed']}")

    except Exception as e:
        logger.exception(f"Sync run {run_id} failed")
        _update_run(run_id, status=PipelineRun.Status.FAILED)
        _append_log(run_id, f"ERROR: {str(e)}")
    finally:
        _active_runs.pop(run_id, None)
        connection.close()


def _sync_poi(poi: POI) -> str:
    """Sync a single POI to the backend."""
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
        'website': poi.osm_website,
        'phone': poi.osm_phone,
        'opening_hours': poi.osm_opening_hours,
        'operator': poi.osm_operator,
        'wikidata': poi.osm_wikidata,
    }

    try:
        response = requests.post(
            f"{settings.SUPERSCHEDULES_API_URL}/api/venues/from-osm/",
            json=payload,
            headers={"Authorization": f"Token {settings.SUPERSCHEDULES_API_TOKEN}"},
            timeout=30
        )

        if response.status_code in (200, 201):
            result = response.json()
            status = result.get('status', 'created')

            poi.venue_id = result.get('venue_id')
            poi.venue_status = POI.VenueStatus.SYNCED
            poi.venue_synced_at = timezone.now()
            poi.venue_sync_error = ''
            poi.save()

            return status
        else:
            poi.venue_status = POI.VenueStatus.FAILED
            poi.venue_sync_error = f"HTTP {response.status_code}: {response.text[:500]}"
            poi.save()
            return 'failed'

    except Exception as e:
        poi.venue_status = POI.VenueStatus.FAILED
        poi.venue_sync_error = str(e)[:500]
        poi.save()
        return 'failed'


def run_discover(run_id: int):
    """Run source discovery for POIs."""
    connection.close()

    try:
        run = PipelineRun.objects.get(id=run_id)
        run.status = PipelineRun.Status.RUNNING
        run.started_at = timezone.now()
        run.save()

        _append_log(run_id, "Starting source discovery...")

        # Build query - only synced POIs with websites
        pois = POI.objects.filter(
            venue_status=POI.VenueStatus.SYNCED,
            source_status=POI.SourceStatus.NOT_STARTED
        ).exclude(osm_website='')

        if run.categories:
            pois = pois.filter(category__in=run.categories)

        if run.city_filter:
            pois = pois.filter(city__icontains=run.city_filter)

        pois = pois.order_by('category', 'name')

        if run.limit:
            pois = pois[:run.limit]

        pois = list(pois)
        total = len(pois)

        if not pois:
            _update_run(run_id, status=PipelineRun.Status.COMPLETED, completed_at=timezone.now())
            _append_log(run_id, "No POIs to discover (need synced POIs with websites)")
            return

        _update_run(run_id, total_items=total)
        _append_log(run_id, f"Found {total} POIs to check for event pages")

        stats = {'created': 0, 'skipped': 0, 'failed': 0}

        for i, poi in enumerate(pois):
            _update_run(
                run_id,
                processed_items=i + 1,
                current_item=poi.name[:100],
                created=stats['created'],
                skipped=stats['skipped'],
                failed=stats['failed'],
            )

            if run.dry_run:
                stats['skipped'] += 1
                continue

            # Import here to avoid circular import
            import asyncio
            from .services.event_page_finder import find_events_page

            try:
                result = asyncio.run(find_events_page(poi))

                if result.get('events_url'):
                    poi.source_status = POI.SourceStatus.DISCOVERED
                    poi.discovered_events_url = result['events_url']
                    poi.discovery_method = result.get('method', '')
                    poi.discovery_confidence = result.get('confidence', 0)
                    poi.save()
                    stats['created'] += 1
                    _append_log(run_id, f"Found: {poi.name[:40]} -> {result['events_url'][:50]}")
                else:
                    poi.source_status = POI.SourceStatus.NO_EVENTS
                    poi.discovery_notes = result.get('notes', 'No events page found')
                    poi.save()
                    stats['skipped'] += 1

            except Exception as e:
                poi.source_status = POI.SourceStatus.NO_EVENTS
                poi.discovery_notes = f"Error: {str(e)[:200]}"
                poi.save()
                stats['failed'] += 1

        _update_run(
            run_id,
            status=PipelineRun.Status.COMPLETED,
            completed_at=timezone.now(),
            current_item='',
            created=stats['created'],
            skipped=stats['skipped'],
            failed=stats['failed'],
        )
        _append_log(run_id, f"Completed: {stats['created']} discovered, {stats['skipped']} no events, {stats['failed']} failed")

    except Exception as e:
        logger.exception(f"Discover run {run_id} failed")
        _update_run(run_id, status=PipelineRun.Status.FAILED)
        _append_log(run_id, f"ERROR: {str(e)}")
    finally:
        _active_runs.pop(run_id, None)
        connection.close()
