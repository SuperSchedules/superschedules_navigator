"""Views for Navigator dashboard."""

import json
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from .models import POI, PipelineRun, WorkerStatus
from .tasks import start_pipeline_run, is_run_active


@login_required
def dashboard(request):
    """Main dashboard showing POI pipeline stats."""
    # POI extraction stats
    poi_total = POI.objects.count()
    poi_with_website = POI.objects.exclude(osm_website='').count()

    # Venue sync stats
    venue_synced = POI.objects.filter(venue_status=POI.VenueStatus.SYNCED).count()
    venue_pending = POI.objects.filter(venue_status=POI.VenueStatus.PENDING).count()
    venue_failed = POI.objects.filter(venue_status=POI.VenueStatus.FAILED).count()

    # Website discovery stats (excluding schools which are skipped)
    active_for_stats = POI.objects.exclude(category='school')
    website_has_osm = active_for_stats.filter(website_status=POI.WebsiteStatus.HAS_OSM).count()
    website_found = active_for_stats.filter(website_status=POI.WebsiteStatus.FOUND).count()
    website_not_found = active_for_stats.filter(website_status=POI.WebsiteStatus.NOT_FOUND).count()
    website_pending = active_for_stats.filter(website_status=POI.WebsiteStatus.NOT_STARTED).count()
    website_failed = active_for_stats.filter(website_status=POI.WebsiteStatus.FAILED).count()

    # Source/event discovery stats (excluding schools which are skipped)
    source_discovered = active_for_stats.filter(source_status=POI.SourceStatus.DISCOVERED).count()
    source_no_events = active_for_stats.filter(source_status=POI.SourceStatus.NO_EVENTS).count()
    source_not_started = active_for_stats.filter(source_status=POI.SourceStatus.NOT_STARTED).count()
    source_skipped = active_for_stats.filter(source_status=POI.SourceStatus.SKIPPED).count()

    # Ready to discover: synced POIs with websites that haven't been scanned yet (excluding schools)
    discovery_ready = active_for_stats.filter(
        venue_status=POI.VenueStatus.SYNCED,
        source_status=POI.SourceStatus.NOT_STARTED
    ).exclude(osm_website='').count()

    # Work queue stats (excluding schools which are skipped)
    active_pois = POI.objects.exclude(category='school')

    # Queue 1: Website discovery - POIs without osm_website that need discovery
    queue_website = active_pois.filter(
        osm_website='',
        website_status=POI.WebsiteStatus.NOT_STARTED,
    ).exclude(city='').count()

    # Queue 2: Event discovery - POIs with website that need event URL discovery
    queue_events = active_pois.filter(
        source_status=POI.SourceStatus.NOT_STARTED,
    ).exclude(city='').filter(
        Q(osm_website__isnull=False) & ~Q(osm_website='') |
        Q(discovered_website__isnull=False) & ~Q(discovered_website='')
    ).count()

    # Queue 3: Venue sync - POIs not yet synced to backend
    queue_sync = active_pois.filter(venue_status=POI.VenueStatus.PENDING).count()

    # Breakdown by category for event discovery queue
    queue_by_category = (
        active_pois.filter(
            source_status=POI.SourceStatus.NOT_STARTED,
        ).exclude(city='').filter(
            Q(osm_website__isnull=False) & ~Q(osm_website='') |
            Q(discovered_website__isnull=False) & ~Q(discovered_website='')
        ).values('category')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    # Schools skipped count
    schools_skipped = POI.objects.filter(category='school').count()

    # Coverage by category
    category_stats = (
        POI.objects.values('category')
        .annotate(
            total=Count('id'),
            with_website=Count('id', filter=~Q(osm_website='')),
            synced=Count('id', filter=Q(venue_status=POI.VenueStatus.SYNCED)),
            discovered=Count('id', filter=Q(source_status=POI.SourceStatus.DISCOVERED)),
        )
        .order_by('-total')
    )

    # Recent pipeline runs
    recent_runs = PipelineRun.objects.all()[:10]

    # Check for any running pipelines
    running_run = PipelineRun.objects.filter(status=PipelineRun.Status.RUNNING).first()

    # Worker status
    try:
        worker = WorkerStatus.objects.get(worker_type=WorkerStatus.WorkerType.URL_DISCOVERY)
    except WorkerStatus.DoesNotExist:
        worker = None

    # Calculate percentages
    venue_sync_pct = round(venue_synced / poi_total * 100) if poi_total > 0 else 0
    website_pct = round(poi_with_website / poi_total * 100) if poi_total > 0 else 0

    context = {
        # Extraction
        'poi_total': poi_total,
        'poi_with_website': poi_with_website,
        'website_pct': website_pct,
        # Venue sync
        'venue_synced': venue_synced,
        'venue_pending': venue_pending,
        'venue_failed': venue_failed,
        'venue_sync_pct': venue_sync_pct,
        # Website discovery
        'website_has_osm': website_has_osm,
        'website_found': website_found,
        'website_not_found': website_not_found,
        'website_pending': website_pending,
        'website_failed': website_failed,
        # Source/event discovery
        'source_discovered': source_discovered,
        'source_no_events': source_no_events,
        'source_not_started': source_not_started,
        'source_skipped': source_skipped,
        'discovery_ready': discovery_ready,
        # Work queue
        'queue_website': queue_website,
        'queue_events': queue_events,
        'queue_sync': queue_sync,
        'queue_by_category': queue_by_category,
        'schools_skipped': schools_skipped,
        # Coverage
        'category_stats': category_stats,
        # Recent runs
        'recent_runs': recent_runs,
        'running_run': running_run,
        # Worker
        'worker': worker,
    }

    return render(request, 'navigator/dashboard.html', context)


@login_required
def run_extract(request):
    """Run POI extraction from OSM."""
    if request.method == 'POST':
        return _start_run(request, PipelineRun.Step.EXTRACT)

    # Get available PBF files
    pbf_files = list(Path('.').glob('*.osm.pbf'))

    context = {
        'step': 'extract',
        'step_title': 'POI Extraction',
        'pbf_files': pbf_files,
        'categories': POI.Category.choices,
    }
    return render(request, 'navigator/run_pipeline.html', context)


@login_required
def run_sync(request):
    """Run venue sync to backend."""
    if request.method == 'POST':
        return _start_run(request, PipelineRun.Step.SYNC)

    # Get pending count by category
    pending_by_category = (
        POI.objects.filter(venue_status=POI.VenueStatus.PENDING)
        .values('category')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    context = {
        'step': 'sync',
        'step_title': 'Venue Sync',
        'categories': POI.Category.choices,
        'pending_by_category': pending_by_category,
        'total_pending': POI.objects.filter(venue_status=POI.VenueStatus.PENDING).count(),
    }
    return render(request, 'navigator/run_pipeline.html', context)


@login_required
def run_discover(request):
    """Run source discovery for POIs."""
    if request.method == 'POST':
        return _start_run(request, PipelineRun.Step.DISCOVER)

    # Get discovery stats
    synced_with_website = POI.objects.filter(
        venue_status=POI.VenueStatus.SYNCED
    ).exclude(osm_website='').count()

    not_started = POI.objects.filter(
        venue_status=POI.VenueStatus.SYNCED,
        source_status=POI.SourceStatus.NOT_STARTED
    ).exclude(osm_website='').count()

    context = {
        'step': 'discover',
        'step_title': 'Source Discovery',
        'categories': POI.Category.choices,
        'synced_with_website': synced_with_website,
        'not_started': not_started,
    }
    return render(request, 'navigator/run_pipeline.html', context)


def _start_run(request, step: str) -> JsonResponse:
    """Start a pipeline run from POST data."""
    # Check if already running
    existing = PipelineRun.objects.filter(status=PipelineRun.Status.RUNNING).first()
    if existing:
        return JsonResponse({
            'error': f'A pipeline is already running: {existing.get_step_display()}',
            'run_id': existing.id,
        }, status=400)

    # Parse form data
    categories = request.POST.getlist('categories')
    city_filter = request.POST.get('city', '').strip()
    limit = int(request.POST.get('limit', 0) or 0)
    dry_run = request.POST.get('dry_run') == 'on'

    # Create run record
    run = PipelineRun.objects.create(
        step=step,
        status=PipelineRun.Status.PENDING,
        categories=categories,
        city_filter=city_filter,
        limit=limit,
        dry_run=dry_run,
    )

    # Start background task
    start_pipeline_run(run)

    return JsonResponse({
        'run_id': run.id,
        'status': 'started',
    })


@login_required
def run_progress(request, run_id: int):
    """Get progress for a pipeline run (AJAX endpoint)."""
    run = get_object_or_404(PipelineRun, id=run_id)

    return JsonResponse({
        'id': run.id,
        'step': run.step,
        'status': run.status,
        'total_items': run.total_items,
        'processed_items': run.processed_items,
        'progress_pct': run.progress_pct,
        'current_item': run.current_item,
        'created': run.created,
        'updated': run.updated,
        'unchanged': run.unchanged,
        'failed': run.failed,
        'skipped': run.skipped,
        'log': run.log,
        'is_running': run.status == PipelineRun.Status.RUNNING,
        'is_complete': run.status in (PipelineRun.Status.COMPLETED, PipelineRun.Status.FAILED),
    })


@login_required
@require_POST
def run_cancel(request, run_id: int):
    """Cancel a running pipeline (just marks it, thread will check)."""
    run = get_object_or_404(PipelineRun, id=run_id)

    if run.status == PipelineRun.Status.RUNNING:
        run.status = PipelineRun.Status.CANCELLED
        run.save()

    return JsonResponse({'status': 'cancelled'})
