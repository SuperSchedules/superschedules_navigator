"""Sync POIs to the main Superschedules backend as Venues."""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from navigator.models import POI

console = Console()


class Command(BaseCommand):
    help = 'Sync POIs to the main Superschedules backend as Venues'

    def add_arguments(self, parser):
        parser.add_argument(
            '--category',
            action='append',
            dest='categories',
            choices=[c[0] for c in POI.Category.choices],
            help='Only sync specific categories (can be repeated)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Max POIs to sync (0 = all)'
        )
        parser.add_argument(
            '--resync',
            action='store_true',
            help='Re-sync already synced POIs (update data)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be synced without actually syncing'
        )
        parser.add_argument(
            '--city',
            type=str,
            help='Only sync POIs in this city'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        categories = options.get('categories')
        resync = options['resync']

        # Check API token
        if not dry_run and not settings.SUPERSCHEDULES_API_TOKEN:
            console.print("[red]Error:[/red] No API token configured. Set SUPERSCHEDULES_API_TOKEN env var.")
            return

        # Build query
        if resync:
            pois = POI.objects.all()
        else:
            pois = POI.objects.filter(venue_status=POI.VenueStatus.PENDING)

        if categories:
            pois = pois.filter(category__in=categories)

        if options.get('city'):
            pois = pois.filter(city__icontains=options['city'])

        pois = pois.order_by('category', 'name')

        if options['limit']:
            pois = pois[:options['limit']]

        pois = list(pois)

        if not pois:
            console.print("[yellow]No POIs to sync[/yellow]")
            return

        console.print(f"\n[bold]POI Sync[/bold]")
        console.print(f"POIs to sync: {len(pois)}")
        console.print(f"API: {settings.SUPERSCHEDULES_API_URL}")
        if dry_run:
            console.print("[yellow]DRY RUN - no changes will be made[/yellow]")
        console.print()

        # Stats
        stats = {
            'created': 0,
            'updated': 0,
            'unchanged': 0,
            'failed': 0,
        }

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Syncing...", total=len(pois))

            for poi in pois:
                progress.update(task, description=f"Syncing: {poi.name[:40]}", advance=1)

                if dry_run:
                    continue

                result = self._sync_poi(poi)
                stats[result] += 1

        self._print_results(stats, dry_run)

    def _sync_poi(self, poi: POI) -> str:
        """
        Sync a single POI to the backend.

        Returns: 'created', 'updated', 'unchanged', or 'failed'
        """
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
            # Website: OSM is trusted, discovered_website only if validated
            'website': poi.osm_website or (
                poi.discovered_website if poi.website_status == POI.WebsiteStatus.VALIDATED else None
            ),
            # Only send events_url if it's been validated by LLM
            'events_url': poi.events_url if poi.source_status == POI.SourceStatus.VALIDATED else None,
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

    def _print_results(self, stats: dict, dry_run: bool):
        """Print sync results."""
        console.print()

        table = Table(title="Sync Results")
        table.add_column("Status", style="cyan")
        table.add_column("Count", justify="right")

        if dry_run:
            table.add_row("Would sync", str(sum(stats.values())), style="yellow")
        else:
            table.add_row("Created", str(stats['created']), style="green")
            table.add_row("Updated", str(stats['updated']), style="yellow")
            table.add_row("Unchanged", str(stats['unchanged']), style="dim")
            table.add_row("Failed", str(stats['failed']), style="red")

        console.print(table)

        if stats['failed'] > 0:
            console.print("\n[red]Check failed POIs in admin for error details.[/red]")
