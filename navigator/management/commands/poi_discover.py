"""Discover event pages for POIs."""

import asyncio

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from navigator.models import POI
from navigator.services.event_page_finder import find_events_page

console = Console()


class Command(BaseCommand):
    help = 'Discover event pages for POIs and optionally create Sources in backend'

    def add_arguments(self, parser):
        parser.add_argument(
            '--category',
            action='append',
            dest='categories',
            choices=[c[0] for c in POI.Category.choices],
            help='Only discover for specific categories (can be repeated)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Max POIs to process (0 = all)'
        )
        parser.add_argument(
            '--has-website',
            action='store_true',
            help='Only POIs with OSM website (faster discovery)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be discovered without saving'
        )
        parser.add_argument(
            '--city',
            type=str,
            help='Only POIs in this city'
        )
        parser.add_argument(
            '--rediscover',
            action='store_true',
            help='Re-discover POIs that already have results'
        )
        parser.add_argument(
            '--push-sources',
            action='store_true',
            help='Push discovered event pages to backend as Sources'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.0,
            help='Delay between requests in seconds (default: 1.0)'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        categories = options.get('categories')
        push_sources = options['push_sources']
        delay = options['delay']

        # Check API token if pushing
        if push_sources and not dry_run and not settings.SUPERSCHEDULES_API_TOKEN:
            console.print("[red]Error:[/red] No API token configured. Set SUPERSCHEDULES_API_TOKEN env var.")
            return

        # Build query - only synced POIs (need venue_id for source creation)
        pois = POI.objects.filter(venue_status=POI.VenueStatus.SYNCED)

        if not options['rediscover']:
            pois = pois.filter(source_status=POI.SourceStatus.NOT_STARTED)

        if options['has_website']:
            pois = pois.exclude(osm_website='')

        if categories:
            pois = pois.filter(category__in=categories)

        if options.get('city'):
            pois = pois.filter(city__icontains=options['city'])

        pois = pois.order_by('category', 'name')

        if options['limit']:
            pois = pois[:options['limit']]

        pois = list(pois)

        if not pois:
            console.print("[yellow]No POIs to discover[/yellow]")
            console.print("Make sure POIs are synced first (venue_status='synced')")
            return

        console.print(f"\n[bold]Event Page Discovery[/bold]")
        console.print(f"POIs to process: {len(pois)}")
        if push_sources:
            console.print(f"[green]Will push discovered sources to API[/green]")
        if dry_run:
            console.print("[yellow]DRY RUN - no changes will be made[/yellow]")
        console.print()

        # Stats
        stats = {
            'discovered': 0,
            'no_events': 0,
            'skipped': 0,
            'failed': 0,
            'sources_created': 0,
        }

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Discovering...", total=len(pois))

            for poi in pois:
                progress.update(task, description=f"Checking: {poi.name[:40]}", advance=1)

                if not poi.osm_website:
                    # Skip POIs without website for now (search+vision fallback not yet implemented)
                    stats['skipped'] += 1
                    if not dry_run:
                        poi.source_status = POI.SourceStatus.SKIPPED
                        poi.discovery_notes = 'No website available'
                        poi.save()
                    continue

                if dry_run:
                    continue

                # Mark as processing
                poi.source_status = POI.SourceStatus.PROCESSING
                poi.save()

                # Run discovery
                result = asyncio.run(find_events_page(poi))

                if result['events_url']:
                    poi.source_status = POI.SourceStatus.DISCOVERED
                    poi.discovered_events_url = result['events_url']
                    poi.discovery_method = result['method']
                    poi.discovery_confidence = result['confidence']
                    poi.discovery_notes = result.get('notes', '')
                    poi.save()

                    stats['discovered'] += 1

                    # Push to backend if requested
                    if push_sources and poi.venue_id:
                        if self._create_source(poi):
                            stats['sources_created'] += 1

                else:
                    poi.source_status = POI.SourceStatus.NO_EVENTS
                    poi.discovery_notes = result.get('notes', '')
                    poi.save()
                    stats['no_events'] += 1

                # Rate limiting
                if delay > 0:
                    asyncio.run(asyncio.sleep(delay))

        self._print_results(stats, dry_run)

    def _create_source(self, poi: POI) -> bool:
        """Create a Source in the backend for the discovered event page."""
        payload = {
            'venue_id': poi.venue_id,
            'events_url': poi.discovered_events_url,
            'discovery_method': poi.discovery_method,
            'discovery_confidence': poi.discovery_confidence,
        }

        try:
            response = requests.post(
                f"{settings.SUPERSCHEDULES_API_URL}/api/sources/",
                json=payload,
                headers={"Authorization": f"Token {settings.SUPERSCHEDULES_API_TOKEN}"},
                timeout=30
            )

            if response.status_code in (200, 201):
                result = response.json()
                poi.source_id = result.get('source_id')
                poi.source_synced_at = timezone.now()
                poi.save()
                return True
            else:
                poi.discovery_notes += f"\nFailed to create source: HTTP {response.status_code}"
                poi.save()
                return False

        except Exception as e:
            poi.discovery_notes += f"\nFailed to create source: {e}"
            poi.save()
            return False

    def _print_results(self, stats: dict, dry_run: bool):
        """Print discovery results."""
        console.print()

        table = Table(title="Discovery Results")
        table.add_column("Status", style="cyan")
        table.add_column("Count", justify="right")

        if dry_run:
            table.add_row("Would process", str(sum(stats.values())), style="yellow")
        else:
            table.add_row("Discovered", str(stats['discovered']), style="green")
            table.add_row("No events page", str(stats['no_events']), style="dim")
            table.add_row("Skipped (no website)", str(stats['skipped']), style="yellow")
            table.add_row("Failed", str(stats['failed']), style="red")

            if stats['sources_created'] > 0:
                table.add_row("Sources created", str(stats['sources_created']), style="green bold")

        console.print(table)
